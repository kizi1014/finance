"""
混合策略回测引擎：趋势跟踪 + 网格交易

核心逻辑：
- 上升趋势（close > MA60 且 MA60 向上）：满仓持有，吃尽涨幅
- 震荡/下跌趋势（close <= MA60 或 MA60 向下）：清仓转网格，低买高卖赚波动

状态切换：
  趋势模式 → 网格模式：清仓，保留现金，开启网格
  网格模式 → 趋势模式：清空网格记录，全部持仓转为趋势底仓
"""

import pandas as pd
from config import (
    INITIAL_CAPITAL, COMMISSION_RATE, MIN_COMMISSION, SLIPPAGE,
    GRID_LOWER, GRID_UPPER, GRID_NUM, GRID_INITIAL_PCT,
    HYBRID_CONFIRM_DAYS
)


class HybridBacktestEngine:
    def __init__(self,
                 initial_capital: float = INITIAL_CAPITAL,
                 trend_ma: int = 60,
                 trend_slope_days: int = 10,
                 lower: float = GRID_LOWER,
                 upper: float = GRID_UPPER,
                 num_grids: int = GRID_NUM,
                 initial_pct: float = GRID_INITIAL_PCT,
                 confirm_days: int = HYBRID_CONFIRM_DAYS):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.position = 0
        self.trend_ma = trend_ma
        self.trend_slope_days = trend_slope_days
        self.confirm_days = confirm_days

        # 网格参数
        self.lower = lower
        self.upper = upper
        self.num_grids = num_grids
        self.step = (upper - lower) / num_grids
        self.initial_pct = initial_pct
        self.grid_lines = [lower + i * self.step for i in range(num_grids + 1)]
        self.per_grid_value = initial_capital / num_grids
        self.grid_shares = {i: 0 for i in range(num_grids)}
        self.last_grid = None

        # 状态
        self.mode = None  # "trend" 或 "grid"
        self.trades = []
        self.daily_values = []

        # 缓冲计数器
        self.above_count = 0   # 连续在MA60上方天数
        self.below_count = 0   # 连续在MA60下方天数

    def _calc_commission(self, amount: float) -> float:
        return max(amount * COMMISSION_RATE, MIN_COMMISSION)

    def check_trend(self, row) -> bool:
        """判断当前是否处于上升趋势"""
        close = row["close"]
        ma_col = f"ma{self.trend_ma}"
        if ma_col not in row or pd.isna(row[ma_col]):
            return False
        ma60 = row[ma_col]
        # 价格在MA60上方，且MA60本身在向上走
        return close > ma60

    def get_grid_index(self, price: float) -> int:
        if price <= self.lower:
            return 0
        if price >= self.upper:
            return self.num_grids - 1
        return int((price - self.lower) / self.step)

    def _buy_all(self, date, price: float, label: str = "趋势满仓"):
        """趋势模式：用全部可用资金买入"""
        exec_price = price * (1 + SLIPPAGE)
        shares = int(self.capital / exec_price / 100) * 100

        # 考虑佣金，递减直到可承受
        while shares >= 100:
            amount = shares * exec_price
            commission = self._calc_commission(amount)
            total_cost = amount + commission
            if total_cost <= self.capital:
                break
            shares -= 100

        if shares <= 0:
            return False

        amount = shares * exec_price
        commission = self._calc_commission(amount)
        total_cost = amount + commission

        self.capital -= total_cost
        self.position += shares

        self.trades.append({
            "date": date, "action": label, "grid": "-",
            "price": round(exec_price, 3), "shares": shares,
            "amount": round(amount, 2), "commission": round(commission, 2),
            "capital_after": round(self.capital, 2)
        })
        print(f"  📈 {date.strftime('%Y-%m-%d')} {label}: "
              f"价={exec_price:.3f}, 股={shares}, 额={amount:.2f}, 佣={commission:.2f}")
        return True

    def _sell_all(self, date, price: float, label: str = "趋势清仓"):
        """趋势模式：清仓全部持仓"""
        if self.position <= 0:
            return False
        exec_price = price * (1 - SLIPPAGE)
        amount = self.position * exec_price
        commission = self._calc_commission(amount)
        revenue = amount - commission

        self.capital += revenue

        self.trades.append({
            "date": date, "action": label, "grid": "-",
            "price": round(exec_price, 3), "shares": self.position,
            "amount": round(amount, 2), "commission": round(commission, 2),
            "capital_after": round(self.capital, 2)
        })
        print(f"  📉 {date.strftime('%Y-%m-%d')} {label}: "
              f"价={exec_price:.3f}, 股={self.position}, 额={amount:.2f}, 佣={commission:.2f}")
        self.position = 0
        return True

    def _init_grid(self, date, price: float):
        """切换到网格模式时，建立网格底仓"""
        current_grid = self.get_grid_index(price)
        self.last_grid = current_grid

        # 在当前价格下方的网格建立底仓
        grids_to_fill = list(range(current_grid + 1))
        if not grids_to_fill:
            return

        capital_per_grid = (self.initial_capital * self.initial_pct) / len(grids_to_fill)
        for g in grids_to_fill:
            buy_price = self.grid_lines[g]
            shares = int(capital_per_grid / buy_price / 100) * 100
            if shares > 0:
                amount = shares * buy_price
                commission = self._calc_commission(amount)
                total_cost = amount + commission
                if total_cost <= self.capital:
                    self.capital -= total_cost
                    self.grid_shares[g] = shares
                    self.position += shares
                    self.trades.append({
                        "date": date, "action": "网格底仓", "grid": g,
                        "grid_price": round(buy_price, 3), "price": round(buy_price, 3),
                        "shares": shares, "amount": round(amount, 2),
                        "commission": round(commission, 2),
                        "capital_after": round(self.capital, 2)
                    })
                    print(f"  📦 网格底仓[{g}]: 价={buy_price:.3f}, 股={shares}, 额={amount:.2f}")

    def _grid_buy(self, grid_idx: int, date, price: float):
        if self.grid_shares[grid_idx] > 0:
            return False
        buy_price = price * (1 + SLIPPAGE)
        target_shares = int(self.per_grid_value / buy_price / 100) * 100
        if target_shares <= 0:
            return False

        amount = target_shares * buy_price
        commission = self._calc_commission(amount)
        total_cost = amount + commission

        while total_cost > self.capital and target_shares >= 100:
            target_shares -= 100
            amount = target_shares * buy_price
            commission = self._calc_commission(amount)
            total_cost = amount + commission
        if target_shares <= 0 or total_cost > self.capital:
            return False

        self.capital -= total_cost
        self.grid_shares[grid_idx] = target_shares
        self.position += target_shares

        self.trades.append({
            "date": date, "action": "网格买入", "grid": grid_idx,
            "grid_price": round(self.grid_lines[grid_idx], 3),
            "price": round(buy_price, 3), "shares": target_shares,
            "amount": round(amount, 2), "commission": round(commission, 2),
            "capital_after": round(self.capital, 2)
        })
        print(f"  📈 {date.strftime('%Y-%m-%d')} 网格买入[{grid_idx}]: "
              f"价={buy_price:.3f}, 股={target_shares}, 额={amount:.2f}, 佣={commission:.2f}")
        return True

    def _grid_sell(self, grid_idx: int, date, price: float):
        if self.grid_shares[grid_idx] <= 0:
            return False
        sell_price = price * (1 - SLIPPAGE)
        sell_shares = self.grid_shares[grid_idx]
        amount = sell_shares * sell_price
        commission = self._calc_commission(amount)
        revenue = amount - commission

        self.capital += revenue
        self.position -= sell_shares
        self.grid_shares[grid_idx] = 0

        self.trades.append({
            "date": date, "action": "网格卖出", "grid": grid_idx,
            "grid_price": round(self.grid_lines[grid_idx], 3),
            "price": round(sell_price, 3), "shares": sell_shares,
            "amount": round(amount, 2), "commission": round(commission, 2),
            "capital_after": round(self.capital, 2)
        })
        print(f"  📉 {date.strftime('%Y-%m-%d')} 网格卖出[{grid_idx}]: "
              f"价={sell_price:.3f}, 股={sell_shares}, 额={amount:.2f}, 佣={commission:.2f}")
        return True

    def _run_grid_step(self, date, price: float):
        """执行一步网格交易"""
        current_grid = self.get_grid_index(price)
        if current_grid > self.last_grid:
            for g in range(self.last_grid, current_grid):
                self._grid_sell(g, date, price)
        elif current_grid < self.last_grid:
            for g in range(current_grid, self.last_grid):
                self._grid_buy(g, date, price)
        self.last_grid = current_grid

    def run(self, df: pd.DataFrame) -> dict:
        print(f"\n🚀 开始混合策略回测，初始资金: {self.initial_capital:,.2f} 元")
        print(f"   趋势判断: 收盘价 > MA{self.trend_ma} (缓冲 {self.confirm_days} 天确认)")
        print(f"   网格区间: [{self.lower:.2f}, {self.upper:.2f}], {self.num_grids} 格")
        print("=" * 60)

        # 计算均线
        df = df.copy()
        df[f"ma{self.trend_ma}"] = df["close"].rolling(window=self.trend_ma, min_periods=self.trend_ma).mean()

        for _, row in df.iterrows():
            date = row["date"]
            price = row["close"]
            trend_up = self.check_trend(row)

            # ===== 更新缓冲计数器 =====
            if trend_up:
                self.above_count += 1
                self.below_count = 0
            else:
                self.below_count += 1
                self.above_count = 0

            # ===== 趋势模式确认 =====
            if self.above_count >= self.confirm_days and self.mode != "trend":
                self.mode = "trend"
                self.grid_shares = {i: 0 for i in range(self.num_grids)}
                self.last_grid = None
                print(f"\n🔄 {date.strftime('%Y-%m-%d')} 切换为【趋势模式】"
                      f" (连续{self.confirm_days}天 > MA{self.trend_ma})")
                if self.position == 0:
                    self._buy_all(date, price, "趋势建仓")

            # ===== 网格模式确认 =====
            elif self.below_count >= self.confirm_days and self.mode != "grid":
                self.mode = "grid"
                print(f"\n🔄 {date.strftime('%Y-%m-%d')} 切换为【网格模式】"
                      f" (连续{self.confirm_days}天 <= MA{self.trend_ma})")
                if self.position > 0:
                    self._sell_all(date, price, "趋势结束清仓")
                self._init_grid(date, price)

            # ===== 执行当前模式的交易 =====
            if self.mode == "trend":
                if self.position == 0:
                    self._buy_all(date, price, "趋势补仓")
            elif self.mode == "grid":
                self._run_grid_step(date, price)

            # 记录每日资产
            total_value = self.capital + self.position * price
            self.daily_values.append({
                "date": date,
                "capital": self.capital,
                "position_value": self.position * price,
                "total_value": total_value,
                "position_ratio": (self.position * price) / total_value if total_value > 0 else 0,
                "mode": self.mode,
                "above_count": self.above_count,
                "below_count": self.below_count
            })

        final_price = df.iloc[-1]["close"]
        final_value = self.capital + self.position * final_price

        print("=" * 60)
        print(f"🏁 回测结束")
        return self._generate_report(df, final_value)

    def _generate_report(self, df: pd.DataFrame, final_value: float) -> dict:
        start_price = df.iloc[0]["close"]
        end_price = df.iloc[-1]["close"]

        benchmark_shares = int(self.initial_capital / start_price / 100) * 100
        benchmark_cost = benchmark_shares * start_price
        benchmark_commission = self._calc_commission(benchmark_cost)
        benchmark_value = benchmark_shares * end_price - benchmark_commission

        total_return = (final_value - self.initial_capital) / self.initial_capital
        benchmark_return = (benchmark_value - self.initial_capital) / self.initial_capital

        days = (df.iloc[-1]["date"] - df.iloc[0]["date"]).days
        years = max(days / 365, 0.01)
        annual_return = (1 + total_return) ** (1 / years) - 1
        benchmark_annual = (1 + benchmark_return) ** (1 / years) - 1

        values_df = pd.DataFrame(self.daily_values)
        values_df["cummax"] = values_df["total_value"].cummax()
        values_df["drawdown"] = (values_df["total_value"] - values_df["cummax"]) / values_df["cummax"]
        max_drawdown = values_df["drawdown"].min()

        # 统计各模式天数
        trend_days = len([d for d in self.daily_values if d.get("mode") == "trend"])
        grid_days = len([d for d in self.daily_values if d.get("mode") == "grid"])

        buy_count = len([t for t in self.trades if "买入" in t["action"] or "建仓" in t["action"] or "底仓" in t["action"]])
        sell_count = len([t for t in self.trades if "卖出" in t["action"] or "清仓" in t["action"]])

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
            "trend_days": trend_days,
            "grid_days": grid_days,
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
        print(f"买入/建仓:      {buy_count:>12} 次")
        print(f"卖出/清仓:      {sell_count:>12} 次")
        print(f"趋势模式天数:   {trend_days:>12} 天")
        print(f"网格模式天数:   {grid_days:>12} 天")
        print("-" * 50)

        return report
