# -*- coding: utf-8 -*-
"""
策略回测页面 v2 — Plotly 交互式图表 + 大白话策略解释
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import streamlit as st
import pandas as pd
from core.strategies import STRATEGY_REGISTRY
from core.data_fetcher import STOCK_POOL, get_stock_data, generate_demo_data
from core.engine import run_backtest
from utils.chart import plot_backtest, render_strategy_card


def render():
    st.title("策略回测")

    # ========== 控制面板 ==========
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        strategy_name = st.selectbox("选择策略", list(STRATEGY_REGISTRY.keys()), key="s")
    with c2:
        data_source = st.selectbox("数据源", ["演示数据"] + list(STOCK_POOL.keys()), key="d")
    with c3:
        chart_mode = st.radio("图表类型", ["K线图", "折线图"], horizontal=True, key="cm")

    initial_cash = st.number_input("初始资金（元）", 10000, 10000000, 100000, 10000, key="cash")

    strat_info = STRATEGY_REGISTRY[strategy_name]
    st.caption(strat_info["desc"])

    params = {}
    labels = strat_info.get("param_labels", {})
    pcols = st.columns(len(strat_info["params"]))
    for i, (pn, (pmin, pmax, pdef)) in enumerate(strat_info["params"].items()):
        with pcols[i]:
            step = 0.1 if isinstance(pdef, float) else 1
            label = labels.get(pn, pn)
            params[pn] = st.slider(label, pmin, pmax, pdef, step, key=f"p_{pn}")

    # ========== 回测 ==========
    if st.button("开始回测", type="primary", use_container_width=True):
        st.session_state.zoom_range = None
        with st.spinner("获取数据..."):
            if data_source == "演示数据":
                data = generate_demo_data(300)
            else:
                data = get_stock_data(STOCK_POOL[data_source])
                if data is None or data.empty:
                    st.error(f"获取 {data_source} 数据失败，请检查网络")
                    return

        with st.spinner(f"运行「{strategy_name}」..."):
            result = run_backtest(
                data, strat_info["class"], params,
                initial_cash=initial_cash,
                strategy_name=strategy_name,
            )

        st.session_state.backtest_result = result

    # ========== 渲染结果 ==========
    if "backtest_result" not in st.session_state or st.session_state.backtest_result is None:
        st.info("点击「开始回测」查看结果")
        return

    result = st.session_state.backtest_result

    st.divider()

    # ===== 指标面板 =====
    m = result["metrics"]
    mn1, mn2, mn3 = st.columns(3)
    mn1.metric("总收益率", m["总收益率"], delta=m.get("超额收益", ""))
    mn2.metric("最大回撤", m["最大回撤"])
    mn3.metric("夏普比率", m["夏普比率"])
    mn4, mn5, mn6 = st.columns(3)
    mn4.metric("胜率", m["胜率"])
    mn5.metric("交易次数", m["交易次数"])
    mn6.metric("最终资金", m["最终资金"])

    st.divider()

    # ===== 策略大白话解释（可折叠） =====
    explanation = result.get("explanation", {})
    if explanation:
        with st.expander(f"「{strategy_name}」大白话解释", expanded=False):
            st.markdown(render_strategy_card(strategy_name, explanation))

    # ===== 纵轴范围滑块 =====
    import numpy as np
    full_high = float(result["data"]["high"].max())
    full_low = float(result["data"]["low"].min())
    pad = (full_high - full_low) * 0.15
    price_lo, price_hi = st.slider(
        "纵轴（价格）范围",
        min_value=float(int(full_low - pad)),
        max_value=float(int(full_high + pad) + 1),
        value=(full_low, full_high),
        step=0.5,
        key="price_slider",
    )

    # ===== 重置缩放按钮 =====
    xaxis_range = st.session_state.get("zoom_range", None)
    if xaxis_range is not None:
        zc1, zc2 = st.columns([1, 5])
        with zc1:
            if st.button("重置缩放", key="reset_zoom"):
                st.session_state.zoom_range = None
                st.rerun()

    # ===== Plotly 交互式图表 =====
    fig = plot_backtest(
        result["data"],
        result["strategy_name"],
        chart_mode=chart_mode,
        buy_points=result["buy_points"],
        sell_points=result["sell_points"],
        trades=result["trades"],
        yaxis_range=(price_lo, price_hi),
        xaxis_range=xaxis_range,
    )
    chart_event = st.plotly_chart(
        fig, use_container_width=True,
        key="kline_chart",
        on_select="rerun",
        selection_mode=["points"],
        config={
            'displayModeBar': True,
            'modeBarButtonsToRemove': ['lasso2d'],
            'displaylogo': False,
            'doubleClick': False,
        },
    )

    st.caption("提示：点击 K 线实体上的圆点 → 放大到该日前后约一个月；工具栏「框选」可精确选择多根 K 线区间")

    # ===== 处理点击/框选缩放 =====
    if chart_event is not None:
        if hasattr(chart_event, 'selection') and chart_event.selection and chart_event.selection.get("points"):
            points = chart_event.selection["points"]
            dates = sorted(set(pt.get("x") for pt in points if pt.get("x")))
            if not dates:
                st.rerun()
            dti = pd.to_datetime(result["data"].index)
            if len(dates) == 1:
                # 单根 K 线点击 → 放大到 ±15 个交易日（约一个月）
                target = pd.Timestamp(dates[0])
                pos = np.abs((dti - target).days).argmin()
                start = max(0, pos - 15)
                end = min(len(dti) - 1, pos + 15)
            else:
                # 多根 K 线框选 → 精确范围
                t0, t1 = pd.Timestamp(dates[0]), pd.Timestamp(dates[-1])
                start = max(0, np.abs((dti - t0).days).argmin())
                end = min(len(dti) - 1, np.abs((dti - t1).days).argmin())
            st.session_state.zoom_range = (
                dti[start].strftime('%Y-%m-%d'),
                dti[end].strftime('%Y-%m-%d'),
            )
            st.rerun()

    # ===== 交易明细 =====
    if result["trades"]:
        st.subheader("交易明细")
        trade_df = pd.DataFrame(result["trades"])
        display_cols = [c for c in ["买入时间", "买入价", "买入原因", "卖出时间", "卖出价", "卖出原因", "盈亏"] if c in trade_df.columns]
        st.dataframe(
            trade_df[display_cols],
            use_container_width=True, hide_index=True,
            column_config={
                "买入价": st.column_config.NumberColumn(format="¥%.2f"),
                "卖出价": st.column_config.NumberColumn(format="¥%.2f"),
            }
        )
    else:
        st.info("本次回测期间无交易记录")
