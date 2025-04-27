#!/usr/bin/env python3
"""
Simple test script to check yfinance functionality
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import time
import sqlite3
from pathlib import Path

# Set up database connection
DB_PATH = Path(__file__).parent / "alpha_picks.db"
PRICES_TBL = "prices"

def simple_fetch_test(ticker_symbol):
    """Test a basic yfinance fetch for a single ticker"""
    print(f"\n=== Testing fetch for {ticker_symbol} ===")
    try:
        # Get data for the last 30 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        # Format dates as strings
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        
        print(f"Fetching data from {start_str} to {end_str}")
        
        # Download data
        data = yf.download(ticker_symbol, start=start_str, end=end_str, progress=False)
        
        # Check results
        print(f"Data shape: {data.shape}")
        print(f"Columns: {data.columns.tolist()}")
        
        if not data.empty:
            print("\nFirst few rows:")
            print(data.head(3))
            
            # Save to database if data exists
            save_to_db(ticker_symbol, data)
        else:
            print("No data returned")
            
    except Exception as e:
        print(f"Error: {str(e)}")

def save_to_db(ticker, data):
    """Save the ticker data to the database"""
    print("\nSaving to database...")
    
    try:
        # Open connection
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Handle MultiIndex columns format from yfinance
        if isinstance(data.columns, pd.MultiIndex):
            # Get the price column with the correct ticker
            if ('Close', ticker) in data.columns:
                price_series = data[('Close', ticker)]
            else:
                print(f"Could not find Close column for {ticker}")
                return
        else:
            # Handle simpler case (unlikely with current yfinance)
            if 'Adj Close' in data.columns:
                price_series = data['Adj Close']
            elif 'Close' in data.columns:
                price_series = data['Close']
            else:
                print(f"Missing price columns for {ticker}")
                return
        
        # Prepare data
        rows = []
        for date, price in zip(data.index, price_series):
            if not pd.isna(price):
                date_str = date.strftime('%Y-%m-%d')
                price_val = float(price)  # Ensure it's a float
                rows.append((date_str, ticker, price_val))
        
        if not rows:
            print("No valid price data to save")
            return
            
        # Insert data
        cursor.executemany(
            f"INSERT OR IGNORE INTO {PRICES_TBL} (price_date, ticker, adj_close) VALUES (?, ?, ?)",
            rows
        )
        conn.commit()
        print(f"Saved {len(rows)} price records to database")
        
        # Verify the data was saved
        cursor.execute(f"SELECT COUNT(*) FROM {PRICES_TBL} WHERE ticker = ?", (ticker,))
        count = cursor.fetchone()[0]
        print(f"Total records for {ticker} in database: {count}")
        
    except Exception as e:
        print(f"Database error: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        if conn:
            conn.close()

def test_multiple_tickers():
    """Test a few different tickers"""
    tickers = ["AAPL", "MSFT", "GOOGL", "AGX", "STRL", "CLS", "UBER", "BRK-B"] 
    # Note: BRK.B might need to be BRK-B
    
    for ticker in tickers:
        simple_fetch_test(ticker)
        time.sleep(1)  # Avoid rate limiting

if __name__ == "__main__":
    test_multiple_tickers() 