"""
数据获取模块：通过 akshare 获取 ETF 历史行情
"""

import akshare as ak
import pandas as pd
import requests
from datetime import datetime
from config import ETF_CODE, KLINE_PERIOD, BACKTEST_START, BACKTEST_END

# 为 akshare 底层请求添加请求头，避免被反爬
_akshare_session = requests.Session()
_akshare_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
})


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    统一列名为英文小写，兼容 akshare 不同版本的返回格式
    """
    col_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude",
        "涨跌幅": "pct_change",
        "涨跌额": "change",
        "换手率": "turnover",
    }
    # 先尝试中文映射
    rename_dict = {k: v for k, v in col_map.items() if k in df.columns}
    if rename_dict:
        df = df.rename(columns=rename_dict)
    
    # 确保日期列存在且为 datetime
    if "date" not in df.columns and "日期" not in df.columns:
        # 有些接口第一列无列名
        if df.columns[0] == df.index.name or str(df.columns[0]).isdigit():
            df = df.reset_index()
    
    return df


def generate_mock_data(days: int = 500, seed: int = 42) -> pd.DataFrame:
    """
    生成模拟 ETF 历史K线数据（用于无网络环境测试程序逻辑）
    
    模拟沪深300ETF特征：
    - 基准价约 3.5~4.0 元
    - 日波动率约 1.5%
    - 成交量随机
    """
    import numpy as np
    
    np.random.seed(seed)
    dates = pd.date_range(end=datetime.now(), periods=days, freq="B")  # 工作日
    
    returns = np.random.normal(0.0003, 0.015, days)  # 日均收益、波动率
    prices = 3.8 * np.exp(np.cumsum(returns))
    
    # 从收盘价反推 OHLC
    close = prices
    high = close * (1 + np.abs(np.random.normal(0, 0.008, days)))
    low = close * (1 - np.abs(np.random.normal(0, 0.008, days)))
    open_p = close * (1 + np.random.normal(0, 0.005, days))
    
    # 确保 high >= max(open, close), low <= min(open, close)
    high = np.maximum(high, np.maximum(open_p, close))
    low = np.minimum(low, np.minimum(open_p, close))
    
    volume = np.random.randint(1000000, 10000000, days)
    
    df = pd.DataFrame({
        "date": dates,
        "open": np.round(open_p, 3),
        "high": np.round(high, 3),
        "low": np.round(low, 3),
        "close": np.round(close, 3),
        "volume": volume,
    })
    
    print(f"✅ 使用模拟数据（{days} 个交易日）用于测试")
    return df


def _get_baostock_index(start: str, end: str) -> pd.DataFrame:
    """
    通过 baostock 获取沪深300指数真实数据（akshare失效时的备选）
    """
    import baostock as bs
    
    print("📡 尝试通过 baostock 获取沪深300指数真实数据...")
    bs.login()
    
    # baostock 要求日期格式为 YYYY-MM-DD
    start_fmt = pd.to_datetime(start).strftime("%Y-%m-%d") if start else "2022-01-01"
    end_fmt = pd.to_datetime(end).strftime("%Y-%m-%d") if end else datetime.now().strftime("%Y-%m-%d")
    
    rs = bs.query_history_k_data_plus(
        "sh.000300",
        "date,open,high,low,close,volume",
        start_date=start_fmt,
        end_date=end_fmt,
        frequency="d",
        adjustflag="3"  # 复权方式
    )
    
    data_list = []
    while (rs.error_code == "0") & rs.next():
        data_list.append(rs.get_row_data())
    
    bs.logout()
    
    df = pd.DataFrame(data_list, columns=["date", "open", "high", "low", "close", "volume"])
    
    if len(df) == 0:
        raise ValueError("baostock 返回空数据")
    
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # 沪深300指数价格(约5000)与ETF价格(约4)量级不同，进行归一化
    # 使指数走势可用于ETF策略回测
    if df["close"].mean() > 1000:
        scale = df["close"].iloc[0] / 4.0  # 以首日收盘价为基准，归一化到约4元
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col] / scale
        print(f"   (指数数据已归一化到ETF价格量级，比例 1:{scale:.0f})")
    
    df = df.sort_values("date").reset_index(drop=True)
    print(f"✅ 获取成功（沪深300指数），共 {len(df)} 条数据，"
          f"区间: {df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def get_etf_hist(code: str = ETF_CODE,
                 period: str = KLINE_PERIOD,
                 start: str = BACKTEST_START,
                 end: str = BACKTEST_END,
                 use_mock: bool = False) -> pd.DataFrame:
    """
    获取 ETF 历史K线数据
    
    Args:
        code: ETF代码，如 "510300"
        period: K线周期，"daily"=日线
        start: 起始日期，如 "20220101"
        end: 结束日期，如 "20241231"，空字符串表示到今天
        use_mock: 是否使用本地模拟数据（无网络环境测试用）
        
    Returns:
        DataFrame，包含列: date, open, high, low, close, volume
    """
    if use_mock:
        return generate_mock_data()
    
    print(f"📡 正在获取 {code} 的 {period} K线数据...")
    
    if not end:
        end = datetime.now().strftime("%Y%m%d")
    
    # 第1步：尝试 akshare（东方财富）
    try:
        if period == "daily":
            df = ak.fund_etf_hist_em(
                symbol=code,
                period="daily",
                start_date=start,
                end_date=end,
                adjust="qfq"  # 前复权
            )
        else:
            raise ValueError(f"暂不支持的周期: {period}")
        
        df = normalize_columns(df)
        required = ["date", "open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"数据缺少必要列: {col}，实际列: {list(df.columns)}")
        
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        
        df = df.sort_values("date").reset_index(drop=True)
        df = df[required]
        print(f"✅ 获取成功（akshare），共 {len(df)} 条数据，"
              f"区间: {df['date'].min().date()} ~ {df['date'].max().date()}")
        return df
    
    except Exception as e:
        print(f"⚠️ akshare 获取失败: {e}")
    
    # 第2步：尝试 baostock（获取沪深300指数作为替代）
    try:
        df = _get_baostock_index(start=start, end=end)
        return df
    except Exception as e:
        print(f"⚠️ baostock 获取失败: {e}")
    
    # 第3步：降级为模拟数据
    print("🔄 自动切换为模拟数据进行测试...")
    return generate_mock_data()


def get_latest_price(code: str = ETF_CODE) -> dict:
    """
    获取 ETF 最新行情（用于实盘/模拟盘的实时数据）
    
    Returns:
        dict: {"code": ..., "price": ..., "time": ...}
    """
    try:
        df = ak.fund_etf_spot_em()
        row = df[df["代码"] == code]
        if row.empty:
            raise ValueError(f"未找到 {code} 的实时行情")
        
        return {
            "code": code,
            "price": float(row["最新价"].values[0]),
            "time": str(row["时间"].values[0]) if "时间" in row.columns else datetime.now().strftime("%H:%M:%S"),
            "open": float(row["开盘价"].values[0]),
            "high": float(row["最高价"].values[0]),
            "low": float(row["最低价"].values[0]),
            "pre_close": float(row["昨收"].values[0]),
        }
    except Exception as e:
        print(f"⚠️ 获取实时行情失败: {e}")
        return None
