# Alpha Pick Monitor + 系统性风险仪表盘

全面的股票监控和风险管理解决方案，用于跟踪Alpha Pick推荐，并监控系统性风险指标。

## 功能特点

### Alpha Pick 监控

- **自动邮件处理**: 自动检测并处理Seeking Alpha推荐邮件
- **股票数据追踪**: 使用Yahoo Finance API获取实时和历史股价数据
- **绩效监控**: 跟踪每支股票的表现，计算回报率和持有天数
- **灵活分类**: Alpha Picks和Watchlist分开管理
- **批量操作**: 支持一次性添加多支股票

### 系统性风险仪表盘

- **多指标监控**: 跟踪VIX、MOVE、TED利差、收益率曲线和CDX信用利差
- **风险评分**: 使用标准化Z-score计算综合风险评分
- **阈值告警**: 当风险评分超出阈值时自动发送告警
- **历史回测**: 支持回填历史数据，验证风险指标在历史危机中的表现
- **自动去风险**: 在高风险状态下可选择自动降低仓位(需接入券商API)

## 系统要求

- Python 3.8+
- SQLite3 数据库
- 互联网连接(用于获取股票数据和风险指标)

## 安装步骤

1. 克隆仓库:

```bash
git clone https://github.com/yourusername/alphapickTest.git
cd alphapickTest
```

2. 安装依赖:

```bash
pip install -r requirements.txt
```

3. 创建环境变量文件 `.env`:

```
# 邮件设置
EMAIL_HOST=imap.example.com
EMAIL_USER=your_email@example.com
EMAIL_PASS=your_password

# Telegram通知(可选)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# FRED API(用于获取经济指标)
FRED_API_KEY=your_fred_api_key

# Discord通知(可选)
DISCORD_WEBHOOK=your_discord_webhook
```

## 使用方法

### 启动Streamlit界面

```bash
streamlit run alpha_pick_monitor.py
```

这将启动一个带有以下功能的Web界面:
- Alpha Picks管理页面
- Watchlist管理页面
- 批量添加股票页面
- 系统性风险仪表盘

### 命令行操作

也可以通过命令行执行特定操作:

```bash
# 抓取新的Alpha Pick邮件
python alpha_pick_monitor.py --ingest-email

# 更新股票价格
python alpha_pick_monitor.py --ingest-prices

# 同时执行上面两项
python alpha_pick_monitor.py --ingest
```

### 设置风险监控定时任务

```bash
# 回填历史风险数据(首次使用时推荐)
python scheduled_tasks.py --backfill --days 365

# 启动风险监控定时任务(每天上午9:30运行)
python scheduled_tasks.py --daily-time 09:30

# 设置额外的间隔运行(每30分钟运行一次)
python scheduled_tasks.py --daily-time 09:30 --interval 30

# 立即执行一次风险评估
python scheduled_tasks.py --run-now
```

## 风险指标说明

**⚠️ 重要说明**: 以下指标中，只有VIX是从Yahoo Finance获取的真实数据，其他指标可能使用模拟数据或依赖FRED API (如果配置了API密钥)。

| 指标 | 说明 | 危险阈值 | 数据来源 | 真实/模拟 |
|------|------|----------|----------|----------|
| VIX (恐慌指数) | 标普500的隐含波动率 | ≥25 | Yahoo Finance | ✅ 真实数据 |
| MOVE | 美国国债的波动率指数 | ≥120 | 模拟数据/Quandl | ❌ 模拟数据 |
| TED利差 | 银行间借贷与国债收益率差 | ≥70bp | FRED API或模拟 | ⚠️ 需FRED API密钥 |
| 10Y-2Y国债利差 | 收益率曲线斜率 | <0bp (倒挂) | FRED API或模拟 | ⚠️ 需FRED API密钥 |
| CDX-IG信用利差 | 企业违约风险指标 | ≥90bp | 模拟数据/Markit | ❌ 模拟数据 |

为获取更真实的风险评估，建议：
1. 获取并配置FRED API密钥以获取真实的TED利差和国债利差数据
2. 使用回填历史功能来构建合理的基线数据进行比较

## 风险评分计算

风险评分通过以下步骤计算:

1. 对每个指标计算252交易日滚动Z-score
2. 对国债利差指标取负值(因为较小值表示较高风险)
3. 使用加权平均计算综合风险评分
4. 根据风险评分确定风险级别:
   - <0.5: 绿色(低风险)
   - 0.5-1.0: 黄色(中等风险)
   - 1.0-1.5: 橙色(高风险)
   - >1.5: 红色(极高风险)

## 许可证

MIT

## 致谢

- Seeking Alpha for providing stock recommendations
- Yahoo Finance for stock price data
- Federal Reserve Economic Data (FRED) for economic indicators