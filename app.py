# -*- coding: utf-8 -*-
"""
「量策」个人理财工具箱 —— Web 主入口
启动命令: /usr/bin/python3 -m streamlit run app.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd

st.set_page_config(page_title="量策", page_icon="📊", layout="wide")

# ====================== 页面路由 ======================
PAGES = {
    "策略回测": "pages.backtest_page",
    "参数优化": "pages.optimize_page",
    "关于": "pages.about_page",
}

# 侧边栏导航
with st.sidebar:
    st.markdown("## 量策")
    st.markdown("*个人量化理财工具箱*")
    st.divider()
    page = st.radio("导航", list(PAGES.keys()), label_visibility="collapsed")
    st.divider()
    st.caption("v1.0 ｜ macOS")

# 渲染页面
module_name = PAGES[page]
__import__(module_name)
page_module = sys.modules[module_name]
page_module.render()