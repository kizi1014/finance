#!/usr/bin/env python3
"""
ETF 策略盘中实时监控服务

核心逻辑：
    - 交易时间内（9:30-11:30, 13:00-15:00）实时监控行情
    - 信号出现时立即推送通知（买入/卖出/止损）
    - 同一信号只推送一次，避免重复打扰
    - 每 30 分钟发送一次心跳报告，确认程序正常运行
    - 非交易时间自动休眠，节省资源

用法：
    # 启动监控（常驻后台）
    python daily_task.py
    
    # 指定策略
    python daily_task.py --strategy ma
    python daily_task.py --strategy grid
    python daily_task.py --strategy hybrid

systemd 服务配置：
    Type=simple 常驻进程，由 systemd 守护自动重启
"""

import argparse
import sys
import time
from datetime import datetime, time as dt_time

from config import (
    ETF_CODE, ETF_NAME, MA_PERIOD, STRATEGY, REFRESH_INTERVAL,
    USE_DUAL_MA, FAST_MA, SLOW_MA, TREND_MA,
    BACKTEST_START
)
from data_feed import get_etf_hist, get_latest_price
from strategy import generate_signals, get_current_signal
from notifier import Notifier


# ==================== 交易时间判断 ====================

def is_trading_time() -> bool:
    """
    判断当前是否为 A 股交易时间
    
    交易时间：
        上午: 9:30 - 11:30
        下午: 13:00 - 15:00
        周一到周五（节假日不判断，由数据源返回空数据处理）
    """
    now = datetime.now()
    weekday = now.weekday()  # 0=周一, 6=周日
    t = now.time()
    
    # 周末不交易
    if weekday >= 5:
        return False
    
    # 上午 9:30-11:30
    morning_start = dt_time(9, 30)
    morning_end = dt_time(11, 30)
    
    # 下午 13:00-15:00
    afternoon_start = dt_time(13, 0)
    afternoon_end = dt_time(15, 0)
    
    return (
        (morning_start <= t <= morning_end) or
        (afternoon_start <= t <= afternoon_end)
    )


def get_next_trading_start() -> str:
    """返回距离下次交易开始的时间描述"""
    now = datetime.now()
    t = now.time()
    weekday = now.weekday()
    
    # 如果是周末，显示周一
    if weekday >= 5:
        days_until_monday = 7 - weekday
        return f"{days_until_monday}天后（周一）9:30"
    
    # 上午开盘前
    if t < dt_time(9, 30):
        return "今天 9:30"
    
    # 午休时间
    if dt_time(11, 30) < t < dt_time(13, 0):
        return "今天 13:00"
    
    # 下午收盘后
    if t > dt_time(15, 0):
        if weekday == 4:  # 周五
            return "下周一 9:30"
        return "明天 9:30"
    
    return "即将"


# ==================== 均线策略盘中监控 ====================

