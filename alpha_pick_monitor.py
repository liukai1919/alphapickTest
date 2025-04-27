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
import math
import json
import numpy as np

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
            f"CREATE TABLE IF NOT EXISTS {PICKS_TBL} (ticker TEXT, pick_date TEXT, status TEXT DEFAULT 'OPEN', is_watchlist INTEGER DEFAULT 0, UNIQUE(ticker, pick_date))"
        )
        c.execute(
            f"CREATE TABLE IF NOT EXISTS {PRICES_TBL} (ticker TEXT, price_date TEXT, adj_close REAL, UNIQUE(ticker, price_date))"
        )
        
        # Add is_watchlist column if it doesn't exist
        try:
            c.execute(f"SELECT is_watchlist FROM {PICKS_TBL} LIMIT 1")
        except sqlite3.OperationalError:
            print("Adding is_watchlist column to picks table")
            c.execute(f"ALTER TABLE {PICKS_TBL} ADD COLUMN is_watchlist INTEGER DEFAULT 0")

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

def save_picks(rows: List[Tuple[str, str]], is_watchlist: bool = False):
    with conn_ctx() as c:
        for ticker, pick_date in rows:
            c.execute(
                f"INSERT OR IGNORE INTO {PICKS_TBL} (ticker, pick_date, is_watchlist) VALUES (?, ?, ?)", 
                (ticker, pick_date, 1 if is_watchlist else 0)
            )
        if rows:
            if not is_watchlist:
                discord_notify(f"📈 New Alpha Picks: {', '.join(r[0] for r in rows)}")
            else:
                discord_notify(f"👀 New Watchlist Items: {', '.join(r[0] for r in rows)}")

def delete_pick(ticker: str, is_watchlist: bool = False):
    """Delete a ticker from the picks table"""
    with conn_ctx() as c:
        cursor = c.cursor()
        if is_watchlist:
            cursor.execute(f"DELETE FROM {PICKS_TBL} WHERE ticker = ? AND is_watchlist = 1", (ticker,))
        else:
            cursor.execute(f"DELETE FROM {PICKS_TBL} WHERE ticker = ? AND is_watchlist = 0", (ticker,))
        
        # Also delete price data if no other entries use this ticker
        cursor.execute(f"SELECT COUNT(*) FROM {PICKS_TBL} WHERE ticker = ?", (ticker,))
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"DELETE FROM {PRICES_TBL} WHERE ticker = ?", (ticker,))
            
        if is_watchlist:
            discord_notify(f"🗑️ Removed from watchlist: {ticker}")
        else:
            discord_notify(f"🗑️ Removed from picks: {ticker}")
            
def move_to_watchlist(ticker: str):
    """Move a ticker from picks to watchlist"""
    with conn_ctx() as c:
        cursor = c.cursor()
        cursor.execute(f"UPDATE {PICKS_TBL} SET is_watchlist = 1 WHERE ticker = ? AND is_watchlist = 0", (ticker,))
        discord_notify(f"👀 Moved to watchlist: {ticker}")
        
def move_to_picks(ticker: str):
    """Move a ticker from watchlist to picks"""
    with conn_ctx() as c:
        cursor = c.cursor()
        cursor.execute(f"UPDATE {PICKS_TBL} SET is_watchlist = 0 WHERE ticker = ? AND is_watchlist = 1", (ticker,))
        discord_notify(f"📈 Moved to picks: {ticker}")

