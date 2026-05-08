import json
import os
from datetime import datetime, timedelta

import requests
import yfinance as yf

import visualizer

def get_sec_filings(symbol):
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        return []

    try:
        to_date = datetime.now().date()
        from_date = to_date - timedelta(days=90)
        url = (
            "https://financialmodelingprep.com/stable/sec-filings-search/symbol"
            f"?symbol={symbol}"
            f"&from={from_date.strftime('%Y-%m-%d')}"
            f"&to={to_date.strftime('%Y-%m-%d')}"
            "&page=0&limit=20"
            f"&apikey={api_key}"
        )
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            return []

        filings = response.json() or []
        parsed = []
        for item in filings[:8]:
            filed_date = item.get("fillingDate") or item.get("acceptedDate") or ""
            parsed.append(
                {
                    "form_type": item.get("type", ""),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "filed_at": filed_date,
                    "source": "SEC/FMP",
                    "url": item.get("finalLink") or item.get("link") or "",
                }
            )
        return parsed
    except:
        return []

def get_news(symbol):
    api_key = os.getenv("FINNHUB_API_KEY")
    if api_key:
        try:
            url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={(datetime.now()-timedelta(days=3)).strftime('%Y-%m-%d')}&to={datetime.now().strftime('%Y-%m-%d')}&token={api_key}"
            response = requests.get(url)
            if response.status_code == 200:
                news = response.json()
                if news:
                    parsed = []
                    for n in news[:8]:
                        published_dt = datetime.fromtimestamp(n.get("datetime", 0) or 0)
                        parsed.append(
                            {
                                "title": n.get("headline", ""),
                                "summary": n.get("summary", ""),
                                "publisher": n.get("source", ""),
                                "url": n.get("url", ""),
                                "published_at": published_dt.strftime("%Y-%m-%d %H:%M"),
                            }
                        )
                    return parsed
        except:
            pass
    
    # Fallback to market context
    return [
        {"title": "Global Market Sentiment", "summary": "Recent macro trends including interest rate stability and AI sector growth are driving market volatility."},
        {"title": "Sector Outlook", "summary": "Current sector dynamics indicate rotation between growth and value stocks based on inflationary pressures."},
    ]

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
        
        return {
            "symbol": symbol,
            "name": info.get("longName", symbol),
            "price": round(price, 2),
            "high_24h": round(high_24h, 2),
            "low_24h": round(low_24h, 2),
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
            "sec_filings_3m": get_sec_filings(symbol),
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
        "market_data": market_data
    }
    
    os.makedirs("data", exist_ok=True)
    with open("data/latest_market_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
