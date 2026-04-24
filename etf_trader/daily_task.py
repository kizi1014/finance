#!/usr/bin/env python3
"""
ETF 策略每日收盘后定时报告服务

核心逻辑：
    - 每天收盘后（15:05）自动获取当日行情，计算信号
    - 对 ETF_LIST 中配置的所有基金分别生成报告
    - 收盘后发送一次汇总报告（所有 ETF 信号 + 建议操作）
    - 非运行时间自动休眠，节省资源
    - 支持手动触发：python daily_task.py --now

用法：
    # 启动定时服务（常驻后台，每天15:05自动运行）
    python daily_task.py
    
    # 指定策略
    python daily_task.py --strategy ma
    python daily_task.py --strategy grid
    python daily_task.py --strategy hybrid
    
    # 立即执行一次（测试用）
    python daily_task.py --now

systemd 服务配置：
    Type=simple 常驻进程，由 systemd 守护自动重启
"""

import argparse
import sys
import time
from datetime import datetime, time as dt_time, timedelta

from config import (
    ETF_CODE, ETF_NAME, ETF_LIST, MA_PERIOD, STRATEGY,
    USE_DUAL_MA, FAST_MA, SLOW_MA, TREND_MA,
    BACKTEST_START, BACKTEST_END,
    GRID_LOWER, GRID_UPPER, GRID_NUM
)
from data_feed import get_etf_hist, get_daily_close
from strategy import generate_signals, get_current_signal
from notifier import Notifier


# ==================== 交易日判断 ====================

def is_weekday() -> bool:
    """判断今天是否为工作日（周一到周五）"""
    return datetime.now().weekday() < 5


def get_next_run_time() -> datetime:
    """计算下次运行时间（下一个工作日 15:05）"""
    now = datetime.now()
    target_time = dt_time(15, 5)
    
    # 如果今天还没到过目标时间且是工作日
    if now.time() < target_time and is_weekday():
        return now.replace(hour=15, minute=5, second=0, microsecond=0)
    
    # 否则找下一个工作日
    next_day = now + timedelta(days=1)
    while next_day.weekday() >= 5:  # 跳过周末
        next_day += timedelta(days=1)
    
    return next_day.replace(hour=15, minute=5, second=0, microsecond=0)


def wait_until(target: datetime):
    """等待到目标时间"""
    while True:
        now = datetime.now()
        if now >= target:
            break
        remaining = (target - now).total_seconds()
        # 每分钟打印一次等待状态
        if int(remaining) % 60 == 0:
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            print(f"\r⏰ 等待中... 还有 {hours}小时{minutes}分钟 到达 {target.strftime('%Y-%m-%d %H:%M')}", end="", flush=True)
        time.sleep(1)
    print()  # 换行


# ==================== 单只 ETF 报告生成 ====================

