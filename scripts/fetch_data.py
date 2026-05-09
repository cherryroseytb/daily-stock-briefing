import json
import os
import time
from datetime import datetime, timedelta

import requests
import yfinance as yf

import visualizer

# 투자 판단에 유의미한 공시 타입만 필터링
_IMPORTANT_FORMS = {
    "8-K", "10-Q", "10-K",
    "424B2", "424B3",       # 증권 추가 발행
    "425",                   # 합병/인수
    "SC 13G", "SC 13D",     # 대주주 지분 변동
    "DEF 14A",              # 주주총회 안건
    "S-3", "S-3ASR",        # 증권 등록
}

_FORM_LABELS = {
    "8-K":      "중요 사건 공시",
    "10-Q":     "분기 보고서",
    "10-K":     "연간 보고서",
    "424B2":    "증권 추가 발행",
    "424B3":    "증권 추가 발행",
    "425":      "합병/인수 관련 공시",
    "SC 13G":   "대주주 지분 공시",
    "SC 13D":   "대주주 지분 공시(적극적)",
    "DEF 14A":  "주주총회 위임장",
    "S-3":      "증권 등록",
    "S-3ASR":   "증권 등록",
}

def get_sec_filings(symbol):
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        return [{"error": "FMP API 키 없음"}]

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
                parsed = []
                for item in filings:
                    form_type = item.get("type", "")
                    if form_type not in _IMPORTANT_FORMS:
                        continue
                    filed_date = item.get("fillingDate") or item.get("acceptedDate") or ""
                    parsed.append({
                        "form_type": form_type,
                        "form_label": _FORM_LABELS.get(form_type, form_type),
                        "description": item.get("description", ""),
                        "filed_at": filed_date,
                        "source": "SEC/FMP",
                    })
                    if len(parsed) >= 5:
                        break
                return parsed
            print(f"FMP API {symbol} HTTP {response.status_code} (시도 {attempt+1}/3)")
        except Exception as e:
            print(f"FMP API {symbol} 예외 (시도 {attempt+1}/3): {e}")

        if attempt < 2:
            time.sleep(30)

    print(f"FMP API {symbol} 최종 실패")
    return [{"error": "FMP API 실패-응답없음"}]

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
            "sec_filings_6m": get_sec_filings(symbol),
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
