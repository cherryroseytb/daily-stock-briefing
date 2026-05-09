import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta

import requests
import yfinance as yf

import visualizer

# form type 단독 allowlist 대신 중요도 점수로 필터링한다.
# FMP는 같은 SEC 양식도 "SC 13G", "SCHEDULE 13G"처럼 다르게 반환할 수 있다.
_FORM_BASE_SCORES = {
    "8-K": 5, "8-K/A": 4,
    "10-Q": 4, "10-Q/A": 3,
    "10-K": 4, "10-K/A": 3,
    "424B2": 4, "424B3": 4, "424B5": 4,
    "425": 5,
    "SC 13G": 2, "SC 13G/A": 2, "SC 13D": 3, "SC 13D/A": 3,
    "SCHEDULE 13G": 2, "SCHEDULE 13G/A": 2,
    "SCHEDULE 13D": 3, "SCHEDULE 13D/A": 3,
    "DEF 14A": 3,
    "S-3": 3, "S-3/A": 2, "S-3ASR": 3,
    "S-8": 1,
    "4": 1, "4/A": 1,
}

_FORM_LABELS = {
    "8-K":              "중요 사건 공시",
    "8-K/A":            "중요 사건 공시(수정)",
    "10-Q":             "분기 보고서",
    "10-Q/A":           "분기 보고서(수정)",
    "10-K":             "연간 보고서",
    "10-K/A":           "연간 보고서(수정)",
    "424B2":            "증권 추가 발행",
    "424B3":            "증권 추가 발행",
    "425":              "합병/인수 관련 공시",
    "SC 13G":           "대주주 지분 공시",
    "SC 13G/A":         "대주주 지분 공시(수정)",
    "SC 13D":           "대주주 지분 공시(적극적)",
    "SC 13D/A":         "대주주 지분 공시(적극적, 수정)",
    "SCHEDULE 13G":     "대주주 지분 공시",
    "SCHEDULE 13G/A":   "대주주 지분 공시(수정)",
    "SCHEDULE 13D":     "대주주 지분 공시(적극적)",
    "SCHEDULE 13D/A":   "대주주 지분 공시(적극적, 수정)",
    "DEF 14A":          "주주총회 위임장",
    "S-3":              "증권 등록",
    "S-3/A":            "증권 등록(수정)",
    "S-3ASR":           "증권 등록",
    "S-8":              "종업원 보상 증권 등록",
    "4":                "임원/내부자 주식거래",
    "4/A":              "임원/내부자 주식거래(수정)",
}

_HIGH_SIGNAL_KEYWORDS = (
    "merger", "acquisition", "tender offer", "business combination",
    "earnings", "financial results", "quarterly results", "annual results",
    "dividend", "distribution", "bankruptcy", "restructuring",
    "material definitive agreement", "departure of directors",
    "chief executive officer", "chief financial officer", "ceo", "cfo",
)

_LOW_SIGNAL_KEYWORDS = (
    "employee benefit", "incentive plan", "equity incentive",
    "automatic shelf registration",
)


def _normalize_form_type(form_type):
    normalized = re.sub(r"\s+", " ", str(form_type or "").strip().upper())
    if normalized.startswith("FORM "):
        normalized = normalized[5:]
    if normalized in {"13G", "13G/A"}:
        return f"SC {normalized}"
    if normalized in {"13D", "13D/A"}:
        return f"SC {normalized}"
    return normalized


def _filing_text(item):
    return " ".join(
        str(item.get(key, ""))
        for key in ("title", "description", "type")
        if item.get(key)
    ).lower()


def _classify_filing(item):
    form_type = _normalize_form_type(item.get("type", ""))
    text = _filing_text(item)
    score = _FORM_BASE_SCORES.get(form_type, 0)
    reasons = []

    if score:
        reasons.append("known_form")
    if any(keyword in text for keyword in _HIGH_SIGNAL_KEYWORDS):
        score += 2
        reasons.append("high_signal_keyword")
    if any(keyword in text for keyword in _LOW_SIGNAL_KEYWORDS):
        score -= 1
        reasons.append("low_signal_keyword")

    if score >= 5:
        importance = "high"
    elif score >= 3:
        importance = "medium"
    elif score >= 2:
        importance = "low"
    else:
        importance = "noise"

    return {
        "form_type": form_type,
        "score": score,
        "importance": importance,
        "reasons": reasons or ["unrecognized_form"],
    }


