# -*- coding: utf-8 -*-
"""
最小复现 app：复制 discover_page 的扫描状态机与渲染逻辑，但用内存 demo 数据避开网络。

供 core/scan_smoke.py 使用：模拟「空闲」与「扫描完成+结果展示」帧，
断言单帧内 widget 不重复。

注意：本文件不能删除，是扫描流程「单帧无重复」门禁的输入。
"""
import os
import sys
import time
import streamlit as st
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from core import data_fetcher
from core.data_fetcher import generate_demo_data

data_fetcher.get_stock_data = lambda code, **kw: generate_demo_data(120)
data_fetcher.get_fund_nav = lambda code, **kw: None

from pages import discover_page as dp

SCAN_KEYS = [
    '_ds_running', '_ds_results', '_ds_failed', '_ds_pool', '_ds_strategies',
    '_ds_cursor', '_ds_total', '_ds_scan_id', '_ds_type_filter', '_ds_signal_filter',
]
for k in SCAN_KEYS:
    if k not in st.session_state:
        st.session_state[k] = None
if st.session_state._ds_running is None:
    st.session_state._ds_running = False
if st.session_state._ds_results is None:
    st.session_state._ds_results = []
if st.session_state._ds_failed is None:
    st.session_state._ds_failed = []
if st.session_state._ds_cursor is None:
    st.session_state._ds_cursor = 0


def _start_scan(pool_items, strategies, selected_types, selected_signal):
    import uuid
    st.session_state._ds_running = True
    st.session_state._ds_results = []
    st.session_state._ds_failed = []
    st.session_state._ds_pool = pool_items
    st.session_state._ds_strategies = strategies
    st.session_state._ds_cursor = 0
    st.session_state._ds_total = len(pool_items)
    st.session_state._ds_scan_id = uuid.uuid4().hex[:8]
    st.session_state._ds_type_filter = selected_types
    st.session_state._ds_signal_filter = selected_signal


def _continue_scan():
    cursor = st.session_state._ds_cursor
    pool = st.session_state._ds_pool
    strategies = st.session_state._ds_strategies
    total = st.session_state._ds_total
    if cursor >= total:
        st.session_state._ds_running = False
        return
    sym_name, sym_code, sym_cat = pool[cursor]
    for strat_name in strategies:
        try:
            res = dp._scan_symbol_strategy(sym_name, sym_code, strat_name, sym_cat)
            if res is not None:
                st.session_state._ds_results.append(res)
            else:
                st.session_state._ds_failed.append(sym_name)
        except Exception:
            st.session_state._ds_failed.append(sym_name)
    st.session_state._ds_cursor = cursor + 1
    if st.session_state._ds_cursor < total:
        st.progress(st.session_state._ds_cursor / total,
                    text=f"扫描中... {st.session_state._ds_cursor}/{total}")
        st.rerun()
    else:
        st.session_state._ds_running = False


def render():
    st.title("发现（最小复现）")
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        market_options = ["全部市场", "A股", "美股", "加密货币", "板块指数", "基金"]
        selected_market = st.selectbox("市场", market_options, index=0,
                                      disabled=st.session_state._ds_running)
    with col2:
        signal_options = ["全部", "仅买入", "仅卖出"]
        selected_signal = st.selectbox("信号方向", signal_options, index=0,
                                       disabled=st.session_state._ds_running)
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        scan_btn = st.button(
            "扫描中..." if st.session_state._ds_running else "开始扫描",
            type="primary", use_container_width=True,
            disabled=st.session_state._ds_running,
        )

    if st.session_state._ds_running:
        _continue_scan()
        if st.session_state._ds_running:
            return

    if scan_btn:
        pool_items = [("TEST", "TEST.SH", "A股")] * 3
        strategies = list(dp.STRATEGY_REGISTRY.keys())
        _start_scan(pool_items, strategies, "全部市场", "全部")
        st.rerun()

    if st.session_state._ds_results:
        st.write(f"结果：{len(st.session_state._ds_results)} 条")
    else:
        st.info("点击「开始扫描」运行全部策略")


render()