def generate_etf_report(etf_config: dict, strategy: str) -> dict:
    """
    为单只 ETF 生成收盘后报告
    
    Args:
        etf_config: {"code": ..., "name": ..., "grid_lower": ..., "grid_upper": ..., "grid_num": ...}
        strategy: "ma" / "grid" / "hybrid"
    
    Returns:
        dict: 报告数据，包含信号、建议操作等
    """
    code = etf_config["code"]
    name = etf_config["name"]
    
    print(f"\n📊 正在生成 {name} ({code}) 报告...")
    
    # 获取历史数据
    df = get_etf_hist(code=code, start=BACKTEST_START, end=BACKTEST_END)
    if len(df) < MA_PERIOD + 5:
        print(f"  ⚠️ 历史数据不足，跳过")
        return None
    
    # 计算信号
    df = generate_signals(df)
    signal_info = get_current_signal(df)
    
    # 获取最新收盘价
    latest_row = df.iloc[-1]
    close_price = float(latest_row["close"])
    report_date = latest_row["date"]
    if hasattr(report_date, "strftime"):
        report_date = report_date.strftime("%Y-%m-%d")
    
    # 构建报告
    report = {
        "time": f"{report_date} 收盘后",
        "code": code,
        "name": name,
        "close": close_price,
        "signal": signal_info["signal"],
        "signal_label": signal_info.get("signal_label") or "无",
        "ma_values": signal_info.get("ma_values", {}),
        "trend_ok": signal_info.get("trend_ok", True),
        "strategy": strategy,
    }
    
    # 根据策略生成建议操作
    if strategy == "ma":
        report["action"] = _get_ma_action(report)
    elif strategy == "grid":
        report["action"] = _get_grid_action(report, etf_config)
    elif strategy == "hybrid":
        report["action"] = _get_hybrid_action(report, etf_config)
    
    # 打印到控制台
    print(f"  💰 收盘价: {close_price:.3f} 元")
    print(f"  📈 信号: {report['signal_label']}")
    if report["ma_values"]:
        ma_str = " | ".join([f"{k.upper()}={v:.3f}" for k, v in report["ma_values"].items()])
        print(f"  📐 {ma_str}")
    print(f"  💡 建议: {report['action']}")
    
    return report


def _get_ma_action(report: dict) -> str:
    """均线策略建议"""
    signal = report["signal"]
    if signal == 1:
        return "MA金叉信号，建议明日开盘后择机买入或加仓"
    elif signal == -1:
        return "MA死叉信号，建议明日开盘后择机卖出或减仓"
    else:
        return "暂无明确信号，建议持仓观望"


def _get_grid_action(report: dict, etf_config: dict) -> str:
    """网格策略建议"""
    price = report["close"]
    grid_lower = etf_config.get("grid_lower", GRID_LOWER)
    grid_upper = etf_config.get("grid_upper", GRID_UPPER)
    grid_num = etf_config.get("grid_num", GRID_NUM)
    
    grid_step = (grid_upper - grid_lower) / grid_num
    grid_idx = int((price - grid_lower) / grid_step)
    grid_idx = max(0, min(grid_idx, grid_num - 1))
    
    grid_low = grid_lower + grid_idx * grid_step
    grid_high = grid_low + grid_step
    
    distance_to_low = (price - grid_low) / grid_step
    distance_to_high = (grid_high - price) / grid_step
    
    if distance_to_low < 0.1:
        return f"价格接近网格下沿({grid_low:.3f})，建议明日逢低买入一格"
    elif distance_to_high < 0.1:
        return f"价格接近网格上沿({grid_high:.3f})，建议明日逢高卖出一格"
    else:
        return f"当前位于第{grid_idx+1}/{grid_num}格，持仓观望"


def _get_hybrid_action(report: dict, etf_config: dict) -> str:
    """混合策略建议"""
    signal = report["signal"]
    trend_ok = report.get("trend_ok", True)
    
    if signal == 1 and trend_ok:
        return "趋势向上确认，建议满仓持有或明日加仓"
    elif signal == -1:
        return "趋势转弱，建议减仓或清仓观望"
    else:
        # 无趋势信号时，参考网格
        price = report["close"]
        grid_lower = etf_config.get("grid_lower", GRID_LOWER)
        grid_upper = etf_config.get("grid_upper", GRID_UPPER)
        grid_num = etf_config.get("grid_num", GRID_NUM)
        
        grid_step = (grid_upper - grid_lower) / grid_num
        grid_idx = int((price - grid_lower) / grid_step)
        grid_idx = max(0, min(grid_idx, grid_num - 1))
        grid_low = grid_lower + grid_idx * grid_step
        grid_high = grid_low + grid_step
        distance_to_low = (price - grid_low) / grid_step
        distance_to_high = (grid_high - price) / grid_step
        
        if distance_to_low < 0.1:
            return f"无明确趋势，价格接近网格下沿({grid_low:.3f})，建议明日逢低买入"
        elif distance_to_high < 0.1:
            return f"无明确趋势，价格接近网格上沿({grid_high:.3f})，建议明日逢高卖出"
        else:
            return "趋势不明，建议持仓观望，等待明确信号"


