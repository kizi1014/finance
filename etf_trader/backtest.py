"""
回测引擎：模拟历史交易，评估策略表现
"""

import pandas as pd
import numpy as np
from datetime import datetime
from config import (
    INITIAL_CAPITAL, POSITION_RATIO,
    COMMISSION_RATE, MIN_COMMISSION, SLIPPAGE,
    USE_STOP_LOSS, STOP_LOSS_PCT, USE_DUAL_MA, USE_TREND_FILTER
)


class BacktestEngine:
    """
    回测引擎（支持止损）
    
    假设：
    - 按收盘价成交
    - ETF买入单位为100股整数倍
    - ETF免印花税，仅收取佣金
    - 考虑滑点
    """
    
    def __init__(self, initial_capital: float = INITIAL_CAPITAL):
        self.initial_capital = initial_capital
        self.capital = initial_capital  # 可用现金
        self.position = 0               # 持仓股数
        self.entry_price = 0.0          # 持仓成本价（用于止损计算）
        self.trades = []                # 交易记录
        self.daily_values = []          # 每日资产净值
        self.stop_loss_count = 0        # 止损次数统计
        
    def _calc_commission(self, amount: float) -> float:
        """计算交易佣金"""
        commission = amount * COMMISSION_RATE
        return max(commission, MIN_COMMISSION)
    
    def _buy(self, date, price, label="买入"):
        """执行买入"""
        if self.position > 0:
            return False
        
        # 滑点：买入时价格上浮
        exec_price = price * (1 + SLIPPAGE)
        
        # 计算可买股数（100股整数倍），预留佣金空间
        max_shares = int((self.capital * POSITION_RATIO) / (exec_price * (1 + COMMISSION_RATE)) / 100) * 100
        
        if max_shares <= 0:
            return False
        
        amount = max_shares * exec_price
        commission = self._calc_commission(amount)
        total_cost = amount + commission
        
        # 若仍超支，递减100股直到可承受
        while total_cost > self.capital and max_shares >= 100:
            max_shares -= 100
            amount = max_shares * exec_price
            commission = self._calc_commission(amount)
            total_cost = amount + commission
        
        if max_shares <= 0 or total_cost > self.capital:
            return False
        
        self.capital -= total_cost
        self.position += max_shares
        self.entry_price = exec_price  # 记录成本价（含滑点）
        
        self.trades.append({
            "date": date,
            "action": label,
            "price": round(exec_price, 3),
            "shares": max_shares,
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "capital_after": round(self.capital, 2)
        })
        
        print(f"  📈 {date.strftime('%Y-%m-%d')} {label}: 价格={exec_price:.3f}, "
              f"股数={max_shares}, 金额={amount:.2f}, 佣金={commission:.2f}")
        return True
    
    def _sell(self, date, price, label="卖出"):
        """执行卖出"""
        if self.position <= 0:
            return False
        
        # 滑点：卖出时价格下浮
        exec_price = price * (1 - SLIPPAGE)
        
        amount = self.position * exec_price
        commission = self._calc_commission(amount)
        net_revenue = amount - commission
        
        self.capital += net_revenue
        
        self.trades.append({
            "date": date,
            "action": label,
            "price": round(exec_price, 3),
            "shares": self.position,
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "capital_after": round(self.capital, 2)
        })
        
        print(f"  📉 {date.strftime('%Y-%m-%d')} {label}: 价格={exec_price:.3f}, "
              f"股数={self.position}, 金额={amount:.2f}, 佣金={commission:.2f}")
        
        self.position = 0
        self.entry_price = 0.0
        return True
    
    def run(self, df: pd.DataFrame) -> dict:
        """
        运行回测
        
        Args:
            df: 包含 signal 列的 DataFrame
            
        Returns:
            回测结果统计
        """
        print(f"\n🚀 开始回测，初始资金: {self.initial_capital:,.2f} 元")
        print("=" * 60)
        
        for _, row in df.iterrows():
            date = row["date"]
            price = row["close"]
            signal = row["signal"]
            
            # ===== 止损检查 =====
            stop_loss_triggered = False
            if USE_STOP_LOSS and self.position > 0 and self.entry_price > 0:
                loss_ratio = (price - self.entry_price) / self.entry_price
                if loss_ratio <= -STOP_LOSS_PCT:
                    stop_loss_triggered = True
            
            # ===== 交易执行 =====
            if signal == 1 and self.position == 0:
                self._buy(date, price, "金叉买入")
            elif stop_loss_triggered and self.position > 0:
                self._sell(date, price, f"止损卖出(-{STOP_LOSS_PCT*100:.0f}%)")
                self.stop_loss_count += 1
            elif signal == -1 and self.position > 0:
                self._sell(date, price, "死叉卖出")
            
            # 记录每日总资产
            total_value = self.capital + self.position * price
            self.daily_values.append({
                "date": date,
                "capital": self.capital,
                "position_value": self.position * price,
                "total_value": total_value,
                "position_ratio": (self.position * price) / total_value if total_value > 0 else 0
            })
        
        # 最后一天如果还持仓，按收盘价计算市值
        final_price = df.iloc[-1]["close"]
        final_value = self.capital + self.position * final_price
        
        print("=" * 60)
        print(f"🏁 回测结束")
        
        return self._generate_report(df, final_value)
    
    def _generate_report(self, df: pd.DataFrame, final_value: float) -> dict:
        """生成回测报告"""
        # 计算基准收益（买入并持有）
        start_price = df.iloc[0]["close"]
        end_price = df.iloc[-1]["close"]
        
        # 基准：全仓买入并持有
        benchmark_shares = int(self.initial_capital / start_price / 100) * 100
        benchmark_cost = benchmark_shares * start_price
        benchmark_commission = self._calc_commission(benchmark_cost)
        benchmark_value = benchmark_shares * end_price - benchmark_commission
        
        # 策略收益
        total_return = (final_value - self.initial_capital) / self.initial_capital
        benchmark_return = (benchmark_value - self.initial_capital) / self.initial_capital
        
        # 年化收益（简化计算）
        days = (df.iloc[-1]["date"] - df.iloc[0]["date"]).days
        years = max(days / 365, 0.01)
        annual_return = (1 + total_return) ** (1 / years) - 1
        benchmark_annual = (1 + benchmark_return) ** (1 / years) - 1
        
        # 最大回撤
        values_df = pd.DataFrame(self.daily_values)
        values_df["cummax"] = values_df["total_value"].cummax()
        values_df["drawdown"] = (values_df["total_value"] - values_df["cummax"]) / values_df["cummax"]
        max_drawdown = values_df["drawdown"].min()
        
        # 交易次数
        buy_count = len([t for t in self.trades if "买入" in t["action"]])
        sell_count = len([t for t in self.trades if "卖出" in t["action"]])
        stop_loss_count = self.stop_loss_count
        normal_sell = sell_count - stop_loss_count
        
        # 统计被过滤的信号
        blocked_count = int(df["blocked_signal"].sum()) if "blocked_signal" in df.columns else 0
        
        report = {
            "initial_capital": self.initial_capital,
            "final_value": round(final_value, 2),
            "total_return": round(total_return * 100, 2),
            "annual_return": round(annual_return * 100, 2),
            "benchmark_return": round(benchmark_return * 100, 2),
            "benchmark_annual": round(benchmark_annual * 100, 2),
            "excess_return": round((total_return - benchmark_return) * 100, 2),
            "max_drawdown": round(max_drawdown * 100, 2),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "stop_loss_count": stop_loss_count,
            "normal_sell": normal_sell,
            "blocked_count": blocked_count,
            "total_trades": buy_count + sell_count,
            "trades": self.trades,
            "daily_values": self.daily_values
        }
        
        print(f"\n📊 回测报告")
        print("-" * 50)
        print(f"初始资金:       {self.initial_capital:>12,.2f} 元")
        print(f"期末资产:       {final_value:>12,.2f} 元")
        print(f"策略总收益:     {report['total_return']:>11.2f}%")
        print(f"策略年化收益:   {report['annual_return']:>11.2f}%")
        print(f"基准总收益:     {report['benchmark_return']:>11.2f}%")
        print(f"超额收益:       {report['excess_return']:>11.2f}%")
        print(f"最大回撤:       {report['max_drawdown']:>11.2f}%")
        print("-" * 50)
        print(f"买入次数:       {buy_count:>12} 次")
        print(f"  ├─ 正常卖出:  {normal_sell:>12} 次")
        print(f"  └─ 止损卖出:  {stop_loss_count:>12} 次")
        if blocked_count > 0:
            print(f"被过滤的假信号: {blocked_count:>12} 次")
        print("-" * 50)
        
        return report
