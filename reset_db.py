#!/usr/bin/env python3
import sqlite3
import os
from pathlib import Path
from datetime import datetime

# Set path to the database
DB_PATH = Path(__file__).parent / "alpha_picks.db"
PICKS_TBL = "picks"
PRICES_TBL = "prices"

def reset_database():
    print(f"Cleaning database at {DB_PATH}")
    
    # Check if database exists
    if not DB_PATH.exists():
        print("Database doesn't exist yet. Will be created on first run.")
        return
    
    # Connect to database and delete all records
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        
        # Check if tables exist before trying to delete from them
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in c.fetchall()]
        
        if PICKS_TBL in tables:
            c.execute(f"DELETE FROM {PICKS_TBL}")
            print(f"Cleared {PICKS_TBL} table")
        
        if PRICES_TBL in tables:
            c.execute(f"DELETE FROM {PRICES_TBL}")
            print(f"Cleared {PRICES_TBL} table")
        
        # Add the five stocks from the image
        today = datetime.now().strftime("%Y-%m-%d")
        stocks = ["AGX", "STRL", "CLS", "UBER", "BRK.B"]
        
        for stock in stocks:
            c.execute(f"INSERT INTO {PICKS_TBL} (ticker, pick_date) VALUES (?, ?)", 
                     (stock, today))
            print(f"Added {stock} to picks table")
        
        conn.commit()
        print("Database reset complete")

if __name__ == "__main__":
    reset_database() 