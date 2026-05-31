# -*- coding: utf-8 -*-
"""
数据获取模块 - 多源自动降级架构
支持 A 股 / 美股 / 加密货币，每条路径均有 fallback 链，国内网络无需翻墙。
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


# ---------------------------------------------------------------------------
#  私有辅助 — 各数据源适配器
# ---------------------------------------------------------------------------

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """统一列名为 open/high/low/close/volume，索引为 datetime"""
    rename_map = {
        '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low',
        '成交量': 'volume', '成交额': 'amount',
    }
    # 小写兜底
    for col in list(df.columns):
        low = col.lower()
        if low in ('open', 'high', 'low', 'close', 'volume'):
            rename_map[col] = low
    df = df.rename(columns=rename_map)
    # 确保 datetime 索引
    for name_col in ('datetime', 'date', '日期', '时间'):
        if name_col in df.columns:
            df[name_col] = pd.to_datetime(df[name_col], errors='coerce')
            df.dropna(subset=[name_col], inplace=True)
            df.set_index(name_col, inplace=True)
            break
    # 只保留 OHLCV 列
    wanted = [c for c in ('open', 'high', 'low', 'close', 'volume') if c in df.columns]
    if not wanted:
        raise ValueError("缺少必要的 OHLCV 数据列")
    return df[wanted]


# ── open-stock-data ───────────────────────────────────────────────────────

def _try_open_stock_data(symbol: str, market: str, start: str, end: str) -> pd.DataFrame:
    """使用 open-stock-data 获取行情（国内可直连）"""
    from open_stock_data.tools import stock_prices

    # 计算 limit：按交易日估计，至少取 1500 条确保覆盖长周期
    try:
        days = (pd.Timestamp(end) - pd.Timestamp(start)).days
        limit = max(500, int(days * 1.5))
    except Exception:
        limit = 1500

    df = stock_prices(symbol=symbol, market=market, limit=limit)

    # open-stock-data 在某些数据源下返回 CSV 字符串
    if isinstance(df, str):
        from io import StringIO
        df = pd.read_csv(StringIO(df), comment='#')
        # 过滤掉重复表头行（某些源会内嵌列名行）
        for col in df.columns:
            if df[col].dtype == object:
                mask = df[col] == col
                if mask.any():
                    df = df[~mask]
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise RuntimeError("open-stock-data 返回空数据")
    df = _normalize_columns(df)
    # 按日期裁剪
    if isinstance(df.index, pd.DatetimeIndex):
        df = df.loc[start:end]
    return df


# ── akshare ───────────────────────────────────────────────────────────────

def _try_akshare_cn(symbol: str, start: str, end: str) -> pd.DataFrame:
    """A 股 via akshare（国内数据源，无需翻墙）"""
    import akshare as ak

    raw = symbol.replace('.SZ', '').replace('.SH', '')
    df = ak.stock_zh_a_hist(
        symbol=raw, period="daily",
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
        adjust="qfq",
    )
    if df is None or df.empty:
        raise RuntimeError("akshare A 股返回空数据")
    df = _normalize_columns(df)
    return df


def _try_akshare_us(symbol: str, start: str, end: str) -> pd.DataFrame:
    """美股 via akshare（走东方财富美股频道，国内无需翻墙）"""
    import akshare as ak

    # akshare 美股代码格式：106.TSLA → 106 是纳斯达克
    # 尝试几个常见映射
    us_map = {
        'TSLA': '105.TSLA', 'AAPL': '105.AAPL', 'MSFT': '105.MSFT',
        'GOOGL': '105.GOOGL', 'GOOG': '105.GOOG', 'AMZN': '105.AMZN',
        'META': '105.META', 'NVDA': '105.NVDA', 'NFLX': '105.NFLX',
        'BABA': '106.BABA', 'BIDU': '106.BIDU', 'JD': '106.JD',
        'NIO': '106.NIO', 'XPEV': '106.XPEV', 'LI': '106.LI',
        'PLTR': '106.PLTR', 'UBER': '106.UBER', 'PYPL': '105.PYPL',
    }
    ak_symbol = us_map.get(symbol.upper(), f"105.{symbol.upper()}")
    df = ak.stock_us_hist(
        symbol=ak_symbol, period="daily",
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
        adjust="qfq",
    )
    if df is None or df.empty:
        raise RuntimeError("akshare 美股返回空数据")
    df = _normalize_columns(df)
    return df


# ── ccxt (加密货币) ────────────────────────────────────────────────────────

def _try_ccxt_okx(symbol: str, start: str) -> pd.DataFrame:
    """加密货币 via OKX（国内可直连，无需翻墙）"""
    import ccxt

    ex = ccxt.okx({'enableRateLimit': True, 'timeout': 15000})
    ohlcv = ex.fetch_ohlcv(symbol, "1d", since=ex.parse8601(start + "T00:00:00Z"), limit=1000)
    if not ohlcv:
        raise RuntimeError("OKX 返回空数据")
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('datetime', inplace=True)
    df.drop('timestamp', axis=1, inplace=True)
    return df


def _try_ccxt_binance(symbol: str, start: str) -> pd.DataFrame:
    """加密货币 via Binance（备用，国内需翻墙）"""
    import ccxt

    ex = ccxt.binance({'enableRateLimit': True, 'timeout': 15000})
    ohlcv = ex.fetch_ohlcv(symbol, "1d", since=ex.parse8601(start + "T00:00:00Z"), limit=1000)
    if not ohlcv:
        raise RuntimeError("Binance 返回空数据")
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('datetime', inplace=True)
    df.drop('timestamp', axis=1, inplace=True)
    return df


# ---------------------------------------------------------------------------
#  公开 API
# ---------------------------------------------------------------------------

def get_stock_data(symbol: str, start: str = "2024-01-01", end: str = "2025-12-31",
                   freq: str = "1d") -> Optional[pd.DataFrame]:
    """
    获取真实股票数据（多源自动降级）。

    A 股 (.SZ/.SH)：open-stock-data → akshare
    加密货币 (USDT)：ccxt+OKX → ccxt+Binance
    美股 (其他)：    open-stock-data → akshare 美股接口

    国内网络无需翻墙即可获取 A 股和美股数据。
    """
    if symbol.endswith(('.SZ', '.SH')):
        # ── A 股 ──────────────────────────────────────────────────────────
        market = "sh" if symbol.endswith('.SH') else "sz"
        raw = symbol.replace('.SZ', '').replace('.SH', '')
        chain = [
            ("open-stock-data", lambda: _try_open_stock_data(raw, market, start, end)),
            ("akshare",          lambda: _try_akshare_cn(symbol, start, end)),
        ]

    elif symbol.endswith('USDT'):
        # ── 加密货币 ──────────────────────────────────────────────────────
        chain = [
            ("ccxt+OKX",     lambda: _try_ccxt_okx(symbol, start)),
            ("ccxt+Binance", lambda: _try_ccxt_binance(symbol, start)),
        ]

    else:
        # ── 美股 ──────────────────────────────────────────────────────────
        chain = [
            ("open-stock-data", lambda: _try_open_stock_data(symbol, "us", start, end)),
            ("akshare 美股",    lambda: _try_akshare_us(symbol, start, end)),
        ]

    # 遍历 fallback 链
    for src_name, fetcher in chain:
        try:
            df = fetcher()
            if df is not None and not df.empty:
                return df
        except Exception as e:
            print(f"[{symbol}] {src_name} 失败: {e}")

    print(f"[{symbol}] 所有数据源均失败")
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
