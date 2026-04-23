#!/bin/bash
# =============================================================================
# ETF 量化策略 — Linux 服务器一键部署脚本
# =============================================================================
# 用法:
#   chmod +x deploy.sh && ./deploy.sh
#
# 本脚本会自动完成：
#   1. 安装系统依赖 (git, python3, python3-venv)
#   2. 克隆代码仓库
#   3. 创建 Python 虚拟环境并安装依赖
#   4. 创建日志目录
#   5. 安装 systemd 定时服务
#   6. 配置 cron 定时任务
# =============================================================================

set -e

# 配置项
PROJECT_NAME="etf_trader"
INSTALL_DIR="/opt/${PROJECT_NAME}"
REPO_URL="https://github.com/kizi1014/finance.git"
LOG_DIR="/var/log/${PROJECT_NAME}"
SERVICE_NAME="${PROJECT_NAME}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# =============================================================================
# 1. 检查 root 权限
# =============================================================================
if [ "$EUID" -ne 0 ]; then
    log_error "请使用 sudo 运行此脚本"
    exit 1
fi

log_info "开始部署 ETF 量化策略服务..."

# =============================================================================
# 2. 安装系统依赖
# =============================================================================
log_info "安装系统依赖..."
apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip curl >/dev/null 2>&1
log_info "系统依赖安装完成"

# =============================================================================
# 3. 克隆/更新代码
# =============================================================================
if [ -d "$INSTALL_DIR" ]; then
    log_warn "目录 $INSTALL_DIR 已存在，执行 git pull 更新..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    log_info "克隆代码仓库到 $INSTALL_DIR ..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# =============================================================================
# 4. 创建虚拟环境并安装依赖
# =============================================================================
log_info "创建 Python 虚拟环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

log_info "安装 Python 依赖..."
venv/bin/pip install --upgrade pip -q
venv/bin/pip install -r etf_trader/requirements.txt -q

# 安装通知依赖
venv/bin/pip install requests -q

log_info "Python 依赖安装完成"

# =============================================================================
# 5. 创建日志目录
# =============================================================================
log_info "创建日志目录 $LOG_DIR ..."
mkdir -p "$LOG_DIR"
chmod 755 "$LOG_DIR"

# 配置日志轮转
log_info "配置日志轮转..."
cat > /etc/logrotate.d/${PROJECT_NAME} << 'EOF'
/var/log/etf_trader/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 644 root root
}
EOF

# =============================================================================
# 6. 创建 systemd 服务（用于手动触发或守护）
# =============================================================================
log_info "创建 systemd 服务..."

cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=ETF Quant Strategy Daily Task
After=network.target

[Service]
Type=oneshot
User=root
WorkingDirectory=${INSTALL_DIR}/etf_trader
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=${INSTALL_DIR}/etf_trader/.env
ExecStart=${INSTALL_DIR}/etf_trader/venv/bin/python ${INSTALL_DIR}/etf_trader/daily_task.py
StandardOutput=append:${LOG_DIR}/daily.log
StandardError=append:${LOG_DIR}/daily.log

[Install]
WantedBy=multi-user.target
EOF

# =============================================================================
# 7. 创建 systemd timer（定时触发）
# =============================================================================
log_info "创建 systemd timer（交易日 15:05 执行）..."

cat > /etc/systemd/system/${SERVICE_NAME}.timer << 'EOF'
[Unit]
Description=Run ETF strategy daily at 15:05 on weekdays

[Timer]
# 周一到周五 15:05 执行
OnCalendar=Mon..Fri 15:05:00
# 如果错过执行时间，5分钟内补执行
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}.timer
systemctl start ${SERVICE_NAME}.timer

log_info "systemd timer 已启用"

# =============================================================================
# 8. 备用 cron 任务（兼容旧系统）
# =============================================================================
log_info "配置 cron 定时任务（备用）..."

CRON_JOB="5 15 * * 1-5 cd ${INSTALL_DIR}/etf_trader && ${INSTALL_DIR}/etf_trader/venv/bin/python daily_task.py >> ${LOG_DIR}/daily.log 2>&1"

