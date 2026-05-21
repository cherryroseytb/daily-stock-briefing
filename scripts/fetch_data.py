import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import yfinance as yf
from google import genai

import visualizer

KST = ZoneInfo("Asia/Seoul")
MAX_SCREENING_CANDIDATES = 20
TOP_N = 5
NEWS_LIMIT = 5
UNIVERSE_PATH = "data/universe/stock_universe.json"
CACHE_DIR = "data/cache"
INFO_CACHE_HOURS = 24
NEWS_CACHE_HOURS = 12
SEC_CACHE_HOURS = 72


def now_kst():
    return datetime.now(KST)


def _dedupe_symbols(symbols):
    result = []
    seen = set()
    for symbol in symbols:
        normalized = str(symbol).strip().upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _cache_path(namespace, key):
    safe_key = re.sub(r"[^A-Z0-9_.-]", "_", str(key).upper())
    return os.path.join(CACHE_DIR, namespace, f"{safe_key}.json")


def _read_cache(namespace, key, max_age_hours):
    path = _cache_path(namespace, key)
    try:
        if not os.path.exists(path):
            return None
        modified = datetime.fromtimestamp(os.path.getmtime(path), tz=KST)
        if now_kst() - modified > timedelta(hours=max_age_hours):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(namespace, key, payload):
    path = _cache_path(namespace, key)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

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

THEME_POOLS = {
    "AI/반도체": [
        "NVDA", "AMD", "AVGO", "TSM", "ASML", "MU", "ARM", "QCOM", "AMAT", "LRCX",
    ],
    "전력/데이터센터": [
        "VST", "CEG", "ETN", "PWR", "GEV", "NEE", "SO", "DUK", "AMT", "DLR",
    ],
    "방산/우주": [
        "LMT", "RTX", "NOC", "GD", "HII", "KTOS", "PLTR", "BA", "LHX", "RKLB",
    ],
    "원전/우라늄": [
        "CCJ", "CEG", "BWXT", "UEC", "NXE", "SMR", "LEU", "UUUU",
    ],
    "헬스케어/비만치료": [
        "LLY", "NVO", "AMGN", "REGN", "VRTX", "ISRG", "TMO", "ABT", "MRK", "PFE",
    ],
    "금리인하/리츠": [
        "VNQ", "XLRE", "O", "AMT", "DLR", "PLD", "EQIX", "NEE", "TLT", "IYR",
    ],
    "에너지/인프라": [
        "XOM", "CVX", "COP", "SLB", "LNG", "EPD", "ET", "MPLX", "WMB", "KMI",
    ],
}

QUALITY_POOL = [
    "MSFT", "AAPL", "GOOGL", "AMZN", "META", "BRK-B", "COST", "V", "MA", "ADBE",
    "NVDA", "AVGO", "ASML", "TSM", "AMD", "QCOM", "TXN", "ADI", "AMAT", "LRCX",
    "LLY", "NVO", "UNH", "JNJ", "ISRG", "TMO", "REGN", "VRTX", "ABT", "MRK",
    "CAT", "ETN", "GE", "HON", "PH", "DE", "WM", "UNP", "UPS", "LIN",
    "HD", "MCD", "SBUX", "PG", "KO", "PEP", "NKE", "LOW", "WMT", "TGT",
    "JPM", "MS", "BLK", "SPGI", "MCO", "AXP", "ICE", "CME", "SCHW", "BK",
]


def default_universe():
    return {
        "version": 1,
        "updated_at": now_kst().strftime("%Y-%m-%d %H:%M %Z"),
        "refresh_policy": {
            "dividend": "monthly",
            "theme": "weekly",
            "quality": "quarterly",
        },
        "dividend": SEED_POOL,
        "theme": THEME_POOLS,
        "quality": QUALITY_POOL,
    }


