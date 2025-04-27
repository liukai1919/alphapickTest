#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime
import time
import os
import sys
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import argparse

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("risk_monitor.log")
    ]
)
logger = logging.getLogger("risk_scheduler")

# 确保可以导入风险模块
current_dir = Path(__file__).parent.absolute()
sys.path.append(str(current_dir))

# 导入风险监控模块
from risk_monitor import update_risk_assessment, check_risk_alert

def run_risk_assessment():
    """执行风险评估任务"""
    logger.info("开始执行定时风险评估...")
    
    try:
        # 更新风险评估
        risk_data = update_risk_assessment()
        
        # 检查是否需要发送告警
        alert_sent = check_risk_alert(risk_data)
        
        if alert_sent:
            logger.warning(f"已发送风险告警! 级别: {risk_data['risk_level']}, 评分: {risk_data['danger_score']:.2f}")
        else:
            logger.info(f"风险评估完成。级别: {risk_data['risk_level']}, 评分: {risk_data['danger_score']:.2f}")
            
    except Exception as e:
        logger.error(f"风险评估执行失败: {str(e)}", exc_info=True)

def schedule_risk_tasks(daily_time="09:30", interval_minutes=None):
    """设置风险评估定时任务"""
    scheduler = BackgroundScheduler()
    
    # 添加每日定时任务
    scheduler.add_job(
        run_risk_assessment,
        CronTrigger(hour=daily_time.split(":")[0], minute=daily_time.split(":")[1]),
        id="daily_risk_assessment",
        name="每日风险评估",
        replace_existing=True
    )
    
    # 如果指定了间隔，添加间隔执行任务
    if interval_minutes:
        scheduler.add_job(
            run_risk_assessment,
            'interval',
            minutes=interval_minutes,
            id="interval_risk_assessment",
            name=f"每{interval_minutes}分钟风险评估",
            replace_existing=True
        )
    
    # 启动调度器
    scheduler.start()
    logger.info(f"风险评估定时任务已启动（每日{daily_time}执行）")
    if interval_minutes:
        logger.info(f"额外设置了每{interval_minutes}分钟执行一次的间隔任务")
    
    return scheduler