def discord_notify(text: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": text}, timeout=10)
    except Exception:
        pass

# 2️⃣  yfinance → prices

def get_stock_data(auto_refresh: bool = False, refresh_trigger: bool = False):
    """
    获取股票数据，包含时间戳并支持自动刷新功能
    
    Args:
        auto_refresh: 是否启用自动刷新
        refresh_trigger: 是否触发刷新
        
    Returns:
        成功标志和消息
    """
    # 读取股票代码列表
    with conn_ctx() as c:
        cursor = c.cursor()
        cursor.execute(f"SELECT DISTINCT ticker FROM {PICKS_TBL}")
        tickers = [row[0] for row in cursor.fetchall()]
    
    if not tickers:
        return False, "数据库中没有股票代码"
    
    # 如果请求添加新股票，处理添加逻辑
    if 'new_stock_input' in st.session_state and st.session_state.new_stock_input:
        new_ticker = st.session_state.new_stock_input.strip().upper()
        
        # 检查是否已经存在
        if new_ticker in tickers:
            return False, f"{new_ticker} 已存在于数据库中"
        
        # 添加新股票到数据库
        today = datetime.now().date().isoformat()
        save_picks([(new_ticker, today)])
        
        # 更新股票列表
        tickers.append(new_ticker)
        
        # 清空输入
        st.session_state.new_stock_input = ""
    
    # 创建进度指示器
    progress_text = st.empty()
    progress_bar = st.progress(0)
    results_container = st.empty()
    
    # 检查是否需要刷新数据
    should_refresh = auto_refresh or refresh_trigger
    
    if should_refresh:
        progress_text.text("正在获取股票数据...")
        success_results = []
        failed_tickers = []
        
        for i, ticker in enumerate(tickers):
            # 更新进度
            progress_text.text(f"正在更新 {ticker} ({i+1}/{len(tickers)})")
            progress_bar.progress((i) / len(tickers))
            
            # 获取股票数据
            ticker_prices = fetch_ticker_prices(ticker)
            
            # 保存数据到数据库
            if ticker_prices:
                with conn_ctx() as c:
                    cursor = c.cursor()
                    cursor.executemany(
                        f"INSERT OR IGNORE INTO {PRICES_TBL} (price_date, ticker, adj_close) VALUES (?, ?, ?)",
                        ticker_prices
                    )
                latest_price = ticker_prices[-1][2]  # 最新价格是最后一个数据点
                success_results.append(f"{ticker}: ${latest_price:.2f}")
            else:
                failed_tickers.append(ticker)
            
            # 更新显示结果
            update_text = ""
            if success_results:
                update_text += f"**成功更新 ({len(success_results)}):** {', '.join(success_results)}\n\n"
            if failed_tickers:
                update_text += f"**更新失败 ({len(failed_tickers)}):** {', '.join(failed_tickers)}"
            
            results_container.markdown(update_text)
            
            # 更新进度条
            progress_bar.progress((i + 1) / len(tickers))
        
        # 更新最后获取时间
        st.session_state.last_update = datetime.now()
        
        # 清理进度显示
        progress_text.empty()
        
        if len(success_results) > 0:
            return True, f"更新了 {len(success_results)} 支股票的价格数据。{len(failed_tickers)} 支股票更新失败。"
        else:
            return False, "所有股票更新失败，请检查网络连接或尝试使用不同的股票代码格式。"
    
    return False, "未触发数据刷新"

def fetch_ticker_prices(ticker, days_back=90, retry_count=3, retry_delay=1):
    """Fetch prices for a single ticker with retries and better error handling"""
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    # 特殊处理某些股票代码
    ticker_to_use = ticker
    if ticker == "BRK.B":
        ticker_to_use = "BRK-B"  # 伯克希尔B类股需要特殊处理
    
    for attempt in range(retry_count):
        try:
            print(f"Attempting to fetch data for {ticker} (using {ticker_to_use})")
            
            # 使用yfinance的Ticker对象方式获取数据，这通常更可靠
            ticker_obj = yf.Ticker(ticker_to_use)
            data = ticker_obj.history(period=f"{days_back}d")
            
            if data.empty:
                print(f"Empty data for {ticker}")
                time.sleep(retry_delay)
                continue
            
            print(f"Data columns: {data.columns.tolist()}")
            print(f"Data shape: {data.shape}")
            print(f"Data index: {data.index[0]} to {data.index[-1]}")
            
            # 使用Close列获取价格数据
            if 'Close' in data.columns:
                # 预处理 - 按日期排序
                data = data.sort_index()
                
                # 转换为所需格式
                result = []
                for date, row in data.iterrows():
                    price = row['Close']
                    if not pd.isna(price):  # 跳过NaN值
                        date_str = date.strftime('%Y-%m-%d')
                        result.append((date_str, ticker, float(price)))
                
                if result:
                    earliest_price = result[0][2]
                    latest_price = result[-1][2]
                    print(f"Got {len(result)} days of price data for {ticker}")
                    print(f"Earliest price ({result[0][0]}): ${earliest_price:.2f}")
                    print(f"Latest price ({result[-1][0]}): ${latest_price:.2f}")
                    return result
            else:
                print(f"Missing 'Close' column for {ticker}")
                print(f"Available columns: {data.columns.tolist()}")
                time.sleep(retry_delay)
                continue
                
            print(f"No valid prices for {ticker}")
            time.sleep(retry_delay)
            
        except Exception as e:
            print(f"Error fetching {ticker}: {str(e)}")
            import traceback
            traceback.print_exc()
            time.sleep(retry_delay)
    
    print(f"Failed to fetch prices for {ticker} after {retry_count} attempts")
    return []

def update_prices_with_progress(days_back=30):
    """Update prices with progress indicator for Streamlit UI"""
    try:
        # Get list of tickers
        with conn_ctx() as c:
            cursor = c.cursor()
            cursor.execute(f"SELECT DISTINCT ticker FROM {PICKS_TBL}")
            tickers = [row[0] for row in cursor.fetchall()]
        
        if not tickers:
            st.warning("No tickers found in the database")
            return False, "No tickers found"
        
        # Show progress
        progress_text = st.empty()
        progress_bar = st.progress(0)
        results_container = st.empty()
        
        total_updated = 0
        failed_tickers = []
        success_results = []
        
        for i, ticker in enumerate(tickers):
            progress_text.text(f"Updating {ticker} ({i+1}/{len(tickers)})")
            progress_bar.progress((i) / len(tickers))
            
            # Fetch prices for this ticker
            ticker_prices = fetch_ticker_prices(ticker, days_back=days_back)
            
            # Save to database if we got prices
            if ticker_prices:
                with conn_ctx() as c:
                    cursor = c.cursor()
                    cursor.executemany(
                        f"INSERT OR IGNORE INTO {PRICES_TBL} (price_date, ticker, adj_close) VALUES (?, ?, ?)",
                        ticker_prices
                    )
                total_updated += 1
                latest_price = ticker_prices[-1][2]  # 最新价格是最后一个数据点
                success_results.append(f"{ticker}: ${latest_price:.2f}")
            else:
                failed_tickers.append(ticker)
                
            # 更新结果显示
            update_text = ""
            if success_results:
                update_text += f"**成功更新 ({len(success_results)}):** {', '.join(success_results)}\n\n"
            if failed_tickers:
                update_text += f"**更新失败 ({len(failed_tickers)}):** {', '.join(failed_tickers)}"
            
            results_container.markdown(update_text)
                
            # Update progress bar
            progress_bar.progress((i + 1) / len(tickers))
        
        # 更新最后获取时间
        st.session_state.last_update = datetime.now()
        
        # Final update with summary
        progress_text.empty()
        
        if total_updated > 0:
            return True, f"更新了 {total_updated} 支股票的价格数据。{len(failed_tickers)} 支股票更新失败。"
        else:
            return False, "所有股票更新失败，请检查网络连接或尝试使用不同的股票代码格式。"
        
    except Exception as e:
        import traceback
        error_msg = f"Error updating prices: {str(e)}"
        st.error(error_msg)
        st.exception(traceback.format_exc())
        return False, error_msg

# 3️⃣  analytics

def load_view(watchlist_only: bool = False) -> pd.DataFrame:
    """
    从数据库加载并处理股票数据
    
    Args:
        watchlist_only: 是否只加载观察列表
        
    Returns:
        包含处理后股票数据的DataFrame
    """
    with conn_ctx() as c:
        cursor = c.cursor()
        # 根据watchlist状态过滤
        watchlist_filter = "AND is_watchlist = 1" if watchlist_only else "AND is_watchlist = 0"
        cursor.execute(
            f"SELECT * FROM {PICKS_TBL} WHERE 1=1 {watchlist_filter}"
        )
        picks_rows = cursor.fetchall()
        
        if not picks_rows:
            print("No picks found")
            return pd.DataFrame()
            
        # 获取列名
        columns = [desc[0] for desc in cursor.description]
        picks = pd.DataFrame(picks_rows, columns=columns)
        if 'pick_date' in picks.columns:
            picks['pick_date'] = pd.to_datetime(picks['pick_date'])
        
        # 获取所有价格数据
        cursor.execute(f"SELECT * FROM {PRICES_TBL}")
        prices_rows = cursor.fetchall()
        
        if not prices_rows:
            print("No price data found")
            return pd.DataFrame()
            
        # 获取价格表列名
        price_columns = [desc[0] for desc in cursor.description]
        prices = pd.DataFrame(prices_rows, columns=price_columns)
        if 'price_date' in prices.columns:
            prices['price_date'] = pd.to_datetime(prices['price_date'])
            
    # 调试输出
    print(f"Loaded {len(picks)} picks and {len(prices)} price records")
    print(f"Picks columns: {picks.columns.tolist()}")
    print(f"Prices columns: {prices.columns.tolist()}")
    
    # 初始化结果DataFrame
    result_data = []
    for _, pick in picks.iterrows():
        ticker = pick['ticker']
        pick_date = pick['pick_date']
        print(f"\nProcessing {ticker}, pick date: {pick_date}")
        
        # 获取此股票的所有价格记录
        ticker_prices = prices[prices['ticker'] == ticker].sort_values('price_date')
        if ticker_prices.empty:
            print(f"No price data for {ticker}")
            continue
            
        # 打印所有价格记录以便调试
        print(f"All prices for {ticker}:")
        for idx, price_row in ticker_prices.iterrows():
            print(f"  {price_row['price_date'].strftime('%Y-%m-%d')}: ${float(price_row['adj_close']):.2f}")
        
        # 先尝试获取购买当天的价格
        same_day_price = ticker_prices[ticker_prices['price_date'] == pick_date]
        if not same_day_price.empty:
            # 使用当天价格
            entry_price = float(same_day_price.iloc[0]['adj_close'])
            entry_date = same_day_price.iloc[0]['price_date']
        else:
            # 如果当天没有价格，找最接近的价格（优先选择购买日期之前的最新价格）
            before_prices = ticker_prices[ticker_prices['price_date'] < pick_date]
            if not before_prices.empty:
                # 使用购买日期前的最近价格
                entry_price = float(before_prices.iloc[-1]['adj_close']) 
                entry_date = before_prices.iloc[-1]['price_date']
            else:
                # 如果之前没有价格，使用之后的第一个价格
                entry_price = float(ticker_prices.iloc[0]['adj_close'])
                entry_date = ticker_prices.iloc[0]['price_date']
        
        # 获取最新价格
        latest_price = float(ticker_prices.iloc[-1]['adj_close'])
        latest_date = ticker_prices.iloc[-1]['price_date']
        print(f"Latest price: ${latest_price:.2f} on {latest_date.strftime('%Y-%m-%d')}")
        
        # 计算回报
        return_pct = ((latest_price / entry_price) - 1) * 100
        print(f"Return: {return_pct:.2f}%")
        
        # 计算持有天数
        days_held = (pd.Timestamp.now().normalize() - pick_date).days
        
        # 添加到结果中
        result_data.append({
            'ticker': ticker,
            'pick_date': pick_date,
            'latest_price': latest_price,
            'entry_price': entry_price,
            'return_pct': return_pct,
            'days_held': days_held,
            'status': pick.get('status', 'OPEN'),
            'is_watchlist': pick.get('is_watchlist', 0)
        })
    
    if not result_data:
        print("No result data after processing")
        return pd.DataFrame()
        
    # 转换为DataFrame并排序
    result_df = pd.DataFrame(result_data)
    print(f"\nFinal result: {len(result_df)} rows")
    print(result_df)
    return result_df.sort_values('pick_date', ascending=False)

# ─────────────────────────── streamlit ──────────────────────────

def run_streamlit():
    st.set_page_config(layout="wide", page_title="Alpha Pick Monitor")
    st.title("📊 Alpha Pick Monitor")
    
    # 存储上次更新时间
    if 'last_update' not in st.session_state:
        st.session_state.last_update = None
    
    # 添加自动刷新选项
    with st.sidebar:
        st.title("设置")
        auto_refresh = st.checkbox("自动刷新价格", value=False)
        refresh_interval = st.slider("刷新间隔(分钟)", 5, 60, 15, disabled=not auto_refresh)
        
        # 显示上次更新时间
        if st.session_state.last_update:
            st.info(f"上次更新: {st.session_state.last_update.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 计算下次更新时间
            if auto_refresh:
                next_update = st.session_state.last_update + timedelta(minutes=refresh_interval)
                now = datetime.now()
                if now >= next_update:
                    # 触发自动更新
                    st.session_state.trigger_update = True
                    st.experimental_rerun()
                else:
                    # 显示倒计时
                    remaining = (next_update - now).seconds
                    mins = remaining // 60
                    secs = remaining % 60
                    st.text(f"下次更新: {mins}分{secs}秒后")
        
    # 创建tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Alpha Picks", "Watchlist", "Batch Add", "风险监控"])

    with tab1:
        st.header("📈 Alpha Picks")
        
        # 只保留更新价格按钮
        if st.button("🔄 Update Prices", key="update_prices_picks"):
            with st.spinner("Updating prices..."):
                success, message = update_prices_with_progress()
            if success:
                st.success(message)
            else:
                st.error(message)
            # 不立即刷新以便用户查看结果
            st.button("刷新数据", on_click=lambda: st.rerun())

        # Load and display picks
        df = load_view(watchlist_only=False)
        if not df.empty:
            # 格式化要显示的DataFrame
            display_df = df.copy()
            
            # 选择要显示的列并设置其顺序
            display_columns = ["ticker", "pick_date", "latest_price", "entry_price", "return_pct", "days_held"]
            
            # 确保所有需要的列都存在
            for col in display_columns:
                if col not in display_df.columns:
                    display_df[col] = None
            
            # 只保留需要显示的列，并按正确顺序排列
            display_df = display_df[display_columns]
            
            # 将价格数据四舍五入到小数点后两位
            if "latest_price" in display_df.columns:
                display_df["latest_price"] = display_df["latest_price"].round(2)
            if "entry_price" in display_df.columns:
                display_df["entry_price"] = display_df["entry_price"].round(2)
            if "return_pct" in display_df.columns:
                display_df["return_pct"] = display_df["return_pct"].round(2)
            
            # 计算并显示摘要统计
            if not display_df["ticker"].empty:
                avg_return = display_df["return_pct"].mean()
                positive_returns = (display_df["return_pct"] > 0).sum()
                total_stocks = len(display_df)
                success_rate = (positive_returns / total_stocks * 100) if total_stocks > 0 else 0
                
                summary = f"股价更新: {', '.join([f'{t}: ${p:.2f}' for t, p in zip(display_df['ticker'], display_df['latest_price']) if not pd.isna(p)])}"
                st.markdown(summary)
                
                stats = f"平均回报率: **{avg_return:.2f}%** | 成功率: **{success_rate:.1f}%** ({positive_returns}/{total_stocks})"
                st.markdown(stats)
            
            # 显示数据表格
            st.dataframe(
                display_df,
                column_config={
                    "ticker": st.column_config.TextColumn("Ticker"),
                    "pick_date": st.column_config.DateColumn("Date Added"),
                    "latest_price": st.column_config.NumberColumn("Current Price", format="$%.2f"),
                    "entry_price": st.column_config.NumberColumn("Entry Price", format="$%.2f"),
                    "return_pct": st.column_config.NumberColumn("Return", format="%.2f%%"),
                    "days_held": st.column_config.NumberColumn("Days Held")
                },
                use_container_width=True,
                hide_index=True
            )
            
            # Add action buttons below the table
            st.subheader("Actions")
            
            cols = st.columns(4)
            with cols[0]:
                if not df.empty:
                    ticker_to_delete = st.selectbox("Select ticker to delete:", df['ticker'].unique(), key="delete_pick")
                    if st.button("🗑️ Delete", key="delete_pick_btn"):
                        delete_pick(ticker_to_delete)
                        st.success(f"Deleted {ticker_to_delete}")
                        st.rerun()
            
            with cols[1]:
                if not df.empty:
                    ticker_to_watch = st.selectbox("Select ticker to move to watchlist:", df['ticker'].unique(), key="move_to_watch")
                    if st.button("👀 Move to Watchlist", key="move_to_watch_btn"):
                        move_to_watchlist(ticker_to_watch)
                        st.success(f"Moved {ticker_to_watch} to watchlist")
                        st.rerun()
        else:
            st.info("No picks yet – use the Batch Add tab or upload a CSV.")
    
    with tab2:
        st.header("👀 Watchlist")
        
        # Add update prices button at the top
        if st.button("🔄 Update Prices", key="update_prices_watch"):
            with st.spinner("Updating prices..."):
                success, message = update_prices_with_progress()
            if success:
                st.success(message)
            else:
                st.error(message)
            # 不立即刷新以便用户查看结果
            st.button("刷新数据", on_click=lambda: st.rerun())
        
        # Load and display watchlist
        watch_df = load_view(watchlist_only=True)
        if not watch_df.empty:
            # 格式化要显示的DataFrame
            display_df = watch_df.copy()
            
            # 选择要显示的列并设置其顺序
            display_columns = ["ticker", "pick_date", "latest_price", "entry_price", "return_pct", "days_held"]
            
            # 确保所有需要的列都存在
            for col in display_columns:
                if col not in display_df.columns:
                    display_df[col] = None
            
            # 只保留需要显示的列，并按正确顺序排列
            display_df = display_df[display_columns]
            
            # 将价格数据四舍五入到小数点后两位
            if "latest_price" in display_df.columns:
                display_df["latest_price"] = display_df["latest_price"].round(2)
            if "entry_price" in display_df.columns:
                display_df["entry_price"] = display_df["entry_price"].round(2)
            if "return_pct" in display_df.columns:
                display_df["return_pct"] = display_df["return_pct"].round(2)
            
            # 计算并显示摘要统计
            if not display_df["ticker"].empty:
                avg_return = display_df["return_pct"].mean()
                positive_returns = (display_df["return_pct"] > 0).sum()
                total_stocks = len(display_df)
                success_rate = (positive_returns / total_stocks * 100) if total_stocks > 0 else 0
                
                summary = f"股价更新: {', '.join([f'{t}: ${p:.2f}' for t, p in zip(display_df['ticker'], display_df['latest_price']) if not pd.isna(p)])}"
                st.markdown(summary)
                
                stats = f"平均回报率: **{avg_return:.2f}%** | 成功率: **{success_rate:.1f}%** ({positive_returns}/{total_stocks})"
                st.markdown(stats)
            
            # 显示数据表格
            st.dataframe(
                display_df,
                column_config={
                    "ticker": st.column_config.TextColumn("Ticker"),
                    "pick_date": st.column_config.DateColumn("Date Added"),
                    "latest_price": st.column_config.NumberColumn("Current Price", format="$%.2f"),
                    "entry_price": st.column_config.NumberColumn("Entry Price", format="$%.2f"),
                    "return_pct": st.column_config.NumberColumn("Return", format="%.2f%%"),
                    "days_held": st.column_config.NumberColumn("Days Held")
                },
                use_container_width=True,
                hide_index=True
            )
            
            # Add action buttons
            st.subheader("Actions")
            
            cols = st.columns(4)
            with cols[0]:
                ticker_to_delete = st.selectbox("Select ticker to delete:", watch_df['ticker'].unique(), key="delete_watch")
                if st.button("🗑️ Delete", key="delete_watch_btn"):
                    delete_pick(ticker_to_delete, is_watchlist=True)
                    st.success(f"Deleted {ticker_to_delete}")
                    st.rerun()
            
            with cols[1]:
                ticker_to_pick = st.selectbox("Select ticker to move to picks:", watch_df['ticker'].unique(), key="move_to_pick")
                if st.button("📈 Move to Picks", key="move_to_pick_btn"):
                    move_to_picks(ticker_to_pick)
                    st.success(f"Moved {ticker_to_pick} to picks")
                    st.rerun()
        else:
            st.info("No stocks in watchlist yet.")
            
        # Add form to add new watchlist items
        st.subheader("Add to Watchlist")
        with st.form("add_to_watchlist"):
            col1, col2 = st.columns([3, 1])
            with col1:
                ticker = st.text_input("Ticker symbol:", key="new_watch_ticker").upper()
            with col2:
                pick_date = st.date_input("Date:", key="new_watch_date")
            
            submitted = st.form_submit_button("Add to Watchlist")
            if submitted and ticker:
                save_picks([(ticker, pick_date.strftime("%Y-%m-%d"))], is_watchlist=True)
                with st.spinner("Updating prices..."):
                    success, message = update_prices_with_progress(days_back=90)
                if success:
                    st.success(f"Added {ticker} to watchlist and updated prices")
                else:
                    st.warning(f"Added {ticker} to watchlist but price update failed: {message}")
                st.rerun()
    
    with tab3:
        st.header("Batch Add Stocks")
        
        # Add radio button to choose between picks and watchlist
        add_type = st.radio("Add to:", ["Alpha Picks", "Watchlist"], horizontal=True)
        is_watchlist = add_type == "Watchlist"
        
        # Text area for batch input
        st.write("Enter stock tickers (one per line or comma-separated):")
        batch_input = st.text_area("", placeholder="AAPL\nMSFT\nGOOGL\nor: AAPL, MSFT, GOOGL", height=200)
        
        # Date picker for all stocks
        pick_date = st.date_input("Pick Date", value=datetime.utcnow().date())
        
        # Button to process input
        if st.button("Add Stocks"):
            if batch_input:
                # Process input - handle both comma-separated and newline formats
                if "," in batch_input:
                    tickers = [t.strip().upper() for t in batch_input.split(",")]
                else:
                    tickers = [t.strip().upper() for t in batch_input.split("\n")]
                
                # Filter out empty strings
                tickers = [t for t in tickers if t]
                
                if tickers:
                    # Format date as string
                    date_str = pick_date.strftime("%Y-%m-%d")
                    
                    # Prepare data for saving
                    rows = [(ticker, date_str) for ticker in tickers]
                    
                    # Save to database
                    save_picks(rows, is_watchlist=is_watchlist)
                    
                    # Create a spinner to show progress
                    with st.spinner("Fetching stock prices... this may take a moment"):
                        try:
                            # Create a status container
                            status = st.empty()
                            status.info(f"Fetching prices for {len(tickers)} stocks...")
                            
                            # Process each ticker individually with better handling
                            success_count = 0
                            price_rows = []
                            
                            progress_bar = st.progress(0)
                            for i, ticker in enumerate(tickers):
                                # Update status with current ticker
                                status.info(f"Fetching prices for {ticker} ({i+1}/{len(tickers)})...")
                                
                                # Fetch prices with our improved function
                                ticker_prices = fetch_ticker_prices(ticker)
                                
                                if ticker_prices:
                                    price_rows.extend(ticker_prices)
                                    success_count += 1
                                    
                                # Update progress bar
                                progress_bar.progress((i + 1) / len(tickers))
                                
                            # Save all prices to the database
                            if price_rows:
                                with conn_ctx() as c:
                                    cursor = c.cursor()
                                    cursor.executemany(
                                        f"INSERT OR IGNORE INTO {PRICES_TBL} (price_date, ticker, adj_close) VALUES (?, ?, ?)",
                                        price_rows
                                    )
                                
                                # Clear the progress indicators
                                status.empty()
                                progress_bar.empty()
                                
                                # Show success message
                                destination = "watchlist" if is_watchlist else "Alpha Picks"
                                st.success(f"Successfully added {len(tickers)} stocks to {destination} and fetched prices for {success_count} of them!")
                                
                                # Show which tickers failed
                                if success_count < len(tickers):
                                    failed_tickers = [t for t in tickers if t not in [row[1] for row in price_rows]]
                                    st.warning(f"Could not fetch prices for {len(failed_tickers)} stocks: {', '.join(failed_tickers)}")
                            else:
                                # All price fetches failed
                                status.empty()
                                progress_bar.empty()
                                
                                st.warning("Could not fetch prices from Yahoo Finance. Trying alternative method...")
                                
                                # Try using the improved function that handles special tickers
                                with st.spinner("Trying alternative price fetch method..."):
                                    success, message = update_prices_with_progress(days_back=90)
                                
                                if success:
                                    st.success(f"Added {len(tickers)} stocks and updated prices using alternative method")
                                else:
                                    st.warning(f"Added stocks but price update failed: {message}")
                                    
                                    # As last resort, add sample data
                                    if st.button("Add sample price data instead"):
                                        # Manually add sample price data for demonstration
                                        today = datetime.now().date()
                                        yesterday = today - timedelta(days=1)
                                        
                                        with conn_ctx() as c:
                                            cursor = c.cursor()
                                            sample_rows = []
                                            for ticker in tickers:
                                                # Use a more realistic approach - check web for actual price range
                                                import random
                                                base_price = random.uniform(30, 200)  # More realistic range
                                                yesterday_price = base_price * (0.95 + 0.1 * random.random())
                                                today_price = yesterday_price * (0.98 + 0.04 * random.random())
                                                
                                                # Insert sample prices
                                                sample_rows.append((yesterday.strftime("%Y-%m-%d"), ticker, float(yesterday_price)))
                                                sample_rows.append((today.strftime("%Y-%m-%d"), ticker, float(today_price)))
                                            
                                            cursor.executemany(
                                                f"INSERT OR IGNORE INTO {PRICES_TBL} (price_date, ticker, adj_close) VALUES (?, ?, ?)",
                                                sample_rows
                                            )
                                        
                                        st.info(f"Added sample price data for demonstration purposes.")
                        except Exception as e:
                            st.error(f"Error fetching prices: {str(e)}")
                            import traceback
                            st.exception(traceback.format_exc())
                    
                    # Show the added stocks
                    st.write("Added stocks:")
                    st.write(", ".join(tickers))
                else:
                    st.error("No valid tickers found in the input.")
            else:
                st.error("Please enter at least one stock ticker.")
    
    with tab4:
        # 导入风险仪表盘
        try:
            from risk_dashboard import render_risk_dashboard
            render_risk_dashboard()
        except Exception as e:
            st.error(f"无法加载风险仪表盘: {str(e)}")
            st.info("请确保已安装所需依赖并创建了风险监控模块")

# ───────────────────────────── CLI ──────────────────────────────

def ingest_email():
    rows = fetch_email_picks()
    if rows:
        save_picks(rows)
        print(f"[✓] saved {len(rows)} new picks")

def update_prices(days_back: int = 14):
    """Update prices for all tickers without progress indicators (for CLI usage)"""
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    with conn_ctx() as c:
        cursor = c.cursor()
        cursor.execute(f"SELECT DISTINCT ticker FROM {PICKS_TBL}")
        tickers = [row[0] for row in cursor.fetchall()]
    if not tickers:
        return
    
    try:
        # Download data for all tickers
        data = yf.download(tickers, start=cutoff)
        if data.empty:
            print("No data returned from yfinance")
            return
            
        # Create a list to store processed data
        processed_data = []
        
        # Handle the data format based on the number of tickers
        if len(tickers) == 1:
            ticker = tickers[0]
            # For a single ticker, the columns might not be MultiIndex
            if isinstance(data.columns, pd.MultiIndex):
                # Find the Close column
                if ('Close', ticker) in data.columns:
                    price_series = data[('Close', ticker)]
                else:
                    print(f"Could not find Close column for {ticker}")
                    return
            else:
                # Use 'Close' column if 'Adj Close' is not available
                price_col = 'Close' if 'Adj Close' not in data.columns else 'Adj Close'
                price_series = data[price_col]
                
            # Convert to required format
            for date, price in zip(data.index, price_series):
                if not pd.isna(price):  # Skip NaN values
                    processed_data.append((date.strftime('%Y-%m-%d'), ticker, float(price)))
        else:
            # For multiple tickers, we expect a MultiIndex
            if isinstance(data.columns, pd.MultiIndex):
                # Get Close prices for all tickers
                if 'Close' in data.columns.levels[0]:
                    price_data = data['Close']
                else:
                    print("Could not find Close data")
                    return
                    
                # Convert to the required format
                for date in price_data.index:
                    for ticker in price_data.columns:
                        price = price_data.loc[date, ticker]
                        if not pd.isna(price):  # Skip NaN values
                            processed_data.append((date.strftime('%Y-%m-%d'), ticker, float(price)))
            else:
                print("Unexpected data format from yfinance")
                return
        
        # Insert processed data into database
        if processed_data:
            with conn_ctx() as c:
                cursor = c.cursor()
                cursor.executemany(
                    f"INSERT OR IGNORE INTO {PRICES_TBL} (price_date, ticker, adj_close) VALUES (?, ?, ?)",
                    processed_data
                )
            print(f"Updated prices for {len(processed_data)} ticker-days")
        else:
            print("No valid price data found")
            
    except Exception as e:
        print(f"Error updating prices: {e}")
        import traceback
        traceback.print_exc()

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

