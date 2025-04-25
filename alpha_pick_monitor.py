from __future__ import annotations

import email
import imaplib
import os
import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path
from typing import List, Tuple

import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from dotenv import load_dotenv

# ─────────────────────────── settings ────────────────────────────
DB_PATH = Path(__file__).with_name("alpha_picks.db")
PICKS_TBL = "picks"
PRICES_TBL = "prices"

ALPHA_EMAIL_SENDER = "subscriptions@seekingalpha.com"
ALPHA_SUBJECT_RE = re.compile(r"Alpha Pick.*?([A-Z]{1,5})")

load_dotenv()
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

# ─────────────────────────── db helpers ──────────────────────────
@contextmanager
def conn_ctx():
    c = sqlite3.connect(DB_PATH)
    try:
        yield c
    finally:
        c.commit(); c.close()

def init_db():
    with conn_ctx() as c:
        c.execute(
            f"CREATE TABLE IF NOT EXISTS {PICKS_TBL} (ticker TEXT, pick_date TEXT, status TEXT DEFAULT 'OPEN', UNIQUE(ticker, pick_date))"
        )
        c.execute(
            f"CREATE TABLE IF NOT EXISTS {PRICES_TBL} (ticker TEXT, price_date TEXT, adj_close REAL, UNIQUE(ticker, price_date))"
        )

# ─────────────────────────── core logic ─────────────────────────
# 1️⃣  email → picks

def fetch_email_picks(max_batches: int = 10) -> List[Tuple[str, str]]:
    """Return list of (ticker, pick_date) for unseen Alpha Pick emails."""
    # guard missing credentials
    if not all([EMAIL_HOST, EMAIL_USER, EMAIL_PASS]):
        print("[warn] EMAIL creds missing – skip email ingestion")
        return []
    # calculate the date 7 days ago
    cutoff_date = datetime.utcnow().date() - timedelta(days=7)
    with imaplib.IMAP4_SSL(EMAIL_HOST) as M:
        M.login(EMAIL_USER, EMAIL_PASS)
        M.select("INBOX")
        # calculate the date 7 days ago in IMAP format (DD-Mon-YYYY)
        cutoff_date = (datetime.utcnow() - timedelta(days=7)).date()
        typ, data = M.search(None, f'(FROM "{ALPHA_EMAIL_SENDER}" SINCE {cutoff_date.strftime("%d-%b-%Y")})')
        print(f"[info] IMAP search returned typ={typ}, data={data}")
        ids = data[0].split()
        out: List[Tuple[str, str]] = []
        for uid in ids:
            # fetch the full message
            _, msg_data = M.fetch(uid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            # extract and decode subject
            subj, _ = decode_header(msg["Subject"])[0]
            subj = subj.decode() if isinstance(subj, bytes) else subj
            # parse and filter by date header
            date_hdr = msg.get("Date")
            msg_dt = email.utils.parsedate_to_datetime(date_hdr).date()
            print(f"[debug] Email date: {msg_dt}, cutoff: {cutoff_date}")
            if msg_dt < cutoff_date:
                # skip emails older than 7 days
                print(f"[debug] Skipping old email: {subj}")
                continue
            # only process emails matching Alpha Pick in subject
            m = ALPHA_SUBJECT_RE.search(subj or "")
            if not m:
                print(f"[debug] Skipping non-Alpha Pick email: {subj}")
                continue
            # valid pick email
            ticker = m.group(1).upper()
            pick_dt = email.utils.parsedate_to_datetime(date_hdr).date().isoformat()
            print(f"[info] Pick email: {subj}, Date: {date_hdr}")
            out.append((ticker, pick_dt))
        return out

def save_picks(rows: List[Tuple[str, str]]):
    with conn_ctx() as c:
        c.executemany(
            f"INSERT OR IGNORE INTO {PICKS_TBL} (ticker, pick_date) VALUES (?, ?)", rows
        )
        if rows:
            discord_notify(f"📈 New Alpha Picks: {', '.join(r[0] for r in rows)}")

def discord_notify(text: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": text}, timeout=10)
    except Exception:
        pass

# 2️⃣  yfinance → prices

def update_prices(days_back: int = 14):
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    with conn_ctx() as c:
        tickers = [row[0] for row in c.execute(f"SELECT DISTINCT ticker FROM {PICKS_TBL}")]
    if not tickers:
        return
    df = yf.download(tickers, start=cutoff)["Adj Close"].dropna(how="all")
    if isinstance(df, pd.Series):
        df = df.to_frame()
    df = df.stack().reset_index().rename(columns={"level_1": "ticker", 0: "adj_close"})
    with conn_ctx() as c:
        c.executemany(
            f"INSERT OR IGNORE INTO {PRICES_TBL} (price_date, ticker, adj_close) VALUES (?, ?, ?)",
            df[["Date", "ticker", "adj_close"]].values.tolist(),
        )

# 3️⃣  analytics

def load_view() -> pd.DataFrame:
    with conn_ctx() as c:
        picks = pd.read_sql(f"SELECT * FROM {PICKS_TBL}", c, parse_dates=["pick_date"])
        prices = pd.read_sql(f"SELECT * FROM {PRICES_TBL}", c, parse_dates=["price_date"])
    if picks.empty or prices.empty:
        return pd.DataFrame()
    latest = (
        prices.sort_values("price_date")
        .drop_duplicates(["ticker"], keep="last")
        .rename(columns={"adj_close": "latest_price"})[["ticker", "latest_price"]]
    )
    first = (
        prices.sort_values("price_date")
        .drop_duplicates(["ticker"], keep="first")
        .rename(columns={"adj_close": "entry_price"})[["ticker", "entry_price"]]
    )
    df = picks.merge(latest, on="ticker").merge(first, on="ticker")
    df["return_pct"] = (df.latest_price / df.entry_price - 1) * 100
    df["days_held"] = (pd.Timestamp("now").normalize() - df.pick_date).dt.days
    return df.sort_values("pick_date", ascending=False)

# ─────────────────────────── streamlit ──────────────────────────

def run_streamlit():
    st.set_page_config(layout="wide", page_title="Alpha Pick Monitor")
    st.title("📊 Alpha Pick Monitor")

    # 🚀 upload manual CSV
    up = st.file_uploader("Upload Alpha Picks CSV (ticker,pick_date)")
    if up:
        df_new = pd.read_csv(up)
        save_picks(df_new[["ticker", "pick_date"]].values.tolist())
        st.success(f"Imported {len(df_new)} rows")

    if st.button("Fetch email & prices now"):
        ingest_email(); update_prices()
        st.experimental_rerun()

    df = load_view()
    if df.empty:
        st.info("No data yet – click the button to ingest emails or upload CSV.")
        st.stop()
    st.dataframe(df, use_container_width=True)

# ───────────────────────────── CLI ──────────────────────────────

def ingest_email():
    rows = fetch_email_picks()
    if rows:
        save_picks(rows)
        print(f"[✓] saved {len(rows)} new picks")


def main():
    init_db()
    if "streamlit" in sys.modules:
        run_streamlit()
        return
    if "--ingest-email" in sys.argv:
        ingest_email(); return
    if "--ingest-prices" in sys.argv:
        update_prices(); return
    if "--ingest" in sys.argv:
        ingest_email(); update_prices(); return
    print("Usage:\n  --ingest-email     fetch unseen Alpha Pick emails\n  --ingest-prices    refresh Yahoo prices\n  --ingest           both steps\n  streamlit run alpha_pick_monitor.py  # launch dashboard")

if __name__ == "__main__":
    main()