def backfill_historical_data(days=365):
    """回填历史数据，用于测试和初始化"""
    from risk_monitor import collect_risk_indicators, calculate_risk_score
    import pandas as pd
    from tqdm import tqdm
    
    logger.info(f"开始回填{days}天的历史数据...")
    
    # 获取今天的日期
    today = datetime.now().date()
    
    # 创建日期序列
    date_range = pd.date_range(end=today, periods=days).date
    
    # 初始化模拟数据参数
    vix_base = 15.0
    move_base = 80.0
    ted_base = 0.3
    curve_base = 0.5
    cdx_base = 0.6
    
    # 模拟2008年金融危机和2020年3月疫情冲击
    crisis_periods = {
        # 2008金融危机模拟
        "2008-09-15": {"days": 60, "vix_mult": 3.0, "move_mult": 2.5, "ted_mult": 3.0, "curve_mult": -1.0, "cdx_mult": 2.5},
        # 2020年3月COVID-19冲击模拟
        "2020-03-15": {"days": 30, "vix_mult": 4.0, "move_mult": 3.0, "ted_mult": 2.5, "curve_mult": -0.5, "cdx_mult": 2.0}
    }
    
    # 数据库连接
    from risk_monitor import get_conn, RISK_TABLE
    conn = get_conn()
    cursor = conn.cursor()
    
    try:
        # 创建进度条
        for date in tqdm(date_range):
            date_str = date.strftime("%Y-%m-%d")
            
            # 检查日期是否在危机期间
            in_crisis = False
            crisis_mult = {"vix": 1.0, "move": 1.0, "ted": 1.0, "curve": 1.0, "cdx": 1.0}
            
            for crisis_date, params in crisis_periods.items():
                crisis_start = pd.to_datetime(crisis_date).date()
                crisis_end = crisis_start + pd.Timedelta(days=params["days"])
                
                if crisis_start <= date <= crisis_end:
                    # 在危机期间，应用乘数
                    days_in = (date - crisis_start).days
                    intensity = 1.0 - (days_in / params["days"])  # 危机强度随时间衰减
                    
                    crisis_mult["vix"] = 1.0 + (params["vix_mult"] - 1.0) * intensity
                    crisis_mult["move"] = 1.0 + (params["move_mult"] - 1.0) * intensity
                    crisis_mult["ted"] = 1.0 + (params["ted_mult"] - 1.0) * intensity
                    crisis_mult["curve"] = params["curve_mult"] * intensity
                    crisis_mult["cdx"] = 1.0 + (params["cdx_mult"] - 1.0) * intensity
                    
                    in_crisis = True
                    break
            
            # 计算当天的模拟值（添加一些随机性）
            import numpy as np
            np.random.seed(int(date.strftime("%Y%m%d")))
            
            vix = vix_base * crisis_mult["vix"] * (1 + 0.1 * np.random.normal())
            move = move_base * crisis_mult["move"] * (1 + 0.1 * np.random.normal())
            ted = ted_base * crisis_mult["ted"] * (1 + 0.15 * np.random.normal()) / 100
            
            if in_crisis and crisis_mult["curve"] < 0:
                # 危机期间可能出现收益率曲线倒挂
                curve = curve_base * crisis_mult["curve"] * (1 + 0.2 * np.random.normal()) / 100
            else:
                curve = curve_base * (1 + 0.2 * np.random.normal()) / 100
                
            cdx = cdx_base * crisis_mult["cdx"] * (1 + 0.1 * np.random.normal()) / 100
            
            # 确保值在合理范围内
            vix = max(10, min(80, vix))
            move = max(50, min(200, move))
            ted = max(0.001, min(0.02, ted))  # 10-200bp
            curve = max(-0.01, min(0.02, curve))  # -100bp to 200bp
            cdx = max(0.003, min(0.015, cdx))  # 30-150bp
            
            # 插入数据
            cursor.execute(
                f"INSERT OR REPLACE INTO {RISK_TABLE} (date, vix, move, ted, curve, cdx) VALUES (?, ?, ?, ?, ?, ?)",
                (date_str, vix, move, ted, curve, cdx)
            )
            
        # 提交事务
        conn.commit()
        logger.info(f"成功回填了{days}天的历史数据")
        
        # 计算所有日期的风险评分
        for date in tqdm(date_range):
            # 强制设置当前日期，以便计算历史风险评分
            from risk_monitor import calculate_risk_score
            risk_data = calculate_risk_score()
            
    except Exception as e:
        conn.rollback()
        logger.error(f"回填历史数据失败: {str(e)}", exc_info=True)
    finally:
        conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="风险监控定时任务管理")
    parser.add_argument('--daily-time', type=str, default="09:30", help="每日定时执行时间，格式为HH:MM")
    parser.add_argument('--interval', type=int, help="间隔执行分钟数，不设置则只执行每日任务")
    parser.add_argument('--backfill', action='store_true', help="是否回填历史数据")
    parser.add_argument('--days', type=int, default=365, help="回填历史数据的天数")
    parser.add_argument('--run-now', action='store_true', help="立即执行一次风险评估")
    
    args = parser.parse_args()
    
    # 回填历史数据
    if args.backfill:
        backfill_historical_data(days=args.days)
    
    # 立即执行一次
    if args.run_now:
        run_risk_assessment()
    
    # 启动定时任务
    scheduler = schedule_risk_tasks(daily_time=args.daily_time, interval_minutes=args.interval)
    
    try:
        # 保持程序运行
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        # 关闭调度器
        scheduler.shutdown()
        logger.info("定时任务已关闭") 