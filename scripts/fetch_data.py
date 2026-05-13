import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta

import requests
import yfinance as yf
from google import genai

import visualizer

# ──────────────────────────────────────────────
# 글로벌 고배당주 Seed Pool (~95개)
# AI가 이 풀에서 30개를 선정 → API로 스코어링 → Top 5 브리핑
# ──────────────────────────────────────────────
SEED_POOL = [
    # BDC (Business Development Companies) — 고배당 대출형 펀드
    "ARCC", "MAIN", "OXLC", "FSK", "BXSL", "PFLT", "HTGC", "ORCC",
    "PSEC", "GAIN", "GLAD", "SLRC", "GBDC", "CSWC", "TPVG", "SAR",
    "TCPC", "FDUS", "MRCC", "NEWT", "PNNT",

    # Mortgage REIT — 모기지 리츠
    "AGNC", "NLY", "RITM", "RC", "TWO", "IVR", "EARN", "NYMT",
    "GPMT", "AOMR", "RWT", "SACH",

    # Equity REIT — 부동산 리츠 (고배당군)
    "O", "STAG", "NNN", "LTC", "OHI", "SBRA", "MPW", "GOOD",

    # MLP (Master Limited Partnerships) — 에너지 인프라
    "EPD", "ET", "MPLX", "WES", "PAA", "DKL",

    # CEF (Closed-End Funds) — 폐쇄형 펀드
    "UTF", "GOF", "PDI", "PTY", "ECC", "ETV", "BGT", "GHY",
    "PHK", "RQI", "JPC", "AWF", "EXD",

    # Covered Call ETF — 커버드콜 ETF
    "QYLD", "XYLD", "RYLD", "SVOL", "JEPI", "JEPQ",

    # 통신 / 유틸리티 / 담배
    "T", "VZ", "MO", "PM", "D", "SO", "PPL", "LUMN",

    # 국제 ADR — 영국 / 유럽
    "BTI", "SHEL", "BP", "UL", "GSK", "ORAN", "TTE", "VOD",

    # 국제 ADR — 캐나다
    "ENB", "BCE", "TRP", "CM", "BNS", "TD",

    # 국제 ADR — 브라질
    "PBR", "VALE", "ITUB", "BBD",

    # 국제 ADR — 호주 / 기타
    "BHP", "RIO", "WPM",
]

# ──────────────────────────────────────────────
# SEC 공시 필터링 상수
# ──────────────────────────────────────────────
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


# ──────────────────────────────────────────────
# SEC 공시 파싱 유틸
# ──────────────────────────────────────────────
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


