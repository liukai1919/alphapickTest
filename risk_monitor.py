#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime, timedelta
import os
import pandas as pd
import numpy as np
import yfinance as yf
import fredapi
from dotenv import load_dotenv
import time
import requests
import sqlite3
from pathlib import Path

# 加载环境变量
load_dotenv()

# 数据库设置
DB_PATH = Path(__file__).with_name("alpha_picks.db")
RISK_TABLE = "risk_indicators"
RISK_SCORE_TABLE = "risk_scores"

# Fred API密钥
FRED_API_KEY = os.getenv("FRED_API_KEY")

# Telegram通知设置
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 邮件通知设置
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

# 指标权重配置
WEIGHTS = {
    "vix": 0.40,
    "move": 0.25,
    "ted": 0.15,
    "curve": 0.10,
    "cdx": 0.10,
}

# 风险级别阈值
RISK_THRESHOLDS = {
    "GREEN": 0.5,
    "YELLOW": 1.0,
    "ORANGE": 1.5,
    "RED": float('inf')
}

# 数据库连接上下文管理器
def get_conn():
    return sqlite3.connect(DB_PATH)

def init_risk_db():
    """初始化风险监控相关的数据库表"""
    conn = get_conn()
    cursor = conn.cursor()
    
    # 创建风险指标表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {RISK_TABLE} (
        date TEXT,
        vix REAL,
        move REAL,
        ted REAL,
        curve REAL,
        cdx REAL,
        PRIMARY KEY (date)
    )
    """)
    
    # 创建风险评分表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {RISK_SCORE_TABLE} (
        date TEXT,
        danger_score REAL,
        vix_z REAL,
        move_z REAL,
        ted_z REAL,
        curve_z REAL,
        cdx_z REAL,
        risk_level TEXT,
        PRIMARY KEY (date)
    )
    """)
    
    conn.commit()
    conn.close()

def fetch_vix():
    """获取VIX指数数据"""
    try:
        vix = yf.download("^VIX", period="1d")
        return float(vix["Close"].iloc[-1])  # 确保返回标量值而不是Series
    except Exception as e:
        print(f"Error fetching VIX: {e}")
        return None

def fetch_move():
    """获取MOVE指数数据 - 目前使用模拟数据"""
    # 实际实现需要付费API如ICE/Quandl
    # 这里提供模拟数据，实际部署时应替换为真实数据源
    try:
        # 模拟MOVE指数，通常在60-120之间波动
        # 在实际部署中，替换为ICE/Quandl API调用
        # 例如: quandl.get("ICE/BofAML_MOVE", api_key=QUANDL_API_KEY)
        move_value = 80 + np.random.normal(0, 10)  # 模拟数据
        return max(30, min(200, move_value))  # 限制在合理范围内
    except Exception as e:
        print(f"Error fetching MOVE: {e}")
        return None

def fetch_ted():
    """获取TED利差数据"""
    try:
        if not FRED_API_KEY:
            # 如果没有FRED API密钥，使用模拟数据
            ted_value = 0.3 + np.random.normal(0, 0.1)  # 模拟数据，单位为百分点
            return max(0.1, min(1.0, ted_value))  # 限制在合理范围内
        
        fred = fredapi.Fred(api_key=FRED_API_KEY)
        ted = fred.get_series("TEDRATE", limit=1)
        return ted.iloc[-1] / 100  # 转换为小数
    except Exception as e:
        print(f"Error fetching TED spread: {e}")
        return None

def fetch_yield_curve():
    """获取美国国债10年-2年期利差"""
    try:
        if not FRED_API_KEY:
            # 如果没有FRED API密钥，使用模拟数据
            curve_value = 0.2 + np.random.normal(0, 0.3)  # 模拟数据，单位为百分点
            return curve_value
        
        fred = fredapi.Fred(api_key=FRED_API_KEY)
        curve = fred.get_series("T10Y2Y", limit=1)
        return curve.iloc[-1]
    except Exception as e:
        print(f"Error fetching yield curve: {e}")
        return None

def fetch_cdx():
    """获取CDX IG信用利差数据 - 目前使用模拟数据"""
    # 实际实现需要付费数据源如Markit
    try:
        # 模拟CDX IG利差，通常在50-100之间波动
        cdx_value = 65 + np.random.normal(0, 10)  # 模拟数据，单位为基点
        return max(30, min(150, cdx_value)) / 100  # 转换为小数并限制在合理范围内
    except Exception as e:
        print(f"Error fetching CDX: {e}")
        return None