class MASignalMonitor:
    """均线策略盘中信号监控器"""
    
    def __init__(self):
        self.notifier = Notifier()
        self.last_signal_date = None  # 上次信号日期（防止日线信号重复推送）
        self.last_heartbeat = 0       # 上次心跳时间戳
        self.heartbeat_interval = 1800  # 心跳间隔 30 分钟
        self.today_notified_signals = set()  # 今日已通知的信号标识
        
    def _get_signal_id(self, signal_info: dict) -> str:
        """生成信号唯一标识，用于去重"""
        date_str = signal_info["date"].strftime("%Y-%m-%d") if hasattr(signal_info["date"], "strftime") else str(signal_info["date"])
        return f"{date_str}_{signal_info['signal']}"
    
    def _send_heartbeat(self, current_price: float, signal_info: dict):
        """发送心跳报告"""
        now = time.time()
        if now - self.last_heartbeat < self.heartbeat_interval:
            return
        
        self.last_heartbeat = now
        
        ma_lines = []
        for k, v in signal_info.get("ma_values", {}).items():
            ma_lines.append(f"{k.upper()}: {v:.3f}")
        
        content = (
            f"**标的**: {ETF_NAME} ({ETF_CODE})\n"
            f"**当前价格**: {current_price:.3f} 元\n"
            f"**当前信号**: {signal_info.get('signal_label') or '无'}\n"
            + "\n".join(ma_lines) + "\n"
            f"\n⏰ 监控运行正常，信号出现时立即通知"
        )
        
        self.notifier.send("💓 ETF监控心跳", content)
    
    def check_and_notify(self):
        """
        检查当前信号并推送通知
        
        返回:
            dict: 信号信息，无信号返回 None
        """
        # 获取实时价格
        latest = get_latest_price(ETF_CODE)
        if not latest:
            print(f"  ⚠️ 获取实时行情失败，跳过本次检查")
            return None
        
        current_price = latest["price"]
        now_str = datetime.now().strftime("%H:%M:%S")
        
        # 获取历史数据计算均线
        df = get_etf_hist(code=ETF_CODE, start=BACKTEST_START)
        if len(df) < MA_PERIOD + 5:
            print(f"  ⚠️ 历史数据不足，跳过")
            return None
        
        # 计算信号
        df = generate_signals(df)
        signal_info = get_current_signal(df)
        
        # 打印当前状态（控制台）
        signal_label = signal_info.get("signal_label") or "无"
        ma_str = " | ".join([f"{k.upper()}={v:.3f}" for k, v in signal_info.get("ma_values", {}).items()])
        print(f"  [{now_str}] 价格:{current_price:.3f} | {ma_str} | 信号:{signal_label}")
        
        # 发送心跳
        self._send_heartbeat(current_price, signal_info)
        
        # 检查是否有新信号
        signal_id = self._get_signal_id(signal_info)
        current_signal = signal_info["signal"]
        
        # 信号为 0 表示无信号
        if current_signal == 0:
            return signal_info
        
        # 检查是否已经通知过这个信号
        if signal_id in self.today_notified_signals:
            return signal_info
        
        # 新信号，发送通知
        self.today_notified_signals.add(signal_id)
        
        if current_signal == 1:
            # 买入信号
            self.notifier.send_trade_signal(
                signal_type="买入",
                code=ETF_CODE,
                name=ETF_NAME,
                price=current_price,
                ma_values=signal_info.get("ma_values"),
                extra_info=f"盘中实时监控触发 | 当前时间 {now_str}\nMA5上穿MA20，趋势确认，建议立即关注"
            )
        elif current_signal == -1:
            # 卖出信号
            self.notifier.send_trade_signal(
                signal_type="卖出",
                code=ETF_CODE,
                name=ETF_NAME,
                price=current_price,
                ma_values=signal_info.get("ma_values"),
                extra_info=f"盘中实时监控触发 | 当前时间 {now_str}\nMA5下穿MA20，建议立即关注"
            )
        
        return signal_info


# ==================== 网格策略盘中监控 ====================

class GridSignalMonitor:
    """网格策略盘中监控器"""
    
    def __init__(self):
        from config import GRID_LOWER, GRID_UPPER, GRID_NUM
        
        self.notifier = Notifier()
        self.grid_lower = GRID_LOWER
        self.grid_upper = GRID_UPPER
        self.grid_num = GRID_NUM
        self.grid_step = (GRID_UPPER - GRID_LOWER) / GRID_NUM
        
        self.last_grid_idx = None
        self.last_heartbeat = 0
        self.heartbeat_interval = 1800
        self.today_crossed_grids = set()  # 今日已触发过的网格
        
    def _get_grid_info(self, price: float) -> tuple:
        """获取当前价格所在的网格信息"""
        grid_idx = int((price - self.grid_lower) / self.grid_step)
        grid_idx = max(0, min(grid_idx, self.grid_num - 1))
        
        grid_low = self.grid_lower + grid_idx * self.grid_step
        grid_high = grid_low + self.grid_step
        
        return grid_idx, grid_low, grid_high
    
    def _send_heartbeat(self, current_price: float, grid_idx: int, grid_low: float, grid_high: float):
        """发送心跳报告"""
        now = time.time()
        if now - self.last_heartbeat < self.heartbeat_interval:
            return
        
        self.last_heartbeat = now
        
        content = (
            f"**标的**: {ETF_NAME} ({ETF_CODE})\n"
            f"**当前价格**: {current_price:.3f} 元\n"
            f"**当前网格**: 第 {grid_idx+1}/{self.grid_num} 格\n"
            f"**网格区间**: [{grid_low:.3f}, {grid_high:.3f}]\n"
            f"\n⏰ 监控运行正常，触及网格边界时立即通知"
        )
        
        self.notifier.send("💓 ETF网格监控心跳", content)
    
    def check_and_notify(self):
        """检查网格状态并推送通知"""
        latest = get_latest_price(ETF_CODE)
        if not latest:
            print(f"  ⚠️ 获取实时行情失败，跳过")
            return None
        
        current_price = latest["price"]
        now_str = datetime.now().strftime("%H:%M:%S")
        grid_idx, grid_low, grid_high = self._get_grid_info(current_price)
        
        # 打印当前状态
        print(f"  [{now_str}] 价格:{current_price:.3f} | 网格:{grid_idx+1}/{self.grid_num} [{grid_low:.3f}, {grid_high:.3f}]")
        
        # 发送心跳
        self._send_heartbeat(current_price, grid_idx, grid_low, grid_high)
        
        # 计算距离网格边界的比例
        distance_to_low = (current_price - grid_low) / self.grid_step
        distance_to_high = (grid_high - current_price) / self.grid_step
        
        # 判断是否有网格交易机会
        today = datetime.now().strftime("%Y-%m-%d")
        
        # 接近下沿（买入机会）
        if distance_to_low < 0.05:
            grid_key = f"{today}_buy_{grid_idx}"
            if grid_key not in self.today_crossed_grids:
                self.today_crossed_grids.add(grid_key)
                self.notifier.send_trade_signal(
                    signal_type="买入",
                    code=ETF_CODE,
                    name=ETF_NAME,
                    price=current_price,
                    ma_values={"grid_low": grid_low, "grid_high": grid_high, "grid_idx": grid_idx + 1},
                    extra_info=f"盘中实时监控触发 | 当前时间 {now_str}\n价格触及网格下沿({grid_low:.3f})，建议买入一格"
                )
        
        # 接近上沿（卖出机会）
        elif distance_to_high < 0.05:
            grid_key = f"{today}_sell_{grid_idx}"
            if grid_key not in self.today_crossed_grids:
                self.today_crossed_grids.add(grid_key)
                self.notifier.send_trade_signal(
                    signal_type="卖出",
                    code=ETF_CODE,
                    name=ETF_NAME,
                    price=current_price,
                    ma_values={"grid_low": grid_low, "grid_high": grid_high, "grid_idx": grid_idx + 1},
                    extra_info=f"盘中实时监控触发 | 当前时间 {now_str}\n价格触及网格上沿({grid_high:.3f})，建议卖出一格"
                )
        
        self.last_grid_idx = grid_idx
        return {"price": current_price, "grid_idx": grid_idx, "grid_low": grid_low, "grid_high": grid_high}


