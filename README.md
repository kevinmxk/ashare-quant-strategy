# A股主板短线趋势交易辅助策略 V1

这是一个面向个人投资者的命令行交易辅助工具。它不自动下单，不替你选股；你输入候选股票，它根据日线数据输出买点、卖点、止损、止盈、仓位和风险提示。

## 策略定位

- 只分析沪深主板股票，默认排除 ST、创业板、科创板、北交所。
- 适配小资金、手动确认、每周复盘、最长持有约 20 个交易日。
- 主逻辑是趋势突破、趋势回踩、ATR/均线止损、分批止盈、移动止盈。
- 中国五因子思想作为质量过滤层，不直接生成短线买卖点。
- 首板回调作为小仓位事件模块，默认最高 15% 仓位。

## 安装依赖

基础运行只需要：

```powershell
pip install -r requirements.txt
```

如果要拉真实行情，可以再安装其一：

```powershell
pip install akshare
```

或：

```powershell
pip install tushare
```

Tushare 需要设置 `TUSHARE_TOKEN`。

## 快速试跑

先用离线演示数据跑通：

```powershell
python -m ashare_quant.cli --demo
```

分析自选股：

```powershell
python -m ashare_quant.cli --provider akshare --codes 600519,000001,600036 --equity 80000 --peak-equity 80000
```

使用自选股、持仓和财务过滤：

```powershell
python -m ashare_quant.cli --provider akshare --watchlist examples/watchlist.csv --positions examples/positions.csv --fundamentals examples/fundamentals.csv
```

交互模式：

```powershell
python -m ashare_quant.cli --interactive
```

## CSV 行情格式

如果免费接口不稳定，可以把日线数据保存成 `data/600519.csv` 这类文件。字段：

```text
date,open,high,low,close,volume,amount
```

指数数据也用同样格式，文件名为：

```text
000300.csv
000905.csv
000852.csv
```

## 输出

程序会在命令行打印交易卡片，并保存：

```text
reports/signals_YYYY-MM-DD.csv
reports/signals_YYYY-MM-DD_etf.csv
```

每张卡片包含：

- 市场环境
- 个股状态
- 评分
- 建议动作
- 买入区间
- 初始止损
- 第一/第二止盈
- 移动止盈
- 建议仓位和股数
- 触发理由和风险提示

## 重要提醒

这是交易辅助工具，不构成投资建议。下单前请人工确认公告、涨跌停、成交量、盘口流动性和自己的风险承受能力。
