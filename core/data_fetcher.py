# -*- coding: utf-8 -*-
"""
数据获取模块 - 多源自动降级架构
支持 A 股 / 美股 / 加密货币，每条路径均有 fallback 链，国内网络无需翻墙。
增加 SQLite 缓存层：首次联网获取后本地持久化，后续读取直接走缓存。
"""

from datetime import datetime, timedelta
import os
import pandas as pd
import numpy as np
from typing import Optional, List, Dict

from . import data_store

# ---------------------------------------------------------------------------
#  本地缓存层（提升“快”：相同标的+区间直接读盘，避免重复联网）
# ---------------------------------------------------------------------------
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data_cache')
CACHE_TTL_DAYS = 1  # 缓存有效期（天），过期自动重新联网拉取


def _safe_name(symbol: str) -> str:
    return symbol.replace('/', '_').replace('\\', '_').replace(':', '_')


def _cache_path(symbol: str, start: str, end: str, freq: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{_safe_name(symbol)}_{start}_{end}_{freq}.csv")


def _load_cache(path: str):
    if not os.path.exists(path):
        return None
    age_days = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))).days
    if age_days > CACHE_TTL_DAYS:
        return None
    try:
        return pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception:
        return None


def _save_cache(path: str, df: pd.DataFrame):
    try:
        df.to_csv(path)
    except Exception:
        pass

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
    df = df[wanted]
    # 强制转数值，防止数据源返回字符串导致 backtrader TypeError
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    return df


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


# ── baostock (直连，无需 token) ──────────────────────────────────────────

def _try_baostock(symbol: str, start: str, end: str) -> pd.DataFrame:
    """A 股 via baostock 直连（纯 Python，无需 token 或翻墙）"""
    import baostock as bs

    # 转换代码：000001.SZ → sz.000001，600519.SH → sh.600519
    if symbol.endswith('.SZ'):
        bs_code = f"sz.{symbol.replace('.SZ', '')}"
    elif symbol.endswith('.SH'):
        bs_code = f"sh.{symbol.replace('.SH', '')}"
    else:
        raise ValueError(f"不支持的 A 股代码格式: {symbol}")

    lg = bs.login()
    if lg.error_code != '0':
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")

    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            'date,open,high,low,close,volume',
            start_date=start,
            end_date=end,
            frequency='d',
            adjustflag='3',  # 复权类型：3=后复权
        )

        data_list = []
        if rs is not None:
            while (rs.error_code == '0') and rs.next():
                data_list.append(rs.get_row_data())

        if not data_list:
            error_msg = rs.error_msg if hasattr(rs, 'error_msg') else "未知错误"
            raise RuntimeError(f"baostock 返回空数据: {error_msg}")

        # 安全获取列名：rs.fields 可能为空或不存在
        try:
            columns = rs.fields if hasattr(rs, 'fields') and rs.fields else None
        except Exception:
            columns = None
        if columns is None:
            raise RuntimeError("baostock 返回数据缺少列信息(rs.fields 为空)")

        df = pd.DataFrame(data_list, columns=columns)
        df = _normalize_columns(df)
        return df
    finally:
        bs.logout()


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

def _try_ccxt(exchange_id: str, symbol: str, start: str,
               end: Optional[str] = None, timeout: int = 15000) -> pd.DataFrame:
    """加密货币 via ccxt 统一入口。exchange_id 如 'okx'/'gate'/'binance'。"""
    import ccxt

    ex_cls = getattr(ccxt, exchange_id)
    ex = ex_cls({'enableRateLimit': True, 'timeout': timeout})
    ohlcv = ex.fetch_ohlcv(symbol, "1d", since=ex.parse8601(start + "T00:00:00Z"), limit=1000)
    if not ohlcv:
        raise RuntimeError(f"{exchange_id} 返回空数据")
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('datetime', inplace=True)
    df.drop('timestamp', axis=1, inplace=True)
    if end is not None and isinstance(df.index, pd.DatetimeIndex):
        df = df.loc[:end]
    return df


