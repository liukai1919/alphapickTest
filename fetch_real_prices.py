#!/usr/bin/env python3
import sys
import os
import time
import sqlite3
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta

# Set path to the database
DB_PATH = Path(__file__).parent / "alpha_picks.db"
PRICES_TBL = "prices"

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def get_all_tickers():
    """Get all unique tickers from the database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT ticker FROM picks")
        return [row[0] for row in cursor.fetchall()]

def fetch_prices_with_retry(ticker, days_back=90, retry_count=3, retry_delay=2):
    """Fetch prices for a single ticker with retries"""
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    for attempt in range(retry_count):
        try:
            print(f"Fetching prices for {ticker} (attempt {attempt+1}/{retry_count})...")
            data = yf.download(ticker, start=cutoff, progress=False)
            
            if data.empty:
                print(f"No data returned for {ticker}")
                time.sleep(retry_delay)
                continue
                
            # Handle MultiIndex columns from yfinance
            if isinstance(data.columns, pd.MultiIndex):
                # Find the Close column for this ticker
                if ('Close', ticker) in data.columns:
                    price_series = data[('Close', ticker)]
                else:
                    print(f"Could not find Close column for {ticker}")
                    time.sleep(retry_delay)
                    continue
            else:
                # Simpler case (less likely with current yfinance)
                if 'Adj Close' in data.columns:
                    price_series = data['Adj Close']
                elif 'Close' in data.columns:
                    price_series = data['Close']
                else:
                    print(f"Missing price columns for {ticker}")
                    time.sleep(retry_delay)
                    continue
                
            # Convert to the required format for database
            result = []
            for date, price in zip(data.index, price_series):
                if not pd.isna(price):  # Skip NaN values
                    result.append((date.strftime('%Y-%m-%d'), ticker, float(price)))
            
            if result:
                print(f"Got {len(result)} days of price data for {ticker}")
                return result
                
            print(f"No valid prices for {ticker}")
            time.sleep(retry_delay)
            
        except Exception as e:
            print(f"Error fetching {ticker}: {str(e)}")
            import traceback
            traceback.print_exc()
            time.sleep(retry_delay)
    
    print(f"Failed to fetch prices for {ticker} after {retry_count} attempts")
    return []

def save_prices_to_db(price_data):
    """Save price data to the database"""
    if not price_data:
        return 0
        
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(
            f"INSERT OR IGNORE INTO {PRICES_TBL} (price_date, ticker, adj_close) VALUES (?, ?, ?)",
            price_data
        )
        conn.commit()
        return cursor.rowcount

def main():
    """Main function to fetch and save prices for all tickers"""
    tickers = get_all_tickers()
    if not tickers:
        print("No tickers found in the database")
        return
        
    print(f"Found {len(tickers)} tickers in the database")
    
    total_prices_saved = 0
    for ticker in tickers:
        price_data = fetch_prices_with_retry(ticker)
        rows_saved = save_prices_to_db(price_data)
        total_prices_saved += rows_saved
        # Small delay to avoid rate limiting
        time.sleep(1)
    
    print(f"Completed! Saved {total_prices_saved} price records for {len(tickers)} tickers")

if __name__ == "__main__":
    main() 