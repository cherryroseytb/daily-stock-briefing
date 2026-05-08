import json
import os
import yfinance as ticker_info
from datetime import datetime, timedelta
import visualizer

def get_ticker_data(symbol):
    try:
        ticker = ticker_info.Ticker(symbol)
        info = ticker.fast_info
        history_24h = ticker.history(period="1d", interval="5m")
        history_1m = ticker.history(period="1mo")
        
        # 차트 생성
        chart_24h = visualizer.generate_chart(symbol, history_24h, "24h")
        chart_1m = visualizer.generate_chart(symbol, history_1m, "1m")
        
        # 상세 정보
        full_info = ticker.info
        
        return {
            "name": full_info.get("longName", symbol),
            "price": float(history_24h["Close"].iloc[-1]) if not history_24h.empty else 0,
            "high_24h": float(history_24h["High"].max()) if not history_24h.empty else 0,
            "low_24h": float(history_24h["Low"].min()) if not history_24h.empty else 0,
            "fiftyTwoWeekHigh": float(info.fifty_two_week_high) if info.fifty_two_week_high else 0,
            "fiftyTwoWeekLow": float(info.fifty_two_week_low) if info.fifty_two_week_low else 0,
            "dividendYield": float(full_info.get("dividendYield", 0) * 100) if full_info.get("dividendYield") else 0,
            "dividendRate": full_info.get("dividendRate", 0) or 0,
            "exDividendDate": str(full_info.get("exDividendDate", "N/A")),
            "charts": {"24h": f"charts/{symbol}_24h.png", "1m": f"charts/{symbol}_1m.png"}
        }
    except Exception as e:
        return {"error": str(e)}

def main():
    # 1. 포트폴리오 로드
    with open("portfolio.json", "r") as f:
        portfolio = json.load(f)
    
    # 2. 고배당주 후보군 탐색을 위해 1차적으로 LLM 호출이 필요함
    # 이 스크립트는 이제 전달받은 리스트를 기반으로 데이터를 가져오는 역할만 수행
    # 후보군 종목을 portfolio.json이나 별도 설정에서 받아오도록 처리
    target_tickers = list(set(portfolio.get("holdings", []) + portfolio.get("candidates", [])))
    
    market_data = {symbol: get_ticker_data(symbol) for symbol in target_tickers}
    
    result = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "market_data": market_data
    }
    
    os.makedirs("data", exist_ok=True)
    with open("data/latest_market_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