def _parse_filing(item, classification, fallback=False):
    form_type = classification["form_type"]
    filed_date = item.get("fillingDate") or item.get("acceptedDate") or ""
    parsed = {
        "form_type": form_type,
        "form_label": _FORM_LABELS.get(form_type, "기타 SEC 공시"),
        "importance": classification["importance"],
        "importance_score": classification["score"],
        "description": item.get("description", "") or item.get("title", ""),
        "filed_at": filed_date,
        "source": "SEC/FMP",
        "url": item.get("finalLink") or item.get("link") or "",
    }
    if fallback:
        parsed["fallback_reason"] = "importance_filter_empty"
    return parsed


def get_sec_filings(symbol):
    bundle = get_sec_filings_bundle(symbol)
    return bundle["items"]


def get_sec_filings_bundle(symbol):
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        return {
            "items": [{"error": "FMP API 키 없음"}],
            "filter": {"status": "error", "message": "FMP API 키 없음"},
        }

    to_date = datetime.now().date()
    from_date = to_date - timedelta(days=180)
    url = (
        "https://financialmodelingprep.com/stable/sec-filings-search/symbol"
        f"?symbol={symbol}"
        f"&from={from_date.strftime('%Y-%m-%d')}"
        f"&to={to_date.strftime('%Y-%m-%d')}"
        "&page=0&limit=20"
        f"&apikey={api_key}"
    )

    for attempt in range(3):
        try:
            response = requests.get(url, timeout=20)
            if response.status_code == 200:
                filings = response.json() or []
                candidates = []
                excluded_forms = Counter()
                excluded_examples = []

                for item in filings:
                    classification = _classify_filing(item)
                    form_type = classification["form_type"] or "UNKNOWN"
                    if classification["score"] < 2:
                        excluded_forms[form_type] += 1
                        if len(excluded_examples) < 3:
                            excluded_examples.append({
                                "form_type": form_type,
                                "description": item.get("description", "") or item.get("title", ""),
                                "reason": ",".join(classification["reasons"]),
                            })
                        continue

                    candidates.append(_parse_filing(item, classification))

                candidates.sort(
                    key=lambda filing: (
                        filing["importance_score"],
                        filing.get("filed_at", ""),
                    ),
                    reverse=True,
                )
                parsed = candidates[:5]
                status = "ok"

                # 원본 공시가 있는데 전부 필터링되면 "공시 없음"으로 오해하지 않도록
                # 최근 기타 공시를 최소한 남긴다.
                if filings and not parsed:
                    fallback_items = []
                    for item in filings[:3]:
                        fallback_items.append(_parse_filing(
                            item,
                            _classify_filing(item),
                            fallback=True,
                        ))
                    parsed = fallback_items
                    status = "fallback_unfiltered"

                excluded_count = sum(excluded_forms.values())
                hidden_count = max(len(filings) - len(parsed) - excluded_count, 0)

                return {
                    "items": parsed,
                    "filter": {
                        "status": status,
                        "raw_count": len(filings),
                        "shown_count": len(parsed),
                        "excluded_count": excluded_count,
                        "hidden_count": hidden_count,
                        "excluded_forms": dict(excluded_forms),
                        "excluded_examples": excluded_examples,
                    },
                }
            print(f"FMP API {symbol} HTTP {response.status_code} (시도 {attempt+1}/3)")
        except Exception as e:
            print(f"FMP API {symbol} 예외 (시도 {attempt+1}/3): {e}")

        if attempt < 2:
            time.sleep(30)

    print(f"FMP API {symbol} 최종 실패")
    return {
        "items": [{"error": "FMP API 실패-응답없음"}],
        "filter": {"status": "error", "message": "FMP API 실패-응답없음"},
    }

