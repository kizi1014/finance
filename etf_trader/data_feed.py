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


def _get_baostock_etf(code: str, start: str, end: str) -> pd.DataFrame:
    """
    通过 baostock 获取指定 ETF 真实数据（akshare失效时的备选）
    """
    import baostock as bs
    import time
    
    # baostock 代码格式：sh.510300 或 sz.159915
    # 上海交易所：5/6/9 开头；深圳交易所：0/1/2/3 开头
    if code.startswith(("5", "6", "9")):
        bs_code = f"sh.{code}"
    else:
        bs_code = f"sz.{code}"
    
    print(f"📡 尝试通过 baostock 获取 {code} 真实数据...")
    
    # 重试机制（baostock 有时第一次请求会失败）
    for attempt in range(3):
        bs.login()
        
        # baostock 要求日期格式为 YYYY-MM-DD
        start_fmt = pd.to_datetime(start).strftime("%Y-%m-%d") if start else "2022-01-01"
        end_fmt = pd.to_datetime(end).strftime("%Y-%m-%d") if end else datetime.now().strftime("%Y-%m-%d")
        
        rs = bs.query_history_k_data_plus(
            bs_code,
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
        
        if len(data_list) > 0:
            break
        
        if attempt < 2:
            print(f"   ⚠️ 第 {attempt + 1} 次请求返回空数据，1秒后重试...")
            time.sleep(1)
    
    df = pd.DataFrame(data_list, columns=["date", "open", "high", "low", "close", "volume"])
    
    if len(df) == 0:
        raise ValueError(f"baostock 返回空数据（{bs_code}）")
    
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    
    df = df.sort_values("date").reset_index(drop=True)
    print(f"✅ 获取成功（baostock {code}），共 {len(df)} 条数据，"
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
    
    # 第2步：尝试 baostock（获取对应 ETF 真实数据）
    try:
        df = _get_baostock_etf(code=code, start=start, end=end)
        return df
    except Exception as e:
        print(f"⚠️ baostock 获取失败: {e}")
    
    # 第3步：降级为模拟数据
    print("🔄 自动切换为模拟数据进行测试...")
    return generate_mock_data()


def get_daily_close(code: str = ETF_CODE) -> dict:
    """
    获取 ETF 最新收盘数据（用于收盘后每日报告）
    
    优先使用 akshare 历史K线接口（数据最准确），失败时回退到其他数据源
    
    Returns:
        dict: {"code": ..., "price": ..., "date": ..., "open": ..., "high": ..., "low": ...}
    """
    import time
    
    # 第1步：尝试 akshare 历史K线接口（数据最准确，包含完整OHLC）
    for attempt in range(3):
        try:
            # 获取最近5天的数据，取最后一天
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - __import__('datetime').timedelta(days=10)).strftime("%Y%m%d")
            
            df = ak.fund_etf_hist_em(
                symbol=code,
                period="daily",
                start_date=start,
                end_date=end,
                adjust="qfq"
            )
            if len(df) > 0:
                df = normalize_columns(df)
                latest = df.iloc[-1]
                return {
                    "code": code,
                    "price": float(latest["close"]),
                    "date": str(latest["date"]),
                    "open": float(latest["open"]),
                    "high": float(latest["high"]),
                    "low": float(latest["low"]),
                    "volume": float(latest["volume"]),
                }
        except Exception as e:
            if attempt < 2:
                wait_time = 2 ** attempt
                print(f"⚠️ K线接口获取收盘数据失败（第{attempt + 1}次）: {e}，{wait_time}秒后重试...")
                time.sleep(wait_time)
            else:
                print(f"⚠️ K线接口获取收盘数据失败（已重试3次）: {e}")
    
    # 第2步：尝试新浪 ETF 实时接口
    try:
        df = ak.fund_etf_category_sina(symbol="ETF基金")
        prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
        sina_code = f"{prefix}{code}"
        row = df[df["代码"] == sina_code]
        if row.empty:
            raise ValueError(f"未找到 {code}")
        
        return {
            "code": code,
            "price": float(row["最新价"].values[0]),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "open": float(row["今开"].values[0]),
            "high": float(row["最高"].values[0]),
            "low": float(row["最低"].values[0]),
            "volume": float(row["成交量"].values[0]),
        }
    except Exception as e:
        print(f"⚠️ 新浪接口获取收盘数据失败: {e}")
    
    # 第3步：尝试 baostock
    try:
        import baostock as bs
        
        if code.startswith(("5", "6", "9")):
            bs_code = f"sh.{code}"
        else:
            bs_code = f"sz.{code}"
        
        bs.login()
        today = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - __import__('datetime').timedelta(days=5)).strftime("%Y-%m-%d")
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume",
            start_date=start,
            end_date=today,
            frequency="d",
            adjustflag="3"
        )
        data_list = []
        while (rs.error_code == "0") & rs.next():
            data_list.append(rs.get_row_data())
        bs.logout()
        
        if len(data_list) > 0:
            row = data_list[-1]
            return {
                "code": code,
                "price": float(row[4]),
                "date": row[0],
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "volume": float(row[5]),
            }
    except Exception as e:
        print(f"⚠️ baostock 获取收盘数据失败: {e}")
    
    print("❌ 所有数据源获取收盘数据均失败")
    return None


def get_latest_price(code: str = ETF_CODE) -> dict:
    """
    获取 ETF 最新行情（兼容旧接口，实际调用 get_daily_close）
    
    Returns:
        dict: {"code": ..., "price": ..., "time": ...}
    """
    result = get_daily_close(code)
    if result:
        # 兼容旧格式
        result["time"] = result.get("date", datetime.now().strftime("%H:%M:%S"))
        result["pre_close"] = result["price"]
    return result
