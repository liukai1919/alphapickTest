#!/usr/bin/env python3
import sys
import os
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

# Import functions from alpha_pick_monitor
from alpha_pick_monitor import update_prices, init_db

if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    
    print("Updating stock prices...")
    # Use a longer timeframe to ensure we get data
    update_prices(days_back=30)
    
    print("Done! Please refresh the Streamlit app now.") 