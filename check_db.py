#!/usr/bin/env python3
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

# Set path to the database
DB_PATH = Path(__file__).parent / "alpha_picks.db"
PICKS_TBL = "picks"
PRICES_TBL = "prices"

def check_and_fix_database():
    print(f"Checking database at {DB_PATH}")
    
    # Check if database exists
    if not DB_PATH.exists():
        print("Database doesn't exist yet.")
        return
    
    # Connect to database
    with sqlite3.connect(DB_PATH) as conn:
        # Check picks table
        print("\n--- PICKS TABLE ---")
        picks_df = pd.read_sql(f"SELECT * FROM {PICKS_TBL}", conn)
        print(picks_df)
        
        # Check prices table
        print("\n--- PRICES TABLE ---")
        try:
            prices_df = pd.read_sql(f"SELECT * FROM {PRICES_TBL}", conn)
            print(prices_df)
        except:
            print("No prices table or it's empty")
        
        # Add some manual price data if prices table is empty
        c = conn.cursor()
        c.execute(f"SELECT COUNT(*) FROM {PRICES_TBL}")
        count = c.fetchone()[0]
        
        if count == 0:
            print("\n--- ADDING MANUAL PRICE DATA ---")
            stocks = ["AGX", "STRL", "CLS", "UBER", "BRK.B"]
            
            # Generate some dates (yesterday and today)
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            
            # Sample prices - in a real scenario these would come from yfinance
            prices = {
                "AGX": [60.0, 61.5],
                "STRL": [110.0, 112.0],
                "CLS": [20.5, 21.2],
                "UBER": [70.0, 71.5],
                "BRK.B": [410.0, 415.0]
            }
            
            # Insert data for each stock
            for ticker in stocks:
                # Yesterday's price
                c.execute(
                    f"INSERT INTO {PRICES_TBL} (price_date, ticker, adj_close) VALUES (?, ?, ?)",
                    (yesterday.strftime("%Y-%m-%d"), ticker, prices[ticker][0])
                )
                
                # Today's price
                c.execute(
                    f"INSERT INTO {PRICES_TBL} (price_date, ticker, adj_close) VALUES (?, ?, ?)",
                    (today.strftime("%Y-%m-%d"), ticker, prices[ticker][1])
                )
                
                print(f"Added price data for {ticker}")
            
            conn.commit()
            print("Manual price data added successfully")
            
            # Show updated prices table
            print("\n--- UPDATED PRICES TABLE ---")
            prices_df = pd.read_sql(f"SELECT * FROM {PRICES_TBL}", conn)
            print(prices_df)

if __name__ == "__main__":
    check_and_fix_database() 