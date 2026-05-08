import json
import os
import requests
import yfinance as ticker_info
from datetime import datetime, timedelta

def get_finnhub_news(symbol, api_key):
    try:
        # Get news for the last 2 days
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start_date}&to={end_date}&token={api_key}"
        response = requests.get(url)
        if response.status_code == 200:
            news = response.json()
            return [{"title": n["headline"], "publisher": n["source"], "link": n["url"]} for n in news[:5]]
    except Exception as e:
        print(f"Finnhub error for {symbol}: {e}")
    return []

def fetch_stock_data(tickers):
    finnhub_key = os.getenv("FINNHUB_API_KEY")
    alpha_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    
    data = {}
    for symbol in tickers:
        print(f"Fetching data for {symbol}...")
        try:
            ticker = ticker_info.Ticker(symbol)
            info = ticker.info
            history = ticker.history(period="2d")
            
            current_price = info.get("regularMarketPrice") or (history["Close"].iloc[-1] if not history.empty else None)
            prev_close = info.get("regularMarketPreviousClose") or (history["Close"].iloc[-2] if len(history) > 1 else None)
            change = ((current_price - prev_close) / prev_close * 100) if current_price and prev_close else 0
            
            # Prefer Finnhub for news if key exists
            news = []
            if finnhub_key:
                news = get_finnhub_news(symbol, finnhub_key)
            
            if not news: # Fallback to yfinance news
                raw_news = ticker.news or []
                news = [
                    {"title": n.get("title", ""), "publisher": n.get("publisher", ""), "link": n.get("link") or n.get("url", "")}
                    for n in raw_news[:3]
                ]
            
            data[symbol] = {
                "name": info.get("longName", symbol),
                "current_price": current_price,
                "change_percent": round(change, 2),
                "summary": info.get("longBusinessSummary", "")[:300] + "...",
                "news": news
            }
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            data[symbol] = {"error": str(e)}
    
    return data

def main():
    # Load portfolio
    with open("portfolio.json", "r") as f:
        portfolio = json.load(f)
    
    holdings = portfolio.get("holdings", [])
    
    # Fetch data
    market_data = fetch_stock_data(holdings)
    
    # Save results
    result = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "watchlist_criteria": portfolio.get("watchlist_criteria", ""),
        "market_data": market_data
    }
    
    os.makedirs("data", exist_ok=True)
    with open("data/latest_market_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print("Market data saved to data/latest_market_data.json")

if __name__ == "__main__":
    main()
