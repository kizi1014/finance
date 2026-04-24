#!/usr/bin/env python3
"""
盘中监控：工作日交易时段每10分钟检查买卖信号，飞书推送

用法：
    # 启动盘中监控（默认混合策略，10分钟间隔）
    python monitor.py

    # 指定策略和间隔
    python monitor.py --strategy ma --interval 600

    # 指定策略（网格/混合）
    python monitor.py --strategy grid
    python monitor.py --strategy hybrid
"""

import argparse
import sys
import time
from datetime import datetime, time as dt_time, timedelta

import pandas as pd

from config import ETF_LIST, STRATEGY, BACKTEST_START, BACKTEST_END
from data_feed import get_etf_hist, get_latest_price
from strategy import generate_signals, get_current_signal
from notifier import Notifier


def is_trading_time() -> bool:
    """判断当前是否为A股交易时段（工作日 9:30-11:30, 13:00-15:00）"""
    if datetime.now().weekday() >= 5:
        return False
    t = datetime.now().time()
    return (dt_time(9, 30) <= t <= dt_time(11, 30) or
            dt_time(13, 0) <= t <= dt_time(15, 0))


def wait_for_trading() -> int:
    """
    等待下一个交易时段开始，返回等待秒数
    若当前在交易时段中则立即返回 0
    """
    if is_trading_time():
        return 0

    now = datetime.now()
    t = now.time()

    if now.weekday() >= 5:
        next_day = now + timedelta(days=7 - now.weekday())
        target = next_day.replace(hour=9, minute=30, second=0, microsecond=0)
    elif t < dt_time(9, 30):
        target = now.replace(hour=9, minute=30, second=0, microsecond=0)
    elif dt_time(11, 30) < t < dt_time(13, 0):
        target = now.replace(hour=13, minute=0, second=0, microsecond=0)
    else:
        next_day = now + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        target = next_day.replace(hour=9, minute=30, second=0, microsecond=0)

    wait = int((target - now).total_seconds())
    if wait > 0:
        print(f"⏸️ 非交易时段，{wait // 60} 分钟后恢复 (预计 {target.strftime('%H:%M')})")
    return wait


def signal_label(sig: int) -> str:
    return {1: "买入", -1: "卖出", 0: "无"}.get(sig, "未知")


def signal_emoji(sig: int) -> str:
    return {1: "📈", -1: "📉", 0: "➖"}.get(sig, "❓")


def build_signal_msg(etf: dict, price: float, sig: int, label: str,
                     ma_values: dict = None, trend_ok: bool = True) -> str:
    """构建信号通知消息正文"""
    lines = [
        f"📍 {etf['name']} ({etf['code']})",
        f"信号: {signal_emoji(sig)} {label}",
        f"价格: {price:.3f}",
    ]
    if ma_values:
        lines.append("均线: " + " | ".join(f"{k.upper()}={v:.3f}" for k, v in ma_values.items()))
    lines.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)


def build_status_msg(etf: dict, price: float, sig: int, label: str,
                     ma_values: dict = None) -> str:
    """构建盘中状态消息（简洁版）"""
    parts = [f"{etf['name']} {price:.3f} {signal_emoji(sig)}"]
    if ma_values:
        parts.append(" ".join(f"{k.upper()}={v:.3f}" for k, v in ma_values.items()))
    parts.append(label or "无信号")
    return " | ".join(parts)


def fetch_signal(code: str) -> dict:
    """
    获取单只ETF的实时信号

    逻辑：
    1. 获取日线历史数据
    2. 获取实时行情
    3. 将今日实时价格作为最新收盘价更新到DataFrame
    4. 重新计算均线信号
    """
    df = get_etf_hist(code=code, start=BACKTEST_START, end=BACKTEST_END)
    if df is None or len(df) < 60:
        raise ValueError(f"历史数据不足 ({len(df) if df is not None else 0})")

    spot = get_latest_price(code)
    if not spot or not spot.get("price"):
        raise ValueError("无法获取实时价格")

    price = float(spot["price"])
    if price <= 0:
        raise ValueError(f"无效价格: {price}")

    today = pd.Timestamp(datetime.now().strftime("%Y-%m-%d"))
    last_date = df["date"].iloc[-1]

    if last_date < today:
        syn = pd.DataFrame([{
            "date": today, "open": price, "high": price,
            "low": price, "close": price, "volume": 0,
        }])
        df = pd.concat([df, syn], ignore_index=True)
    else:
        mask = df["date"] == today
        if mask.any():
            row_idx = df.index[mask][0]
            df.loc[row_idx, "close"] = price
        else:
            syn = pd.DataFrame([{
                "date": today, "open": price, "high": price,
                "low": price, "close": price, "volume": 0,
            }])
            df = pd.concat([df, syn], ignore_index=True)

    df = generate_signals(df)
    info = get_current_signal(df)

    return {
        "price": price,
        "signal": info["signal"],
        "label": info.get("signal_label", ""),
        "ma_values": info.get("ma_values", {}),
        "trend_ok": info.get("trend_ok", True),
    }


def run_monitor(strategy: str, interval: int = 600):
    """启动盘中监控主循环"""
    notifier = Notifier()
    prev_signals: dict[str, int] = {}

    print(f"\n{'='*60}")
    print(f"📡 ETF 盘中监控 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print(f"策略: {strategy}  |  间隔: {interval}秒  |  标的: {len(ETF_LIST)} 只")
    print(f"{'='*60}\n")

    while True:
        wait = wait_for_trading()
        if wait > 0:
            time.sleep(min(wait, 600))
            continue

        now = datetime.now()
        print(f"\n⏰ [{now.strftime('%H:%M:%S')}] 检查中...")

        all_status = []

        for etf in ETF_LIST:
            code = etf["code"]
            name = etf["name"]

            try:
                info = fetch_signal(code)
                sig = info["signal"]
                prev = prev_signals.get(code, 0)

                status = build_status_msg(etf, info["price"], sig,
                                          info["label"], info["ma_values"])
                all_status.append(status)

                if sig != 0 and sig != prev:
                    prev_signals[code] = sig
                    emoji = signal_emoji(sig)
                    title = f"{emoji} ETF信号 — {name}"
                    msg = build_signal_msg(etf, info["price"], sig,
                                           info["label"], info["ma_values"],
                                           info["trend_ok"])
                    notifier.send(title=title, content=msg)
                    print(f"  🔔 新信号: {name} -> {signal_label(sig)}")

                elif sig == 0 and prev != 0:
                    prev_signals[code] = 0
                    print(f"  ↩️ {name}: 信号消失 (此前: {signal_label(prev)})")
                else:
                    print(f"  {status}")

            except Exception as e:
                print(f"  ❌ {name} ({code}): {e}")

        print(f"💤 等待 {interval} 秒...")
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="ETF 盘中实时监控")
    parser.add_argument("--strategy", choices=["ma", "grid", "hybrid"],
                        default=STRATEGY, help="策略选择")
    parser.add_argument("--interval", type=int, default=600,
                        help="检查间隔（秒），默认 600")
    args = parser.parse_args()

    try:
        run_monitor(args.strategy, args.interval)
    except KeyboardInterrupt:
        print("\n\n🛑 盘中监控已停止")


if __name__ == "__main__":
    sys.exit(main())
