import json
import os
import yfinance as yf
from datetime import datetime, timedelta
import visualizer

def get_ticker_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        history_24h = ticker.history(period="1d", interval="5m")
        history_1m = ticker.history(period="1mo")
        
        # 차트 생성 (반드시 실행)
        visualizer.generate_chart(symbol, history_24h, "24h")
        visualizer.generate_chart(symbol, history_1m, "1m")
        
        # info는 데이터가 없을 가능성이 크므로 info를 기본으로 사용
        info = ticker.info
        
        # 데이터 정제 (None 방지)
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
            "charts": {"24h": f"charts/{symbol}_24h.png", "1m": f"charts/{symbol}_1m.png"}
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
