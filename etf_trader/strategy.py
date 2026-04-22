"""
交易策略模块：均线交叉策略（支持单均线/双均线 + 趋势过滤）

优化版策略规则：
- 双均线交叉（如 MA5 vs MA20）替代收盘价 vs 单均线，更灵敏
- 60日均线趋势过滤：只在 close > MA60 且 MA_slow > MA60 时才允许买入
  （避免在下跌趋势中抄底，减少震荡市假信号）
- 止损信号独立标记，由 backtest.py 执行

信号列说明:
    0  = 无信号
    1  = 买入信号（金叉 + 趋势过滤通过）
    -1 = 卖出信号（死叉）
    -2 = 止损信号（由回测引擎根据持仓成本动态判断）
"""

import pandas as pd
import numpy as np
from config import (
    MA_PERIOD, FAST_MA, SLOW_MA, TREND_MA,
    USE_DUAL_MA, USE_TREND_FILTER
)


def generate_signals(df: pd.DataFrame,
                     use_dual_ma: bool = USE_DUAL_MA,
                     use_trend_filter: bool = USE_TREND_FILTER,
                     fast: int = FAST_MA,
                     slow: int = SLOW_MA,
                     trend: int = TREND_MA,
                     single_period: int = MA_PERIOD) -> pd.DataFrame:
    """
    根据均线交叉生成交易信号
    
    Args:
        df: 包含 close 列的 DataFrame
        use_dual_ma: True=双均线(快vs慢), False=单均线(收盘vsMA)
        use_trend_filter: 是否启用60日趋势过滤
        fast: 快线周期
        slow: 慢线周期
        trend: 趋势线周期
        single_period: 单均线周期（use_dual_ma=False 时生效）
    """
    df = df.copy()
    
    if use_dual_ma:
        # ===== 双均线模式（优化版） =====
        df[f"ma{fast}"] = df["close"].rolling(window=fast, min_periods=fast).mean()
        df[f"ma{slow}"] = df["close"].rolling(window=slow, min_periods=slow).mean()
        df[f"ma{trend}"] = df["close"].rolling(window=trend, min_periods=trend).mean()
        
        df["prev_close"] = df["close"].shift(1)
        df["prev_ma_fast"] = df[f"ma{fast}"].shift(1)
        df["prev_ma_slow"] = df[f"ma{slow}"].shift(1)
        
        # 金叉：快线上穿慢线
        golden_cross = (
            (df[f"ma{fast}"] > df[f"ma{slow}"]) &
            (df["prev_ma_fast"] <= df["prev_ma_slow"])
        )
        
        # 死叉：快线下穿慢线
        death_cross = (
            (df[f"ma{fast}"] < df[f"ma{slow}"]) &
            (df["prev_ma_fast"] >= df["prev_ma_slow"])
        )
        
        # 趋势过滤：收盘价在趋势线上方，且慢线也在趋势线上方（多头排列）
        if use_trend_filter:
            df["trend_up"] = (
                (df["close"] > df[f"ma{trend}"]) &
                (df[f"ma{slow}"] > df[f"ma{trend}"])
            )
            df["trend_ok"] = df["trend_up"]
        else:
            df["trend_up"] = True
            df["trend_ok"] = True
        
        # 被过滤掉的假信号（用于分析）
        df["blocked_signal"] = 0
        df.loc[golden_cross & (~df["trend_ok"]), "blocked_signal"] = 1
        
        df["signal"] = 0
        df.loc[golden_cross & df["trend_ok"], "signal"] = 1   # 趋势过滤后的买入
        df.loc[death_cross, "signal"] = -1                    # 死叉卖出
        
        df["signal_label"] = ""
        df.loc[golden_cross & df["trend_ok"], "signal_label"] = "金叉买入"
        df.loc[death_cross, "signal_label"] = "死叉卖出"
        df.loc[golden_cross & (~df["trend_ok"]), "signal_label"] = "金叉(被过滤)"
    
    else:
        # ===== 单均线模式（原版） =====
        df[f"ma{single_period}"] = df["close"].rolling(window=single_period, min_periods=single_period).mean()
        df["prev_close"] = df["close"].shift(1)
        df["prev_ma"] = df[f"ma{single_period}"].shift(1)
        
        golden_cross = (
            (df["close"] > df[f"ma{single_period}"]) &
            (df["prev_close"] <= df["prev_ma"])
        )
        death_cross = (
            (df["close"] < df[f"ma{single_period}"]) &
            (df["prev_close"] >= df["prev_ma"])
        )
        
        df["signal"] = 0
        df.loc[golden_cross, "signal"] = 1
        df.loc[death_cross, "signal"] = -1
        
        df["signal_label"] = ""
        df.loc[golden_cross, "signal_label"] = "买入"
        df.loc[death_cross, "signal_label"] = "卖出"
    
    return df


def get_current_signal(df: pd.DataFrame) -> dict:
    """获取最新一条数据的信号状态"""
    latest = df.iloc[-1]
    
    # 动态查找均线列名
    ma_cols = [c for c in df.columns if c.startswith("ma") and c[2:].isdigit()]
    
    return {
        "date": latest["date"],
        "close": latest["close"],
        "signal": int(latest["signal"]),
        "signal_label": latest.get("signal_label", ""),
        "trend_ok": bool(latest.get("trend_ok", True)),
        "blocked": bool(latest.get("blocked_signal", 0) == 1),
        "ma_values": {c: latest[c] for c in ma_cols}
    }