# 先删除旧的同名任务
(crontab -l 2>/dev/null | grep -v "daily_task.py" || true) | crontab -
# 添加新任务
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

log_info "cron 任务已配置"

# =============================================================================
# 9. 创建环境变量模板
# =============================================================================
log_info "创建环境变量配置文件..."

if [ ! -f "${INSTALL_DIR}/etf_trader/.env" ]; then
cat > "${INSTALL_DIR}/etf_trader/.env" << 'EOF'
# =============================================================================
# ETF 量化策略 — 通知渠道配置
# 请根据实际使用的通知方式，填写对应的配置项
# =============================================================================

# ---------- 微信企业号（推荐） ----------
# 1. 登录 https://work.weixin.qq.com 创建企业
# 2. 应用管理 → 创建应用，获取 AgentID
# 3. 我的企业 → 企业ID (CorpID)
# 4. 应用 → 查看 Secret
WECHAT_CORP_ID=
WECHAT_AGENT_ID=
WECHAT_SECRET=
WECHAT_TO_USER=@all

# ---------- 钉钉机器人 ----------
# 1. 钉钉群 → 群设置 → 智能群助手 → 添加机器人 → 自定义
# 2. 获取 Webhook 地址和加签密钥
DINGTALK_WEBHOOK=
DINGTALK_SECRET=

# ---------- Server酱（最简单） ----------
# 1. 访问 https://sct.ftqq.com/ 登录获取 SendKey
SERVERCHAN_KEY=
EOF
    log_warn "请在 ${INSTALL_DIR}/etf_trader/.env 中配置通知渠道"
else
    log_info "环境变量文件已存在，跳过创建"
fi

# =============================================================================
# 10. 创建快捷命令
# =============================================================================
log_info "创建快捷命令..."

cat > /usr/local/bin/etf-run << EOF
#!/bin/bash
# 手动执行策略任务
cd ${INSTALL_DIR}/etf_trader
source venv/bin/activate
python daily_task.py \$@
EOF
chmod +x /usr/local/bin/etf-run

cat > /usr/local/bin/etf-logs << EOF
#!/bin/bash
# 查看日志
tail -f ${LOG_DIR}/daily.log
EOF
chmod +x /usr/local/bin/etf-logs

cat > /usr/local/bin/etf-status << EOF
#!/bin/bash
# 查看服务状态
echo "=== systemd timer 状态 ==="
systemctl status ${SERVICE_NAME}.timer --no-pager
echo ""
echo "=== 下次执行时间 ==="
systemctl list-timers ${SERVICE_NAME}.timer --no-pager
echo ""
echo "=== 最近日志 ==="
tail -n 20 ${LOG_DIR}/daily.log
EOF
chmod +x /usr/local/bin/etf-status

# =============================================================================
# 11. 完成
# =============================================================================
log_info "========================================"
log_info "部署完成！"
log_info "========================================"
echo ""
echo "安装目录: $INSTALL_DIR"
echo "日志目录: $LOG_DIR"
echo ""
echo "快捷命令:"
echo "  etf-run          手动执行策略任务"
echo "  etf-run --strategy grid   执行网格策略"
echo "  etf-logs         查看实时日志"
echo "  etf-status       查看服务状态"
echo ""
echo "管理命令:"
echo "  systemctl status ${SERVICE_NAME}.timer   查看定时器状态"
echo "  systemctl start ${SERVICE_NAME}.service  立即执行任务"
echo "  journalctl -u ${SERVICE_NAME}            查看系统日志"
echo ""
echo "⚠️ 重要：请编辑 ${INSTALL_DIR}/etf_trader/.env 配置通知渠道"
echo "   至少配置微信、钉钉、Server酱 中的一种"
echo ""
echo "测试通知:"
echo "  cd ${INSTALL_DIR}/etf_trader"
echo "  source .env && venv/bin/python notifier.py"
echo ""