def load_universe():
    fallback = default_universe()
    try:
        with open(UNIVERSE_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        return {
            "version": loaded.get("version", fallback["version"]),
            "updated_at": loaded.get("updated_at", fallback["updated_at"]),
            "refresh_policy": loaded.get("refresh_policy", fallback["refresh_policy"]),
            "dividend": _dedupe_symbols(loaded.get("dividend") or fallback["dividend"]),
            "theme": loaded.get("theme") or fallback["theme"],
            "quality": _dedupe_symbols(loaded.get("quality") or fallback["quality"]),
        }
    except Exception:
        return fallback


def get_report_profile(run_dt=None):
    run_dt = run_dt or now_kst()
    weekday = run_dt.weekday()
    if weekday in {0, 3}:
        return {
            "type": "dividend",
            "title": "고배당/현금흐름 후보",
            "description": "배당률, 배당 지속성, 재무 안정성을 기준으로 현금흐름형 후보를 선별합니다.",
        }
    if weekday in {1, 4}:
        return {
            "type": "theme",
            "title": "모멘텀/테마 후보",
            "description": "최근 뉴스와 시장 모멘텀이 붙은 주요 테마 안에서 후보를 선별합니다.",
        }
    if weekday in {2, 5}:
        return {
            "type": "quality",
            "title": "장기 퀄리티 후보",
            "description": "3년 이상 보유 관점에서 사업 품질, 재무 안정성, 성장성을 기준으로 선별합니다.",
        }
    return {
        "type": "weekly_summary",
        "title": "주간 요약",
        "description": "이번 주 브리핑과 후보를 요약하고 다음 주 체크포인트를 정리합니다.",
    }

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
def _is_us_ticker(symbol):
    # 미국 종목은 거래소 접미사가 없음 (예: 035420.KS는 KOSPI)
    return "." not in str(symbol)


def get_sec_filings_bundle(symbol):
    # SEC EDGAR/FMP는 미국 상장 종목만 지원
    if not _is_us_ticker(symbol):
        return {
            "items": [],
            "filter": {"status": "non_us", "message": "미국 종목만 검색 가능합니다"},
        }

    cached = _read_cache("sec_filings", symbol, SEC_CACHE_HOURS)
    if cached is not None:
        return cached

    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        return {
            "items": [{"error": "FMP API 키 없음"}],
            "filter": {"status": "error", "message": "FMP API 키 없음"},
        }

    to_date = now_kst().date()
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

                result = {
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
                _write_cache("sec_filings", symbol, result)
                return result
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
    cached = _read_cache("news", symbol, NEWS_CACHE_HOURS)
    if cached is not None:
        return cached

    api_key = os.getenv("FINNHUB_API_KEY")
    if api_key:
        try:
            from_dt = (now_kst() - timedelta(days=3)).strftime("%Y-%m-%d")
            to_dt = now_kst().strftime("%Y-%m-%d")
            url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={from_dt}&to={to_dt}&token={api_key}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                news = response.json()
                if news:
                    parsed = []
                    for n in news[:NEWS_LIMIT]:
                        published_dt = datetime.fromtimestamp(n.get("datetime", 0) or 0, tz=KST)
                        parsed.append({
                            "title": n.get("headline", ""),
                            "summary": n.get("summary", ""),
                            "publisher": n.get("source", ""),
                            "published_at": published_dt.strftime("%Y-%m-%d %H:%M"),
                        })
                    _write_cache("news", symbol, parsed)
                    return parsed
        except Exception:
            pass

    try:
        ticker = yf.Ticker(symbol)
        news_items = ticker.news or []
        if news_items:
            parsed = []
            for n in news_items[:NEWS_LIMIT]:
                content = n.get("content", n)
                title = content.get("title") or n.get("title", "")
                summary = content.get("summary") or n.get("summary", "")
                publisher = (content.get("provider", {}) or {}).get("displayName") or n.get("publisher", "Yahoo Finance")
                pub_raw = content.get("pubDate") or n.get("providerPublishTime")
                if isinstance(pub_raw, int):
                    pub_str = datetime.fromtimestamp(pub_raw, tz=KST).strftime("%Y-%m-%d %H:%M")
                else:
                    pub_str = str(pub_raw or "")[:16]
                if title:
                    parsed.append({
                        "title": title,
                        "summary": summary,
                        "publisher": publisher,
                        "published_at": pub_str,
                    })
            _write_cache("news", symbol, parsed)
            return parsed
    except Exception:
        pass

    _write_cache("news", symbol, [])
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
def get_ticker_info_light(symbol, require_dividend=False):
    cached = _read_cache("ticker_info_light", symbol, INFO_CACHE_HOURS)
    if cached is not None:
        if require_dividend and cached.get("dividend_yield_pct", 0) <= 0:
            return {"symbol": symbol, "skip": "배당 없음"}
        return cached

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        dividend_yield = info.get("dividendYield") or 0
        if require_dividend and dividend_yield <= 0:
            return {"symbol": symbol, "skip": "배당 없음"}

        # 5년 배당 이력 일관성 확인
        try:
            dividends = ticker.dividends
            dividend_consistent = _check_dividend_consistency(dividends, years=5)
        except Exception:
            dividend_consistent = None  # 데이터 없으면 중립

        result = {
            "symbol": symbol,
            "name": info.get("longName", symbol),
            "dividend_yield_pct": round(dividend_yield * 100, 2),
            "dividend_rate": info.get("dividendRate") or 0,
            "market_cap": info.get("marketCap") or 0,
            "debt_to_equity": info.get("debtToEquity"),
            "payout_ratio": info.get("payoutRatio"),
            "profit_margins": info.get("profitMargins"),
            "operating_margins": info.get("operatingMargins"),
            "return_on_equity": info.get("returnOnEquity"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "free_cashflow": info.get("freeCashflow") or 0,
            "beta": info.get("beta"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh") or 0,
            "fifty_two_week_low": info.get("fiftyTwoWeekLow") or 0,
            "current_price": info.get("regularMarketPrice") or info.get("currentPrice") or 0,
            "dividend_consistent": dividend_consistent,
        }
        _write_cache("ticker_info_light", symbol, result)
        return result
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def _check_dividend_consistency(dividends, years=5):
    """최근 N년간 배당 감소(10% 이상) 여부. True=감소 없음."""
    if dividends is None or dividends.empty:
        return None

    cutoff = now_kst() - timedelta(days=years * 365)
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


def _pct(value):
    if value is None:
        return None
    try:
        return float(value) * 100
    except Exception:
        return None


def _price_position(info):
    price = info.get("current_price") or 0
    low = info.get("fifty_two_week_low") or 0
    high = info.get("fifty_two_week_high") or 0
    if not price or not low or not high or high <= low:
        return None
    return max(0, min(1, (price - low) / (high - low)))


def score_theme_candidate(info):
    score = 0
    details = {}

    market_cap = info.get("market_cap", 0)
    if market_cap >= 100_000_000_000:
        cap_score = 20
    elif market_cap >= 20_000_000_000:
        cap_score = 17
    elif market_cap >= 5_000_000_000:
        cap_score = 13
    elif market_cap >= 1_000_000_000:
        cap_score = 8
    else:
        cap_score = 3
    score += cap_score

    revenue_growth = _pct(info.get("revenue_growth"))
    if revenue_growth is None:
        growth_score = 10
    elif revenue_growth >= 25:
        growth_score = 25
    elif revenue_growth >= 15:
        growth_score = 21
    elif revenue_growth >= 8:
        growth_score = 16
    elif revenue_growth >= 0:
        growth_score = 10
    else:
        growth_score = 4
    score += growth_score

    operating_margin = _pct(info.get("operating_margins"))
    if operating_margin is None:
        margin_score = 8
    elif operating_margin >= 30:
        margin_score = 15
    elif operating_margin >= 18:
        margin_score = 12
    elif operating_margin >= 8:
        margin_score = 8
    elif operating_margin >= 0:
        margin_score = 5
    else:
        margin_score = 1
    score += margin_score

    position = _price_position(info)
    if position is None:
        price_score = 10
    elif position <= 0.35:
        price_score = 20
    elif position <= 0.65:
        price_score = 16
    elif position <= 0.85:
        price_score = 10
    else:
        price_score = 5
    score += price_score

    dte = info.get("debt_to_equity")
    if dte is None:
        debt_score = 10
    elif dte <= 75:
        debt_score = 20
    elif dte <= 150:
        debt_score = 15
    elif dte <= 300:
        debt_score = 9
    else:
        debt_score = 3
    score += debt_score

    details.update({
        "market_cap": market_cap,
        "cap_score": cap_score,
        "revenue_growth_pct": revenue_growth,
        "growth_score": growth_score,
        "operating_margin_pct": operating_margin,
        "margin_score": margin_score,
        "price_position_52w": position,
        "price_score": price_score,
        "debt_to_equity": dte,
        "debt_score": debt_score,
    })
    return score, details


def score_quality_candidate(info):
    score = 0
    details = {}

    market_cap = info.get("market_cap", 0)
    if market_cap >= 200_000_000_000:
        cap_score = 15
    elif market_cap >= 50_000_000_000:
        cap_score = 13
    elif market_cap >= 10_000_000_000:
        cap_score = 10
    else:
        cap_score = 5
    score += cap_score

    roe = _pct(info.get("return_on_equity"))
    if roe is None:
        roe_score = 10
    elif roe >= 30:
        roe_score = 20
    elif roe >= 20:
        roe_score = 17
    elif roe >= 12:
        roe_score = 13
    elif roe >= 0:
        roe_score = 8
    else:
        roe_score = 2
    score += roe_score

    operating_margin = _pct(info.get("operating_margins"))
    if operating_margin is None:
        margin_score = 10
    elif operating_margin >= 30:
        margin_score = 20
    elif operating_margin >= 20:
        margin_score = 17
    elif operating_margin >= 12:
        margin_score = 13
    elif operating_margin >= 0:
        margin_score = 8
    else:
        margin_score = 2
    score += margin_score

    revenue_growth = _pct(info.get("revenue_growth"))
    earnings_growth = _pct(info.get("earnings_growth"))
    growth_base = max(v for v in [revenue_growth, earnings_growth, 0] if v is not None)
    if growth_base >= 25:
        growth_score = 20
    elif growth_base >= 15:
        growth_score = 17
    elif growth_base >= 8:
        growth_score = 13
    elif growth_base >= 0:
        growth_score = 8
    else:
        growth_score = 3
    score += growth_score

    fcf = info.get("free_cashflow", 0)
    cash_score = 15 if fcf > 5_000_000_000 else 12 if fcf > 1_000_000_000 else 8 if fcf > 0 else 4
    score += cash_score

    position = _price_position(info)
    if position is None:
        valuation_score = 5
    elif position <= 0.55:
        valuation_score = 10
    elif position <= 0.8:
        valuation_score = 7
    else:
        valuation_score = 4
    score += valuation_score

    details.update({
        "market_cap": market_cap,
        "cap_score": cap_score,
        "roe_pct": roe,
        "roe_score": roe_score,
        "operating_margin_pct": operating_margin,
        "margin_score": margin_score,
        "revenue_growth_pct": revenue_growth,
        "earnings_growth_pct": earnings_growth,
        "growth_score": growth_score,
        "free_cashflow": fcf,
        "cash_score": cash_score,
        "price_position_52w": position,
        "valuation_score": valuation_score,
    })
    return score, details


# ──────────────────────────────────────────────
# Gemini로 Seed Pool → 30개 후보 선정
# ──────────────────────────────────────────────
def select_candidates_with_ai(seed_pool, api_key, profile):
    seed_pool = _dedupe_symbols(seed_pool)
    if not api_key:
        print(f"GEMINI_API_KEY 없음 — seed pool 앞 {MAX_SCREENING_CANDIDATES}개로 fallback")
        return seed_pool[:MAX_SCREENING_CANDIDATES]

    client = genai.Client(api_key=api_key)
    report_type = profile["type"]
    if report_type == "dividend":
        criteria = """
1. Annual dividend yield of 10% or more when available
2. No obvious recent dividend cut risk
3. No meaningful bankruptcy risk when considering debt levels and market capitalization
4. Sector diversification
"""
    elif report_type == "theme":
        criteria = """
1. Strong relevance to current market themes and catalysts
2. Sufficient liquidity and market capitalization
3. Recent business momentum or news relevance
4. Avoid penny stocks and highly speculative micro-caps
"""
    else:
        criteria = """
1. Durable competitive position for a 3+ year holding period
2. Strong profitability or cash-flow profile
3. Healthy balance sheet and manageable valuation risk
4. Sector diversification
"""

    prompt = f"""
You are a professional investment analyst.

Today's discovery theme: {profile['title']}
Description: {profile['description']}

From the following ticker universe, select exactly {MAX_SCREENING_CANDIDATES} stocks that best meet these criteria:
{criteria}

Available tickers:
{', '.join(seed_pool)}

IMPORTANT: Respond with ONLY a JSON array of exactly {MAX_SCREENING_CANDIDATES} ticker symbols. No explanation, no markdown, no other text.
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
                return valid[:MAX_SCREENING_CANDIDATES]

        print(f"AI 응답 파싱 실패 — seed pool 앞 {MAX_SCREENING_CANDIDATES}개로 fallback")
    except Exception as e:
        print(f"AI 선정 오류: {e} — seed pool 앞 {MAX_SCREENING_CANDIDATES}개로 fallback")

    return seed_pool[:MAX_SCREENING_CANDIDATES]


def get_seed_pool_for_profile(universe, profile):
    report_type = profile["type"]
    if report_type == "dividend":
        return _dedupe_symbols(universe.get("dividend", SEED_POOL))
    if report_type == "quality":
        return _dedupe_symbols(universe.get("quality", QUALITY_POOL))

    theme_map = universe.get("theme") or THEME_POOLS
    flattened = []
    for symbols in theme_map.values():
        flattened.extend(symbols)
    return _dedupe_symbols(flattened)


# ──────────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────────
def build_weekly_summary_data(profile):
    os.makedirs("data", exist_ok=True)
    recent = []
    cutoff = now_kst().date() - timedelta(days=7)
    briefings_dir = "briefings"
    if os.path.isdir(briefings_dir):
        for name in sorted(os.listdir(briefings_dir), reverse=True):
            if not name.endswith(".md"):
                continue
            date_text = name[:-3]
            try:
                file_date = datetime.strptime(date_text, "%Y-%m-%d").date()
            except ValueError:
                continue
            if file_date < cutoff:
                continue
            path = os.path.join(briefings_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                recent.append({
                    "date": date_text,
                    "file": path,
                    "content": content[:12000],
                })
            except Exception as e:
                recent.append({"date": date_text, "file": path, "error": str(e)})

    return {
        "date": now_kst().strftime("%Y-%m-%d %H:%M"),
        "report_profile": profile,
        "market_data": {},
        "candidate_rankings": [],
        "weekly_sources": recent[:7],
        "screening_meta": {
            "mode": "weekly_summary",
            "source_count": len(recent[:7]),
            "top5": [],
        },
        "api_stats": {
            "yfinance": 0,
            "news": 0,
            "fmp": 0,
            "charts": 0,
            "limits": {
                "max_screening_candidates": MAX_SCREENING_CANDIDATES,
                "news_per_ticker": NEWS_LIMIT,
                "info_cache_hours": INFO_CACHE_HOURS,
                "news_cache_hours": NEWS_CACHE_HOURS,
                "sec_cache_hours": SEC_CACHE_HOURS,
            },
        },
    }


def main():
    with open("portfolio.json", "r") as f:
        portfolio = json.load(f)

    holdings = portfolio.get("holdings", [])
    gemini_key = os.getenv("GEMINI_API_KEY")
    run_dt = now_kst()
    profile = get_report_profile(run_dt)
    universe = load_universe()

    if profile["type"] == "weekly_summary":
        print("=" * 50)
        print("Sunday profile: weekly summary data build")
        print("=" * 50)
        result = build_weekly_summary_data(profile)
        with open("data/latest_market_data.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("완료 — data/latest_market_data.json 저장됨")
        return

    # Step 1: AI가 seed pool에서 30개 후보 선정
    print("=" * 50)
    print(f"Step 1: AI 후보 종목 선정 ({profile['title']})")
    print("=" * 50)
    seed_pool = get_seed_pool_for_profile(universe, profile)
    ai_candidates = select_candidates_with_ai(seed_pool, gemini_key, profile)
    print(f"선정된 후보: {ai_candidates}")

    # Step 2: 후보 경량 데이터 수집 + 스코어링
    print("\n" + "=" * 50)
    print("Step 2: 후보 종목 스코어링")
    print("=" * 50)
    scored = []
    for symbol in ai_candidates:
        print(f"  스코어링: {symbol}")
        info_light = get_ticker_info_light(symbol, require_dividend=(profile["type"] == "dividend"))
        if "error" in info_light or "skip" in info_light:
            reason = info_light.get("error") or info_light.get("skip")
            print(f"    → 제외: {reason}")
            continue
        if profile["type"] == "theme":
            s, details = score_theme_candidate(info_light)
        elif profile["type"] == "quality":
            s, details = score_quality_candidate(info_light)
        else:
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
    top5_symbols = [s["symbol"] for s in scored[:TOP_N]]
    print(f"\nTop {TOP_N} 최종 선정: {top5_symbols}")

    # Step 3: holdings + topN 전체 데이터 수집 (차트/뉴스/공시 포함)
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
        "date": run_dt.strftime("%Y-%m-%d %H:%M"),
        "report_profile": profile,
        "market_data": market_data,
        "candidate_rankings": scored[:TOP_N],
        "screening_meta": {
            "mode": profile["type"],
            "title": profile["title"],
            "seed_pool_size": len(seed_pool),
            "ai_selected_count": len(ai_candidates),
            "scored_count": len(scored),
            "top5": top5_symbols,
            "max_screening_candidates": MAX_SCREENING_CANDIDATES,
        },
        "api_stats": {
            "yfinance": len(all_tickers) + len(ai_candidates),
            "news": len(all_tickers),
            "fmp": len(all_tickers),
            "charts": len(all_tickers) * 3,
            "limits": {
                "max_screening_candidates": MAX_SCREENING_CANDIDATES,
                "news_per_ticker": NEWS_LIMIT,
                "info_cache_hours": INFO_CACHE_HOURS,
                "news_cache_hours": NEWS_CACHE_HOURS,
                "sec_cache_hours": SEC_CACHE_HOURS,
            },
        },
    }

    os.makedirs("data", exist_ok=True)
    with open("data/latest_market_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n완료 — data/latest_market_data.json 저장됨")


if __name__ == "__main__":
    main()
