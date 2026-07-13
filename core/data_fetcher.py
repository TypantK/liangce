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
        '开盘价': 'open', '收盘价': 'close', '最高价': 'high', '最低价': 'low',
        '日期': 'date', '时间': 'date',
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


def _try_eastmoney_board_kline(board_code: str, start: str, end: str) -> pd.DataFrame:
    """直连东方财富板块历史 K 线接口（带完整 UA，规避无 UA 被拒）。

    东方财富行业板块的行情市场号为 90，secid 形如 "90.BK1036"。
    返回归一化后的 OHLCV DataFrame。
    """
    import requests

    secid = f"90.{board_code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",            # 日 K
        "fqt": "0",              # 不复权（板块指数本身无复权概念）
        "beg": start.replace("-", ""),
        "end": end.replace("-", ""),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "*/*",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    klines = data.get("data", {}).get("klines", [])
    if not klines:
        raise RuntimeError(f"东方财富板块 {board_code} 返回空 K 线")
    rows = []
    for line in klines:
        # 格式: 日期,开盘,收盘,最高,最低,成交量,成交额,...
        parts = line.split(",")
        rows.append({
            "日期": parts[0],
            "开盘": float(parts[1]),
            "收盘": float(parts[2]),
            "最高": float(parts[3]),
            "最低": float(parts[4]),
            "成交量": float(parts[5]),
        })
    df = pd.DataFrame(rows)
    return _normalize_columns(df)


def _try_akshare_sector(symbol: str, start: str, end: str) -> pd.DataFrame:
    """申万行业板块指数（真实板块数据）。

    优先级：直连东方财富板块 K 线（带 UA，最稳）→ akshare 行业板块接口兜底。
    symbol 形如 "半导体" / "半导体#BK1036"：
      - 仅行业名时自动查询行业列表匹配代码；
      - 带 #代码 时直接指定东方财富行业板块代码（更稳）。
    """
    import akshare as ak
    import time

    # 拆分行业名与板块代码
    board_name = symbol
    board_code = None
    if '#' in symbol:
        board_name, board_code = symbol.split('#', 1)

    # 若仅有行业名，先通过 akshare 行业列表解析出板块代码
    if not board_code:
        try:
            industry_df = ak.stock_board_industry_name_em()
            name_col = code_col = None
            for col in industry_df.columns:
                cl = col.strip()
                if cl in ('行业', '板块名称', '名称', 'name'):
                    name_col = col
                elif cl in ('板块代码', '代码', 'code'):
                    code_col = col
            matched = industry_df[industry_df[name_col].astype(str).str.contains(board_name, na=False)]
            if not matched.empty:
                board_code = str(matched.iloc[0][code_col])
        except Exception:
            pass
    if not board_code:
        raise RuntimeError(f"无法解析行业板块代码: {board_name}")

    last_err = None
    # 主路径：直连东方财富（带 UA），重试 3 次
    for attempt in range(3):
        try:
            df = _try_eastmoney_board_kline(board_code, start, end)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            last_err = e
            time.sleep(1)

    # 兜底：akshare 行业板块接口
    try:
        df = ak.stock_board_industry_hist_em(symbol=board_code, period="日k", adjust="")
        if df is not None and not df.empty:
            return _normalize_columns(df)
    except Exception as e:
        last_err = e

    raise RuntimeError(f"行业板块获取失败: {last_err}")


def _try_ths_sector(symbol: str, start: str, end: str) -> pd.DataFrame:
    """同花顺行业指数（独立域名 10jqka，不受东方财富限流影响）。

    这是板块数据最稳的主路径。symbol 为同花顺行业名称（需与
    stock_board_industry_name_ths 返回的行业名精确一致，例如
    '半导体'/'饮料制造'/'其他电源设备' 等）。

    返回归一化后的 OHLCV DataFrame（开/收/高/低/成交量/成交额）。
    """
    import akshare as ak

    # 同花顺行业指数接口：symbol 接受精确行业名
    df = ak.stock_board_industry_index_ths(
        symbol=symbol,
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
    )
    if df is None or df.empty:
        raise RuntimeError(f"同花顺行业指数 {symbol} 返回空数据")
    df = _normalize_columns(df)
    if df is None or df.empty:
        raise RuntimeError(f"同花顺行业指数 {symbol} 归一化后为空")
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
#  缓存新鲜度策略 —— 按标的类型差异化
# ---------------------------------------------------------------------------

# 中国大陆法定节假日（休市，无行情）。仅列近月常用日期，过期无害（多联网一次）。
# 需要更精确可接入交易日历库；此处用轻量清单覆盖常见场景。
_CN_HOLIDAYS = {
    # 2026 年（示例，按需补充）
    "2026-01-01",
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    "2026-04-06", "2026-05-01", "2026-06-19",
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",
}


def _prev_business_day(d: pd.Timestamp, holidays: set) -> pd.Timestamp:
    """返回 d（含）起、往前的最近一个非周末、非节假日的交易日。"""
    while d.weekday() >= 5 or d.strftime('%Y-%m-%d') in holidays:
        d -= pd.Timedelta(days=1)
    return d


