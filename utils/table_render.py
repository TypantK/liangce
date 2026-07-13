# -*- coding: utf-8 -*-
"""
统一表格渲染层
============================================================
问题背景：
  项目里多处渲染「表格」，风格各不相同：
    A. 原生 st.dataframe（跟随全局主题）
    B. 回测页交易明细表：纯手写 <table> 字符串，硬编码浅色配色，深色模式错位
    C. 板块预测页概率表 / 关键价位表：DataFrame.to_html + .replace 注入样式，
       且深色/浅色各写一份、两张表模板互相复制

本模块提供**唯一**的 HTML 表格渲染入口，所有页面共用同一套样式与主题适配：
  - 自动跟随 theme（dark / light）
  - 支持列对齐、逐单元格着色回调、行底色回调
  - 统一表头 / 边框 / 字体 / 内边距

与 utils.chart 共用同一套主题配色常量，避免「改一处漏一处」。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

import pandas as pd

# 复用图表模块的主题配色，保证全站一致。
# chart 依赖 plotly；若运行环境缺 plotly（仅用表格时），降级到等值内置常量，
# 避免「只想画表格却因缺 plotly 崩溃」。
try:
    from utils import chart as _c
    _FONT = _c.CN_FONT
    _CONST = {
        "CARD_BG": _c.CARD_BG, "FG": _c.FG,
        "LIGHT_CARD_BG": _c.LIGHT_CARD_BG, "LIGHT_FG": _c.LIGHT_FG,
        "LIGHT_GRID_C": _c.LIGHT_GRID_C,
    }
except Exception:  # pragma: no cover - 缺 plotly 时的降级
    _FONT = "PingFang SC, Microsoft YaHei, SimHei, Arial Unicode MS, sans-serif"
    _CONST = {
        "CARD_BG": "#1a1d2e", "FG": "#c8cce0",
        "LIGHT_CARD_BG": "#f3f4f6", "LIGHT_FG": "#1f2937",
        "LIGHT_GRID_C": "#e5e7eb",
    }


def _palette(theme: str) -> Dict[str, str]:
    """返回当前主题下的表格配色。与 chart.py 常量对齐。"""
    if theme == "light":
        return {
            "th_bg": _CONST["LIGHT_CARD_BG"],   # 表头背景
            "th_fg": _CONST["LIGHT_FG"],        # 表头文字
            "th_border": _CONST["LIGHT_GRID_C"],  # 表头下边框
            "td_fg": _CONST["LIGHT_FG"],        # 单元格文字
            "td_border": _CONST["LIGHT_GRID_C"],  # 单元格下边框
            "row_alt": "rgba(0,0,0,0.02)",      # 斑马纹
        }
    return {
        "th_bg": _CONST["CARD_BG"],
        "th_fg": _CONST["FG"],
        "th_border": "#2a2d3e",
        "td_fg": _CONST["FG"],
        "td_border": "#2a2d3e",
        "row_alt": "rgba(255,255,255,0.02)",
    }


def _esc(v: Any) -> str:
    """轻量转义，避免破坏表格结构。允许调用方通过 cell_html 注入受控 HTML。"""
    s = "" if v is None else str(v)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_table(
    df: pd.DataFrame,
    theme: str = "dark",
    *,
    columns: Optional[Sequence[str]] = None,
    aligns: Optional[Sequence[str]] = None,
    zebra: bool = False,
    row_bg: Optional[Callable[[int, pd.Series], Optional[str]]] = None,
    cell_html: Optional[Callable[[str, Any, pd.Series], Optional[str]]] = None,
    col_widths: Optional[Sequence[str]] = None,
    font_size: int = 14,
    render: bool = True,
) -> str:
    """把 DataFrame 渲染成统一风格、自动适配主题的 HTML 表格。

    参数：
      df         : 数据源（可包含辅助列，供回调读取）
      theme      : "dark" / "light"
      columns    : 需要显示的列（顺序即展示顺序）；缺省显示 df 全部列。
                   未列入的列仍可在 row_bg / cell_html 回调中通过完整行访问，
                   便于携带「辅助字段」而不展示为列。
      aligns     : 每列文本对齐（"left"/"center"/"right"），长度与显示列数一致；缺省全部 left
      zebra      : 是否斑马纹
      row_bg     : 回调 (row_idx, row_series) -> 背景色 或 None（用于按行着色，如买/卖）
      cell_html  : 回调 (col_name, value, row_series) -> 该单元格的完整 HTML 内容 或 None
                   返回 None 时用转义后的原值；返回字符串时**原样注入**（调用方负责安全）
      col_widths : 每列宽度（如 ["10%","4%",...]），用于定宽表格
      font_size  : 字号 px
      render     : True 时直接 st.markdown 输出；False 时仅返回 HTML 字符串

    返回：完整 HTML 字符串。
    """
    p = _palette(theme)
    cols = list(columns) if columns is not None else list(df.columns)
    ncol = len(cols)

    if aligns is None:
        aligns = ["left"] * ncol
    else:
        aligns = list(aligns) + ["left"] * (ncol - len(aligns))

    table_style = (
        f"width:100%;border-collapse:collapse;font-family:{_FONT};"
        f"font-size:{font_size}px;"
        + ("table-layout:fixed;" if col_widths else "")
    )
    parts: List[str] = [f'<table style="{table_style}">']

    # colgroup 定宽
    if col_widths:
        cg = "".join(f'<col style="width:{w}">' for w in col_widths)
        parts.append(f"<colgroup>{cg}</colgroup>")

    # 表头
    th_common = (
        f"background:{p['th_bg']};color:{p['th_fg']};padding:10px 14px;"
        f"border-bottom:2px solid {p['th_border']};font-weight:600;"
    )
    parts.append("<tr>")
    for c, a in zip(cols, aligns):
        parts.append(f'<th style="{th_common}text-align:{a}">{_esc(c)}</th>')
    parts.append("</tr>")

    # 数据行
    for i, (_, row) in enumerate(df.iterrows()):
        bg = None
        if row_bg is not None:
            bg = row_bg(i, row)
        if bg is None and zebra and i % 2 == 1:
            bg = p["row_alt"]
        tr_style = f'background:{bg};' if bg else ""
        parts.append(f'<tr style="{tr_style}">')
        for c, a in zip(cols, aligns):
            val = row[c]
            inner = None
            if cell_html is not None:
                inner = cell_html(c, val, row)
            if inner is None:
                inner = _esc(val)
            td_style = (
                f"color:{p['td_fg']};padding:8px 14px;"
                f"border-bottom:1px solid {p['td_border']};text-align:{a}"
            )
            parts.append(f'<td style="{td_style}">{inner}</td>')
        parts.append("</tr>")

    parts.append("</table>")
    html = "\n".join(parts)

    if render:
        import streamlit as st
        st.markdown(html, unsafe_allow_html=True)
    return html
