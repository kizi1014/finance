"""
网格交易策略回测引擎

经典网格逻辑：
1. 在 [lower, upper] 之间划分 N 个等差网格
2. 以第一天收盘价为锚点，在其下方的网格全部建底仓
3. 价格每跌破一个未持仓的网格 → 买入一份
4. 价格每涨破一个已持仓的网格 → 卖出一份
5. 始终在区间内低买高卖，赚取波动差价
"""

import pandas as pd
from config import (
    INITIAL_CAPITAL, COMMISSION_RATE, MIN_COMMISSION, SLIPPAGE,
    GRID_LOWER, GRID_UPPER, GRID_NUM, GRID_INITIAL_PCT
)


class GridBacktestEngine:
    def __init__(self,
                 initial_capital: float = INITIAL_CAPITAL,
                 lower: float = GRID_LOWER,
                 upper: float = GRID_UPPER,
                 num_grids: int = GRID_NUM,
                 initial_pct: float = GRID_INITIAL_PCT):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.position = 0
        self.lower = lower
        self.upper = upper
        self.num_grids = num_grids
        self.step = (upper - lower) / num_grids
        self.initial_pct = initial_pct

        # 网格线（从低到高）
        self.grid_lines = [lower + i * self.step for i in range(num_grids + 1)]

        # 每格目标持仓资金
        self.per_grid_value = initial_capital / num_grids

        # 记录每格买入的股数（0 表示该格未持仓）
        self.grid_shares = {i: 0 for i in range(num_grids)}

        self.trades = []
        self.daily_values = []
        self.last_grid = None

    def _calc_commission(self, amount: float) -> float:
        return max(amount * COMMISSION_RATE, MIN_COMMISSION)

    def get_grid_index(self, price: float) -> int:
        """根据价格确定所在网格编号（0 ~ num_grids-1）"""
        if price <= self.lower:
            return 0
        if price >= self.upper:
            return self.num_grids - 1
        return int((price - self.lower) / self.step)

    def _buy_grid(self, grid_idx: int, date, price: float, reason: str = "网格买入"):
        """在指定网格买入"""
        buy_price = price * (1 + SLIPPAGE)
        # 该格应买入的股数
        target_shares = int(self.per_grid_value / buy_price / 100) * 100

        if target_shares <= 0 or self.grid_shares[grid_idx] > 0:
            return False

        amount = target_shares * buy_price
        commission = self._calc_commission(amount)
        total_cost = amount + commission

        if total_cost > self.capital:
            # 资金不足，尝试买更少
            while total_cost > self.capital and target_shares >= 100:
                target_shares -= 100
                amount = target_shares * buy_price
                commission = self._calc_commission(amount)
                total_cost = amount + commission
            if target_shares <= 0:
                return False

        self.capital -= total_cost
        self.grid_shares[grid_idx] = target_shares
        self.position += target_shares

        self.trades.append({
            "date": date,
            "action": reason,
            "grid": grid_idx,
            "grid_price": round(self.grid_lines[grid_idx], 3),
            "price": round(buy_price, 3),
            "shares": target_shares,
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "capital_after": round(self.capital, 2)
        })

        print(f"  📈 {date.strftime('%Y-%m-%d')} {reason}[{grid_idx}]: "
              f"价={buy_price:.3f}, 股={target_shares}, 额={amount:.2f}, 佣={commission:.2f}")
        return True

    def _sell_grid(self, grid_idx: int, date, price: float, reason: str = "网格卖出"):
        """在指定网格卖出"""
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
            "date": date,
            "action": reason,
            "grid": grid_idx,
            "grid_price": round(self.grid_lines[grid_idx], 3),
            "price": round(sell_price, 3),
            "shares": sell_shares,
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "capital_after": round(self.capital, 2)
        })

        print(f"  📉 {date.strftime('%Y-%m-%d')} {reason}[{grid_idx}]: "
              f"价={sell_price:.3f}, 股={sell_shares}, 额={amount:.2f}, 佣={commission:.2f}")
        return True

    def run(self, df: pd.DataFrame) -> dict:
        """运行网格回测"""
        print(f"\n🚀 开始网格回测，初始资金: {self.initial_capital:,.2f} 元")
        print(f"   网格区间: [{self.lower:.2f}, {self.upper:.2f}], "
              f"共 {self.num_grids} 格, 步长 {self.step:.3f}")
        print("=" * 60)

        # ===== 初始建仓 =====
        first_price = df.iloc[0]["close"]
        start_grid = self.get_grid_index(first_price)
        self.last_grid = start_grid

        print(f"\n📦 初始建仓: 首日收盘价={first_price:.3f}, 位于第 {start_grid} 格")

        # 在当前价格下方的所有网格建立底仓
        grids_to_fill = list(range(start_grid + 1))
        capital_per_grid = (self.initial_capital * self.initial_pct) / len(grids_to_fill)

        for g in grids_to_fill:
            price = self.grid_lines[g]
            shares = int(capital_per_grid / price / 100) * 100
            if shares > 0:
                amount = shares * price
                commission = self._calc_commission(amount)
                total_cost = amount + commission
                if total_cost <= self.capital:
                    self.capital -= total_cost
                    self.grid_shares[g] = shares
                    self.position += shares
                    self.trades.append({
                        "date": df.iloc[0]["date"],
                        "action": "初始建仓",
                        "grid": g,
                        "grid_price": round(price, 3),
                        "price": round(price, 3),
                        "shares": shares,
                        "amount": round(amount, 2),
                        "commission": round(commission, 2),
                        "capital_after": round(self.capital, 2)
                    })
                    print(f"  📦 初始建仓[{g}]: 价={price:.3f}, 股={shares}, 额={amount:.2f}")

        print(f"   建仓完成: 持仓 {self.position} 股, 现金 {self.capital:,.2f} 元")
        print("-" * 60)

        # ===== 逐日交易 =====
        for _, row in df.iterrows():
            date = row["date"]
            price = row["close"]
            current_grid = self.get_grid_index(price)

            # 价格上涨，穿越了上方网格线 → 卖出经过的格子
            if current_grid > self.last_grid:
                for g in range(self.last_grid, current_grid):
                    self._sell_grid(g, date, price, "网格卖出")

            # 价格下跌，穿越了下方网格线 → 买入对应的格子
            elif current_grid < self.last_grid:
                for g in range(current_grid, self.last_grid):
                    self._buy_grid(g, date, price, "网格买入")

            self.last_grid = current_grid

            # 记录每日总资产
            total_value = self.capital + self.position * price
            self.daily_values.append({
                "date": date,
                "capital": self.capital,
                "position_value": self.position * price,
                "total_value": total_value,
                "position_ratio": (self.position * price) / total_value if total_value > 0 else 0
            })

        # 最终按收盘价清算
        final_price = df.iloc[-1]["close"]
        final_value = self.capital + self.position * final_price

        print("=" * 60)
        print(f"🏁 回测结束")

        return self._generate_report(df, final_value)

    def _generate_report(self, df: pd.DataFrame, final_value: float) -> dict:
        """生成回测报告"""
        start_price = df.iloc[0]["close"]
        end_price = df.iloc[-1]["close"]

        # 基准：买入并持有
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

        buy_count = len([t for t in self.trades if "买入" in t["action"] or "建仓" in t["action"]])
        sell_count = len([t for t in self.trades if "卖出" in t["action"]])

        # 统计网格占用情况
        occupied_grids = sum(1 for v in self.grid_shares.values() if v > 0)

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
            "total_trades": buy_count + sell_count,
            "occupied_grids": occupied_grids,
            "total_grids": self.num_grids,
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
        print(f"卖出:           {sell_count:>12} 次")
        print(f"当前占用网格:   {occupied_grids:>12} / {self.num_grids}")
        print("-" * 50)

        return report
