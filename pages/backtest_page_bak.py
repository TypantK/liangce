# -*- coding: utf-8 -*-
"""
策略回测页面 — K线/折线双模式
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import streamlit as st
import pandas as pd
from core.strategies import STRATEGY_REGISTRY
from core.data_fetcher import STOCK_POOL, get_stock_data, generate_demo_data
from core.engine import run_backtest
from utils.chart import plot_backtest


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
    pcols = st.columns(len(strat_info["params"]))
    for i, (pn, (pmin, pmax, pdef)) in enumerate(strat_info["params"].items()):
        with pcols[i]:
            step = 0.1 if isinstance(pdef, float) else 1
            params[pn] = st.slider(pn, pmin, pmax, pdef, step, key=f"p_{pn}")

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
            result = run_backtest(data, strat_info["class"], params, initial_cash)

        st.divider()

        m = result["metrics"]
        mn1, mn2, mn3, mn4, mn5, mn6 = st.columns(6)
        mn1.metric("总收益率", m["总收益率"], delta=m.get("超额收益", ""))
        mn2.metric("最大回撤", m["最大回撤"])
        mn3.metric("夏普比率", m["夏普比率"])
        mn4.metric("胜率", m["胜率"])
        mn5.metric("交易次数", m["交易次数"])
        mn6.metric("最终资金", m["最终资金"])

        st.divider()

        img_b64 = plot_backtest(
            data, strategy_name,
            chart_mode=chart_mode,
            buy_points=result["buy_points"],
            sell_points=result["sell_points"],
        )
        st.image(f"data:image/png;base64,{img_b64}", use_container_width=True)

        if result["trades"]:
            st.subheader("交易明细")
            st.dataframe(pd.DataFrame(result["trades"]),
                         use_container_width=True, hide_index=True)
        else:
            st.info("本次回测期间无交易记录")