# ──────────────────────────────────────────────
# SEC 공시 수집
# ──────────────────────────────────────────────
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
                    key=lambda f: (f["importance_score"], f.get("filed_at", "")),
                    reverse=True,
                )
                parsed = candidates[:5]
                status = "ok"

                if filings and not parsed:
                    fallback_items = []
                    for item in filings[:3]:
                        fallback_items.append(_parse_filing(
                            item, _classify_filing(item), fallback=True,
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


# ──────────────────────────────────────────────
# 뉴스 수집
# ──────────────────────────────────────────────
def get_news(symbol):
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


# ──────────────────────────────────────────────
# 전체 데이터 수집 (holdings + top5용)
# ──────────────────────────────────────────────
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


# ──────────────────────────────────────────────
# 스코어링용 경량 데이터 수집 (차트/뉴스/공시 없음)
# ──────────────────────────────────────────────
def get_ticker_info_light(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        dividend_yield = info.get("dividendYield") or 0
        # 배당 없는 종목은 스코어링 불필요
        if dividend_yield <= 0:
            return {"symbol": symbol, "skip": "배당 없음"}

        # 5년 배당 이력 일관성 확인
        try:
            dividends = ticker.dividends
            dividend_consistent = _check_dividend_consistency(dividends, years=5)
        except Exception:
            dividend_consistent = None  # 데이터 없으면 중립

        return {
            "symbol": symbol,
            "name": info.get("longName", symbol),
            "dividend_yield_pct": round(dividend_yield * 100, 2),
            "dividend_rate": info.get("dividendRate") or 0,
            "market_cap": info.get("marketCap") or 0,
            "debt_to_equity": info.get("debtToEquity"),
            "payout_ratio": info.get("payoutRatio"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh") or 0,
            "fifty_two_week_low": info.get("fiftyTwoWeekLow") or 0,
            "current_price": info.get("regularMarketPrice") or 0,
            "dividend_consistent": dividend_consistent,
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def _check_dividend_consistency(dividends, years=5):
    """최근 N년간 배당 감소(10% 이상) 여부. True=감소 없음."""
    if dividends is None or dividends.empty:
        return None

    cutoff = datetime.now() - timedelta(days=years * 365)
    try:
        # timezone-aware 인덱스 처리
        if dividends.index.tz is not None:
            cutoff = cutoff.replace(tzinfo=dividends.index.tz)
        recent = dividends[dividends.index >= cutoff]
    except Exception:
        recent = dividends.tail(years * 4)  # 분기배당 기준 fallback

    if len(recent) < 2:
        return None

    by_year = recent.groupby(recent.index.year).sum()
    if len(by_year) < 2:
        return None

    for i in range(1, len(by_year)):
        prev = by_year.iloc[i - 1]
        curr = by_year.iloc[i]
        if prev > 0 and curr < prev * 0.90:  # 10% 이상 감소 시 cut 판정
            return False
    return True


# ──────────────────────────────────────────────
# 후보 종목 스코어링 (100점 만점)
# ──────────────────────────────────────────────
def score_candidate(info):
    score = 0
    details = {}

    # 1. 배당률 (0-40점): 10% 미만은 후보 제외 기준이므로 10% = 기본점
    yield_pct = info.get("dividend_yield_pct", 0)
    if yield_pct >= 20:
        div_score = 40
    elif yield_pct >= 15:
        div_score = 32
    elif yield_pct >= 12:
        div_score = 24
    elif yield_pct >= 10:
        div_score = 16
    else:
        div_score = max(0, int(yield_pct * 1.5))
    score += div_score
    details["dividend_yield_pct"] = yield_pct
    details["dividend_score"] = div_score

    # 2. 배당 일관성 (0-25점)
    consistent = info.get("dividend_consistent")
    if consistent is True:
        consistency_score = 25
    elif consistent is None:
        consistency_score = 12  # 데이터 없으면 중간값
    else:
        consistency_score = 0
    score += consistency_score
    details["dividend_consistent"] = consistent
    details["consistency_score"] = consistency_score

    # 3. 시가총액 (0-20점): 부도위험 간접 지표
    market_cap = info.get("market_cap", 0)
    if market_cap >= 5_000_000_000:      # $5B+
        cap_score = 20
    elif market_cap >= 1_000_000_000:    # $1B+
        cap_score = 15
    elif market_cap >= 300_000_000:      # $300M+
        cap_score = 8
    else:
        cap_score = 0
    score += cap_score
    details["market_cap"] = market_cap
    details["cap_score"] = cap_score

    # 4. 부채비율 (0-15점): 낮을수록 재무 안정
    dte = info.get("debt_to_equity")
    if dte is None:
        debt_score = 8  # 데이터 없으면 중간값
    elif dte <= 50:
        debt_score = 15
    elif dte <= 150:
        debt_score = 12
    elif dte <= 300:
        debt_score = 8
    elif dte <= 500:
        debt_score = 4
    else:
        debt_score = 0
    score += debt_score
    details["debt_to_equity"] = dte
    details["debt_score"] = debt_score

    return score, details


# ──────────────────────────────────────────────
# Gemini로 Seed Pool → 30개 후보 선정
# ──────────────────────────────────────────────
def select_candidates_with_ai(seed_pool, api_key):
    if not api_key:
        print("GEMINI_API_KEY 없음 — seed pool 앞 30개로 fallback")
        return seed_pool[:30]

    client = genai.Client(api_key=api_key)
    prompt = f"""
You are a professional investment analyst specializing in high-dividend stocks.

From the following list of global high-dividend stock tickers, select exactly 30 stocks that best meet these criteria:
1. Annual dividend yield of 10% or more (high-risk stocks acceptable)
2. No dividend cuts in the past 5 years (maintained or increased)
3. No meaningful bankruptcy risk when considering debt levels and market capitalization

If more than 30 stocks meet criteria 1-3, prioritize by:
- Higher dividend yield
- Longer track record of consistent dividends
- Stronger financial position (larger market cap, lower debt)
- Sector diversification (avoid selecting too many from the same category)

Available tickers:
{', '.join(seed_pool)}

IMPORTANT: Respond with ONLY a JSON array of exactly 30 ticker symbols. No explanation, no markdown, no other text.
Example format: ["ARCC", "MAIN", "OXLC", ...]
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = response.text.strip()
        # JSON 배열 추출
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        if match:
            tickers = json.loads(match.group())
            # seed pool에 있는 종목만 허용 (환각 방지)
            valid = [t.strip().upper() for t in tickers
                     if isinstance(t, str) and t.strip().upper() in seed_pool]
            if len(valid) >= 10:
                print(f"AI 선정 완료: {len(valid)}개")
                return valid[:30]

        print("AI 응답 파싱 실패 — seed pool 앞 30개로 fallback")
    except Exception as e:
        print(f"AI 선정 오류: {e} — seed pool 앞 30개로 fallback")

    return seed_pool[:30]


# ──────────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────────
def main():
    with open("portfolio.json", "r") as f:
        portfolio = json.load(f)

    holdings = portfolio.get("holdings", [])
    gemini_key = os.getenv("GEMINI_API_KEY")

    # Step 1: AI가 seed pool에서 30개 후보 선정
    print("=" * 50)
    print("Step 1: AI 후보 종목 선정 (seed pool → 30개)")
    print("=" * 50)
    ai_candidates = select_candidates_with_ai(SEED_POOL, gemini_key)
    print(f"선정된 후보: {ai_candidates}")

    # Step 2: 30개 경량 데이터 수집 + 스코어링
    print("\n" + "=" * 50)
    print("Step 2: 후보 종목 스코어링")
    print("=" * 50)
    scored = []
    for symbol in ai_candidates:
        print(f"  스코어링: {symbol}")
        info_light = get_ticker_info_light(symbol)
        if "error" in info_light or "skip" in info_light:
            reason = info_light.get("error") or info_light.get("skip")
            print(f"    → 제외: {reason}")
            continue
        s, details = score_candidate(info_light)
        scored.append({
            "symbol": symbol,
            "name": info_light.get("name", symbol),
            "score": s,
            "dividend_yield_pct": info_light.get("dividend_yield_pct", 0),
            "details": details,
        })
        print(f"    → 점수: {s}/100 (배당률 {info_light.get('dividend_yield_pct', 0):.1f}%)")

    scored.sort(key=lambda x: x["score"], reverse=True)
    top5_symbols = [s["symbol"] for s in scored[:5]]
    print(f"\nTop 5 최종 선정: {top5_symbols}")

    # Step 3: holdings + top5 전체 데이터 수집 (차트/뉴스/공시 포함)
    print("\n" + "=" * 50)
    print("Step 3: 전체 데이터 수집 (holdings + Top 5)")
    print("=" * 50)
    all_tickers = list(dict.fromkeys(holdings + top5_symbols))  # 순서 유지, 중복 제거
    market_data = {}
    for symbol in all_tickers:
        print(f"  Full fetch: {symbol}")
        data = get_ticker_data(symbol)
        # top5에 스코어 정보 주입 (브리핑 프롬프트에서 활용)
        if symbol in top5_symbols:
            score_info = next((s for s in scored if s["symbol"] == symbol), None)
            if score_info:
                data["screening_score"] = score_info["score"]
                data["screening_details"] = score_info["details"]
        market_data[symbol] = data

    result = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "market_data": market_data,
        "candidate_rankings": scored[:5],
        "screening_meta": {
            "seed_pool_size": len(SEED_POOL),
            "ai_selected_count": len(ai_candidates),
            "scored_count": len(scored),
            "top5": top5_symbols,
        },
        "api_stats": {
            "yfinance": len(all_tickers) + len(ai_candidates),
            "news": len(all_tickers),
            "fmp": len(all_tickers),
            "charts": len(all_tickers) * 3,
        },
    }

    os.makedirs("data", exist_ok=True)
    with open("data/latest_market_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n완료 — data/latest_market_data.json 저장됨")


if __name__ == "__main__":
    main()
