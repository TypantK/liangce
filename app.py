# -*- coding: utf-8 -*-
"""
「量策」个人理财工具箱 —— Web 主入口
启动命令: python -m streamlit run app.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import logging

# 启动门禁：尽早挂载全局错误收集器（WARNING/ERROR 自动落盘 + 归档 errors.db），
# 这样 Streamlit 热重载或页面模块 import 之前产生的告警也能被捕获。
try:
    from utils.error_collector import install_error_collector
    install_error_collector()
except Exception:  # noqa: BLE001
    # 收集器自身失败绝不能影响主流程
    logging.getLogger(__name__).warning("错误收集器挂载失败（不影响主流程）", exc_info=False)

st.set_page_config(page_title="量策", page_icon="📊", layout="wide")

# ====================== 页面路由 ======================
PAGES = {
    "发现": "pages.discover_page",
    "板块预测": "pages.sector_prediction",
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
    st.caption("v1.0 ｜ 本地")

# 渲染页面
module_name = PAGES[page]
__import__(module_name)
page_module = sys.modules[module_name]
page_module.render()