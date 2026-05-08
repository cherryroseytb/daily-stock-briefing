import json
import os
import requests
import yfinance as ticker_info
from datetime import datetime, timedelta
import visualizer

def get_finnhub_news(symbol, api_key):
    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start_date}&to={end_date}&token={api_key}"
        response = requests.get(url)
        if response.status_code == 200:
            news = response.json()
            return [{"title": n["headline"], "publisher": n["source"], "link": n["url"]} for n in news[:7]]
    except Exception as e:
        print(f"Finnhub error for {symbol}: {e}")
    return []

def fetch_stock_data(tickers):
    finnhub_key = os.getenv("FINNHUB_API_KEY")
    data = {}
    
    for symbol in tickers:
        print(f"Fetching data for {symbol}...")
        try:
            ticker = ticker_info.Ticker(symbol)
            info = ticker.info
            
            # Historical Data
            history_24h = ticker.history(period="1d", interval="5m")
            history_1m = ticker.history(period="1mo")
            
            # Chart Generation
            chart_24h = visualizer.generate_chart(symbol, history_24h, "24h")
            chart_1m = visualizer.generate_chart(symbol, history_1m, "1m")
            
            current_price = info.get("regularMarketPrice") or (history_24h["Close"].iloc[-1] if not history_24h.empty else None)
            
            data[symbol] = {
                "name": info.get("longName", symbol),
                "current_price": current_price if current_price else 0,
                "high_24h": float(history_24h["High"].max()) if not history_24h.empty else 0,
                "low_24h": float(history_24h["Low"].min()) if not history_24h.empty else 0,
                "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh", 0),
                "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow", 0),
                "dividendRate": info.get("dividendRate", 0),
                "dividendYield": info.get("dividendYield", 0),
                "exDividendDate": str(info.get("exDividendDate", "N/A")),
                "charts": {
                    "24h": f"charts/{symbol}_24h.png",
                    "1m": f"charts/{symbol}_1m.png"
                },
                "news": get_finnhub_news(symbol, finnhub_key) if finnhub_key else [],
                "financials": {
                    "payout_ratio": info.get("payoutRatio") if info.get("payoutRatio") else 0,
                    "debt_to_equity": info.get("debtToEquity") if info.get("debtToEquity") else 0
                }
            }
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            data[symbol] = {"error": str(e)}
    return data

def main():
    with open("portfolio.json", "r") as f:
        portfolio = json.load(f)
    
    # Combined list: holdings + top dividend candidates
    candidates = ["ARCC", "FSK", "AGNC", "PFLT", "BXSL"]
    tickers = list(set(portfolio.get("holdings", []) + candidates))
    
    market_data = fetch_stock_data(tickers)
    
    result = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "watchlist_criteria": portfolio.get("watchlist_criteria", ""),
        "market_data": market_data
    }
    
    os.makedirs("data", exist_ok=True)
    with open("data/latest_market_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
