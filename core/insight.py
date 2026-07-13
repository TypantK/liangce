# -*- coding: utf-8 -*-
"""
智能洞察层（规则之外的辅助信息）
============================================================
本模块提供「不依赖 12 个固定策略规则」的辅助判断维度，给发现页的
信号卡片附上一层更偏「人脑直觉」的洞察，用于辅助推荐。

设计原则（与项目一致：事实/推断分离，取不到就降级，绝不编造）：
  - 量价异动：今日成交量 vs 近 20 日均量（放量/缩量倍数）
  - 相对强度：标的近 20 日涨幅 vs 同期沪深 300（跑赢/跑输大盘）
  - 估值温度计：当前价在最近 250 日分位（高位/低位/中位）
  - 新闻情绪：近 3 日新闻情绪分（复用 core.sentiment_fetcher）
  - 板块联动：所属板块今日涨跌（复用 core.daily_review 行业热点）

所有维度独立降级，任何一项取不到返回 None，UI 显示「—」，不影响其它。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from .data_fetcher import get_stock_data as _get_stock_data
from .daily_review import fetch_sectors
from . import sentiment_fetcher

# streamlit 缓存装饰器（insight 在 streamlit 运行时由 discover_page 调用）
try:
    import streamlit as st
except Exception:  # 非 streamlit 环境（如测试）降级为无缓存
    class _Stub:
        @staticmethod
        def cache_data(*a, **k):
            def deco(fn):
                return fn
            return deco
    st = _Stub()


# ---------------------------------------------------------------------------
#  工具
# ---------------------------------------------------------------------------

def _safe_ratio(numer: Optional[float], denom: Optional[float]) -> Optional[float]:
    """安全除法，返回比值或 None。"""
    try:
        if numer is None or denom is None or denom == 0:
            return None
        return float(numer) / float(denom)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _pct_change(series: pd.Series) -> Optional[float]:
    """返回序列首尾涨跌幅（百分比）。需至少 2 个元素。"""
    if series is None or len(series) < 2:
        return None
    first, last = float(series.iloc[0]), float(series.iloc[-1])
    if first == 0:
        return None
    return (last - first) / first * 100.0


# ---------------------------------------------------------------------------
#  1. 量价异动
# ---------------------------------------------------------------------------

def volume_anomaly(df: pd.DataFrame) -> Dict[str, Any]:
    """今日成交量 vs 近 20 日均量。

    返回 {value, label, note}，value 为倍数（今日/20日均），None 表示无法计算。
    """
    result = {"value": None, "label": "—", "note": "成交量数据不足"}
    if df is None or "volume" not in df.columns or len(df) < 2:
        return result
    vols = df["volume"].astype(float)
    today_vol = float(vols.iloc[-1])
    window = vols.iloc[:-1].tail(20)
    if len(window) == 0:
        return result
    avg20 = float(window.mean())
    ratio = _safe_ratio(today_vol, avg20)
    if ratio is None:
        return result
    # 单位美化：成交量单位因标的而异，仅给倍数更稳健
    if ratio >= 2.0:
        label = f"显著放量 {ratio:.1f} 倍"
    elif ratio >= 1.3:
        label = f"温和放量 {ratio:.1f} 倍"
    elif ratio <= 0.5:
        label = f"明显缩量 {ratio:.1f} 倍"
    elif ratio <= 0.8:
        label = f"缩量 {ratio:.1f} 倍"
    else:
        label = f"量能平稳 ({ratio:.1f} 倍)"
    result.update({"value": ratio, "label": label, "note": "今日量/近20日均量"})
    return result


# ---------------------------------------------------------------------------
#  2. 估值温度计（当前价在最近 250 日分位）
# ---------------------------------------------------------------------------

def valuation_thermometer(df: pd.DataFrame, lookback: int = 250) -> Dict[str, Any]:
    """当前价在最近 lookback 日收盘区间的分位（0=最低，1=最高）。

    返回 {value, label, note}。
    """
    result = {"value": None, "label": "—", "note": "历史数据不足"}
    if df is None or "close" not in df.columns or len(df) < 20:
        return result
    closes = df["close"].astype(float).tail(lookback)
    cur = float(closes.iloc[-1])
    lo, hi = float(closes.min()), float(closes.max())
    if hi == lo:
        return result
    pct = (cur - lo) / (hi - lo)
    result["value"] = round(pct, 3)
    if pct >= 0.8:
        label = f"处于年内高位 ({pct*100:.0f}% 分位)"
    elif pct <= 0.2:
        label = f"处于年内低位 ({pct*100:.0f}% 分位)"
    else:
        label = f"处于中部 ({pct*100:.0f}% 分位)"
    result["label"] = label
    result["note"] = f"近{min(len(closes), lookback)}日收盘区间分位"
    return result


# ---------------------------------------------------------------------------
#  3. 相对强度（标的 vs 沪深300）
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_index_300() -> Optional[pd.DataFrame]:
    """抓取沪深300近 30 日收盘，用于相对强弱基准。1 小时缓存。"""
    return _get_stock_data("1.000300", start=(datetime.now() - timedelta(days=80)).strftime("%Y-%m-%d"),
                           end=datetime.now().strftime("%Y-%m-%d"))


def relative_strength(df: pd.DataFrame) -> Dict[str, Any]:
    """标的近 20 日涨幅 vs 同期沪深300。

    返回 {value, label, note}，value = 标的涨幅 - 沪深300涨幅（百分点）。
    """
    result = {"value": None, "label": "—", "note": "基准指数数据不足"}
    if df is None or "close" not in df.columns or len(df) < 5:
        return result
    own = _pct_change(df["close"].astype(float).tail(20))
    bench = None
    try:
        idx = _fetch_index_300()
        if idx is not None and "close" in idx.columns and len(idx) >= 5:
            bench = _pct_change(idx["close"].astype(float).tail(20))
    except Exception:
        bench = None
    if own is None:
        return result
    if bench is None:
        result["note"] = "沪深300基准暂不可用，仅看自身涨幅"
        result["value"] = round(own, 2)
        result["label"] = f"自身近20日 {own:+.1f}%"
        return result
    diff = own - bench
    result["value"] = round(diff, 2)
    if diff >= 3:
        label = f"显著跑赢大盘 (+{diff:.1f}pt)"
    elif diff >= 0:
        label = f"略强于大盘 (+{diff:.1f}pt)"
    elif diff >= -3:
        label = f"略弱于大盘 ({diff:.1f}pt)"
    else:
        label = f"明显跑输大盘 ({diff:.1f}pt)"
    result["label"] = label
    result["note"] = f"自身 {own:+.1f}% vs 沪深300 {bench:+.1f}%"
    return result


# ---------------------------------------------------------------------------
#  4. 新闻情绪（复用 sentiment_fetcher）
# ---------------------------------------------------------------------------

# 简易中文情绪词打分（无需外部模型，纯本地，可解释）
_POS_WORDS = ["涨", "增", "升", "利", "好", "购", "超", "预", "期", "盈", "利", "回", "购",
              "签", "单", "突", "破", "加", "仓", "买", "入", "上", "调", "看", "多", "红", "喜"]
_NEG_WORDS = ["跌", "减", "降", "利", "空", "亏", "损", "裁", "员", "查", "调", "退", "市",
              "暴", "跌", "熔", "断", "立", "案", "风", "险", "下", "调", "看", "空", "绿", "警"]


def _score_text(text: str) -> float:
    """对单条文本做朴素情绪打分，范围约 [-1, 1]。"""
    if not text:
        return 0.0
    score = 0.0
    for w in _POS_WORDS:
        if w in text:
            score += 0.5
    for w in _NEG_WORDS:
        if w in text:
            score -= 0.5
    # 限制幅度
    return max(-3.0, min(3.0, score))


def news_sentiment(query: str, max_news: int = 6) -> Dict[str, Any]:
    """抓取近 3 日相关新闻并做朴素情绪打分。

    返回 {value, label, note, count}，value 为平均情绪分（约 [-3,3]）。
    """
    result = {"value": None, "label": "—", "note": "新闻抓取不可用", "count": 0}
    try:
        news = sentiment_fetcher.fetch_news(query, max_results=max_news)
    except Exception:
        return result
    if not news:
        result["note"] = "近3日无相关新闻"
        return result

    recent_cut = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    scores = []
    for n in news:
        # 日期过滤：仅在 date 存在且过旧时跳过
        d = n.get("date", "")
        if d and isinstance(d, str) and len(d) >= 10 and d[:10] < recent_cut:
            continue
        text = (n.get("title", "") or "") + " " + (n.get("snippet", "") or "")
        scores.append(_score_text(text))

    result["count"] = len(scores)
    if not scores:
        result["note"] = "近3日无相关新闻"
        return result
    avg = float(np.mean(scores))
    result["value"] = round(avg, 2)
    if avg >= 1.0:
        label = f"新闻偏多 (+{avg:.1f})"
    elif avg > 0.2:
        label = f"新闻略偏多 (+{avg:.1f})"
    elif avg >= -0.2:
        label = f"新闻中性 ({avg:.1f})"
    elif avg > -1.0:
        label = f"新闻略偏空 ({avg:.1f})"
    else:
        label = f"新闻偏空 ({avg:.1f})"
    result["label"] = label
    result["note"] = f"近3日 {len(scores)} 条新闻平均情绪"
    return result


# ---------------------------------------------------------------------------
#  5. 板块联动（复用 daily_review 行业热点）
# ---------------------------------------------------------------------------

_SECTOR_KEYWORDS = {
    "白酒": ["白酒"], "半导体": ["半导体"], "新能源汽车": ["新能源汽车", "汽车"],
    "光伏设备": ["光伏"], "医药生物": ["医药", "医疗", "生物"], "银行": ["银行"],
    "军工": ["军工", "国防"], "招商中证白酒": ["白酒"], "易方达蓝筹": ["白酒", "蓝筹"],
}

# 标的展示名 → 可能所属板块关键词
_SYMBOL_SECTOR_MAP = {
    "平安银行": ["银行"], "万科A": ["地产", "房地产"], "中国平安": ["保险", "金融"],
    "贵州茅台": ["白酒"], "招商银行": ["银行"], "比亚迪": ["新能源汽车", "汽车"],
    "宁德时代": ["新能源", "电池"], "五粮液": ["白酒"],
    "特斯拉": ["新能源汽车"], "苹果": ["科技", "消费电子"],
    "BTC/USDT": [], "ETH/USDT": [],
}


def sector_linkage(symbol_name: str, sector_name: Optional[str] = None) -> Dict[str, Any]:
    """标的所属板块今日涨跌（复用 daily_review 行业热点）。

    返回 {value, label, note}，value 为板块今日涨跌幅（%），None 表示不匹配。
    """
    result = {"value": None, "label": "—", "note": "未匹配到所属板块"}
    # 优先用 SECTOR 池中声明的板块名
    keywords = []
    if sector_name:
        keywords = [sector_name]
    else:
        keywords = _SYMBOL_SECTOR_MAP.get(symbol_name, [])
    if not keywords:
        result["note"] = "无对应板块映射"
        return result
    try:
        sec = fetch_sectors(top_n=30)
    except Exception:
        return result
    top = sec.get("top", []) or []
    bottom = sec.get("bottom", []) or []
    all_sec = list(top) + list(bottom)
    if not all_sec:
        result["note"] = "行业热点数据暂不可用"
        return result
    # 匹配：板块名含任一关键词
    for r in all_sec:
        name = str(r.get("name", ""))
        if any(kw in name for kw in keywords):
            pct = _safe_pct(r.get("pct"))
            if pct is None:
                continue
            result["value"] = round(pct, 2)
            # 背离判断交由调用方组合，这里只给板块自身涨跌
            result["label"] = f"所属板块 {name} {pct:+.2f}%"
            result["note"] = f"板块：{name}"
            result["sector_name"] = name
            return result
    result["note"] = "所属板块未在涨幅/跌幅榜"
    return result


def _safe_pct(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
#  聚合入口：给单个标的算完整洞察
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def build_insight(symbol_name: str, symbol_code: str, asset_type: str) -> Dict[str, Any]:
    """为单个标的计算全部「规则外」洞察维度。

    各维度独立降级；symbol_code 用于取行情、query 用于新闻。
    基金与板块指数成交量无意义，量价异动维度略过。
    """
    has_volume = asset_type not in ("基金",)
    df = None
    try:
        df = _get_stock_data(symbol_code,
                             start=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"),
                             end=datetime.now().strftime("%Y-%m-%d"))
    except Exception:
        df = None

    # 新闻查询词：个股用代码/名，板块用板块名
    if symbol_code.startswith("SECTOR:"):
        query = symbol_code[len("SECTOR:"):]
    else:
        query = symbol_name

    # 板块联动：SECTOR 自身就是板块，无需映射
    sector_arg = symbol_code[len("SECTOR:"):] if symbol_code.startswith("SECTOR:") else None

    out = {
        "volume": volume_anomaly(df) if (has_volume and df is not None) else {"value": None, "label": "—", "note": "基金/板块无量能维度"},
        "valuation": valuation_thermometer(df),
        "relative_strength": relative_strength(df),
        "sentiment": news_sentiment(query),
        "sector": sector_linkage(symbol_name, sector_arg),
    }
    return out


# ---------------------------------------------------------------------------
#  汇总：把单个洞察压缩成一行「人话」标签
# ---------------------------------------------------------------------------

def summarize_insight(insight: Dict[str, Any]) -> List[str]:
    """把洞察 dict 压成若干条短标签（只保留有信息的维度）。"""
    tags = []
    for key in ("volume", "valuation", "relative_strength", "sentiment", "sector"):
        d = insight.get(key)
        if d and d.get("label") and d.get("label") != "—":
            tags.append(d["label"])
    return tags
