# -*- coding: utf-8 -*-
"""
参数优化页面 — 双参数网格搜索 + 热力图
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

from core.data_fetcher import STOCK_POOL, get_stock_data
from core.strategies import STRATEGY_REGISTRY
from core.optimizer import grid_search, METRIC_LABELS

# ---- 深色主题配色（与 chart.py 对齐）----
BG       = '#131520'
GRID_C   = '#1f2335'
FG       = '#c8cce0'
FG_SOFT  = '#6b7094'
LINE_C   = '#2a2d3e'
CARD_BG  = '#1a1d2e'
CN_FONT  = 'PingFang SC, Microsoft YaHei, SimHei, Arial Unicode MS, sans-serif'

METRIC_OPTIONS = ["sharpe", "annualized_return", "win_rate"]


def _build_heatmap(result, theme="dark"):
    """用 Plotly 热力图展示网格搜索结果。"""
    matrix = np.array(result["matrix"])
    p1_vals = result["p1_vals"]
    p2_vals = result["p2_vals"]

    if theme == "light":
        _bg, _fg, _fg_soft = '#ffffff', '#1f2937', '#6b7280'
        colorscale = 'RdYlGn'
    else:
        _bg, _fg, _fg_soft = BG, FG, FG_SOFT
        colorscale = 'Viridis'

    # 用文本标注保留高亮数值
    zmax = np.nanmax(matrix)
    zmin = np.nanmin(matrix)

    fig = go.Figure(data=go.Heatmap(
        z=matrix,
        x=[str(v) for v in p1_vals],
        y=[str(v) for v in p2_vals],
        colorscale=colorscale,
        zmin=zmin,
        zmax=zmax,
        hovertemplate=(
            f"{result['param1']}: %{{x}}<br>"
            f"{result['param2']}: %{{y}}<br>"
            f"{result['best_metric_label']}: %{{z:.3f}}<extra></extra>"
        ),
        colorbar=dict(
            title=result["best_metric_label"],
            title_font=dict(color=_fg_soft, family=CN_FONT),
            tickfont=dict(color=_fg_soft),
        ),
    ))

    fig.update_layout(
        template='plotly_dark' if theme == "dark" else 'plotly_white',
        paper_bgcolor=_bg,
        plot_bgcolor=_bg,
        font=dict(color=_fg, family=CN_FONT),
        title=dict(
            text=f"<b>{result['strategy_name']}</b> — {result['param1']} × {result['param2']}",
            font=dict(color=_fg, size=17, family=CN_FONT),
            x=0.01,
            xanchor='left',
        ),
        xaxis=dict(
            title=result['param1'],
            title_font=dict(color=_fg_soft, family=CN_FONT),
            tickfont=dict(color=_fg_soft),
            gridcolor=GRID_C if theme == "dark" else '#e5e7eb',
        ),
        yaxis=dict(
            title=result['param2'],
            title_font=dict(color=_fg_soft, family=CN_FONT),
            tickfont=dict(color=_fg_soft),
            gridcolor=GRID_C if theme == "dark" else '#e5e7eb',
        ),
        height=550,
        margin=dict(l=80, r=50, t=60, b=80),
    )

    return fig


def render():
    st.title("参数优化")

    # ========== 侧边栏：主题 ==========
    theme_label = st.sidebar.radio("主题", ["夜间", "白天"], key="opt_theme")
    theme = "dark" if theme_label == "夜间" else "light"

    # ========== 股票选择 ==========
    stock_names = list(STOCK_POOL.keys())
    stock_name = st.sidebar.selectbox("股票标的", stock_names, key="opt_stock")
    stock_code = STOCK_POOL[stock_name]

    # ========== 策略选择 ==========
    strategy_names = list(STRATEGY_REGISTRY.keys())
    strategy_name = st.sidebar.selectbox("选择策略", strategy_names, key="opt_strat")
    strat_info = STRATEGY_REGISTRY[strategy_name]

    # ========== 选择 2 个优化参数 ==========
    param_names = list(strat_info["params"].keys())
    param_labels = strat_info.get("param_labels", {})

    col_a, col_b = st.sidebar.columns(2)
    with col_a:
        p1_name = st.selectbox("参数一", param_names, key="opt_p1",
                               format_func=lambda x: param_labels.get(x, x))
    with col_b:
        remaining = [p for p in param_names if p != p1_name]
        p2_default = remaining[0] if remaining else param_names[-1]
        p2_name = st.selectbox("参数二", remaining, key="opt_p2",
                               format_func=lambda x: param_labels.get(x, x),
                               index=remaining.index(p2_default) if p2_default in remaining else 0)

    # ========== 参数范围滑块 ==========
    p1_min, p1_max, p1_def = strat_info["params"][p1_name]
    p2_min, p2_max, p2_def = strat_info["params"][p2_name]

    p1_step = 0.05 if p1_name == "position_pct" else (0.1 if isinstance(p1_def, float) else 1)
    p2_step = 0.05 if p2_name == "position_pct" else (0.1 if isinstance(p2_def, float) else 1)

    st.sidebar.markdown("---")
    st.sidebar.caption(param_labels.get(p1_name, p1_name))
    p1_range = st.sidebar.slider(
        "范围", p1_min, p1_max, (p1_min, p1_max), p1_step, key="opt_r1")

    st.sidebar.caption(param_labels.get(p2_name, p2_name))
    p2_range = st.sidebar.slider(
        "范围", p2_min, p2_max, (p2_min, p2_max), p2_step, key="opt_r2")

    # ========== 优化指标 ==========
    metric_key = st.sidebar.selectbox(
        "优化指标", METRIC_OPTIONS, key="opt_metric",
        format_func=lambda x: METRIC_LABELS.get(x, x),
        index=0,
    )

    # ========== 日期 & 资金 ==========
    st.sidebar.markdown("---")
    c_s, c_e = st.sidebar.columns(2)
    with c_s:
        backtest_start = st.date_input(
            "起始", datetime.now() - timedelta(days=365),
            key="opt_bs")
    with c_e:
        backtest_end = st.date_input(
            "结束", datetime.now(), key="opt_be")

    initial_cash = st.sidebar.number_input("初始资金", 10000, 10000000, 100000, 10000, key="opt_cash")

    # ========== 开始优化 ==========
    if st.sidebar.button("开始优化", type="primary", use_container_width=True, key="opt_btn"):
        with st.spinner(f"获取 {stock_name} 数据..."):
            data = get_stock_data(stock_code)
            if data is None or data.empty:
                st.error(f"获取 {stock_name} 数据失败")
                return

            start_dt = pd.Timestamp(backtest_start)
            end_dt = pd.Timestamp(backtest_end) + pd.Timedelta(days=1)
            data = data[(data.index >= start_dt) & (data.index < end_dt)]
            if data.empty:
                st.warning(f"日期范围 {backtest_start} ~ {backtest_end} 内无数据")
                return

        # 其他参数用默认值
        base_params = {}
        for pn, (pmin, pmax, pdef) in strat_info["params"].items():
            if pn not in (p1_name, p2_name):
                base_params[pn] = pdef

        # 进度条
        progress_bar = st.progress(0)
        status_text = st.empty()

        def _progress(i, total):
            progress_bar.progress(i / total)
            status_text.text(f"正在回测... {i}/{total}")

        with st.spinner(f"网格搜索「{strategy_name}」参数组合..."):
            result = grid_search(
                data, strat_info["class"], base_params,
                p1_name, p1_range[0], p1_range[1], p1_def,
                p2_name, p2_range[0], p2_range[1], p2_def,
                metric=metric_key,
                initial_cash=initial_cash,
                strategy_name=strategy_name,
                progress_callback=_progress,
            )

        progress_bar.empty()
        status_text.empty()

        st.session_state.opt_result = result
        st.session_state.opt_data = data

    if "opt_result" not in st.session_state or st.session_state.opt_result is None:
        st.info("配置参数后点击「开始优化」")
        return

    result = st.session_state.opt_result
    st.divider()

    # ---- 热力图 ----
    fig = _build_heatmap(result, theme=theme)
    st.plotly_chart(fig, use_container_width=True)

    # ---- 最优参数 ----
    st.subheader("最优参数组合")

    # 指标数值禁止截断
    st.markdown("""
    <style>
    [data-testid="stMetricValue"] {
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
    }
    </style>
    """, unsafe_allow_html=True)
    bp = result["best_params"]
    bm = result["best_metric"]
    bl = result["best_metric_label"]

    if bp:
        cols = st.columns(len(bp) + 1)
        for ci, (k, v) in enumerate(bp.items()):
            label = param_labels.get(k, k)
            cols[ci].metric(label, str(v))
        cols[-1].metric(bl, f"{bm:.3f}" if bm is not None else "N/A")
    else:
        st.warning("未找到有效参数组合（所有回测结果均为无效值）")

    # ---- 全部组合数据表 ----
    with st.expander("全部组合数据"):
        p1_vals = result["p1_vals"]
        p2_vals = result["p2_vals"]
        matrix = np.array(result["matrix"])

        rows = []
        for i, v2 in enumerate(p2_vals):
            for j, v1 in enumerate(p1_vals):
                rows.append({
                    result["param1"]: v1,
                    result["param2"]: v2,
                    bl: round(matrix[i, j], 3) if not np.isnan(matrix[i, j]) else None,
                })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
