# -*- coding: utf-8 -*-
"""
情绪事件 / 基金净值 的本地缓存编排层

解决的问题：
  回测页面里「抓取情绪事件」「获取净值数据」原本只缓存在 streamlit 的
  session_state 中，每次脚本重跑（任何交互、st.rerun）都会清空，导致每次
  点击都要重新联网抓取，体验很差。

  本模块把数据落到已有的 SQLite 持久化层（data_store），并针对不同数据
  特性制定缓存更新 / 使用策略：

  ── 基金净值 ──
    维度：fund_code
    失效策略：净值仅在交易日收盘后更新。缓存命中条件为「缓存最新日期 >= 今天-1天」
              （即已包含到昨天为止的数据）；否则视为过期，重新联网拉取并覆盖写入。
    理由：盘中净值未定，用昨天及之前的全量数据回测足够；同一基金同日重复点击
          直接命中缓存，秒级返回。

  ── 情绪事件 ──
    维度：(symbol, sector) —— 既支持个股代码，也支持板块（如 "SECTOR:半导体"）
    失效策略：新闻时效短，采用 TTL（默认 6 小时）+ 同维度命中复用。
              超过 TTL 才重新抓取；换标的 / 板块则视为新维度，重新抓取。
    理由：新闻热度的半衰期以小时计，6 小时内的重复点击直接复用，避免重复抓取
          与情绪信号漂移。

所有接口均带「降级」：联网失败时，若本地有任意历史缓存则继续使用，保证体验。
"""

from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from . import data_store


# ===========================================================================
#  缓存策略参数（可按需调整）
# ===========================================================================
FUND_NAV_TTL_DAYS = 1          # 基金净值缓存有效期（天）：1 天 = 包含到昨天的数据即视为有效
SENTIMENT_TTL_HOURS = 6        # 情绪事件缓存有效期（小时）


# ===========================================================================
#  交易日辅助
# ===========================================================================
def _is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5


def _latest_cache_date_str(rows: List[dict]) -> Optional[str]:
    """从缓存记录列表中取最新日期字符串（YYYY-MM-DD）。"""
    if not rows:
        return None
    dates = [r.get("date", "") for r in rows if r.get("date")]
    if not dates:
        return None
    return max(dates)


# ===========================================================================
#  基金净值缓存
# ===========================================================================
def load_fund_nav_cached(fund_code: str) -> Optional["pd.DataFrame"]:
    """
    带缓存策略的基金净值加载。

    命中条件：存在缓存，且缓存最新日期 >=（今天 - FUND_NAV_TTL_DAYS 天）。
    命中返回 DataFrame；未命中或过期返回 None（调用方需联网刷新）。
    """
    import pandas as pd

    data_store.init_db()
    cached = data_store.load_fund_nav(fund_code)
    if cached is None or cached.empty:
        return None

    latest = cached.index[-1]
    if not isinstance(latest, pd.Timestamp):
        latest = pd.Timestamp(latest)
    # 缓存需覆盖到「今天 - TTL」之前，即至少包含到昨天的数据
    cutoff = datetime.now() - timedelta(days=FUND_NAV_TTL_DAYS)
    if latest >= pd.Timestamp(cutoff.strftime("%Y-%m-%d")):
        return cached
    return None


def save_fund_nav_cached(fund_code: str, nav_df: "pd.DataFrame") -> int:
    """把净值 DataFrame 写入 SQLite 缓存（覆盖式：INSERT OR REPLACE）。"""
    if nav_df is None or nav_df.empty:
        return 0
    rows = []
    for idx, row in nav_df.iterrows():
        d = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        rows.append({
            "date": d,
            "nav": float(row.get("nav")) if row.get("nav") is not None else None,
            "acc_nav": float(row.get("acc_nav")) if row.get("acc_nav") is not None else None,
        })
    return data_store.save_fund_nav(fund_code, rows)


# ===========================================================================
#  情绪事件缓存
# ===========================================================================
def _sentiment_cache_valid(rows: List[dict]) -> bool:
    """判断缓存是否在 TTL 内有效。"""
    if not rows:
        return False
    latest_created = None
    for r in rows:
        ca = r.get("created_at")
        if ca:
            try:
                t = datetime.strptime(ca, "%Y-%m-%d %H:%M:%S")
                if latest_created is None or t > latest_created:
                    latest_created = t
            except (ValueError, TypeError):
                continue
    if latest_created is None:
        # 没有时间戳，退回基于最新事件日期的宽松判断
        ld = _latest_cache_date_str(rows)
        if ld is None:
            return False
        try:
            evt_date = datetime.strptime(ld, "%Y-%m-%d")
        except (ValueError, TypeError):
            return False
        return (datetime.now() - evt_date).days <= 1
    return (datetime.now() - latest_created) <= timedelta(hours=SENTIMENT_TTL_HOURS)


def _rows_to_events(rows: List[dict]) -> List[Tuple[str, int, str]]:
    """把 sentiment_events 表记录转回 [(date, score, title), ...] 事件元组。"""
    events = []
    for r in rows:
        score = r.get("score")
        events.append((r.get("date", ""), score if score is not None else 0, r.get("title", "")))
    return events


def _events_to_records(events: List[Tuple[str, int, str]],
                       symbol: Optional[str],
                       sector: Optional[str]) -> List[dict]:
    """把 [(date, score, title), ...] 事件元组转成可入库的 dict 列表。"""
    from core.sentiment import format_sentiment_tag
    records = []
    for date_str, score, title in events:
        if not title:
            continue
        records.append({
            "date": date_str,
            "symbol": symbol,
            "sector": sector,
            "title": title,
            "summary": None,
            "sentiment": format_sentiment_tag(score),
            "score": int(score),
            "source": "cache",
            "url": None,
        })
    return records


def load_sentiment_cached(symbol: Optional[str],
                          sector: Optional[str]) -> Optional[List[Tuple[str, int, str]]]:
    """
    带缓存策略的情绪事件加载。

    命中条件：存在该维度（symbol 或 sector）的缓存，且缓存时间在 TTL 内。
    命中返回事件元组列表；未命中 / 过期 / 空返回 None（调用方需联网刷新）。
    """
    data_store.init_db()
    if symbol:
        rows = data_store.load_sentiment_events(symbol=symbol)
    elif sector:
        rows = data_store.load_sentiment_events(sector=sector)
    else:
        return None

    if not rows:
        return None
    if _sentiment_cache_valid(rows):
        return _rows_to_events(rows)
    return None


def save_sentiment_cached(events: List[Tuple[str, int, str]],
                          symbol: Optional[str],
                          sector: Optional[str]) -> int:
    """把情绪事件元组列表写入 SQLite 缓存。"""
    if not events:
        return 0
    records = _events_to_records(events, symbol, sector)
    return data_store.save_sentiment_events(records)