# ==================== 混合策略盘中监控 ====================

class HybridSignalMonitor:
    """混合策略（趋势+网格）盘中监控器"""
    
    def __init__(self):
        from config import GRID_LOWER, GRID_UPPER, GRID_NUM
        
        self.ma_monitor = MASignalMonitor()
        self.grid_monitor = GridSignalMonitor()
        self.notifier = Notifier()
        
        self.grid_lower = GRID_LOWER
        self.grid_upper = GRID_UPPER
        self.grid_num = GRID_NUM
        self.grid_step = (GRID_UPPER - GRID_LOWER) / GRID_NUM
        
        self.last_heartbeat = 0
        self.heartbeat_interval = 1800
        self.today_notified = set()
    
    def _get_grid_info(self, price: float) -> tuple:
        grid_idx = int((price - self.grid_lower) / self.grid_step)
        grid_idx = max(0, min(grid_idx, self.grid_num - 1))
        grid_low = self.grid_lower + grid_idx * self.grid_step
        grid_high = grid_low + self.grid_step
        return grid_idx, grid_low, grid_high
    
    def check_and_notify(self):
        """混合策略检查"""
        latest = get_latest_price(ETF_CODE)
        if not latest:
            print(f"  ⚠️ 获取实时行情失败，跳过")
            return None
        
        current_price = latest["price"]
        now_str = datetime.now().strftime("%H:%M:%S")
        
        # 获取历史数据
        df = get_etf_hist(code=ETF_CODE, start=BACKTEST_START)
        if len(df) < MA_PERIOD + 5:
            print(f"  ⚠️ 历史数据不足")
            return None
        
        df = generate_signals(df)
        signal_info = get_current_signal(df)
        
        # 网格信息
        grid_idx, grid_low, grid_high = self._get_grid_info(current_price)
        
        # 打印状态
        signal_label = signal_info.get("signal_label") or "无"
        ma_str = " | ".join([f"{k.upper()}={v:.3f}" for k, v in signal_info.get("ma_values", {}).items()])
        print(f"  [{now_str}] 价格:{current_price:.3f} | {ma_str} | 趋势:{signal_label} | 网格:{grid_idx+1}/{self.grid_num}")
        
        # 心跳
        now = time.time()
        if now - self.last_heartbeat >= self.heartbeat_interval:
            self.last_heartbeat = now
            content = (
                f"**标的**: {ETF_NAME} ({ETF_CODE})\n"
                f"**当前价格**: {current_price:.3f} 元\n"
                f"**趋势信号**: {signal_label}\n"
                f"**网格位置**: 第 {grid_idx+1}/{self.grid_num} 格\n"
                f"\n⏰ 监控运行正常"
            )
            self.notifier.send("💓 ETF混合监控心跳", content)
        
        # 信号判断
        today = datetime.now().strftime("%Y-%m-%d")
        current_signal = signal_info["signal"]
        trend_ok = signal_info.get("trend_ok", True)
        
        # 趋势买入信号（优先级最高）
        if current_signal == 1 and trend_ok:
            key = f"{today}_trend_buy"
            if key not in self.today_notified:
                self.today_notified.add(key)
                self.notifier.send_trade_signal(
                    signal_type="买入",
                    code=ETF_CODE,
                    name=ETF_NAME,
                    price=current_price,
                    ma_values=signal_info.get("ma_values"),
                    extra_info=f"盘中实时监控触发 | 当前时间 {now_str}\n趋势向上确认，建议满仓持有"
                )
        
        # 趋势卖出信号
        elif current_signal == -1:
            key = f"{today}_trend_sell"
            if key not in self.today_notified:
                self.today_notified.add(key)
                self.notifier.send_trade_signal(
                    signal_type="卖出",
                    code=ETF_CODE,
                    name=ETF_NAME,
                    price=current_price,
                    ma_values=signal_info.get("ma_values"),
                    extra_info=f"盘中实时监控触发 | 当前时间 {now_str}\n趋势转弱，建议清仓"
                )
        
        # 无趋势信号时，按网格提醒
        else:
            distance_to_low = (current_price - grid_low) / self.grid_step
            distance_to_high = (grid_high - current_price) / self.grid_step
            
            if distance_to_low < 0.05:
                key = f"{today}_grid_buy_{grid_idx}"
                if key not in self.today_notified:
                    self.today_notified.add(key)
                    self.notifier.send_trade_signal(
                        signal_type="买入",
                        code=ETF_CODE,
                        name=ETF_NAME,
                        price=current_price,
                        ma_values={"grid_low": grid_low, "grid_high": grid_high},
                        extra_info=f"盘中实时监控触发 | 当前时间 {now_str}\n无明确趋势，价格触及网格下沿，建议买入一格"
                    )
            elif distance_to_high < 0.05:
                key = f"{today}_grid_sell_{grid_idx}"
                if key not in self.today_notified:
                    self.today_notified.add(key)
                    self.notifier.send_trade_signal(
                        signal_type="卖出",
                        code=ETF_CODE,
                        name=ETF_NAME,
                        price=current_price,
                        ma_values={"grid_low": grid_low, "grid_high": grid_high},
                        extra_info=f"盘中实时监控触发 | 当前时间 {now_str}\n无明确趋势，价格触及网格上沿，建议卖出一格"
                    )
        
        return signal_info