# ---------------------------------------------------------------------------
#  公开 API
# ---------------------------------------------------------------------------

def get_stock_data(symbol: str, start: Optional[str] = None, end: Optional[str] = None,
                   freq: str = "1d") -> Optional[pd.DataFrame]:
    """
    获取真实股票数据（多源自动降级 + 本地缓存）。

    A 股 (.SZ/.SH)：open-stock-data → baostock 直连 → akshare
    加密货币 (USDT)：ccxt+OKX → ccxt+Binance
    美股 (其他)：    open-stock-data → akshare 美股接口

    国内网络无需翻墙即可获取 A 股和美股数据。
    相同标的+区间会自动缓存到本地（默认 1 天），第二次起秒级返回，避免重复联网。

    start / end 默认为最近一年至今。
    """
    if end is None:
        end = datetime.now().strftime('%Y-%m-%d')
    if start is None:
        start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

    # ── 1. 先查 SQLite 缓存 ──────────────────────────────────────────
    data_store.init_db()
    if data_store.has_stock_data(symbol, start, end):
        cached = data_store.load_stock_prices(symbol, start, end)
        if cached is not None and not cached.empty:
            print(f"[{symbol}] 命中缓存，共 {len(cached)} 条")
            return cached

    # ── 2. 构建 fallback 链 ──────────────────────────────────────────
    if symbol.startswith('SECTOR:'):
        # ── 申万行业板块指数 ──────────────────────────────────────────
        board = symbol[len('SECTOR:'):]
        chain = [
            ("akshare 行业板块", lambda: _try_akshare_sector(board, start, end)),
        ]

    elif symbol.endswith(('.SZ', '.SH')):
        market = "sh" if symbol.endswith('.SH') else "sz"
        raw = symbol.replace('.SZ', '').replace('.SH', '')
        chain = [
            ("open-stock-data", lambda: _try_open_stock_data(raw, market, start, end)),
            ("baostock",        lambda: _try_baostock(symbol, start, end)),
            ("akshare",         lambda: _try_akshare_cn(symbol, start, end)),
        ]

    elif symbol.endswith('USDT'):
        chain = [
            ("ccxt+Gate.io", lambda: _try_ccxt("gate", symbol, start, end, timeout=30000)),
            ("ccxt+OKX",     lambda: _try_ccxt("okx", symbol, start, end, timeout=15000)),
            ("ccxt+Binance", lambda: _try_ccxt("binance", symbol, start, end, timeout=15000)),
        ]

    else:
        chain = [
            ("open-stock-data", lambda: _try_open_stock_data(symbol, "us", start, end)),
            ("akshare 美股",    lambda: _try_akshare_us(symbol, start, end)),
        ]

    # ── 3. 遍历 fallback 链 ─────────────────────────────────────────
    for src_name, fetcher in chain:
        try:
            df = fetcher()
            if df is not None and not df.empty:
                # 写入缓存
                written = data_store.save_stock_prices(symbol, df)
                print(f"[{symbol}] {src_name} 成功，缓存 {written} 条")
                return df
        except Exception as e:
            print(f"[{symbol}] {src_name} 失败: {e}")

    # ── 4. 联网全部失败，尝试返回缓存中的部分数据 ─────────────────
    cached = data_store.load_stock_prices(symbol, start, end)
    if cached is not None and not cached.empty:
        print(f"[{symbol}] 联网失败，使用缓存中部分数据 ({len(cached)} 条)")
        return cached

    print(f"[{symbol}] 所有数据源均失败，且无缓存")
    return None


