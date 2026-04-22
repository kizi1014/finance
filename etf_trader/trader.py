"""
交易执行模块

支持三种模式：
1. simulate  - 模拟盘（打印交易信号，不实际下单）
2. qmt       - QMT 实盘（需安装 QMT 并配置账号）
3. manual    - 手动模式（打印信号，人工在券商APP下单）
"""

import time
from datetime import datetime
from config import COMMISSION_RATE, MIN_COMMISSION, POSITION_RATIO


class BaseTrader:
    """交易基类"""
    
    def __init__(self, initial_capital: float = 100_000):
        self.capital = initial_capital
        self.position = 0
        self.trades = []
    
    def buy(self, code: str, price: float, date=None):
        raise NotImplementedError
    
    def sell(self, code: str, price: float, date=None):
        raise NotImplementedError
    
    def get_position(self, code: str) -> int:
        return self.position


class SimulateTrader(BaseTrader):
    """
    模拟盘交易器
    
    按信号模拟成交，记录交易日志和盈亏，不实际下单。
    适合策略验证和纸面交易。
    """
    
    def _calc_commission(self, amount: float) -> float:
        return max(amount * COMMISSION_RATE, MIN_COMMISSION)
    
    def buy(self, code: str, price: float, date=None):
        if self.position > 0:
            print(f"  ⏭️ 已持仓，跳过买入")
            return False
        
        if date is None:
            date = datetime.now()
        
        max_shares = int((self.capital * POSITION_RATIO) / price / 100) * 100
        if max_shares <= 0:
            print(f"  ⚠️ 资金不足，无法买入")
            return False
        
        amount = max_shares * price
        commission = self._calc_commission(amount)
        total_cost = amount + commission
        
        self.capital -= total_cost
        self.position = max_shares
        
        self.trades.append({
            "time": date,
            "action": "买入",
            "code": code,
            "price": round(price, 3),
            "shares": max_shares,
            "amount": round(amount, 2),
            "commission": round(commission, 2)
        })
        
        print(f"  📈 【模拟买入】{code} @ {price:.3f} × {max_shares}股，"
              f"金额 {amount:.2f}，佣金 {commission:.2f}")
        return True
    
    def sell(self, code: str, price: float, date=None):
        if self.position <= 0:
            print(f"  ⏭️ 空仓，跳过卖出")
            return False
        
        if date is None:
            date = datetime.now()
        
        amount = self.position * price
        commission = self._calc_commission(amount)
        net_revenue = amount - commission
        
        profit = net_revenue - (sum([t["amount"] for t in self.trades if t["action"] == "买入"]) 
                                - sum([t["amount"] for t in self.trades if t["action"] == "卖出"]))
        
        self.capital += net_revenue
        
        self.trades.append({
            "time": date,
            "action": "卖出",
            "code": code,
            "price": round(price, 3),
            "shares": self.position,
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "profit": round(net_revenue - self.trades[-1]["amount"], 2) if self.trades else 0
        })
        
        print(f"  📉 【模拟卖出】{code} @ {price:.3f} × {self.position}股，"
              f"金额 {amount:.2f}，佣金 {commission:.2f}")
        self.position = 0
        return True
    
    def status(self):
        """打印当前账户状态"""
        print(f"\n💰 模拟账户状态")
        print(f"   可用资金: {self.capital:,.2f} 元")
        print(f"   持仓股数: {self.position} 股")
        if self.trades:
            print(f"   历史交易: {len(self.trades)} 笔")


class QMTTrader(BaseTrader):
    """
    QMT 实盘交易器（框架预留）
    
    需要：
    1. 安装 QMT 量化交易软件（如国金QMT、华泰QMT等）
    2. 开通miniQMT权限
    3. 安装 xtquant 库
    
    使用时取消下方注释并完善逻辑。
    """
    
    def __init__(self, qmt_path: str = "", account: str = ""):
        super().__init__()
        self.qmt_path = qmt_path
        self.account = account
        self.xt_trader = None
        self._init_qmt()
    
    def _init_qmt(self):
        try:
            # 取消注释以启用 QMT
            # import sys
            # sys.path.append(self.qmt_path)
            # from xtquant.xttrader import XtQuantTrader
            # from xtquant.xttype import StockAccount
            # 
            # self.xt_trader = XtQuantTrader(self.qmt_path, "etf_strategy")
            # self.xt_trader.start()
            # connect_result = self.xt_trader.connect()
            # if connect_result == 0:
            #     print("✅ QMT 连接成功")
            # else:
            #     print(f"❌ QMT 连接失败，错误码: {connect_result}")
            pass
        except ImportError:
            print("⚠️ 未安装 xtquant，QMT 交易不可用")
    
    def buy(self, code: str, price: float, date=None):
        """QMT 买入下单"""
        # 示例代码（需根据实际 QMT API 调整）
        # from xtquant.xttype import XtTradeRequest
        # request = XtTradeRequest()
        # request.stock_code = code + ".SH"  # 沪市加 .SH
        # request.order_type = 50  # 限价单
        # request.price = price
        # request.order_volume = 100  # 需计算实际股数
        # self.xt_trader.order(self.account, request)
        print(f"  📈 【QMT买入】{code} @ {price:.3f}（需完善QMT下单代码）")
        return True
    
    def sell(self, code: str, price: float, date=None):
        """QMT 卖出下单"""
        print(f"  📉 【QMT卖出】{code} @ {price:.3f}（需完善QMT下单代码）")
        return True


class ManualTrader(BaseTrader):
    """
    手动提醒交易器
    
    只打印交易提醒，不自动下单，用户手动在券商APP操作。
    """
    
    def buy(self, code: str, price: float, date=None):
        print(f"\n🔔 【买入提醒】")
        print(f"   标的: {code}")
        print(f"   信号: 均线金叉")
        print(f"   建议买入价: {price:.3f} 元")
        print(f"   操作: 请在券商APP中手动买入")
        print("-" * 40)
        return True
    
    def sell(self, code: str, price: float, date=None):
        print(f"\n🔔 【卖出提醒】")
        print(f"   标的: {code}")
        print(f"   信号: 均线死叉")
        print(f"   建议卖出价: {price:.3f} 元")
        print(f"   操作: 请在券商APP中手动卖出")
        print("-" * 40)
        return True


def create_trader(mode: str, **kwargs):
    """工厂函数，根据模式创建对应的交易器"""
    if mode == "simulate":
        return SimulateTrader(kwargs.get("initial_capital", 100_000))
    elif mode == "qmt":
        return QMTTrader(
            qmt_path=kwargs.get("qmt_path", ""),
            account=kwargs.get("account", "")
        )
    elif mode == "manual":
        return ManualTrader()
    else:
        raise ValueError(f"不支持的交易模式: {mode}")
