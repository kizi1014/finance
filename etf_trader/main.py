#!/usr/bin/env python3
"""
ETF 均线策略自动交易程序

用法:
    # 回测模式（默认）
    python main.py
    
    # 模拟盘模式（实时监控，模拟成交）
    python main.py --mode simulate
    
    # 手动提醒模式
    python main.py --mode manual
"""

import argparse
import time
import sys
from datetime import datetime

from config import (
    ETF_CODE, ETF_NAME, MA_PERIOD, RUN_MODE, REFRESH_INTERVAL, STRATEGY,
    USE_DUAL_MA, USE_TREND_FILTER, USE_STOP_LOSS, STOP_LOSS_PCT,
    FAST_MA, SLOW_MA, TREND_MA,
    GRID_LOWER, GRID_UPPER, GRID_NUM, GRID_INITIAL_PCT
)
from data_feed import get_etf_hist, get_latest_price
from strategy import generate_signals, get_current_signal
from backtest import BacktestEngine
from grid_backtest import GridBacktestEngine
from hybrid_backtest import HybridBacktestEngine
from trader import create_trader


def run_ma_backtest():
    """运行均线策略回测"""
    print(f"\n{'='*60}")
    print(f"📈 ETF均线策略回测")
    print(f"{'='*60}")
    print(f"标的: {ETF_NAME} ({ETF_CODE})")
    
    if USE_DUAL_MA:
        print(f"策略: MA{FAST_MA} × MA{SLOW_MA} 双均线交叉")
        if USE_TREND_FILTER:
            print(f"      + MA{TREND_MA} 趋势过滤（只做多）")
        if USE_STOP_LOSS:
            print(f"      + {STOP_LOSS_PCT*100:.0f}% 止损保护")
    else:
        print(f"策略: 收盘价 × MA{MA_PERIOD} 单均线交叉")
    
    df = get_etf_hist(code=ETF_CODE)
    df = generate_signals(df)
    engine = BacktestEngine()
    report = engine.run(df)
    
    if report["trades"]:
        print(f"\n📋 交易明细")
        print("-" * 80)
        print(f"{'日期':<12} {'操作':<16} {'价格':>8} {'股数':>10} {'金额':>12} {'佣金':>8}")
        print("-" * 80)
        for t in report["trades"]:
            print(f"{t['date'].strftime('%Y-%m-%d'):<12} {t['action']:<16} "
                  f"{t['price']:>8.3f} {t['shares']:>10} {t['amount']:>12.2f} {t['commission']:>8.2f}")
    
    return report


def run_hybrid_backtest():
    """运行混合策略回测"""
    print(f"\n{'='*60}")
    print(f"📈 ETF混合策略回测（趋势+网格）")
    print(f"{'='*60}")
    print(f"标的: {ETF_NAME} ({ETF_CODE})")
    print(f"逻辑: 上升趋势满仓持有 | 震荡/下跌转网格交易")

    df = get_etf_hist(code=ETF_CODE)
    engine = HybridBacktestEngine()
    report = engine.run(df)

    if report["trades"]:
        print(f"\n📋 交易明细")
        print("-" * 85)
        print(f"{'日期':<12} {'操作':<14} {'网格':>4} {'价格':>8} {'股数':>10} {'金额':>12} {'佣金':>8}")
        print("-" * 85)
        for t in report["trades"]:
            print(f"{t['date'].strftime('%Y-%m-%d'):<12} {t['action']:<14} "
                  f"{str(t.get('grid', '-')):>4} {t['price']:>8.3f} {t['shares']:>10} "
                  f"{t['amount']:>12.2f} {t['commission']:>8.2f}")

    return report


def run_grid_backtest():
    """运行网格策略回测"""
    print(f"\n{'='*60}")
    print(f"📈 ETF网格策略回测")
    print(f"{'='*60}")
    print(f"标的: {ETF_NAME} ({ETF_CODE})")
    print(f"策略: 等差网格 ({GRID_LOWER:.1f} ~ {GRID_UPPER:.1f}, {GRID_NUM} 格)")
    print(f"      初始建仓 {GRID_INITIAL_PCT*100:.0f}%，价格下跌买入 / 上涨卖出")
    
    df = get_etf_hist(code=ETF_CODE)
    engine = GridBacktestEngine(
        lower=GRID_LOWER,
        upper=GRID_UPPER,
        num_grids=GRID_NUM,
        initial_pct=GRID_INITIAL_PCT
    )
    report = engine.run(df)
    
    if report["trades"]:
        print(f"\n📋 交易明细")
        print("-" * 85)
        print(f"{'日期':<12} {'操作':<14} {'网格':>4} {'价格':>8} {'股数':>10} {'金额':>12} {'佣金':>8}")
        print("-" * 85)
        for t in report["trades"]:
            print(f"{t['date'].strftime('%Y-%m-%d'):<12} {t['action']:<14} "
                  f"{t.get('grid', '-'):>4} {t['price']:>8.3f} {t['shares']:>10} "
                  f"{t['amount']:>12.2f} {t['commission']:>8.2f}")
    
    return report


