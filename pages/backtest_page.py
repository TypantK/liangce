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

        # ===== Plotly 交互式图表 =====
        fig = plot_backtest(
            result["data"],
            strategy_name,
            chart_mode=chart_mode,
            buy_points=result["buy_points"],
            sell_points=result["sell_points"],
            trades=result["trades"],
            yaxis_range=(price_lo, price_hi),
        )
        st.plotly_chart(fig, use_container_width=True, config={
            'displayModeBar': True,
            'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
            'displaylogo': False,
        })

        # ===== 交易明细 =====
        if result["trades"]:
            st.subheader("交易明细")
            trade_df = pd.DataFrame(result["trades"])
            # 只展示关键列
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