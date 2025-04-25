#!/usr/bin/env python3
"""
Example script to connect to Gmail, fetch unseen Alpha Pick emails,
and print the ticker and pick date.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

from alpha_pick_monitor import fetch_email_picks


def main():
    # Default to Gmail IMAP host if none provided
    EMAIL_HOST = os.getenv('EMAIL_HOST', 'imap.gmail.com')
    EMAIL_USER = os.getenv('EMAIL_USER')
    EMAIL_PASS = os.getenv('EMAIL_PASS')

    if not all([EMAIL_HOST, EMAIL_USER, EMAIL_PASS]):
        print("Please set EMAIL_HOST, EMAIL_USER, and EMAIL_PASS in your environment or .env file.")
        return

    # Override module-level settings
    import alpha_pick_monitor
    alpha_pick_monitor.EMAIL_HOST = EMAIL_HOST
    alpha_pick_monitor.EMAIL_USER = EMAIL_USER
    alpha_pick_monitor.EMAIL_PASS = EMAIL_PASS

    picks = fetch_email_picks()
    if picks:
        print("Fetched new Alpha Picks:")
        for ticker, pick_date in picks:
            print(f"- {ticker} on {pick_date}")
    else:
        print("No new Alpha Picks found.")


if __name__ == '__main__':
    main() 