def collect_risk_indicators():
    """收集所有风险指标数据并保存到数据库"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 获取各项指标
    vix = fetch_vix()
    move = fetch_move()
    ted = fetch_ted()
    curve = fetch_yield_curve()
    cdx = fetch_cdx()
    
    # 检查数据有效性
    if not all([vix, move, ted is not None, curve is not None, cdx]):
        print("Some indicators could not be fetched, using available ones")
    
    # 存储到数据库
    conn = get_conn()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            f"INSERT OR REPLACE INTO {RISK_TABLE} (date, vix, move, ted, curve, cdx) VALUES (?, ?, ?, ?, ?, ?)",
            (today, vix, move, ted, curve, cdx)
        )
        conn.commit()
        print(f"Stored risk indicators for {today}")
    except Exception as e:
        print(f"Error storing risk indicators: {e}")
    finally:
        conn.close()
    
    return {
        "date": today,
        "vix": vix,
        "move": move,
        "ted": ted,
        "curve": curve,
        "cdx": cdx
    }

def calculate_risk_score():
    """计算风险评分，使用252天滚动Z分数"""
    conn = get_conn()
    
    # 获取所有历史指标数据
    indicators = pd.read_sql(f"SELECT * FROM {RISK_TABLE}", conn)
    indicators['date'] = pd.to_datetime(indicators['date'])
    indicators.set_index('date', inplace=True)
    indicators.sort_index(inplace=True)
    
    # 如果数据不足，返回默认风险评分
    if len(indicators) < 30:  # 至少需要30天数据才能计算有意义的Z分数
        print("Not enough historical data for meaningful Z-scores")
        default_score = 0.0
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "date": today,
            "danger_score": default_score,
            "risk_level": "GREEN",
            "z_scores": {k: 0 for k in WEIGHTS.keys()}
        }
    
    # 计算252天滚动Z分数（如果数据少于252天，使用所有可用数据）
    window = min(252, len(indicators))
    z_scores = pd.DataFrame()
    
    for col in WEIGHTS.keys():
        if col in indicators.columns:
            mean = indicators[col].rolling(window).mean()
            std = indicators[col].rolling(window).std()
            # 对于国债利差，小值更危险，所以取负
            if col == 'curve':
                z_scores[col] = -(indicators[col] - mean) / std
            else:
                z_scores[col] = (indicators[col] - mean) / std
    
    # 处理可能的NaN值
    z_scores.fillna(0, inplace=True)
    
    # 计算加权危险分数
    danger_scores = pd.Series(0, index=z_scores.index)
    for col, weight in WEIGHTS.items():
        if col in z_scores.columns:
            danger_scores += z_scores[col] * weight
    
    # 获取最新评分
    latest_date = indicators.index.max()
    latest_score = danger_scores[latest_date]
    
    # 确定风险级别
    risk_level = "GREEN"
    for level, threshold in sorted(RISK_THRESHOLDS.items(), key=lambda x: x[1]):
        if latest_score <= threshold:
            risk_level = level
            break
    
    # 存储到数据库
    latest_record = {
        "date": latest_date.strftime("%Y-%m-%d"),
        "danger_score": latest_score,
        "vix_z": z_scores.loc[latest_date, "vix"] if "vix" in z_scores.columns else 0,
        "move_z": z_scores.loc[latest_date, "move"] if "move" in z_scores.columns else 0,
        "ted_z": z_scores.loc[latest_date, "ted"] if "ted" in z_scores.columns else 0,
        "curve_z": z_scores.loc[latest_date, "curve"] if "curve" in z_scores.columns else 0,
        "cdx_z": z_scores.loc[latest_date, "cdx"] if "cdx" in z_scores.columns else 0,
        "risk_level": risk_level
    }
    
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""INSERT OR REPLACE INTO {RISK_SCORE_TABLE} 
            (date, danger_score, vix_z, move_z, ted_z, curve_z, cdx_z, risk_level) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                latest_record["date"], 
                latest_record["danger_score"],
                latest_record["vix_z"],
                latest_record["move_z"],
                latest_record["ted_z"], 
                latest_record["curve_z"],
                latest_record["cdx_z"],
                latest_record["risk_level"]
            )
        )
        conn.commit()
    except Exception as e:
        print(f"Error storing risk score: {e}")
    finally:
        conn.close()
    
    # 格式化返回值
    z_scores_dict = {
        "vix": latest_record["vix_z"],
        "move": latest_record["move_z"],
        "ted": latest_record["ted_z"],
        "curve": latest_record["curve_z"],
        "cdx": latest_record["cdx_z"]
    }
    
    return {
        "date": latest_record["date"],
        "danger_score": latest_record["danger_score"],
        "risk_level": risk_level,
        "z_scores": z_scores_dict
    }

def get_previous_risk_level():
    """获取前一天的风险级别"""
    conn = get_conn()
    cursor = conn.cursor()
    
    try:
        # 获取最新两条记录
        cursor.execute(
            f"SELECT date, risk_level FROM {RISK_SCORE_TABLE} ORDER BY date DESC LIMIT 2"
        )
        records = cursor.fetchall()
        
        if len(records) >= 2:
            return records[1][1]  # 返回倒数第二条记录的风险级别
        elif records:
            return records[0][1]  # 如果只有一条记录，返回该记录的风险级别
        else:
            return "GREEN"  # 默认绿色
            
    except Exception as e:
        print(f"Error fetching previous risk level: {e}")
        return "GREEN"  # 默认绿色
    finally:
        conn.close()

def send_telegram_notification(message):
    """发送Telegram通知"""
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        print("Telegram credentials missing, skipping notification")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, data=data)
        if response.status_code == 200:
            print("Telegram notification sent successfully")
            return True
        else:
            print(f"Failed to send Telegram notification: {response.text}")
            return False
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")
        return False

def send_email_notification(subject, message):
    """发送邮件通知"""
    if not all([EMAIL_HOST, EMAIL_USER, EMAIL_PASS]):
        print("Email credentials missing, skipping notification")
        return False
    
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER  # 发送给自己
        msg['Subject'] = subject
        
        msg.attach(MIMEText(message, 'plain'))
        
        server = smtplib.SMTP(EMAIL_HOST)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
        
        print("Email notification sent successfully")
        return True
    except Exception as e:
        print(f"Error sending email notification: {e}")
        return False

def check_risk_alert(risk_data):
    """检查是否需要发送风险告警"""
    curr_level = risk_data["risk_level"]
    prev_level = get_previous_risk_level()
    
    # 只有当风险级别升级到橙色或红色，且与前一天不同时才发送告警
    if curr_level in ["ORANGE", "RED"] and curr_level != prev_level:
        # 获取原始指标值
        conn = get_conn()
        indicators = pd.read_sql(
            f"SELECT * FROM {RISK_TABLE} WHERE date = '{risk_data['date']}'", 
            conn
        )
        conn.close()
        
        if not indicators.empty:
            vix = indicators.iloc[0]["vix"]
            move = indicators.iloc[0]["move"]
            ted = indicators.iloc[0]["ted"] * 100  # 转换为基点
            
            # 构建告警消息
            msg = (f"🚨 系统性风险 {curr_level}! Danger={risk_data['danger_score']:.2f}\n"
                  f"VIX={vix:.1f}, MOVE={move:.0f}, TED={ted:.1f}bp")
            
            # 发送通知
            send_telegram_notification(msg)
            send_email_notification(f"风险告警: {curr_level}", msg)
            
            # 如果是红色警报，可以在这里添加自动清仓逻辑
            if curr_level == "RED":
                # TODO: 接入券商API实现自动清仓
                print("RED ALERT: Would trigger position liquidation if broker API connected")
            
            return True
    
    return False

def get_latest_risk_data():
    """获取最新的风险数据，用于仪表盘显示"""
    conn = get_conn()
    
    # 获取最新风险评分
    score_df = pd.read_sql(
        f"SELECT * FROM {RISK_SCORE_TABLE} ORDER BY date DESC LIMIT 1", 
        conn
    )
    
    # 获取最新指标数据
    indicators_df = pd.read_sql(
        f"SELECT * FROM {RISK_TABLE} ORDER BY date DESC LIMIT 1", 
        conn
    )
    
    conn.close()
    
    if score_df.empty or indicators_df.empty:
        return None
    
    # 组合数据
    result = {
        "date": score_df.iloc[0]["date"],
        "danger_score": score_df.iloc[0]["danger_score"],
        "risk_level": score_df.iloc[0]["risk_level"],
        "z_scores": {
            "vix": score_df.iloc[0]["vix_z"],
            "move": score_df.iloc[0]["move_z"],
            "ted": score_df.iloc[0]["ted_z"],
            "curve": score_df.iloc[0]["curve_z"],
            "cdx": score_df.iloc[0]["cdx_z"]
        },
        "indicators": {
            "vix": indicators_df.iloc[0]["vix"],
            "move": indicators_df.iloc[0]["move"],
            "ted": indicators_df.iloc[0]["ted"] * 100,  # 转换为基点
            "curve": indicators_df.iloc[0]["curve"] * 100,  # 转换为基点
            "cdx": indicators_df.iloc[0]["cdx"] * 100  # 转换为基点
        }
    }
    
    return result

def get_historical_risk_data(days=60):
    """获取历史风险数据，用于仪表盘趋势图"""
    conn = get_conn()
    
    # 获取风险评分历史
    query = f"""
    SELECT s.date, s.danger_score, s.risk_level, i.vix, i.move, i.ted, i.curve, i.cdx
    FROM {RISK_SCORE_TABLE} s
    JOIN {RISK_TABLE} i ON s.date = i.date
    ORDER BY s.date DESC
    LIMIT {days}
    """
    
    df = pd.read_sql(query, conn)
    conn.close()
    
    if df.empty:
        return pd.DataFrame()
    
    # 转换日期格式并倒序
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    
    # 转换某些指标为基点显示
    df['ted'] = df['ted'] * 100
    df['curve'] = df['curve'] * 100
    df['cdx'] = df['cdx'] * 100
    
    return df

def update_risk_assessment():
    """更新风险评估的主函数"""
    print("Updating risk assessment...")
    
    # 确保数据库表已创建
    init_risk_db()
    
    # 收集指标数据
    indicators = collect_risk_indicators()
    
    # 计算风险评分
    risk_data = calculate_risk_score()
    
    # 检查是否需要发送告警
    check_risk_alert(risk_data)
    
    print(f"Risk assessment updated: Level={risk_data['risk_level']}, Score={risk_data['danger_score']:.2f}")
    return risk_data

if __name__ == "__main__":
    # 更新风险评估
    risk_data = update_risk_assessment()
    print(f"Current risk level: {risk_data['risk_level']}")
    print(f"Danger score: {risk_data['danger_score']:.2f}") 