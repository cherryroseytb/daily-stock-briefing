import matplotlib.pyplot as plt
import pandas as pd
import os

def generate_chart(symbol, history, timeframe, output_dir="charts"):
    os.makedirs(output_dir, exist_ok=True)
    plt.figure(figsize=(10, 4))
    plt.plot(history.index, history['Close'], label='Close Price', color='blue')
    plt.title(f"{symbol} - {timeframe} Price Trend")
    plt.xlabel("Date/Time")
    plt.ylabel("Price")
    plt.grid(True)
    
    file_path = os.path.join(output_dir, f"{symbol}_{timeframe}.png")
    plt.savefig(file_path)
    plt.close()
    return file_path
