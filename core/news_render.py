# -*- coding: utf-8 -*-
"""
统一新闻/信号源渲染层
============================================================
问题背景：
  项目里多处渲染「新闻/信号源」列表（板块预测的信号源、回测页的情绪事件来源、
  回测页的当日资讯），原本各自实现，导致有的新闻可点击跳转、有的不能，体验割裂。

本模块提供**唯一**的渲染入口，所有页面共用同一套样式与跳转逻辑：
  - 标题可点击跳转（有 url 才跳，无 url 则纯文本，绝不编造链接）
  - 利好/利空/中性徽章
  - 来源 / 地区 / 日期等元信息

数据兼容两种形态：
  1. dict（fetch_news 风格）：{"title","url","source","score","region","date", ...}
  2. tuple： (date, score, title) 或 (date, score, title, url)
      —— 兼容 core.sentiment 升级前的三元组与升级后的四元组
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple, Union

# 单条新闻的两种合法形态
NewsItem = Union[Dict[str, Any], Tuple]


def _normalize(item: NewsItem) -> Dict[str, Any]:
    """把 dict 或 tuple 归一化为统一的 dict 字段。

    返回 {date, score, title, url, source, region}，缺失字段给默认值。
    """
    if isinstance(item, dict):
        url = item.get("url", "") or ""
        score = item.get("score", 0)
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = 0
        return {
            "date": item.get("date", ""),
            "score": score,
            "title": item.get("title", "") or "（无标题）",
            "url": url,
            "source": item.get("source", ""),
            "region": item.get("region", ""),
        }
    # tuple / list
    if isinstance(item, (tuple, list)):
        date = item[0] if len(item) > 0 else ""
        score = item[1] if len(item) > 1 else 0
        title = item[2] if len(item) > 2 else "（无标题）"
        url = item[3] if len(item) > 3 else ""
        return {
            "date": date,
            "score": score,
            "title": title,
            "url": url or "",
            "source": "",
            "region": "",
        }
    # 兜底
    return {"date": "", "score": 0, "title": str(item), "url": "", "source": "", "region": ""}


def _badge(score: int):
    """返回 (背景色, 文字色, 标签文案)。"""
    if score > 0:
        return "#2e7d32", "#ffffff", f"利好 +{score}"
    elif score < 0:
        return "#c62828", "#ffffff", f"利空 {score}"
    return "#6b7280", "#ffffff", "中性"


def _row_html(n: Dict[str, Any], theme: str = "dark") -> str:
    """渲染单条新闻为 HTML（带可点击标题）。"""
    bg_badge, tx_badge, badge = _badge(n["score"])
    title_text = n["title"] or "（无标题）"
    # 有 url 才套链接，否则纯文本（避免空链接）
    if n["url"]:
        title_html = (
            f'<a href="{n["url"]}" target="_blank" '
            f'style="color:inherit;text-decoration:none">{title_text}</a>'
        )
    else:
        title_html = title_text

    # 元信息行：日期 · 来源/地区
    meta_parts = [p for p in (str(n["date"]) if n["date"] else "",
                              n["region"] or "", n["source"] or "") if p]
    meta = " · ".join(meta_parts)

    return f"""
    <div style="border-left:4px solid {bg_badge};background:
        {'rgba(46,125,50,0.08)' if n['score']>0 else ('rgba(198,40,40,0.08)' if n['score']<0 else 'rgba(107,114,128,0.08)')};
        padding:8px 12px;border-radius:6px;margin:4px 0;font-size:13px;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
            <span style="font-weight:600;color:#c8cce0">{title_html}</span>
            <span style="background:{bg_badge};color:{tx_badge};
                padding:1px 8px;border-radius:4px;font-size:11px;white-space:nowrap">{badge}</span>
        </div>
        <div style="font-size:11px;color:#6b7094;margin-top:2px">{meta}</div>
    </div>
    """


def render_news_cards(items: List[NewsItem], theme: str = "dark"):
    """以卡片形式渲染新闻列表（两列布局），用于信号源/情绪事件来源。

    直接通过 st.markdown(unsafe_allow_html=True) 输出，调用方无需再写循环。
    """
    import streamlit as st

    if not items:
        st.info("暂未抓取到相关新闻信号源（可能处于空窗期或通道不可用）。")
        return

    norm = [_normalize(it) for it in items]
    # 按情绪分排序：利好在前、利空在后
    norm.sort(key=lambda x: x["score"], reverse=True)

    cols = st.columns(2)
    for i, n in enumerate(norm):
        with cols[i % 2]:
            st.markdown(_row_html(n, theme), unsafe_allow_html=True)


def render_news_list(items: List[NewsItem], theme: str = "dark"):
    """以纵向列表形式渲染新闻（无分列），用于「当日资讯」等紧凑场景。

    每条按利好/利空给底色块，标题可点击跳转。
    """
    import streamlit as st

    if not items:
        st.caption("当日无相关资讯")
        return

    norm = [_normalize(it) for it in items]
    for n in norm:
        if n["score"] > 0:
            box = (f'<div style="background:#e8f5e9;padding:8px 12px;border-radius:6px;margin:4px 0;'
                   f'border-left:4px solid #2e7d32">📈 <b>利好</b> (+{n["score"]}) &nbsp; '
                   f'{_link_or_text(n)}</div>')
        elif n["score"] < 0:
            box = (f'<div style="background:#ffebee;padding:8px 12px;border-radius:6px;margin:4px 0;'
                   f'border-left:4px solid #c62828">📉 <b>利空</b> ({n["score"]}) &nbsp; '
                   f'{_link_or_text(n)}</div>')
        else:
            box = (f'<div style="color:#888;padding:4px 12px;margin:2px 0">'
                   f'➖ 中性 &nbsp; {_link_or_text(n)}</div>')
        st.markdown(box, unsafe_allow_html=True)


def _link_or_text(n: Dict[str, Any]) -> str:
    title_text = n["title"] or "（无标题）"
    if n["url"]:
        return (f'<a href="{n["url"]}" target="_blank" '
                f'style="color:inherit;text-decoration:none">{title_text}</a>')
    return title_text
