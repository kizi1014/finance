#!/usr/bin/env python3
"""
每日定时任务：收盘后运行策略，检测信号，推送通知

用法：
    # 手动执行
    python daily_task.py
    
    # 指定策略
    python daily_task.py --strategy ma
    python daily_task.py --strategy grid
    python daily_task.py --strategy hybrid

推荐定时（cron）：
    # 每天 15:05 执行（A股收盘后5分钟）
    5 15 * * 1-5 cd /opt/etf_trader && /opt/etf_trader/venv/bin/python daily_task.py >> /var/log/etf_trader/daily.log 2>&1
"""

import argparse
import sys
from datetime import datetime

from config import (
    ETF_CODE, ETF_NAME, MA_PERIOD, STRATEGY,
    USE_DUAL_MA, FAST_MA, SLOW_MA, TREND_MA,
    INITIAL_CAPITAL, BACKTEST_START
)
from data_feed import get_etf_hist
from strategy import generate_signals, get_current_signal
from backtest import BacktestEngine
from grid_backtest import GridBacktestEngine
from hybrid_backtest import HybridBacktestEngine
from notifier import Notifier


def run_ma_daily():
    """均线策略每日检查"""
    print(f"\n{'='*60}")
    print(f"📈 均线策略每日检查 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"标的: {ETF_NAME} ({ETF_CODE})")
    
    # 获取数据
    df = get_etf_hist(code=ETF_CODE, start=BACKTEST_START)
    if len(df) < MA_PERIOD + 5:
        print("❌ 数据不足，跳过")
        return None
    
    # 计算信号
    df = generate_signals(df)
    signal_info = get_current_signal(df)
    
    # 构建报告
    report = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "code": ETF_CODE,
        "name": ETF_NAME,
        "close": signal_info["close"],
        "signal": signal_info["signal"],
        "signal_label": signal_info["signal_label"],
        "trend_ok": signal_info["trend_ok"],
        "blocked": signal_info["blocked"],
        "ma_values": signal_info["ma_values"],
    }
    
    # 打印信号详情
    print(f"\n收盘价: {signal_info['close']:.3f}")
    for k, v in signal_info["ma_values"].items():
        print(f"{k.upper()}: {v:.3f}")
    print(f"信号: {signal_info['signal_label'] or '无'}")
    
    # 判断是否需要通知
    notifier = Notifier()
    
    if signal_info["signal"] == 1:
        # 买入信号
        report["action"] = "建议买入"
        notifier.send_trade_signal(
            signal_type="买入",
            code=ETF_CODE,
            name=ETF_NAME,
            price=signal_info["close"],
            ma_values=signal_info["ma_values"],
            extra_info="MA5上穿MA20，趋势确认，建议建仓"
        )
    elif signal_info["signal"] == -1:
        # 卖出信号
        report["action"] = "建议卖出"
        notifier.send_trade_signal(
            signal_type="卖出",
            code=ETF_CODE,
            name=ETF_NAME,
            price=signal_info["close"],
            ma_values=signal_info["ma_values"],
            extra_info="MA5下穿MA20，建议清仓"
        )
    elif signal_info["blocked"]:
        # 被过滤的信号
        report["action"] = "金叉被过滤（趋势向下）"
        notifier.send(
            title="⚠️ ETF信号提醒 — 金叉被过滤",
            content=f"{ETF_NAME} ({ETF_CODE}) 出现金叉，但趋势未确认，已过滤。\n"
                    f"收盘价: {signal_info['close']:.3f}\n"
                    f"建议观望，等待趋势转好。"
        )
    else:
        report["action"] = "无操作"
        print("\n✅ 今日无交易信号")
    
    # 发送每日报告（无论是否有信号）
    notifier.send_daily_report(report)
    
    return report


def run_grid_daily():
    """网格策略每日检查"""
    print(f"\n{'='*60}")
    print(f"📊 网格策略每日检查 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"标的: {ETF_NAME} ({ETF_CODE})")
    
    from config import GRID_LOWER, GRID_UPPER, GRID_NUM, GRID_INITIAL_PCT
    
    df = get_etf_hist(code=ETF_CODE, start=BACKTEST_START)
    latest = df.iloc[-1]
    close = latest["close"]
    
    # 计算当前所在网格
    grid_step = (GRID_UPPER - GRID_LOWER) / GRID_NUM
    grid_idx = int((close - GRID_LOWER) / grid_step)
    grid_idx = max(0, min(grid_idx, GRID_NUM - 1))
    
    grid_low = GRID_LOWER + grid_idx * grid_step
    grid_high = grid_low + grid_step
    
    report = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "code": ETF_CODE,
        "name": ETF_NAME,
        "close": close,
        "signal_label": f"网格第{grid_idx+1}/{GRID_NUM}格",
        "ma_values": {"grid_low": grid_low, "grid_high": grid_high},
    }
    
    print(f"\n收盘价: {close:.3f}")
    print(f"当前网格: 第 {grid_idx+1}/{GRID_NUM} 格")
    print(f"网格区间: [{grid_low:.3f}, {grid_high:.3f}]")
    
    notifier = Notifier()
    
    # 网格策略提醒：接近网格边界时提醒
    distance_to_low = (close - grid_low) / grid_step
    distance_to_high = (grid_high - close) / grid_step
    
    if distance_to_low < 0.1:
        report["action"] = "接近网格下沿，准备买入"
        notifier.send_trade_signal(
            signal_type="买入",
            code=ETF_CODE,
            name=ETF_NAME,
            price=close,
            ma_values={"grid_low": grid_low, "grid_high": grid_high},
            extra_info=f"价格接近网格下沿({grid_low:.3f})，建议买入一格"
        )
    elif distance_to_high < 0.1:
        report["action"] = "接近网格上沿，准备卖出"
        notifier.send_trade_signal(
            signal_type="卖出",
            code=ETF_CODE,
            name=ETF_NAME,
            price=close,
            ma_values={"grid_low": grid_low, "grid_high": grid_high},
            extra_info=f"价格接近网格上沿({grid_high:.3f})，建议卖出一格"
        )
    else:
        report["action"] = "持仓观望"
        print("\n✅ 价格在网格中部，无需操作")
    
    notifier.send_daily_report(report)
    return report


