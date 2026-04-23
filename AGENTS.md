# AGENTS.md

## Project: ETF 混合策略自动交易程序

A Python quantitative trading system for Chinese A-share ETFs, with backtesting, live monitoring, and multi-channel notifications.

---

## Run Commands

```bash
cd etf_trader
pip install -r requirements.txt

# Backtest (default — runs hybrid strategy by default, configurable in config.py)
python main.py

# Backtest a specific strategy
python main.py --strategy ma       # MA crossover
python main.py --strategy grid     # grid
python main.py --strategy hybrid   # hybrid (default)

# Batch backtest all ETFs
python main.py --mode batch --strategy hybrid --top 5

# Live modes (real-time monitoring)
python main.py --mode simulate     # simulated trading
python main.py --mode manual       # print alerts only

# Server monitoring service (systemd)
python daily_task.py --strategy hybrid    # ma / grid / hybrid
```

## Architecture

```
etf_trader/
├── config.py           # All parameters — ETF code, MA periods, strategy toggles, capital
├── data_feed.py        # Data source: akshare → baostock (ETF fallback) → mock data
├── strategy.py         # Signal generation: MA crossover + trend filter
├── backtest.py         # MA strategy backtest engine
├── grid_backtest.py    # Grid strategy backtest engine
├── hybrid_backtest.py  # Hybrid (trend + grid) backtest engine
├── batch_backtest.py   # Batch backtest engine for multiple ETFs
├── trader.py           # Live trading (simulate/manual/qmt modes)
├── notifier.py         # Notifications: wechat > dingtalk > serverchan > console
├── daily_task.py       # Intraday monitoring service entrypoint
└── main.py             # CLI entrypoint
```

**Entry points**: `main.py` for backtest/live CLI, `daily_task.py` for server monitoring.

## Key Conventions

- **Data fallback chain**: akshare → baostock (对应ETF真实数据) → mock data. Never crashes on network failure.
- **akshare rate limits** apply; `REFRESH_INTERVAL` in `config.py` controls polling cadence (default 60s).
- **Notification priority**: WeChat Work > DingTalk > ServerChan > console. At least one channel must be configured via env vars.
- **Default strategy is hybrid** (`STRATEGY = "hybrid"` in config.py). Grid/MA strategy backtest requires `--strategy grid` or `--strategy ma`.
- **No test suite** exists. Manual verification by running backtest and inspecting output.
- **`.env` file** for secrets (notification keys). Not checked into repo.
- **Chinese-language codebase** throughout (variable names, comments, output).

## Server Deployment

```bash
# On Linux server
curl -fsSL https://raw.githubusercontent.com/kizi1014/finance/main/deploy/deploy.sh | bash

# After deployment
sudo nano /opt/etf_trader/etf_trader/.env   # configure notification channel
etf-start                                    # start systemd service
etf-logs                                     # view live logs
etf-status                                   # service status
etf-restart                                  # restart after config changes
```

Shortcut commands (`etf-start`, `etf-logs`, `etf-status`, `etf-restart`) are installed by `deploy.sh` under `/usr/local/bin`.

## Important Quirks

- `data_feed.py`: baostock fallback now fetches the actual ETF data (e.g., `sh.510300`), not HS300 index. The old index normalization logic has been removed.
- `data_feed.py:21–49`: akshare column names vary by version; `normalize_columns()` handles Chinese→English mapping.
- `strategy.py:124`: `ma_values` dict keys use lowercase like `"ma5"` not `"MA5"`.
- `config.py`: `STRATEGY = "hybrid"` means `--strategy` defaults to hybrid. Always specify `--strategy grid` or `--strategy ma` to run other backtests.
- `batch_backtest.py`: supports `grid`, `ma`, and `hybrid` strategies for batch backtesting.

## Batch Backtest

```bash
# 批量回测所有ETF（默认混合策略）
python main.py --mode batch --top 5

# 指定策略
python main.py --mode batch --strategy grid --top 3
python main.py --mode batch --strategy ma --top 3
```

批量回测支持的ETF在 `config.py:ETF_LIST` 中配置，包括：
- 510300 华泰柏瑞沪深300ETF
- 159952 华夏创业板ETF
- 512100 南方中证1000ETF
- 159915 易方达创业板ETF
- 588000 华夏科创50ETF

## Running Individual Test

```bash
# 回测单个ETF
python main.py --strategy ma
python main.py --strategy grid
python main.py --strategy hybrid   # default
```
