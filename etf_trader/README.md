# ETF 均线策略自动交易程序

基于 **20日均线交叉** 的沪深300场内ETF量化交易策略。

## 策略逻辑

### 原版（单均线）
| 信号 | 条件 | 操作 |
|------|------|------|
| 金叉（买入）| 当日收盘价 **上穿** 20日均线 | 买入 |
| 死叉（卖出）| 当日收盘价 **下穿** 20日均线 | 卖出 |

### 优化版（默认启用）
在 `config.py` 中通过开关自由组合：

| 优化项 | 作用 | 配置项 |
|--------|------|--------|
| **双均线交叉** | MA5 上穿 MA20 买入（比收盘价更灵敏） | `USE_DUAL_MA = True` |
| **趋势过滤** | 只在 `close > MA60` 且 `MA20 > MA60` 时买入，过滤下跌趋势中的假反弹 | `USE_TREND_FILTER = True` |
| **止损保护** | 持仓亏损达到 5% 强制卖出，控制单笔亏损 | `USE_STOP_LOSS = True` |

买入条件（需同时满足）：
1. MA5 上穿 MA20（金叉）
2. 收盘价 > MA60（大趋势向上）
3. MA20 > MA60（中期趋势在长期趋势之上）

卖出条件（满足任一）：
1. MA5 下穿 MA20（死叉）
2. 持仓亏损 ≥ 5%（止损）

## 项目结构

```
etf_trader/
├── config.py           # 配置参数（标的、资金、费率等）
├── data_feed.py        # 数据获取（akshare）
├── strategy.py         # 策略计算（均线、信号）
├── backtest.py         # 回测引擎
├── grid_backtest.py    # 网格策略回测
├── hybrid_backtest.py  # 混合策略回测
├── trader.py           # 交易执行（模拟/QMT/手动）
├── notifier.py         # 通知模块（微信/钉钉/Server酱）
├── daily_task.py       # 每日定时任务（服务器部署用）
├── main.py             # 主程序入口
├── requirements.txt    # Python依赖
└── README.md           # 本文件

deploy/
├── deploy.sh           # Linux 服务器一键部署脚本
└── README.md           # 服务器部署详细指南
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行回测

```bash
python main.py
```

回测会自动下载 510300（华泰柏瑞沪深300ETF）的历史数据，计算均线信号，并输出回测报告。

### 3. 运行模拟盘

```bash
python main.py --mode simulate
```

程序会定时获取最新行情，出现均线交叉信号时模拟成交，并跟踪账户盈亏。

### 4. 手动提醒模式

```bash
python main.py --mode manual
```

只在终端打印买卖提醒，不自动下单，适合在券商APP里手动操作。

## 配置说明

编辑 `config.py` 修改以下参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `ETF_CODE` | ETF代码 | `510300`（华泰柏瑞沪深300ETF） |
| `MA_PERIOD` | 均线周期 | `20` |
| `INITIAL_CAPITAL` | 初始资金（回测用） | `100000` |
| `POSITION_RATIO` | 每次买入仓位比例 | `1.0`（全仓） |
| `COMMISSION_RATE` | 券商佣金率 | `0.0003`（万3） |
| `RUN_MODE` | 默认运行模式 | `"backtest"` |
| `STRATEGY` | 策略选择 | `"grid"`（可选 ma/grid/hybrid） |

其他沪深300 ETF 可选：
- `510330` 华夏沪深300ETF
- `159919` 嘉实沪深300ETF

## 服务器部署（信号推送）

将策略部署到 Linux 服务器，每天收盘后自动计算信号，通过微信/钉钉推送通知。

### 一键部署

```bash
# 在 Linux 服务器上执行
sudo curl -fsSL https://raw.githubusercontent.com/kizi1014/finance/main/deploy/deploy.sh | bash
```

### 配置通知

编辑 `/opt/etf_trader/etf_trader/.env`，配置至少一种通知渠道：

```bash
# Server酱（最简单）
SERVERCHAN_KEY=你的SendKey

# 或钉钉机器人
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
DINGTALK_SECRET=加签密钥

# 或微信企业号
WECHAT_CORP_ID=企业ID
WECHAT_AGENT_ID=应用AgentID
WECHAT_SECRET=应用Secret
```

### 管理命令

```bash
etf-run            # 手动执行策略任务
etf-logs           # 查看实时日志
etf-status         # 查看服务状态
```

详细部署指南见 [`deploy/README.md`](deploy/README.md)。

## 实盘交易接入

### 方式一：QMT（全自动）

1. 开通支持 QMT 的券商（如国金、华泰、银河等）
2. 申请开通 **miniQMT** 权限
3. 安装券商提供的 QMT 客户端（仅 Windows）
4. 在 `config.py` 中填写 QMT 路径和账号
5. 在 `trader.py` 的 `QMTTrader` 中取消注释并完善下单代码
6. 运行：`python main.py --mode qmt`

### 方式二：服务器信号推送 + 手动下单（推荐过渡方案）

按上方"服务器部署"章节操作，收到微信/钉钉通知后，在券商APP手动下单。

### 方式三：手动执行

使用 `--mode manual`，程序会在出现信号时打印提醒，你手动在券商APP中下单。

## 风险提示

⚠️ **本策略仅为技术演示，不构成投资建议。**

1. **震荡市风险**：均线策略在趋势行情中表现较好，但在震荡市中会频繁出现假信号（反复打脸）。
2. **滑点与冲击成本**：实盘成交价可能与信号价格存在偏差，大额资金冲击成本更高。
3. **无法成交风险**：涨停/跌停时无法买入/卖出。
4. **策略失效风险**：任何策略都可能随着市场环境变化而失效。

建议先用 **回测** 和 **模拟盘** 充分验证后，再考虑小资金实盘。

## 扩展建议

- 加入 **止损机制**（如亏损 5% 强制止损）✅ 已实现
- 加入 **仓位管理**（如均线多头排列时满仓，空头时空仓或半仓）
- 加入 **过滤条件**（如只在大盘趋势向上时开仓）✅ 已实现
- 优化为 **分钟级策略**（需接入实时行情源）
- 接入 **邮件/微信通知**（信号出现时自动提醒）✅ 已实现

## 依赖

- [akshare](https://www.akshare.xyz/) - 免费金融数据接口
- pandas / numpy - 数据处理
- matplotlib - 绘图（如需可视化）
- requests - 通知推送
