# -*- coding: utf-8 -*-
"""
数据获取模块 - 支持A股/美股/加密货币
"""

import pandas as pd
import numpy as np
from typing import Optional

STOCK_POOL = {
    "平安银行":     "000001.SZ",
    "万科A":        "000002.SZ",
    "中国平安":     "601318.SH",
    "贵州茅台":     "600519.SH",
    "招商银行":     "600036.SH",
    "比亚迪":       "002594.SZ",
    "宁德时代":     "300750.SZ",
    "五粮液":       "000858.SZ",
    "特斯拉":       "TSLA",
    "苹果":         "AAPL",
    "BTC/USDT":    "BTC/USDT",
    "ETH/USDT":    "ETH/USDT",
}


def get_stock_data(symbol: str, start: str = "2024-01-01", end: str = "2025-12-31",
                   freq: str = "1d") -> Optional[pd.DataFrame]:
    """获取真实股票数据"""
    try:
        if symbol.endswith(('.SZ', '.SH')):
            import akshare as ak
            df = ak.stock_zh_a_hist(
                symbol=symbol.replace('.SZ', '').replace('.SH', ''),
                period="daily",
                start_date=start.replace("-", ""),
                end_date=end.replace("-", ""),
                adjust="qfq"
            )
            df.rename(columns={
                '日期': 'datetime', '开盘': 'open', '收盘': 'close',
                '最高': 'high', '最低': 'low', '成交量': 'volume'
            }, inplace=True)
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)
            return df[['open', 'high', 'low', 'close', 'volume']]

        elif symbol.endswith('USDT'):
            import ccxt
            ex = ccxt.binance({'enableRateLimit': True})
            ohlcv = ex.fetch_ohlcv(
                symbol, "1d",
                since=ex.parse8601(start + "T00:00:00Z"),
                limit=1000
            )
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('datetime', inplace=True)
            df.drop('timestamp', axis=1, inplace=True)
            return df

        else:
            import yfinance as yf
            data = yf.download(symbol, start=start, end=end, interval=freq, progress=False)
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.droplevel(1)
            return data
    except Exception as e:
        print(f"获取 {symbol} 数据失败: {e}")
        return None


def generate_demo_data(n_bars: int = 300) -> pd.DataFrame:
    """
    生成日线模拟数据用于演示。
    使用交易日历（周一至周五），模拟真实股票走势。
    """
    np.random.seed(42)

    # ---- 交易日历（跳过周末） ----
    dates = pd.date_range('2024-01-02', periods=n_bars * 2, freq='B')[:n_bars]

    # ---- 股价：对数正态随机游走 + 趋势 ----
    rng = np.random.RandomState(42)
    daily_returns = rng.randn(n_bars) * 0.018
    # 叠加一个小幅趋势
    trend = np.linspace(0, 0.4, n_bars)  # 从 0 到 +40%
    log_returns = daily_returns + 0.0003
    prices = 50 * np.exp(np.cumsum(log_returns) + trend)

    # ---- OHLC ----
    close = prices
    intra_range = np.abs(rng.randn(n_bars)) * 0.012
    high = close * (1 + intra_range * 0.7)
    low = close * (1 - intra_range * 0.7)
    open_price = np.roll(close, 1)
    open_price[0] = close[0] * (1 + rng.randn() * 0.005)

    # 确保 OHLC 约束
    high = np.maximum(high, np.maximum(open_price, close))
    low = np.minimum(low, np.minimum(open_price, close))

    # ---- 成交量 ----
    base_vol = 8_000_000
    volume = np.abs(rng.randn(n_bars) * base_vol * 0.4 + base_vol).astype(int)

    df = pd.DataFrame({
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    }, index=dates)
    df.index.name = 'datetime'

    return df