# ==================== 主程序 ====================

def run_monitor(strategy: str):
    """
    启动盘中监控服务（常驻进程）
    
    Args:
        strategy: "ma" / "grid" / "hybrid"
    """
    print(f"\n{'='*60}")
    print(f"🚀 ETF策略盘中实时监控服务启动")
    print(f"{'='*60}")
    print(f"标的: {ETF_NAME} ({ETF_CODE})")
    print(f"策略: {strategy}")
    print(f"刷新间隔: {REFRESH_INTERVAL} 秒")
    print(f"心跳间隔: 30 分钟")
    print(f"\n⚠️ 提示: 按 Ctrl+C 停止程序")
    print("-" * 60)
    
    # 创建对应的监控器
    if strategy == "grid":
        monitor = GridSignalMonitor()
    elif strategy == "hybrid":
        monitor = HybridSignalMonitor()
    else:
        monitor = MASignalMonitor()
    
    # 发送启动通知
    notifier = Notifier()
    notifier.send(
        title="🚀 ETF监控服务已启动",
        content=f"标的: {ETF_NAME} ({ETF_CODE})\n"
                f"策略: {strategy}\n"
                f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"\n交易时间内将实时监控，信号出现时立即通知。"
    )
    
    try:
        while True:
            now = datetime.now()
            now_str = now.strftime("%H:%M:%S")
            
            if is_trading_time():
                # 交易时间内：实时监控
                print(f"\n[{now_str}] 交易中...")
                monitor.check_and_notify()
                time.sleep(REFRESH_INTERVAL)
                
            else:
                # 非交易时间：休眠等待
                next_start = get_next_trading_start()
                print(f"\r[{now_str}] ⏰ 非交易时间，下次交易: {next_start}", end="", flush=True)
                
                # 收盘后发送一次总结报告
                if dt_time(15, 0) <= now.time() <= dt_time(15, 5):
                    # 只在收盘后 5 分钟内发送一次日终报告
                    pass  # 可选：发送日终总结
                
                time.sleep(60)  # 非交易时间每分钟检查一次
                
    except KeyboardInterrupt:
        print("\n\n🛑 监控服务已停止")
        notifier.send(
            title="🛑 ETF监控服务已停止",
            content=f"停止时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"如需重新启动，请运行: python daily_task.py"
        )


def main():
    parser = argparse.ArgumentParser(description="ETF策略盘中实时监控服务")
    parser.add_argument(
        "--strategy",
        choices=["ma", "grid", "hybrid"],
        default=STRATEGY,
        help="策略选择: ma=均线, grid=网格, hybrid=混合"
    )
    args = parser.parse_args()
    
    run_monitor(args.strategy)


if __name__ == "__main__":
    sys.exit(main())
