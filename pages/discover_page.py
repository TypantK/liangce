# -*- coding: utf-8 -*-
"""
发现页 —— 用最新行情运行全部策略，扫描今日信号
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import backtrader as bt

from core.strategies import STRATEGY_REGISTRY
from core.data_fetcher import STOCK_POOL, get_stock_data
from core.engine import _make_logged_strategy


# ============================================================
#  辅助函数
# ============================================================

def _classify_symbol(code):
    """按代码后缀分类标的类型"""
    if code.endswith(('.SZ', '.SH')):
        return 'A股'
    elif 'USDT' in code:
        return '加密货币'
    else:
        return '美股'


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_data_cached(symbol_code):
    """获取最近 90 个交易日的数据（带 1 小时缓存）"""
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=150)).strftime('%Y-%m-%d')
    df = get_stock_data(symbol_code, start=start, end=end)
    if df is None or df.empty:
        return None
    # 只保留最近 90 行
    return df.tail(90)


@st.cache_data(ttl=3600, show_spinner=False)
def _scan_symbol_strategy(symbol_name, symbol_code, strategy_name):
    """
    对单个（标的, 策略）对运行回测，提取信号。
    返回 dict 或 None（数据/回测失败）。
    """
    data = _fetch_data_cached(symbol_code)
    if data is None:
        return None

    strat_info = STRATEGY_REGISTRY[strategy_name]
    default_params = {pn: prange[2] for pn, prange in strat_info["params"].items()}

    try:
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(100000)
        cerebro.broker.setcommission(commission=0.0005)
        cerebro.adddata(bt.feeds.PandasData(dataname=data))

        LoggedCls = _make_logged_strategy(strat_info["class"], strategy_name)
        cerebro.addstrategy(LoggedCls, **default_params)

        cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.02)
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

        results = cerebro.run()
        strat = results[0]

        trade_log = getattr(strat, '_trade_log', [])
        has_position = bool(strat.position)
        recent_price = float(data['close'].iloc[-1])
        now = data.index[-1]

        signal = "无信号"
        signal_date = ""
        signal_desc = ""

        if has_position:
            signal = "持有中"
            signal_desc = "当前持仓中"
            signal_date = now.strftime('%Y-%m-%d')
        elif trade_log:
            last_trade = trade_log[-1]
            bi = min(last_trade['baropen'], len(data) - 1)
            si = min(last_trade['barclose'], len(data) - 1)

            open_date = data.index[bi]
            close_date = data.index[si]

            if len(data) >= 3:
                last_3 = data.index[-3:]
            else:
                last_3 = data.index

            if close_date in last_3:
                signal = "卖出信号"
                signal_date = close_date.strftime('%Y-%m-%d')
                reason = last_trade.get('exit_reason', '策略卖出信号')
                signal_desc = f"卖出价 {last_trade['exit']:.2f}，原因：{reason}"
            elif open_date in last_3:
                signal = "买入信号"
                signal_date = open_date.strftime('%Y-%m-%d')
                reason = last_trade.get('entry_reason', '策略买入信号')
                signal_desc = f"买入价 {last_trade['entry']:.2f}，原因：{reason}"
            else:
                signal_desc = "最近一笔交易不在近 3 日内"

        return {
            'symbol': symbol_name,
            'strategy': strategy_name,
            'signal': signal,
            'signal_date': signal_date,
            'signal_desc': signal_desc,
            'recent_price': recent_price,
            'category': _classify_symbol(symbol_code),
        }
    except Exception as e:
        return {
            'symbol': symbol_name,
            'strategy': strategy_name,
            'signal': '扫描失败',
            'signal_date': '',
            'signal_desc': str(e)[:120],
            'recent_price': 0,
            'category': _classify_symbol(symbol_code),
        }


# ============================================================
#  UI 组件
# ============================================================

def _render_card(result, theme):
    """渲染单张信号卡片"""
    signal = result['signal']
    if signal == '买入信号':
        border = '#2e7d32'
        bg = '#1b2e1b' if theme == 'dark' else '#e8f5e9'
        tag_bg = '#2e7d32'
        tag_text = '买入机会'
        tag_color = '#ffffff'
        text_color = '#a5d6a7' if theme == 'dark' else '#1b5e20'
        desc_color = '#81c784' if theme == 'dark' else '#2e7d32'
    elif signal == '卖出信号':
        border = '#c62828'
        bg = '#2e1b1b' if theme == 'dark' else '#ffebee'
        tag_bg = '#c62828'
        tag_text = '卖出信号'
        tag_color = '#ffffff'
        text_color = '#ef9a9a' if theme == 'dark' else '#b71c1c'
        desc_color = '#e57373' if theme == 'dark' else '#c62828'
    elif signal == '持有中':
        border = '#f9a825'
        bg = '#2e2a1b' if theme == 'dark' else '#fff8e1'
        tag_bg = '#f9a825'
        tag_text = '当前持有'
        tag_color = '#1a1a1a'
        text_color = '#ffe082' if theme == 'dark' else '#795548'
        desc_color = '#ffd54f' if theme == 'dark' else '#6d4c41'
    else:
        return None  # 无信号的卡片不渲染

    price_str = f"{result['recent_price']:.2f}" if result['recent_price'] else "N/A"

    return f"""
    <div style="
        background:{bg};
        border-left:4px solid {border};
        border-radius:8px;
        padding:12px 16px;
        margin:6px 0;
        font-family:'PingFang SC','Microsoft YaHei',sans-serif;
    ">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <span style="font-weight:700;font-size:15px;color:{text_color}">
                {result['symbol']}
            </span>
            <span style="
                background:{tag_bg};
                color:{tag_color};
                padding:2px 10px;
                border-radius:4px;
                font-size:12px;
                font-weight:600;
            ">{tag_text}</span>
        </div>
        <div style="font-size:13px;color:{desc_color};margin-bottom:4px">
            {result['signal_desc']}
        </div>
        <div style="display:flex;justify-content:space-between;font-size:11px;color:{'#6b7094' if theme == 'dark' else '#9e9e9e'}">
            <span>策略：{result['strategy']}</span>
            <span>价格：{price_str} ｜ 信号日：{result['signal_date']}</span>
        </div>
    </div>"""


# ============================================================
#  render()
# ============================================================
def render():
    theme = st.session_state.get("_theme_mode", "dark")

    # ========== 标题 ==========
    st.title("发现")
    st.caption("用最新行情运行全部策略，扫描今日信号")

    # ========== 筛选区 ==========
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        type_options = ["全部", "A股", "美股", "加密货币"]
        selected_types = st.multiselect(
            "标的类型", type_options, default=["全部"],
            help="筛选要扫描的标的类型"
        )
    with col2:
        signal_options = ["全部", "仅买入", "仅卖出"]
        selected_signal = st.selectbox(
            "信号方向", signal_options, index=0,
            help="按信号方向过滤结果"
        )
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        scan_btn = st.button("开始扫描", type="primary", use_container_width=True)

    # ========== 扫描逻辑 ==========
    if not scan_btn:
        if theme == "light":
            st.markdown("""
            <style>
            [data-testid="stAppViewContainer"], [data-testid="stHeader"],
            .stApp { background: #ffffff !important; }
            [data-testid="stSidebar"] { background: #f8f9fa !important; }
            h1, h2, h3, h4, p, label, .stMarkdown, .stCaption { color: #1f2937 !important; }
            .stSelectbox label, .stMultiselect label { color: #1f2937 !important; }
            section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2,
            section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] p,
            section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] .stMarkdown,
            section[data-testid="stSidebar"] .stCaption { color: #1f2937 !important; }
            </style>
            """, unsafe_allow_html=True)
        st.info("点击「开始扫描」运行全部策略")
        return

    # 确定要扫描的标的
    pool_items = []
    for name, code in STOCK_POOL.items():
        cat = _classify_symbol(code)
        if "全部" in selected_types or cat in selected_types:
            pool_items.append((name, code, cat))

    if not pool_items:
        st.warning("没有符合条件的标的")
        return

    strategies = list(STRATEGY_REGISTRY.keys())

    # ========== 进度条 ==========
    total_tasks = len(pool_items) * len(strategies)
    progress_bar = st.progress(0)
    status_text = st.empty()

    all_results = []
    failed_symbols = []

    for i, (sym_name, sym_code, sym_cat) in enumerate(pool_items):
        has_data = _fetch_data_cached(sym_code)
        if has_data is None:
            failed_symbols.append(sym_name)
            progress_bar.progress((i * len(strategies) + len(strategies)) / total_tasks)
            continue

        for j, strat_name in enumerate(strategies):
            task_idx = i * len(strategies) + j + 1
            status_text.text(f"扫描中... {sym_name} × {strat_name} ({task_idx}/{total_tasks})")
            progress_bar.progress(task_idx / total_tasks)

            res = _scan_symbol_strategy(sym_name, sym_code, strat_name)
            if res is not None:
                all_results.append(res)

    progress_bar.empty()
    status_text.empty()

    # ========== 过滤信号 ==========
    if selected_signal == "仅买入":
        signals_of_interest = ["买入信号", "持有中"]
    elif selected_signal == "仅卖出":
        signals_of_interest = ["卖出信号"]
    else:
        signals_of_interest = ["买入信号", "卖出信号", "持有中"]

    filtered = [r for r in all_results if r['signal'] in signals_of_interest]

    # ========== 结果展示 ==========
    st.markdown("---")
    st.subheader(f"扫描结果（共 {len(filtered)} 条信号）")

    if not filtered:
        st.info("今日暂无符合条件的信号")
        if failed_symbols:
            st.caption(f"数据获取失败: {', '.join(failed_symbols)}")
        return

    # 分组
    buy_signals = [r for r in filtered if r['signal'] == '买入信号']
    sell_signals = [r for r in filtered if r['signal'] == '卖出信号']
    hold_signals = [r for r in filtered if r['signal'] == '持有中']
    fail_signals = [r for r in all_results if r['signal'] == '扫描失败']

    # 买入信号区
    if buy_signals:
        st.markdown("### 📈 买入机会")
        st.caption(f"共 {len(buy_signals)} 条")
        cols = st.columns(2)
        for idx, r in enumerate(buy_signals):
            with cols[idx % 2]:
                st.markdown(_render_card(r, theme), unsafe_allow_html=True)

    # 卖出信号区
    if sell_signals:
        st.markdown("### 📉 卖出信号")
        st.caption(f"共 {len(sell_signals)} 条")
        cols = st.columns(2)
        for idx, r in enumerate(sell_signals):
            with cols[idx % 2]:
                st.markdown(_render_card(r, theme), unsafe_allow_html=True)

    # 持有中
    if hold_signals:
        st.markdown("### 📊 当前持有")
        st.caption(f"共 {len(hold_signals)} 条")
        cols = st.columns(2)
        for idx, r in enumerate(hold_signals):
            with cols[idx % 2]:
                st.markdown(_render_card(r, theme), unsafe_allow_html=True)

    # 扫描失败
    if fail_signals:
        with st.expander(f"扫描失败（共 {len(fail_signals)} 条）"):
            fail_df = pd.DataFrame([
                {"标的": r['symbol'], "策略": r['strategy'], "错误": r['signal_desc']}
                for r in fail_signals
            ])
            st.dataframe(fail_df, use_container_width=True, hide_index=True)

    if failed_symbols:
        st.caption(f"数据获取失败: {', '.join(failed_symbols)}")