def get_news(symbol):
    # 1순위: Finnhub
    api_key = os.getenv("FINNHUB_API_KEY")
    if api_key:
        try:
            from_dt = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
            to_dt = datetime.now().strftime("%Y-%m-%d")
            url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={from_dt}&to={to_dt}&token={api_key}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                news = response.json()
                if news:
                    parsed = []
                    for n in news[:8]:
                        published_dt = datetime.fromtimestamp(n.get("datetime", 0) or 0)
                        parsed.append({
                            "title": n.get("headline", ""),
                            "summary": n.get("summary", ""),
                            "publisher": n.get("source", ""),
                            "published_at": published_dt.strftime("%Y-%m-%d %H:%M"),
                        })
                    return parsed
        except Exception:
            pass

    # 2순위: yfinance fallback
    try:
        ticker = yf.Ticker(symbol)
        news_items = ticker.news or []
        if news_items:
            parsed = []
            for n in news_items[:8]:
                content = n.get("content", n)
                title = content.get("title") or n.get("title", "")
                summary = content.get("summary") or n.get("summary", "")
                publisher = (content.get("provider", {}) or {}).get("displayName") or n.get("publisher", "Yahoo Finance")
                pub_raw = content.get("pubDate") or n.get("providerPublishTime")
                if isinstance(pub_raw, int):
                    pub_str = datetime.fromtimestamp(pub_raw).strftime("%Y-%m-%d %H:%M")
                else:
                    pub_str = str(pub_raw or "")[:16]
                if title:
                    parsed.append({
                        "title": title,
                        "summary": summary,
                        "publisher": publisher,
                        "published_at": pub_str,
                    })
            return parsed
    except Exception:
        pass

    return []

def get_ticker_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        history_24h = ticker.history(period="1d", interval="5m")
        history_1m = ticker.history(period="1mo")
        history_1y = ticker.history(period="1y")

        visualizer.generate_chart(symbol, history_24h, "24h")
        visualizer.generate_chart(symbol, history_1m, "1m")
        visualizer.generate_chart(symbol, history_1y, "1y")

        info = ticker.info

        price = float(history_24h["Close"].iloc[-1]) if not history_24h.empty else 0
        high_24h = float(history_24h["High"].max()) if not history_24h.empty else price
        low_24h = float(history_24h["Low"].min()) if not history_24h.empty else price
        high_1m = float(history_1m["High"].max()) if not history_1m.empty else 0
        low_1m = float(history_1m["Low"].min()) if not history_1m.empty else 0

        sec_filings = get_sec_filings_bundle(symbol)

        return {
            "symbol": symbol,
            "name": info.get("longName", symbol),
            "price": round(price, 2),
            "high_24h": round(high_24h, 2),
            "low_24h": round(low_24h, 2),
            "high_1m": round(high_1m, 2),
            "low_1m": round(low_1m, 2),
            "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh", 0),
            "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow", 0),
            "dividendYield": round(float(info.get("dividendYield", 0) * 100), 2) if info.get("dividendYield") else 0,
            "dividendRate": info.get("dividendRate", 0) or 0,
            "exDividendDate": str(info.get("exDividendDate", "N/A")),
            "charts": {
                "24h": f"charts/{symbol}_24h.png",
                "1m": f"charts/{symbol}_1m.png",
                "1y": f"charts/{symbol}_1y.png",
            },
            "news": get_news(symbol),
            "sec_filings_6m": sec_filings["items"],
            "sec_filings_filter": sec_filings["filter"],
        }
    except Exception as e:
        print(f"Error {symbol}: {e}")
        return {"symbol": symbol, "error": str(e)}

def main():
    with open("portfolio.json", "r") as f:
        portfolio = json.load(f)

    tickers = list(set(portfolio.get("holdings", []) + portfolio.get("candidates", [])))
    market_data = {symbol: get_ticker_data(symbol) for symbol in tickers}

    result = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "market_data": market_data,
        "api_stats": {
            "yfinance": len(tickers),
            "news": len(tickers),
            "fmp": len(tickers),
            "charts": len(tickers) * 3,
        },
    }

    os.makedirs("data", exist_ok=True)
    with open("data/latest_market_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