def run_live(mode: str):
    """
    实时运行（模拟盘/手动提醒）
    
    说明：
    - 日线策略通常每天只需要判断一次（收盘后或次日开盘前）
    - 本程序简化为定时轮询，实际生产建议用定时任务（如 cron）
    """
    print(f"\n{'='*60}")
    print(f"🔄 ETF均线策略实时监控")
    print(f"{'='*60}")
    print(f"标的: {ETF_NAME} ({ETF_CODE})")
    print(f"模式: {mode}")
    print(f"策略: {MA_PERIOD}日均线交叉")
    print(f"刷新间隔: {REFRESH_INTERVAL} 秒")
    print(f"\n⚠️ 提示: 按 Ctrl+C 停止程序")
    print("-" * 60)
    
    trader = create_trader(mode)
    last_signal_date = None
    
    try:
        while True:
            now = datetime.now()
            
            # 只在交易时间运行判断（简化版，实际可更精细）
            # A股交易时间: 9:30-11:30, 13:00-15:00
            if not (9 <= now.hour < 16):
                print(f"\r⏰ {now.strftime('%H:%M:%S')} 非交易时间，等待中...", end="", flush=True)
                time.sleep(REFRESH_INTERVAL)
                continue
            
            # 获取最近 N 天的数据（至少 MA_PERIOD+5 天）
            df = get_etf_hist(
                code=ETF_CODE,
                start=(now.replace(day=1) if now.month > 1 else now.replace(year=now.year-1, month=12, day=1)).strftime("%Y%m%d")
            )
            
            if len(df) < MA_PERIOD + 5:
                print(f"数据不足，等待更多数据...")
                time.sleep(REFRESH_INTERVAL)
                continue
            
            # 计算信号
            df = generate_signals(df, period=MA_PERIOD)
            signal_info = get_current_signal(df)
            
            print(f"\n📊 {now.strftime('%Y-%m-%d %H:%M:%S')} "
                  f"收盘价: {signal_info['close']:.3f}  "
                  f"MA{MA_PERIOD}: {signal_info['ma20']:.3f}  "
                  f"信号: {signal_info['signal_label'] or '无'}")
            
            # 只在信号发生变化时执行交易
            current_date = signal_info['date']
            if current_date != last_signal_date and signal_info['signal'] != 0:
                if signal_info['signal'] == 1:
                    trader.buy(ETF_CODE, signal_info['close'], date=current_date)
                elif signal_info['signal'] == -1:
                    trader.sell(ETF_CODE, signal_info['close'], date=current_date)
                last_signal_date = current_date
            
            if mode == "simulate":
                trader.status()
            
            time.sleep(REFRESH_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\n🛑 程序已停止")
        if mode == "simulate":
            trader.status()


def main():
    parser = argparse.ArgumentParser(description="ETF均线策略自动交易程序")
    parser.add_argument(
        "--mode",
        choices=["backtest", "simulate", "manual", "qmt"],
        default=RUN_MODE,
        help="运行模式: backtest=回测, simulate=模拟盘, manual=手动提醒, qmt=QMT实盘"
    )
    parser.add_argument(
        "--strategy",
        choices=["ma", "grid", "hybrid"],
        default=STRATEGY,
        help="策略选择: ma=均线策略, grid=网格策略, hybrid=趋势+网格混合"
    )
    parser.add_argument(
        "--start",
        default=None,
        help="回测起始日期，如 20220101"
    )
    args = parser.parse_args()
    
    if args.mode == "backtest":
        if args.strategy == "grid":
            run_grid_backtest()
        elif args.strategy == "hybrid":
            run_hybrid_backtest()
        else:
            run_ma_backtest()
    else:
        run_live(args.mode)


if __name__ == "__main__":
    main()
