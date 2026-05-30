# -*- coding: utf-8 -*-
"""
关于页面 - 预留后续扩展入口
"""

import streamlit as st


def render():
    st.title("关于「量策」")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        ### 当前功能
        - **策略回测**：双均线、RSI、MACD、布林带四种策略，参数可调
        - 支持 A 股、美股、加密货币历史数据
        - 完整绩效指标：夏普比率、最大回撤、胜率

        ### 技术栈
        - Python + Streamlit + Backtrader
        - macOS 原生兼容
        """)

    with col2:
        st.markdown("""
        ### 计划中的功能
        - 多策略对比回测
        - 参数网格寻优
        - 选股策略（基本面 + 技术面筛选）
        - 持仓管理 / 记账
        - 基金定投模拟
        - 资产配置分析
        - 财务报表可视化
        """)

    st.divider()
    st.caption("v1.0 — 由 Marvis 搭建 | 运行在 macOS 本地")