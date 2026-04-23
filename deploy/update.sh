#!/bin/bash
# =============================================================================
# ETF 量化策略 — 服务器自动更新脚本
# =============================================================================
# 用法:
#   chmod +x update.sh && sudo ./update.sh
#
# 本脚本会自动完成：
#   1. 拉取最新代码
#   2. 更新 Python 依赖
#   3. 重启 systemd 服务
#   4. 验证服务状态
# =============================================================================

set -e

# 配置项
PROJECT_NAME="etf_trader"
INSTALL_DIR="/opt/${PROJECT_NAME}"
LOG_DIR="/var/log/${PROJECT_NAME}"
SERVICE_NAME="${PROJECT_NAME}"
REPO_URL="https://github.com/kizi1014/finance.git"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

# =============================================================================
# 1. 检查 root 权限
# =============================================================================
if [ "$EUID" -ne 0 ]; then
    log_error "请使用 sudo 运行此脚本"
    exit 1
fi

log_info "开始更新 ETF 量化策略服务..."

# =============================================================================
# 2. 检查安装目录
# =============================================================================
if [ ! -d "$INSTALL_DIR" ]; then
    log_warn "安装目录 $INSTALL_DIR 不存在，执行全新部署..."
    curl -fsSL "${REPO_URL/raw.githubusercontent.com/raw.githubusercontent.com}" | sed 's|deploy.sh|deploy.sh|' | bash
    exit 0
fi

cd "$INSTALL_DIR"

# =============================================================================
# 3. 备份当前配置
# =============================================================================
log_step "备份当前配置..."
BACKUP_DIR="/tmp/etf_trader_backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -f etf_trader/.env "$BACKUP_DIR/" 2>/dev/null || true
cp -f etf_trader/config.py "$BACKUP_DIR/" 2>/dev/null || true
log_info "配置已备份到 $BACKUP_DIR"

# =============================================================================
# 4. 拉取最新代码
# =============================================================================
log_step "拉取最新代码..."

# 保存当前 commit hash
OLD_HASH=$(git rev-parse HEAD)
log_info "当前版本: ${OLD_HASH:0:8}"

# 拉取更新
git fetch origin main
git reset --hard origin/main

NEW_HASH=$(git rev-parse HEAD)
log_info "最新版本: ${NEW_HASH:0:8}"

if [ "$OLD_HASH" = "$NEW_HASH" ]; then
    log_warn "代码已是最新版本，无需更新"
else
    log_info "代码已更新"
    echo ""
    git log --oneline --no-decorate "${OLD_HASH}..${NEW_HASH}" | head -20
    echo ""
fi

# =============================================================================
# 5. 恢复配置文件
# =============================================================================
log_step "恢复配置文件..."

# 恢复 .env（通知配置）
if [ -f "$BACKUP_DIR/.env" ]; then
    cp -f "$BACKUP_DIR/.env" etf_trader/.env
    log_info ".env 通知配置已恢复"
else
    log_warn ".env 不存在，请手动配置通知渠道"
fi

# 恢复自定义 config.py（如果有）
if [ -f "$BACKUP_DIR/config.py" ]; then
    # 检查用户是否修改过关键配置（非默认的ETF_CODE等）
    OLD_ETF=$(grep "^ETF_CODE" "$BACKUP_DIR/config.py" | awk -F'"' '{print $2}')
    NEW_ETF=$(grep "^ETF_CODE" etf_trader/config.py | awk -F'"' '{print $2}')
    
    if [ "$OLD_ETF" != "$NEW_ETF" ]; then
        log_warn "检测到自定义 ETF 配置，保留原 config.py"
        cp -f "$BACKUP_DIR/config.py" etf_trader/config.py
    else
        log_info "config.py 使用新版本"
    fi
fi

# =============================================================================
# 6. 更新 Python 依赖
# =============================================================================
log_step "更新 Python 依赖..."

cd etf_trader

