#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import os
import sys
from pathlib import Path

# 确保可以导入风险模块和主程序模块
current_dir = Path(__file__).parent.absolute()
sys.path.append(str(current_dir))
from risk_monitor import (
    update_risk_assessment, 
    get_latest_risk_data, 
    get_historical_risk_data,
    RISK_THRESHOLDS
)

# 颜色映射
RISK_COLORS = {
    "GREEN": "#4CAF50",   # 绿色
    "YELLOW": "#FFC107",  # 黄色
    "ORANGE": "#FF9800",  # 橙色
    "RED": "#F44336",     # 红色
}

def risk_color(level):
    """获取风险级别对应的颜色"""
    return RISK_COLORS.get(level, "#4CAF50")

def render_risk_dashboard():
    """渲染系统性风险仪表盘页面"""
    st.title("📊 系统性风险仪表盘")
    
    col1, col2 = st.columns([3, 1])
    
    with col2:
        update_btn = st.button("🔄 更新风险评估", use_container_width=True)
        if update_btn:
            with st.spinner("正在更新风险评估..."):
                risk_data = update_risk_assessment()
                st.success(f"风险评估已更新: {risk_data['risk_level']}")
                st.rerun()
    
    with col1:
        st.write("实时监控系统性风险指标，在市场危险升高时提前警告")
    
    # 获取最新风险数据
    risk_data = get_latest_risk_data()
    
    if not risk_data:
        st.warning("暂无风险数据，请点击更新按钮获取最新数据")
        return
    
    # 获取历史数据用于趋势图
    historical_data = get_historical_risk_data(days=60)
    
    # 显示当前风险水平
    display_current_risk(risk_data)
    
    # 显示风险指标详情
    display_risk_indicators(risk_data)
    
    # 显示风险评分趋势
    if not historical_data.empty:
        display_risk_trend(historical_data)
    else:
        st.info("暂无历史数据，无法显示趋势图")
    
    # 显示风险指标趋势
    if not historical_data.empty:
        display_indicators_trend(historical_data)