def _expected_latest_trading_day(symbol: str) -> pd.Timestamp:
    """按标的类型推算"此刻理应已存在的最新收盘数据日期"。

    缓存里最新一根 K 线 >= 该日期，即视为新鲜，无需联网；否则视为过期需刷新。
    差异化依据：
      - 加密货币（USDT，7×24 无休市）：昨天（当日仍在进行中，收盘数据尚未定型）。
      - 美股（时差）：美东交易日收盘对应北京次日；简化为"上一个美东工作日"，
        用北京时间减 1 天后取工作日（不含节假日精细处理，容错为多刷一次）。
      - A 股 / 板块指数：交易时段 15:00 收盘。当天若为交易日且已过 15:30 → 今天；
        否则回退到最近的交易日（自动跳过周末与节假日）。
    """
    now = datetime.now()
    today = pd.Timestamp(now.date())

    # —— 加密货币：全天候，最新完整日为昨天 ——
    if symbol.endswith('USDT'):
        return today - pd.Timedelta(days=1)

    # —— 美股：北京时间比美东早，"今天"的美股尚未开盘/收盘 ——
    #    以北京时间前一天为基准取工作日（美股节假日不精细处理，容错多刷一次）。
    is_a_share = symbol.endswith(('.SZ', '.SH'))
    is_sector = symbol.startswith('SECTOR:')
    if not is_a_share and not is_sector:
        base = today - pd.Timedelta(days=1)
        # 美股不套用 A 股节假日，仅跳过周末
        while base.weekday() >= 5:
            base -= pd.Timedelta(days=1)
        return base

    # —— A 股 / 板块指数：15:00 收盘，留缓冲到 15:30 ——
    closed_today = (now.hour > 15) or (now.hour == 15 and now.minute >= 30)
    if closed_today:
        return _prev_business_day(today, _CN_HOLIDAYS)
    # 未收盘：当日数据尚未定型，期望值回退到上一个交易日
    return _prev_business_day(today - pd.Timedelta(days=1), _CN_HOLIDAYS)


# ---------------------------------------------------------------------------
#  公开 API
# ---------------------------------------------------------------------------

def get_stock_data(symbol: str, start: Optional[str] = None, end: Optional[str] = None,
                   freq: str = "1d", force_refresh: bool = False) -> Optional[pd.DataFrame]:
    """
    获取真实股票数据（多源自动降级 + 本地缓存）。

    A 股 (.SZ/.SH)：open-stock-data → baostock 直连 → akshare
    加密货币 (USDT)：ccxt+OKX → ccxt+Binance
    美股 (其他)：    open-stock-data → akshare 美股接口
    板块指数 (SECTOR:xxx)：akshare 申万行业板块指数

    国内网络无需翻墙即可获取 A 股和美股数据。
    相同标的+区间会自动缓存到本地（默认 1 天），第二次起秒级返回，避免重复联网。

    start / end 默认为最近一年至今。
    force_refresh: 为 True 时无条件跳过本地缓存、强制重新联网拉取最新行情。
                   一般无需手动指定：函数会按标的类型（A股/板块/美股/加密货币）
                   自动判断缓存是否已覆盖"此刻理应存在的最新交易日"，
                   缺失才联网，避免休市日反复联网、也不会一直返回旧数据。
    """
    if end is None:
        end = datetime.now().strftime('%Y-%m-%d')
    if start is None:
        start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

    # ── 1. 先查 SQLite 缓存（force_refresh 时跳过）────────────────────
    data_store.init_db()
    if not force_refresh and data_store.has_stock_data(symbol, start, end):
        cached = data_store.load_stock_prices(symbol, start, end)
        # 差异化新鲜度判断：缓存最新一根 K 线是否已覆盖"预期最新交易日"。
        # 不同标的（A股/板块/美股/加密货币）的预期日不同，见 _expected_latest_trading_day。
        if cached is not None and not cached.empty and len(cached) >= 65 \
                and isinstance(cached.index, pd.DatetimeIndex):
            expected = _expected_latest_trading_day(symbol)
            latest = pd.Timestamp(cached.index[-1]).normalize()
            if latest >= expected.normalize():
                print(f"[{symbol}] 命中缓存（最新 {latest.date()} ≥ 预期 {expected.date()}），共 {len(cached)} 条")
                return cached
            else:
                print(f"[{symbol}] 缓存过期（最新 {latest.date()} < 预期 {expected.date()}），重新联网获取")
        else:
            print(f"[{symbol}] 缓存不完整，重新联网获取")
    elif force_refresh:
        print(f"[{symbol}] 强制刷新，跳过缓存重新联网获取")

    # ── 2. 构建 fallback 链 ──────────────────────────────────────────
    if symbol.startswith('SECTOR:'):
        # ── 申万/同花顺行业板块指数 ──────────────────────────────────
        # 主路径用同花顺（独立域名，不受东方财富限流影响）；
        # 兜底仍尝试东方财富直连 + akshare 行业板块接口。
        board = symbol[len('SECTOR:'):]
        chain = [
            ("同花顺行业指数", lambda: _try_ths_sector(board, start, end)),
            ("东方财富板块直连", lambda: _try_akshare_sector(board, start, end)),
        ]

    elif symbol.endswith(('.SZ', '.SH')):
        # ── A 股 ──────────────────────────────────────────────────────────
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