if [ ! -d "venv" ]; then
    log_warn "虚拟环境不存在，创建中..."
    python3 -m venv venv
fi

venv/bin/pip install --upgrade pip -q
venv/bin/pip install -r requirements.txt -q

# 安装/更新通知依赖
venv/bin/pip install requests -q

log_info "Python 依赖更新完成"

# =============================================================================
# 7. 更新 systemd 服务（如有变化）
# =============================================================================
log_step "检查 systemd 服务配置..."

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
if [ -f "$SERVICE_FILE" ]; then
    # 检查服务文件是否需要更新
    if ! grep -q "daily_task.py" "$SERVICE_FILE"; then
        log_warn "systemd 服务配置需要更新..."
        
        cat > "$SERVICE_FILE" << EOF
[Unit]
Description=ETF Quant Strategy Real-time Monitor
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}/etf_trader
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=${INSTALL_DIR}/etf_trader/.env
ExecStart=${INSTALL_DIR}/etf_trader/venv/bin/python ${INSTALL_DIR}/etf_trader/daily_task.py --strategy hybrid
Restart=always
RestartSec=10
StandardOutput=append:${LOG_DIR}/monitor.log
StandardError=append:${LOG_DIR}/monitor.log

[Install]
WantedBy=multi-user.target
EOF
        
        systemctl daemon-reload
        log_info "systemd 服务已更新（默认策略: hybrid）"
    else
        # 确保服务使用 hybrid 策略
        if ! grep -q "\-\-strategy hybrid" "$SERVICE_FILE"; then
            sed -i 's|daily_task.py|daily_task.py --strategy hybrid|' "$SERVICE_FILE"
            systemctl daemon-reload
            log_info "systemd 服务已更新为 hybrid 策略"
        fi
    fi
else
    log_warn "systemd 服务文件不存在，创建中..."
    
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=ETF Quant Strategy Real-time Monitor
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}/etf_trader
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=${INSTALL_DIR}/etf_trader/.env
ExecStart=${INSTALL_DIR}/etf_trader/venv/bin/python ${INSTALL_DIR}/etf_trader/daily_task.py --strategy hybrid
Restart=always
RestartSec=10
StandardOutput=append:${LOG_DIR}/monitor.log
StandardError=append:${LOG_DIR}/monitor.log

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}.service
    log_info "systemd 服务已创建"
fi

# =============================================================================
# 8. 重启服务
# =============================================================================
log_step "重启服务..."

# 停止旧服务
systemctl stop ${SERVICE_NAME}.service 2>/dev/null || true
sleep 2

# 启动新服务
systemctl start ${SERVICE_NAME}.service

# 等待服务启动
sleep 3

# =============================================================================
# 9. 验证状态
# =============================================================================
log_step "验证服务状态..."

if systemctl is-active --quiet ${SERVICE_NAME}.service; then
    log_info "✅ 服务运行正常"
else
    log_error "❌ 服务启动失败"
    echo ""
    systemctl status ${SERVICE_NAME}.service --no-pager
    exit 1
fi

# 检查最近日志
sleep 2
log_info "最近日志:"
echo "---"
tail -n 20 ${LOG_DIR}/monitor.log 2>/dev/null || log_warn "暂无日志"
echo "---"

# =============================================================================
# 10. 完成
# =============================================================================
echo ""
log_info "========================================"
log_info "更新完成！"
log_info "========================================"
echo ""
echo "版本: ${NEW_HASH:0:8}"
echo "安装目录: $INSTALL_DIR"
echo "日志目录: $LOG_DIR"
echo ""
echo "快捷命令:"
echo "  etf-start        启动监控服务"
echo "  etf-stop         停止监控服务"
echo "  etf-restart      重启监控服务"
echo "  etf-logs         查看实时日志"
echo "  etf-status       查看服务状态"
echo ""
echo "当前配置:"
echo "  默认策略: hybrid（趋势+网格）"
echo "  ETF列表: 510300, 159952, 512100, 159915, 588000"
echo ""
