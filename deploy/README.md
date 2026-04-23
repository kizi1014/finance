# ETF 量化策略 — Linux 服务器部署指南

## 方案概述

**Linux 服务器定时计算信号 → 微信/钉钉推送通知 → 手动在券商 APP 下单**

- ✅ 成本低（Linux 服务器约 500-1000 元/年）
- ✅ 风险可控（不自动下单，人工确认）
- ✅ 7×24 小时稳定运行
- ✅ 多渠道推送（微信/钉钉/Server酱）

---

## 服务器要求

| 配置项 | 最低要求 | 推荐 |
|--------|---------|------|
| 系统 | Ubuntu 20.04+ / CentOS 7+ | Ubuntu 22.04 LTS |
| CPU | 1核 | 2核 |
| 内存 | 1GB | 2GB |
| 磁盘 | 20GB | 40GB SSD |
| 带宽 | 1Mbps | 2Mbps |

**推荐云服务商**:
- 阿里云 ECS：2核2G，约 600元/年（新用户首年 99元）
- 腾讯云 CVM：2核2G，约 600元/年
- 华为云：类似价格

**地域选择**: 国内任意节点即可（数据通过 akshare 获取，无需低延迟）

---

## 快速部署

### 1. 购买服务器并连接

```bash
# 通过 SSH 连接到服务器
ssh root@你的服务器IP
```

### 2. 一键部署

```bash
# 下载部署脚本
curl -fsSL https://raw.githubusercontent.com/kizi1014/finance/main/deploy/deploy.sh -o deploy.sh

# 执行部署
chmod +x deploy.sh && sudo ./deploy.sh
```

或者手动执行：

```bash
cd /opt
sudo git clone https://github.com/kizi1014/finance.git etf_trader
cd etf_trader/etf_trader

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install requests
```

### 3. 配置通知渠道

编辑环境变量文件：

```bash
sudo nano /opt/etf_trader/etf_trader/.env
```

#### 方式一：Server酱（最简单，推荐新手）

1. 访问 https://sct.ftqq.com/ 用 GitHub 账号登录
2. 复制 SendKey
3. 填入 `.env`：

```bash
SERVERCHAN_KEY=你的SendKey
```

#### 方式二：钉钉机器人

1. 打开钉钉群 → 群设置 → 智能群助手 → 添加机器人 → 自定义
2. 获取 Webhook 地址和加签密钥
3. 填入 `.env`：

```bash
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
DINGTALK_SECRET=加签密钥
```

#### 方式三：微信企业号（最稳定）

1. 访问 https://work.weixin.qq.com 注册企业微信
2. 应用管理 → 创建应用，记录 AgentID
3. 我的企业 → 企业ID (CorpID)
4. 应用 → 查看 Secret
5. 填入 `.env`：

```bash
WECHAT_CORP_ID=企业ID
WECHAT_AGENT_ID=应用AgentID
WECHAT_SECRET=应用Secret
WECHAT_TO_USER=@all
```

### 4. 测试通知

```bash
# 加载环境变量并测试
source /opt/etf_trader/etf_trader/.env
cd /opt/etf_trader/etf_trader
venv/bin/python notifier.py
```

如果配置正确，你会收到一条测试消息。

### 5. 手动运行策略

```bash
# 均线策略
etf-run

# 网格策略
etf-run --strategy grid

# 混合策略
etf-run --strategy hybrid
```

### 6. 查看日志

```bash
# 实时查看日志
etf-logs

# 查看服务状态
etf-status
```

---

## 定时任务说明

部署完成后，系统会自动配置定时任务：

- **执行时间**: 周一到周五 15:05（A股收盘后 5 分钟）
- **执行内容**: 运行 `daily_task.py`，计算信号并推送通知
- **日志位置**: `/var/log/etf_trader/daily.log`

### 管理定时任务

```bash
# 查看定时器状态
systemctl status etf_trader.timer

# 立即执行一次
systemctl start etf_trader.service

# 停止定时任务
systemctl stop etf_trader.timer

# 重新启用
systemctl start etf_trader.timer
systemctl enable etf_trader.timer
```

### 修改执行时间

```bash
sudo nano /etc/systemd/system/etf_trader.timer
```

修改 `OnCalendar` 行，例如改为早上 9:35：

```ini
OnCalendar=Mon..Fri 9:35:00
```

然后重载：

```bash
sudo systemctl daemon-reload
sudo systemctl restart etf_trader.timer
```

---

## 通知内容示例

### 买入信号

```
📈 ETF交易信号 — 买入

标的: 华泰柏瑞沪深300ETF (510300)
信号: 买入
参考价格: 4.052 元
MA5: 4.010
MA20: 3.998
MA60: 3.950

MA5上穿MA20，趋势确认，建议建仓

⏰ 请在券商APP中手动操作
```

### 每日报告（无信号时）

```
📊 ETF策略每日报告

运行时间: 2026-04-22 15:05:03
标的: 华泰柏瑞沪深300ETF (510300)
最新收盘价: 4.052
当前信号: 无
MA5: 4.010
MA20: 3.998
MA60: 3.950
```

---

## 故障排查

### 收不到通知

```bash
# 1. 检查环境变量是否加载
cat /opt/etf_trader/etf_trader/.env

# 2. 手动测试通知
cd /opt/etf_trader/etf_trader
source .env
venv/bin/python -c "from notifier import Notifier; n = Notifier(); n.send('测试', '这是一条测试消息')"

# 3. 检查日志
tail -n 50 /var/log/etf_trader/daily.log
```

### 策略运行报错

```bash
# 查看详细日志
journalctl -u etf_trader --no-pager -n 100

# 手动运行看错误
etf-run
```

### 数据获取失败

akshare 偶尔会因数据源维护而失败，程序会自动：
1. 尝试 baostock 备选数据源
2. 降级为模拟数据（仅用于测试）

如果长期失败，检查服务器网络：

```bash
ping www.eastmoney.com
curl -I https://quote.eastmoney.com
```

---

## 升级更新

```bash
cd /opt/etf_trader
sudo git pull origin main
sudo systemctl restart etf_trader.timer
```

---

## 安全建议

1. **修改 SSH 端口**：避免默认 22 端口被扫描
2. **配置防火墙**：只开放必要的端口
3. **定期备份**：重要配置和日志定期备份
4. **监控告警**：可配置服务器监控（如阿里云云监控）

---

## 进阶：Docker 部署（可选）

如果你熟悉 Docker，也可以用容器化部署：

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY etf_trader/ .
RUN pip install --no-cache-dir -r requirements.txt requests

ENV PYTHONUNBUFFERED=1
CMD ["python", "daily_task.py"]
```

```bash
docker build -t etf-trader .
docker run --env-file .env etf-trader
```

---

## 后续升级路径

当前是"信号推送 + 手动下单"方案，后续可升级为全自动：

1. **QMT 全自动**：购买 Windows 云服务器，安装 QMT 客户端，完善 `trader.py` 中的 `QMTTrader`
2. **券商 API 直连**：如券商支持 XTP/PTrade 等 Linux API，可新增交易器类对接
3. **多因子策略**：在 `strategy.py` 中加入更多技术指标和过滤条件
