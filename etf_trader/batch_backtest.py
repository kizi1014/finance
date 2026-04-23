"""
批量回测引擎：对多只ETF进行批量回测，生成汇总报告
"""
from __future__ import print_function, division

import pandas as pd
from typing import List, Dict, Optional
from config import (
    ETF_LIST, INITIAL_CAPITAL, BACKTEST_START, BACKTEST_END,
    GRID_INITIAL_PCT
)
from data_feed import get_etf_hist
from strategy import generate_signals
from grid_backtest import GridBacktestEngine
from backtest import BacktestEngine
from hybrid_backtest import HybridBacktestEngine
from strategy import generate_signals


def run_single_etf_backtest(etf_config: Dict, strategy: str = "grid") -> Optional[Dict]:
    """
    对单个ETF运行回测

    Args:
        etf_config: ETF配置字典，包含 code, name, grid_* 参数
        strategy: 策略类型，支持 "grid", "ma", "hybrid"

    Returns:
        回测结果字典，失败返回 None
    """
    code = etf_config["code"]
    name = etf_config["name"]

    print(f"\n{'='*60}")
    print(f"📈 批量回测 | {name} ({code})")
    print(f"{'='*60}")

    try:
        df = get_etf_hist(code=code, start=BACKTEST_START, end=BACKTEST_END)
        if len(df) < 60:
            print(f"⚠️ 数据不足 ({len(df)} 条)，跳过")
            return None

        if strategy == "grid":
            engine = GridBacktestEngine(
                initial_capital=INITIAL_CAPITAL,
                lower=etf_config.get("grid_lower", 3.0),
                upper=etf_config.get("grid_upper", 5.5),
                num_grids=etf_config.get("grid_num", 25),
                initial_pct=GRID_INITIAL_PCT
            )
            report = engine.run(df)
        elif strategy == "ma":
            df_signals = generate_signals(df)
            engine = BacktestEngine(initial_capital=INITIAL_CAPITAL)
            report = engine.run(df_signals)
        elif strategy == "hybrid":
            engine = HybridBacktestEngine(
                initial_capital=INITIAL_CAPITAL,
                lower=etf_config.get("grid_lower", 3.0),
                upper=etf_config.get("grid_upper", 5.5),
                num_grids=etf_config.get("grid_num", 25),
                initial_pct=GRID_INITIAL_PCT
            )
            report = engine.run(df)
        else:
            print(f"⚠️ 不支持的策略: {strategy}")
            return None

        return {
            "code": code,
            "name": name,
            "strategy": strategy,
            "start_date": df.iloc[0]["date"].strftime("%Y-%m-%d"),
            "end_date": df.iloc[-1]["date"].strftime("%Y-%m-%d"),
            "data_points": len(df),
            **report
        }

    except Exception as e:
        print(f"❌ 回测失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def run_batch_backtest(strategy: str = "grid", etf_list: List[Dict] = None) -> pd.DataFrame:
    """
    批量回测多只ETF

    Args:
        strategy: 策略类型
        etf_list: ETF列表，默认使用 config.ETF_LIST

    Returns:
        汇总结果DataFrame
    """
    if etf_list is None:
        etf_list = ETF_LIST

    print(f"\n{'#'*60}")
    print(f"# 批量回测开始 | 共 {len(etf_list)} 只ETF | 策略: {strategy}")
    print(f"{'#'*60}")

    results = []
    success_count = 0
    fail_count = 0

    for i, etf in enumerate(etf_list, 1):
        print(f"\n[{i}/{len(etf_list)}] 正在回测: {etf['name']} ({etf['code']})")
        result = run_single_etf_backtest(etf, strategy)
        if result:
            results.append(result)
            success_count += 1
        else:
            fail_count += 1

    if not results:
        print("\n❌ 所有ETF回测均失败")
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values("total_return", ascending=False)

    print(f"\n{'#'*60}")
    print(f"# 批量回测汇总 | 成功: {success_count} | 失败: {fail_count}")
    print(f"{'#'*60}")

    print(f"\n📊 汇总表格 (按总收益降序)")
    print("-" * 100)
    print(f"{'ETF名称':<20} {'代码':<8} {'策略':<6} {'总收益':>8} {'年化收益':>8} {'超额收益':>8} {'最大回撤':>8} {'买入':>6} {'卖出':>6}")
    print("-" * 100)

    for _, row in df.iterrows():
        print(f"{row['name']:<20} {row['code']:<8} {row['strategy']:<6} "
              f"{row['total_return']:>7.2f}% {row['annual_return']:>7.2f}% "
              f"{row['excess_return']:>7.2f}% {row['max_drawdown']:>7.2f}% "
              f"{row['buy_count']:>6} {row['sell_count']:>6}")

    print("-" * 100)
    print(f"{'平均':<28} {df['total_return'].mean():>7.2f}% {df['annual_return'].mean():>7.2f}% "
          f"{df['excess_return'].mean():>7.2f}% {df['max_drawdown'].mean():>7.2f}%")

    return df


def print_top_etfs(df: pd.DataFrame, top_n: int = 3, metric: str = "total_return"):
    """
    显示最优ETF

    Args:
        df: 回测结果DataFrame
        top_n: 显示前几名
        metric: 排序指标 (total_return / annual_return / max_drawdown / excess_return)
    """
    if df.empty or metric not in df.columns:
        return

    df_sorted = df.sort_values(metric, ascending=(metric == "max_drawdown"))

    print(f"\n🏆 TOP {top_n} ({metric})")
    print("-" * 50)
    for i, (_, row) in enumerate(df_sorted.head(top_n).iterrows(), 1):
        print(f"  {i}. {row['name']} ({row['code']}): {row[metric]:.2f}%")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ETF批量回测")
    parser.add_argument("--strategy", default="grid", choices=["grid", "ma", "hybrid"])
    parser.add_argument("--top", type=int, default=3, help="显示TOP N")
    args = parser.parse_args()

    df = run_batch_backtest(strategy=args.strategy)
    if not df.empty:
        print_top_etfs(df, args.top, "total_return")
        print_top_etfs(df, args.top, "annual_return")
        print_top_etfs(df, args.top, "max_drawdown")