def display_current_risk(risk_data):
    """显示当前风险等级和评分"""
    level = risk_data["risk_level"]
    score = risk_data["danger_score"]
    
    # 根据风险级别选择颜色
    color = risk_color(level)
    
    # 创建风险等级展示区
    st.markdown(
        f"""
        <div style="
            background-color: {color}; 
            color: white; 
            padding: 20px; 
            border-radius: 10px; 
            text-align: center;
            margin-bottom: 20px;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
            font-weight: bold;
        ">
            <h2 style="margin: 0; color: white;">当前风险等级: {level}</h2>
            <p style="margin: 10px 0 0 0; font-size: 18px;">
                风险评分: {score:.2f}
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    # 使用进度条直观显示风险评分
    progress_val = min(score / 2.0, 1.0)  # 风险分数最大显示为2.0时满格
    st.progress(progress_val, text=f"Danger Score: {score:.2f}")
    
    # 风险等级说明
    if level in ["ORANGE", "RED"]:
        st.error("⚠️ 当前市场风险较高，建议减仓或对冲") 
    elif level == "YELLOW":
        st.warning("⚠️ 市场开始出现波动，请密切关注")
    else:
        st.success("✅ 当前市场系统性风险较低")

def display_risk_indicators(risk_data):
    """显示各风险指标详情"""
    st.subheader("风险指标详情")
    
    indicators = risk_data["indicators"]
    z_scores = risk_data["z_scores"]
    
    # 定义指标阈值和描述
    thresholds = {
        "vix": {"name": "VIX恐慌指数", "danger": 25, "unit": "", "desc": "标普500隐含波动率"},
        "move": {"name": "MOVE指数", "danger": 120, "unit": "", "desc": "美债波动率指数"},
        "ted": {"name": "TED利差", "danger": 70, "unit": "bp", "desc": "银行间信用风险"},
        "curve": {"name": "10Y-2Y国债利差", "danger": 0, "unit": "bp", "desc": "收益率曲线斜率"},
        "cdx": {"name": "CDX-IG信用利差", "danger": 90, "unit": "bp", "desc": "企业违约风险"}
    }
    
    # 创建指标展示卡片
    cols = st.columns(len(indicators))
    
    for i, (key, value) in enumerate(indicators.items()):
        if key not in thresholds:
            continue
            
        with cols[i]:
            # 判断指标是否超过危险阈值
            is_danger = False
            if key == "curve":
                is_danger = value < thresholds[key]["danger"]
            else:
                is_danger = value >= thresholds[key]["danger"]
            
            # 设置卡片颜色
            bg_color = "#FF5252" if is_danger else "#4CAF50"
            opacity = min(0.8, max(0.2, abs(z_scores[key]) * 0.2)) if z_scores[key] else 0.2
            
            # 创建卡片
            st.markdown(
                f"""
                <div style="
                    background-color: {bg_color}; 
                    opacity: {opacity + 0.2};
                    padding: 15px; 
                    border-radius: 5px; 
                    text-align: center;
                    color: white;
                    height: 130px;
                    display: flex;
                    flex-direction: column;
                    justify-content: space-between;
                ">
                    <h4 style="margin: 0;">{thresholds[key]["name"]}</h4>
                    <div>
                        <h3 style="margin: 5px 0;">{value:.1f}{thresholds[key]["unit"]}</h3>
                        <p style="margin: 0; font-size: 12px;">Z-Score: {z_scores[key]:.2f}</p>
                    </div>
                    <p style="margin: 0; font-size: 11px;">{thresholds[key]["desc"]}</p>
                </div>
                """,
                unsafe_allow_html=True
            )

def display_risk_trend(data):
    """显示风险评分趋势图"""
    st.subheader("风险评分趋势")
    
    # 创建风险评分趋势图
    fig = go.Figure()
    
    # 添加区域背景色，标识不同风险级别
    fig.add_trace(go.Scatter(
        x=data['date'],
        y=[RISK_THRESHOLDS['GREEN']] * len(data),
        fill=None,
        mode='lines',
        line=dict(width=0),
        showlegend=False
    ))
    
    fig.add_trace(go.Scatter(
        x=data['date'],
        y=[RISK_THRESHOLDS['YELLOW']] * len(data),
        fill='tonexty',
        mode='lines',
        line=dict(width=0),
        fillcolor='rgba(76, 175, 80, 0.3)',  # 绿色区域
        name='低风险'
    ))
    
    fig.add_trace(go.Scatter(
        x=data['date'],
        y=[RISK_THRESHOLDS['ORANGE']] * len(data),
        fill='tonexty',
        mode='lines',
        line=dict(width=0),
        fillcolor='rgba(255, 193, 7, 0.3)',  # 黄色区域
        name='中风险'
    ))
    
    fig.add_trace(go.Scatter(
        x=data['date'],
        y=[RISK_THRESHOLDS['RED']] * len(data),
        fill='tonexty',
        mode='lines',
        line=dict(width=0),
        fillcolor='rgba(255, 152, 0, 0.3)',  # 橙色区域
        name='高风险'
    ))
    
    fig.add_trace(go.Scatter(
        x=data['date'],
        y=[2.5] * len(data),  # 图表上限
        fill='tonexty',
        mode='lines',
        line=dict(width=0),
        fillcolor='rgba(244, 67, 54, 0.3)',  # 红色区域
        name='极高风险'
    ))
    
    # 添加风险评分线
    fig.add_trace(go.Scatter(
        x=data['date'],
        y=data['danger_score'],
        mode='lines+markers',
        line=dict(color='black', width=2),
        name='风险评分'
    ))
    
    # 设置图表布局
    fig.update_layout(
        height=400,
        margin=dict(l=20, r=20, t=30, b=20),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=1.02,
            xanchor="center",
            x=0.5
        ),
        xaxis=dict(title='日期'),
        yaxis=dict(title='风险评分', range=[0, 2.5])
    )
    
    st.plotly_chart(fig, use_container_width=True)

def display_indicators_trend(data):
    """显示各风险指标趋势图"""
    st.subheader("风险指标趋势")
    
    # 创建标签页，分别显示不同指标
    tabs = st.tabs(["VIX", "MOVE", "TED利差", "国债利差", "CDX"])
    
    # VIX趋势
    with tabs[0]:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=data['date'],
            y=data['vix'],
            mode='lines',
            name='VIX'
        ))
        # 添加阈值线
        fig.add_shape(
            type="line",
            x0=data['date'].min(),
            y0=25,
            x1=data['date'].max(),
            y1=25,
            line=dict(color="red", dash="dash"),
        )
        fig.add_annotation(
            x=data['date'].max(),
            y=25,
            text="危险阈值: 25",
            showarrow=False,
            yshift=10
        )
        fig.update_layout(
            height=350,
            margin=dict(l=20, r=20, t=30, b=20),
            xaxis=dict(title='日期'),
            yaxis=dict(title='VIX指数')
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # MOVE趋势
    with tabs[1]:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=data['date'],
            y=data['move'],
            mode='lines',
            name='MOVE'
        ))
        # 添加阈值线
        fig.add_shape(
            type="line",
            x0=data['date'].min(),
            y0=120,
            x1=data['date'].max(),
            y1=120,
            line=dict(color="red", dash="dash"),
        )
        fig.add_annotation(
            x=data['date'].max(),
            y=120,
            text="危险阈值: 120",
            showarrow=False,
            yshift=10
        )
        fig.update_layout(
            height=350,
            margin=dict(l=20, r=20, t=30, b=20),
            xaxis=dict(title='日期'),
            yaxis=dict(title='MOVE指数')
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # TED利差趋势
    with tabs[2]:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=data['date'],
            y=data['ted'],
            mode='lines',
            name='TED利差'
        ))
        # 添加阈值线
        fig.add_shape(
            type="line",
            x0=data['date'].min(),
            y0=70,
            x1=data['date'].max(),
            y1=70,
            line=dict(color="red", dash="dash"),
        )
        fig.add_annotation(
            x=data['date'].max(),
            y=70,
            text="危险阈值: 70bp",
            showarrow=False,
            yshift=10
        )
        fig.update_layout(
            height=350,
            margin=dict(l=20, r=20, t=30, b=20),
            xaxis=dict(title='日期'),
            yaxis=dict(title='TED利差 (基点)')
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # 国债利差趋势
    with tabs[3]:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=data['date'],
            y=data['curve'],
            mode='lines',
            name='10Y-2Y国债利差'
        ))
        # 添加阈值线
        fig.add_shape(
            type="line",
            x0=data['date'].min(),
            y0=0,
            x1=data['date'].max(),
            y1=0,
            line=dict(color="red", dash="dash"),
        )
        fig.add_annotation(
            x=data['date'].max(),
            y=0,
            text="危险阈值: 收益率曲线倒挂",
            showarrow=False,
            yshift=10
        )
        fig.update_layout(
            height=350,
            margin=dict(l=20, r=20, t=30, b=20),
            xaxis=dict(title='日期'),
            yaxis=dict(title='10Y-2Y利差 (基点)')
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # CDX趋势
    with tabs[4]:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=data['date'],
            y=data['cdx'],
            mode='lines',
            name='CDX-IG信用利差'
        ))
        # 添加阈值线
        fig.add_shape(
            type="line",
            x0=data['date'].min(),
            y0=90,
            x1=data['date'].max(),
            y1=90,
            line=dict(color="red", dash="dash"),
        )
        fig.add_annotation(
            x=data['date'].max(),
            y=90,
            text="危险阈值: 90bp",
            showarrow=False,
            yshift=10
        )
        fig.update_layout(
            height=350,
            margin=dict(l=20, r=20, t=30, b=20),
            xaxis=dict(title='日期'),
            yaxis=dict(title='CDX-IG利差 (基点)')
        )
        st.plotly_chart(fig, use_container_width=True)

# 如果直接运行此脚本，显示独立的风险仪表盘
if __name__ == "__main__":
    st.set_page_config(
        page_title="系统性风险仪表盘",
        page_icon="📊",
        layout="wide",
    )
    render_risk_dashboard() 