def run_hybrid_daily():
    """混合策略每日检查"""
    print(f"\n{'='*60}")
    print(f"🔀 混合策略每日检查 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"标的: {ETF_NAME} ({ETF_CODE})")
    
    df = get_etf_hist(code=ETF_CODE, start=BACKTEST_START)
    df = generate_signals(df)
    signal_info = get_current_signal(df)
    
    from config import GRID_LOWER, GRID_UPPER, GRID_NUM
    
    close = signal_info["close"]
    grid_step = (GRID_UPPER - GRID_LOWER) / GRID_NUM
    grid_idx = int((close - GRID_LOWER) / grid_step)
    grid_idx = max(0, min(grid_idx, GRID_NUM - 1))
    
    grid_low = GRID_LOWER + grid_idx * grid_step
    grid_high = grid_low + grid_step
    
    report = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "code": ETF_CODE,
        "name": ETF_NAME,
        "close": close,
        "signal_label": signal_info["signal_label"] or "无趋势信号",
        "trend_ok": signal_info["trend_ok"],
        "ma_values": {**signal_info["ma_values"], "grid_low": grid_low, "grid_high": grid_high},
    }
    
    print(f"\n收盘价: {close:.3f}")
    for k, v in signal_info["ma_values"].items():
        print(f"{k.upper()}: {v:.3f}")
    print(f"趋势信号: {signal_info['signal_label'] or '无'}")
    print(f"网格位置: 第 {grid_idx+1}/{GRID_NUM} 格 [{grid_low:.3f}, {grid_high:.3f}]")
    
    notifier = Notifier()
    
    # 混合策略逻辑：趋势信号优先，无趋势信号时按网格提醒
    if signal_info["signal"] == 1 and signal_info["trend_ok"]:
        report["action"] = "趋势向上，建议满仓持有"
        notifier.send_trade_signal(
            signal_type="买入",
            code=ETF_CODE,
            name=ETF_NAME,
            price=close,
            ma_values=signal_info["ma_values"],
            extra_info="上升趋势确认，建议满仓持有，停止网格卖出"
        )
    elif signal_info["signal"] == -1:
        report["action"] = "趋势转弱，建议清仓或转网格"
        notifier.send_trade_signal(
            signal_type="卖出",
            code=ETF_CODE,
            name=ETF_NAME,
            price=close,
            ma_values=signal_info["ma_values"],
            extra_info="趋势转弱，建议清仓或切换为网格交易模式"
        )
    else:
        # 无明确趋势信号，按网格提醒
        distance_to_low = (close - grid_low) / grid_step
        distance_to_high = (grid_high - close) / grid_step
        
        if distance_to_low < 0.1:
            report["action"] = "震荡市，接近网格下沿买入"
            notifier.send_trade_signal(
                signal_type="买入",
                code=ETF_CODE,
                name=ETF_NAME,
                price=close,
                ma_values={"grid_low": grid_low, "grid_high": grid_high},
                extra_info="无明确趋势，按网格策略接近下沿买入"
            )
        elif distance_to_high < 0.1:
            report["action"] = "震荡市，接近网格上沿卖出"
            notifier.send_trade_signal(
                signal_type="卖出",
                code=ETF_CODE,
                name=ETF_NAME,
                price=close,
                ma_values={"grid_low": grid_low, "grid_high": grid_high},
                extra_info="无明确趋势，按网格策略接近上沿卖出"
            )
        else:
            report["action"] = "观望"
            print("\n✅ 无明确信号，持仓观望")
    
    notifier.send_daily_report(report)
    return report


def main():
    parser = argparse.ArgumentParser(description="ETF策略每日定时任务")
    parser.add_argument(
        "--strategy",
        choices=["ma", "grid", "hybrid"],
        default=STRATEGY,
        help="策略选择: ma=均线, grid=网格, hybrid=混合"
    )
    args = parser.parse_args()
    
    print(f"\n🚀 ETF策略每日任务启动")
    print(f"策略: {args.strategy}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        if args.strategy == "grid":
            report = run_grid_daily()
        elif args.strategy == "hybrid":
            report = run_hybrid_daily()
        else:
            report = run_ma_daily()
        
        print(f"\n✅ 任务完成")
        return 0
        
    except Exception as e:
        print(f"\n❌ 任务失败: {e}")
        # 发送错误通知
        notifier = Notifier()
        notifier.send(
            title="🚨 ETF策略运行异常",
            content=f"策略: {args.strategy}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n错误: {str(e)}\n\n请检查服务器日志。"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
