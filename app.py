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

# 运行留痕：每次 app 启动 / 页面切换都在 data/run_logs/ 留一条记录
try:
    from utils import run_logger
    _RUN_LOG_OK = True
except Exception:  # noqa: BLE001
    _RUN_LOG_OK = False

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
if _RUN_LOG_OK:
    run_logger.log_run("app", f"open:{module_name}", ok=True, detail="用户打开页面")
try:
    __import__(module_name)
    page_module = sys.modules[module_name]
    page_module.render()
except Exception as e:  # noqa: BLE001
    # 页面 import 或渲染期异常（如顶层 NameError）极少概率未被 streamlit 走 logging，
    # 这里主动以 ERROR 级别记录，确保被错误收集器归档到 errors.db / error_logs。
    logging.getLogger(__name__).error(
        f"页面 {module_name} 加载/渲染失败: {type(e).__name__}: {e}", exc_info=True)
    if _RUN_LOG_OK:
        run_logger.log_run("app", f"open:{module_name}", ok=False,
                           detail=f"{type(e).__name__}: {e}", exc=e)
    st.exception(e)