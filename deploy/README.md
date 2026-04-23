# ETF 量化策略 — Linux 服务器部署指南（盘中实时监控版）

## 方案概述

**Linux 服务器盘中实时监控 → 信号出现时即时推送微信/钉钉 → 手动在券商 APP 下单**

- ✅ **盘中实时监控**：交易时间内每 60 秒检查一次行情
- ✅ **信号即时推送**：买入/卖出信号出现时立即通知，不等到收盘
- ✅ **防重复打扰**：同一信号只推送一次
- ✅ **心跳保活**：每 30 分钟发送一次状态报告，确认程序正常运行
- ✅ **自动守护**：systemd 常驻服务，崩溃自动重启
- ✅ **非交易时间自动休眠**：节省资源

---

## 服务器要求

| 配置项 | 最低要求 | 推荐 |
|--------|---------|------|
| 系统 | Ubuntu 20.04+ / CentOS 7+ | Ubuntu 22.04 LTS |
| CPU | 1核 | 1核 |
| 内存 | 512MB | 1GB |
| 磁盘 | 10GB | 20GB SSD |
| 带宽 | 1Mbps | 1Mbps |

> 💡 **配置要求很低**：程序只是定时拉取数据和计算均线，不需要高配置。1核1G 足够。

**推荐云服务商**:
- 阿里云 ECS：1核1G，约 300元/年（新用户首年 99元）
- 腾讯云 CVM：1核1G，约 300元/年
- 华为云：类似价格

---

## 快速部署

### 1. 购买服务器并连接

```bash
ssh root@你的服务器IP
```

### 2. 一键部署

```bash
# 下载部署脚本
curl -fsSL https://raw.githubusercontent.com/kizi1014/finance/main/deploy/deploy.sh -o deploy.sh

# 执行部署
chmod +x deploy.sh && sudo ./deploy.sh
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

### 5. 启动监控服务

```bash
# 启动监控（systemd 常驻守护）
etf-start

# 查看状态
etf-status

# 查看实时日志
etf-logs
```

---

## 服务管理

```bash
# 启动 / 停止 / 重启
etf-start
etf-stop
etf-restart

# 查看实时日志
etf-logs

# 查看服务状态
etf-status

# systemctl 原生命令
systemctl status etf_trader
systemctl start etf_trader
systemctl stop etf_trader
systemctl restart etf_trader

# 查看系统日志
journalctl -u etf_trader -f
```

---

## 监控逻辑说明

### 交易时间内（9:30-11:30, 13:00-15:00）

程序每 **60 秒** 执行一次：

1. 拉取 ETF 实时行情
2. 获取历史数据计算均线
3. 判断当前信号状态
4. **如果信号发生变化** → 立即推送微信/钉钉通知
5. **每 30 分钟** → 发送一次心跳报告

### 非交易时间

程序自动休眠，每分钟检查一次是否到交易时间。

### 防重复机制

- 同一交易日的同一信号只推送 **一次**
- 即使价格反复穿越均线，也不会重复打扰

---

## 通知内容示例

### 买入信号（即时推送）

```
📈 ETF交易信号 — 买入

标的: 华泰柏瑞沪深300ETF (510300)
信号: 买入
参考价格: 4.052 元
MA5: 4.010
MA20: 3.998
MA60: 3.950

盘中实时监控触发 | 当前时间 10:23:15
MA5上穿MA20，趋势确认，建议立即关注

⏰ 请在券商APP中手动操作
⏱️ 通知时间: 2026-04-22 10:23:15
```

### 心跳报告（每30分钟）

```
💓 ETF监控心跳

标的: 华泰柏瑞沪深300ETF (510300)
当前价格: 4.052 元
当前信号: 无
MA5: 4.010
MA20: 3.998
MA60: 3.950

⏰ 监控运行正常，信号出现时立即通知
```

### 服务启动通知

```
🚀 ETF监控服务已启动

标的: 华泰柏瑞沪深300ETF (510300)
策略: ma
启动时间: 2026-04-22 09:00:00

交易时间内将实时监控，信号出现时立即通知。
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
tail -n 50 /var/log/etf_trader/monitor.log

# 4. 检查服务状态
systemctl status etf_trader
```

### 服务无法启动

```bash
# 查看详细错误
journalctl -u etf_trader --no-pager -n 100

# 手动运行看错误
cd /opt/etf_trader/etf_trader
source venv/bin/activate
source .env
python daily_task.py
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
sudo etf-restart
```

---

## 安全建议

1. **修改 SSH 端口**：避免默认 22 端口被扫描
2. **配置防火墙**：只开放必要的端口
3. **定期备份**：重要配置和日志定期备份
4. **监控告警**：可配置服务器监控（如阿里云云监控）

---

## 进阶：调整刷新频率

编辑 `config.py`：

```python
# 数据刷新间隔（秒）
# 60 秒 = 1分钟，适合日线策略
# 30 秒 = 更灵敏，但注意 akshare 有频率限制
REFRESH_INTERVAL = 60
```

修改后重启服务：

```bash
etf-restart
```

---

## 后续升级路径

当前是"盘中信号推送 + 手动下单"方案，后续可升级为全自动：

1. **QMT 全自动**：购买 Windows 云服务器，安装 QMT 客户端，完善 `trader.py` 中的 `QMTTrader`
2. **券商 API 直连**：如券商支持 XTP/PTrade 等 Linux API，可新增交易器类对接