# ==================== 汇总报告 ====================

def generate_all_reports(strategy: str) -> list:
    """
    为 ETF_LIST 中所有 ETF 生成报告
    
    Returns:
        list: 各 ETF 报告字典列表
    """
    print(f"\n{'='*60}")
    print(f"📊 ETF 每日收盘报告 ({datetime.now().strftime('%Y-%m-%d')})")
    print(f"{'='*60}")
    
    reports = []
    for etf in ETF_LIST:
        report = generate_etf_report(etf, strategy)
        if report:
            reports.append(report)
    
    print(f"\n{'='*60}")
    print(f"✅ 共生成 {len(reports)}/{len(ETF_LIST)} 只 ETF 报告")
    print("=" * 60)
    
    return reports


# ==================== 主程序 ====================

def run_once(strategy: str, notifier: Notifier = None):
    """
    执行一次每日报告（所有 ETF）
    
    Args:
        strategy: "ma" / "grid" / "hybrid"
        notifier: 通知器实例，为 None 时自动创建
    """
    if notifier is None:
        notifier = Notifier()
    
    # 生成所有 ETF 报告
    reports = generate_all_reports(strategy)
    if not reports:
        print("⚠️ 没有生成任何报告，跳过本次发送")
        return
    
    # 发送汇总通知
    notifier.send_daily_summary(reports, strategy)
    print(f"✅ 汇总报告已发送 ({datetime.now().strftime('%H:%M:%S')})")


def run_service(strategy: str):
    """
    启动每日定时服务（常驻进程）
    
    Args:
        strategy: "ma" / "grid" / "hybrid"
    """
    etf_names = ", ".join([e["name"] for e in ETF_LIST])
    
    print(f"\n{'='*60}")
    print(f"🚀 ETF策略每日收盘后报告服务启动")
    print(f"{'='*60}")
    print(f"监控标的: {len(ETF_LIST)} 只 ETF")
    print(f"策略: {strategy}")
    print(f"运行时间: 每个工作日 15:05")
    print(f"\n⚠️ 提示: 按 Ctrl+C 停止程序")
    print("-" * 60)
    
    notifier = Notifier()
    
    # 发送启动通知
    notifier.send(
        title="🚀 ETF每日报告服务已启动",
        content=f"监控标的数: {len(ETF_LIST)} 只\n"
                f"策略: {strategy}\n"
                f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"\n每个工作日收盘后（15:05）自动发送报告。"
    )
    
    try:
        while True:
            # 计算下次运行时间
            next_run = get_next_run_time()
            print(f"\n📅 下次运行时间: {next_run.strftime('%Y-%m-%d %H:%M')}")
            
            # 等待到目标时间
            wait_until(next_run)
            
            # 执行报告
            print(f"\n{'='*60}")
            print(f"⏰ 到达运行时间，开始生成报告...")
            run_once(strategy, notifier)
            
            # 等待一小段时间避免重复执行
            time.sleep(60)
            
    except KeyboardInterrupt:
        print("\n\n🛑 服务已停止")
        notifier.send(
            title="🛑 ETF每日报告服务已停止",
            content=f"停止时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"如需重新启动，请运行: python daily_task.py"
        )


def main():
    parser = argparse.ArgumentParser(description="ETF策略每日收盘后报告服务")
    parser.add_argument(
        "--strategy",
        choices=["ma", "grid", "hybrid"],
        default=STRATEGY,
        help="策略选择: ma=均线, grid=网格, hybrid=混合"
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="立即执行一次报告（不启动定时服务）"
    )
    args = parser.parse_args()
    
    if args.now:
        # 立即执行一次
        run_once(args.strategy)
    else:
        # 启动定时服务
        run_service(args.strategy)


if __name__ == "__main__":
    sys.exit(main())