def fund_nav_to_ohlcv(nav_df: pd.DataFrame) -> pd.DataFrame:
    """
    将基金净值数据转为 OHLCV 格式，供回测引擎使用。
    基金只有每日单位净值，没有 OHLCV，此处模拟生成。

    nav_df: ak.fund_open_fund_info_em 返回的 DataFrame，
            含 'date' 和 'nav'（单位净值）两列。
    Returns: DataFrame with DatetimeIndex + OHLCV columns
    """
    df = nav_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")

    # close = 当日净值
    df["close"] = df["nav"]
    # open = 前一日净值（首日与当日相同）
    df["open"] = df["nav"].shift(1).fillna(df["nav"])
    # high / low = open 和 close 的较大/较小值
    df["high"] = df[["open", "close"]].max(axis=1)
    df["low"] = df[["open", "close"]].min(axis=1)
    # 固定成交量（基金无成交量概念，给一个占位值避免 backtrader 报错）
    df["volume"] = 1000000

    return df[["open", "high", "low", "close", "volume"]]


def get_fund_nav(fund_code: str, start: Optional[str] = None,
                 end: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    获取基金净值数据（带 SQLite 缓存）。

    fund_code: 基金代码，如 "000001"（华夏成长混合）
    start/end: 日期 YYYY-MM-DD，默认最近一年。

    数据源：akshare → open-stock-data（fallback）。
    返回 DataFrame，含 date / nav / acc_nav 列，按日期升序。
    """
    if end is None:
        end = datetime.now().strftime('%Y-%m-%d')
    if start is None:
        start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

    # ── 1. 先查缓存 ──────────────────────────────────────────────────
    data_store.init_db()
    cached = data_store.load_fund_nav(fund_code, start, end)
    if cached is not None and not cached.empty:
        print(f"[基金 {fund_code}] 命中缓存，共 {len(cached)} 条")
        return cached

    # ── 2. 联网获取 ──────────────────────────────────────────────────
    records: List[Dict] = []
    df = None

    # 尝试 akshare
    try:
        import akshare as ak
        raw = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        if raw is not None and not raw.empty:
            # akshare 返回的列名可能不同版本有差异，做兼容
            date_col = None
            nav_col = None
            for col in raw.columns:
                low = col.lower().replace(" ", "")
                if "净值日期" in col or low in ("date", "净值日期"):
                    date_col = col
                elif "单位净值" in col or low == "nav":
                    nav_col = col

            if date_col is None:
                # 尝试把第一列当日期
                date_col = raw.columns[0]
            if nav_col is None and len(raw.columns) >= 2:
                nav_col = raw.columns[1]

            for _, row in raw.iterrows():
                d = str(row[date_col])[:10]
                nv = row[nav_col] if nav_col else None
                records.append({"date": d, "nav": nv, "acc_nav": None})
    except Exception as e:
        print(f"[基金 {fund_code}] akshare 失败: {e}")

    # 如果 akshare 失败，尝试 open-stock-data
    if not records:
        try:
            from open_stock_data.tools import fund_nav as osd_fund_nav
            raw = osd_fund_nav(fund_code)
            if raw is not None and not raw.empty:
                for _, row in raw.iterrows():
                    records.append({
                        "date": str(row.get("date", ""))[:10],
                        "nav": row.get("nav"),
                        "acc_nav": row.get("acc_nav"),
                    })
        except Exception as e:
            print(f"[基金 {fund_code}] open-stock-data 失败: {e}")

    # ── 3. 写入缓存并返回 ────────────────────────────────────────────
    if records:
        data_store.save_fund_nav(fund_code, records)
        print(f"[基金 {fund_code}] 联网获取成功，缓存 {len(records)} 条")

        # 构建 DataFrame 返回
        data_rows = []
        for r in records:
            try:
                t = pd.Timestamp(r["date"])
                if pd.Timestamp(start) <= t <= pd.Timestamp(end):
                    data_rows.append(r)
            except Exception:
                pass
        if data_rows:
            df = pd.DataFrame(data_rows)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").set_index("date")
            return df

    # ── 4. 联网全部失败，尝试返回缓存中已有数据 ──────────────────────
    cached = data_store.load_fund_nav(fund_code, start, end)
    if cached is not None and not cached.empty:
        print(f"[基金 {fund_code}] 联网失败，使用缓存中部分数据 ({len(cached)} 条)")
        return cached

    print(f"[基金 {fund_code}] 所有数据源均失败，且无缓存")
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
