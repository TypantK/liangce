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
from core.data_fetcher import STOCK_POOL, get_stock_data, get_fund_nav, fund_nav_to_ohlcv
from core.engine import _make_logged_strategy
from core import insight as insight_module
from utils import run_logger


# ============================================================
#  每日复盘（借鉴 skill-market-daily-review 的章节结构，数据走自有免费源）
# ============================================================

@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_daily_review_cached():
    """获取每日复盘数据（30 分钟缓存，避免扫描 rerun 时反复联网）。"""
    from core.daily_review import build_daily_review
    return build_daily_review()


def _fmt_pct(v):
    if v is None:
        return "—"
    color = "#e05252" if v > 0 else ("#2e9e5b" if v < 0 else "#9e9e9e")
    sign = "+" if v > 0 else ""
    return f"<span style='color:{color};font-weight:600'>{sign}{v:.2f}%</span>"


def _fmt_num(v, unit=""):
    return "—" if v is None else f"{v:,.0f}{unit}"


def _render_daily_review(theme):
    """渲染每日复盘面板：指数概览 / 市场宽度 / 行业热点 / 资金面。

    原则（借鉴 daily-review）：只陈述事实、不做买卖建议；取不到的数据显示「—」，
    绝不估算编造；顶部标注 T+1 数据口径与免责声明。
    """
    with st.expander("📋 今日市场复盘（点击展开 / 收起）", expanded=False):
        review = _fetch_daily_review_cached()

        as_of = review.get("as_of", "")
        after_close = review.get("is_after_close", False)
        stage = "盘后收盘数据" if after_close else "盘中/盘前，数据以最近收盘为准"
        st.caption(
            f"数据对应交易日：约 {as_of}（{stage}）｜ 生成于 {review.get('generated_at','')}"
            "　—　本页仅客观陈述市场数据，不构成任何投资建议（只述不荐）"
        )

        # ---- 交付前校验门禁（借鉴 daily-review 的 validate_report 思路）----
        _val = review.get("_validation")
        if isinstance(_val, dict):
            if _val.get("ok"):
                if _val.get("warnings"):
                    st.caption("⚠️ 复盘数据已就绪，部分章节口径提示：" +
                               "；".join(_val["warnings"]))
            else:
                st.error("复盘数据校验未通过：" + "；".join(_val.get("errors", [])))
        elif _val is not None:
            st.caption("复盘数据校验结果不可用")

        # ---- 1. 指数概览 ----
        st.markdown("**① 指数概览**")
        idx = review.get("indices", {})
        idx_list = idx.get("list", [])
        if idx_list:
            cols = st.columns(len(idx_list))
            for c, it in zip(cols, idx_list):
                price = "—" if it["price"] is None else f"{it['price']:.2f}"
                c.markdown(
                    f"<div style='text-align:center'><div style='font-size:12px;color:#9e9e9e'>{it['name']}</div>"
                    f"<div style='font-size:18px;font-weight:700'>{price}</div>"
                    f"<div style='font-size:13px'>{_fmt_pct(it['pct'])}</div></div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("指数数据暂不可用")

        # ---- 2. 市场宽度 ----
        st.markdown("**② 市场宽度**")
        b = review.get("breadth", {})
        bc = st.columns(5)
        bc[0].metric("上涨家数", _fmt_num(b.get("up")))
        bc[1].metric("下跌家数", _fmt_num(b.get("down")))
        bc[2].metric("平盘家数", _fmt_num(b.get("flat")))
        bc[3].metric("涨停数", _fmt_num(b.get("limit_up")))
        bc[4].metric("跌停数", _fmt_num(b.get("limit_down")))

        # ---- 3. 行业热点 ----
        st.markdown("**③ 行业热点**")
        s = review.get("sectors", {})
        sc1, sc2 = st.columns(2)
        with sc1:
            st.caption("涨幅居前")
            top = s.get("top", [])
            if top:
                for r in top:
                    st.markdown(
                        f"{r['name']}　{_fmt_pct(_safe_pct(r.get('pct')))}",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("暂不可用")
        with sc2:
            st.caption("跌幅居前")
            bottom = s.get("bottom", [])
            if bottom:
                for r in bottom:
                    st.markdown(
                        f"{r['name']}　{_fmt_pct(_safe_pct(r.get('pct')))}",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("暂不可用")

        # ---- 4. 资金面 ----
        st.markdown("**④ 资金面**")
        cap = review.get("capital", {})
        north = cap.get("north")
        st.markdown(
            f"北向资金净流入（参考）：**{'—' if north is None else f'{north:,.2f} 亿元'}**",
        )
        st.caption(cap.get("north_note", ""))
        inflow = cap.get("main_inflow", [])
        if inflow:
            st.caption("行业主力净流入居前（万元）")
            df = pd.DataFrame(inflow)
            if not df.empty and "inflow" in df.columns:
                df["inflow"] = df["inflow"].map(lambda x: f"{x:,.0f}")
                df.columns = ["行业", "主力净流入"]
                st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.caption("资金流数据暂不可用")


def _safe_pct(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ============================================================
#  辅助函数
# ============================================================

# 资产大类 → 市场筛选下拉项
ASSET_CATEGORY = {
    'A股': 'A股',
    '美股': '美股',
    '加密货币': '加密货币',
    '板块': '板块指数',
    '基金': '基金',
}


def _classify_symbol(code, asset_type=None):
    """按资产类型分类标的（优先使用 pool 中声明的类型，避免代码后缀误判）。

    注意：本函数在模块顶层 _DISCOVER_STOCK_ITEMS 之前定义，避免 import 时 NameError。
    """
    if asset_type in ASSET_CATEGORY:
        return ASSET_CATEGORY[asset_type]
    if code.startswith('SECTOR:'):
        return '板块指数'
    if code.endswith(('.SZ', '.SH')):
        return 'A股'
    elif 'USDT' in code:
        return '加密货币'
    else:
        return '美股'


# 发现页扩展标的池：除固定股票外，额外纳入板块指数与基金。
# 每项结构：(展示名, 抓取代码, 资产类型)
#   - 股票/板块/加密直接走 get_stock_data（板块代码形如 SECTOR:白酒）
#   - 基金走 get_fund_nav -> fund_nav_to_ohlcv
# STOCK_POOL 是 {名称: 代码} 的 2 元组映射，这里统一补上资产类型，
# 与下方板块/基金合并成统一的 (名称, 代码, 类型) 三元组池。
_DISCOVER_STOCK_ITEMS = [
    (name, code, run_logger.timed_call("discover_page", "_classify_symbol", _classify_symbol, code))
    for name, code in STOCK_POOL.items()
]

DISCOVER_POOL = _DISCOVER_STOCK_ITEMS + [
    # —— 板块指数（申万/同花顺行业）——
    ("白酒板块",     "SECTOR:白酒",        "板块"),
    ("半导体板块",   "SECTOR:半导体",      "板块"),
    ("新能源汽车板块", "SECTOR:新能源汽车",  "板块"),
    ("光伏设备板块",  "SECTOR:光伏设备",    "板块"),
    ("医药生物板块",  "SECTOR:医药生物",    "板块"),
    ("银行板块",     "SECTOR:银行",        "板块"),
    ("军工板块",     "SECTOR:军工",        "板块"),
    # —— 基金（常见 ETF / 主动基金）——
    ("沪深300ETF",   "510300",            "基金"),
    ("科创50ETF",    "588000",            "基金"),
    ("中概互联网ETF", "513050",            "基金"),
    ("纳指ETF",      "513100",            "基金"),
    ("招商中证白酒",  "161725",            "基金"),
    ("易方达蓝筹",    "005827",            "基金"),
]


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_data_cached(symbol_code, asset_type='stock'):
    """获取最近 90 个交易日的数据（带 1 小时缓存）"""
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=150)).strftime('%Y-%m-%d')
    if asset_type == '基金':
        nav = get_fund_nav(symbol_code, start=start, end=end)
        if nav is None or nav.empty:
            return None
        df = fund_nav_to_ohlcv(nav)
    else:
        df = get_stock_data(symbol_code, start=start, end=end)
    if df is None or df.empty:
        return None
    # 只保留最近 90 行
    return df.tail(90)


@st.cache_data(ttl=3600, show_spinner=False)
def _scan_symbol_strategy(symbol_name, symbol_code, strategy_name, asset_type='stock'):
    """
    对单个（标的, 策略）对运行回测，提取信号。
    返回 dict 或 None（数据/回测失败）。
    """
    data = _fetch_data_cached(symbol_code, asset_type)
    if data is None:
        return None

    # 规则之外的「智能洞察」层（量价/估值/相对强弱/情绪/板块联动）
    try:
        _insight = insight_module.build_insight(symbol_name, symbol_code, asset_type)
    except Exception:
        _insight = {}

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
            # 从后往前找到第一笔真实交易（跳过情绪拦截的 baropen=0 假交易）
            last_trade = None
            for t in reversed(trade_log):
                if t.get('baropen', 0) > 0 or t.get('barclose', 0) > 0:
                    last_trade = t
                    break

            if last_trade is not None:
                raw_bo = last_trade['baropen']
                raw_bc = last_trade['barclose']
                data_len = len(data)

                # 仅当 bar 索引在数据范围内且落在最后 2 根 bar 时才视为新鲜信号
                # 不使用 min() 夹紧，避免越界索引被强制拉到末尾造成假信号
                is_open_fresh = 0 < raw_bo < data_len and raw_bo >= data_len - 2
                is_close_fresh = 0 < raw_bc < data_len and raw_bc >= data_len - 2

                if is_close_fresh:
                    signal = "卖出信号"
                    signal_date = data.index[raw_bc].strftime('%Y-%m-%d')
                    reason = last_trade.get('exit_reason', '策略卖出信号')
                    signal_desc = f"卖出价 {last_trade['exit']:.2f}，原因：{reason}"
                elif is_open_fresh:
                    signal = "买入信号"
                    signal_date = data.index[raw_bo].strftime('%Y-%m-%d')
                    reason = last_trade.get('entry_reason', '策略买入信号')
                    signal_desc = f"买入价 {last_trade['entry']:.2f}，原因：{reason}"
                else:
                    signal_desc = "最近一笔真实交易不在末尾 2 日内"
            else:
                signal_desc = "无真实交易记录"

        return {
            'symbol': symbol_name,
            'strategy': strategy_name,
            'signal': signal,
            'signal_date': signal_date,
            'signal_desc': signal_desc,
            'recent_price': recent_price,
            'category': _classify_symbol(symbol_code, asset_type),
            '_insight': _insight,
        }
    except Exception as e:
        return {
            'symbol': symbol_name,
            'strategy': strategy_name,
            'signal': '扫描失败',
            'signal_date': '',
            'signal_desc': str(e)[:120],
            'recent_price': 0,
            'category': _classify_symbol(symbol_code, asset_type),
            '_insight': {},
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

    # 合并同标的多个策略的命中信息
    hit_strategies = result.get('_hit_strategies', [result.get('strategy', '')])
    hit_strategies = [s for s in hit_strategies if s]
    strategy_str = "、".join(hit_strategies) if hit_strategies else result.get('strategy', '')

    # 原因：去重后展示（最多 2 条，避免卡片过长）
    all_reasons = result.get('_all_reasons', [result.get('signal_desc', '')])
    all_reasons = [r for r in all_reasons if r]
    seen = set()
    unique_reasons = []
    for rs in all_reasons:
        if rs not in seen:
            seen.add(rs)
            unique_reasons.append(rs)
    extra = ""
    if len(unique_reasons) > 1:
        shown = unique_reasons[:2]
        extra = "；另有 " + str(len(unique_reasons) - len(shown)) + " 个策略同样触发" if len(unique_reasons) > len(shown) else ""
        reason_str = "；".join(shown) + extra
    else:
        reason_str = unique_reasons[0] if unique_reasons else result.get('signal_desc', '')

    # 规则之外的「智能洞察」行（量价/估值/相对强弱/情绪/板块联动）
    insight = result.get('_insight') or {}
    insight_tags = insight_module.summarize_insight(insight) if insight else []
    if insight_tags:
        chips = "".join(
            f"<span style='display:inline-block;background:{'#2a2f55' if theme=='dark' else '#eef1fb'};"
            f"color:{'#aeb8ff' if theme=='dark' else '#3a47c2'};"
            f"padding:2px 8px;border-radius:10px;font-size:10px;margin:2px 4px 2px 0'>"
            f"{t}</span>"
            for t in insight_tags
        )
        insight_html = (
            f"<div style='margin:6px 0 4px;line-height:1.6'>{chips}</div>"
        )
    else:
        insight_html = ""

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
            {reason_str}
        </div>
        {insight_html}
        <div style="display:flex;justify-content:space-between;font-size:11px;color:{'#6b7094' if theme == 'dark' else '#9e9e9e'}">
            <span>策略：{strategy_str}</span>
            <span>价格：{price_str} ｜ 信号日：{result['signal_date']}</span>
        </div>
        <div style="font-size:11px;color:{'#6b7094' if theme == 'dark' else '#9e9e9e'};margin-top:2px">
            类型：{result.get('category', '—')}
        </div>
    </div>"""


# ============================================================
#  扫描状态机
# ============================================================

SCAN_KEYS = [
    '_ds_running',       # bool: 是否正在扫描
    '_ds_results',       # list: 已收集的扫描结果
    '_ds_failed',        # list: 数据获取失败的标的名
    '_ds_pool',          # list: 扫描标的快照 [(name, code, cat), ...]
    '_ds_strategies',    # list: 策略名快照
    '_ds_cursor',        # int: 当前处理的标的索引
    '_ds_total',         # int: 总标的数
    '_ds_scan_id',       # str: 本次扫描唯一 ID（用于区分新旧扫描）
    '_ds_type_filter',   # list: 快照时的类型筛选
    '_ds_signal_filter', # str: 快照时的信号方向筛选
]


def _init_scan_state():
    """初始化扫描相关的 session_state 键"""
    for key in SCAN_KEYS:
        if key not in st.session_state:
            st.session_state[key] = None
    if st.session_state._ds_running is None:
        st.session_state._ds_running = False
    if st.session_state._ds_results is None:
        st.session_state._ds_results = []
    if st.session_state._ds_failed is None:
        st.session_state._ds_failed = []
    if st.session_state._ds_cursor is None:
        st.session_state._ds_cursor = 0


def _start_scan(pool_items, strategies, selected_types, selected_signal):
    """启动一次新扫描"""
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
    """处理一批（1 个标的 × 全部策略），然后 rerun"""
    cursor = st.session_state._ds_cursor
    pool = st.session_state._ds_pool
    strategies = st.session_state._ds_strategies
    total = st.session_state._ds_total

    if cursor >= total:
        st.session_state._ds_running = False
        return

    sym_name, sym_code, sym_cat = pool[cursor]

    # 检查数据是否可用
    has_data = _fetch_data_cached(sym_code, sym_cat)
    if has_data is None:
        st.session_state._ds_failed.append(sym_name)
    else:
        for strat_name in strategies:
            res = _scan_symbol_strategy(sym_name, sym_code, strat_name, sym_cat)
            if res is not None:
                st.session_state._ds_results.append(res)

    st.session_state._ds_cursor = cursor + 1

    if st.session_state._ds_cursor < total:
        # 还没扫完，展示进度后 rerun 继续下一批
        done = st.session_state._ds_cursor
        next_name = pool[done][0] if done < total else ""
        st.progress(done / total,
            text=f"扫描中... {done}/{total} 个标的，下一个: {next_name}")
        import time; time.sleep(0.05)
        st.rerun()
    else:
        # 最后一批：仅设状态，**不要 rerun**，让 render() 自然走到「情况3」展示结果。
        # 这样避免「扫描中帧」与「完成帧」在 streamlit 客户端短暂共存导致的"两行"视觉问题。
        st.session_state._ds_running = False


# 信号优先级：数字越小越优先（用于同一标的多策略去重）
_SIGNAL_PRIORITY = {
    "买入信号": 0,
    "卖出信号": 1,
    "持有中": 2,
}


def _dedupe_by_symbol(results):
    """
    按标的（symbol）去重合并。

    同一标的被多个策略扫描时会产生多条记录，这里只保留一条：
      1. 按优先级取最优信号（买入 > 卖出 > 持有）；
      2. 把命中该信号的全部策略与原因合并到描述中。
    """
    merged = {}
    for r in results:
        sym = r['symbol']
        if sym not in merged:
            merged[sym] = dict(r)  # 浅拷贝
            merged[sym]['_hit_strategies'] = [r['strategy']]
            merged[sym]['_all_reasons'] = [r['signal_desc']]
            # 取第一个非空的洞察作为该标的洞察
            merged[sym]['_insight'] = r.get('_insight') or {}
            continue
        exist = merged[sym]
        exist['_hit_strategies'].append(r['strategy'])
        exist['_all_reasons'].append(r['signal_desc'])
        # 若当前记录信号优先级更优，则覆盖主记录（信号/价格/日期）
        if _SIGNAL_PRIORITY.get(r['signal'], 99) < _SIGNAL_PRIORITY.get(exist['signal'], 99):
            for k in ('signal', 'signal_date', 'signal_desc', 'recent_price', 'category'):
                exist[k] = r[k]
        # 若主记录洞察为空且当前有洞察，补上
        if not exist.get('_insight') and r.get('_insight'):
            exist['_insight'] = r['_insight']
    return list(merged.values())


def _render_insight_brief(filtered, theme):
    """智能洞察线索汇总：从所有信号标的里提炼「规则外」的重点线索。

    仅提示有正向/值得关注意义的维度（放量、低位、跑赢大盘、新闻偏多），
    不重复策略信号本身。取不到数据的维度不显示。
    """
    clues = []  # (标的, 维度, 文案)
    for r in filtered:
        ins = r.get('_insight') or {}
        name = r['symbol']
        # 放量
        vol = ins.get('volume') or {}
        if vol.get('value') is not None and vol['value'] >= 1.3:
            clues.append((name, "量价", vol['label']))
        # 低位
        val = ins.get('valuation') or {}
        if val.get('value') is not None and val['value'] <= 0.2:
            clues.append((name, "估值", val['label']))
        # 跑赢大盘
        rs = ins.get('relative_strength') or {}
        if rs.get('value') is not None and rs['value'] >= 0:
            clues.append((name, "强弱", rs['label']))
        # 新闻偏多
        sent = ins.get('sentiment') or {}
        if sent.get('value') is not None and sent['value'] >= 0.5:
            clues.append((name, "情绪", sent['label']))
        # 板块上涨（个股板块联动）
        sec = ins.get('sector') or {}
        if sec.get('value') is not None and sec['value'] > 0:
            clues.append((name, "板块", sec['label']))

    if not clues:
        return

    with st.expander("💡 智能洞察线索（规则之外的辅助关注，点击展开）", expanded=True):
        st.caption(
            "以下线索由「量价/估值/相对强弱/新闻情绪/板块联动」五个维度综合得出，"
            "不依赖固定策略规则，仅供辅助参考，不构成投资建议。"
        )
        # 按标的分组展示
        from collections import OrderedDict
        grouped = OrderedDict()
        for name, dim, text in clues:
            grouped.setdefault(name, []).append((dim, text))
        for name, items in grouped.items():
            line = "　".join(f"【{d}】{t}" for d, t in items)
            st.markdown(
                f"<div style='font-size:12px;margin:3px 0'>"
                f"<b style='color:{'#a5d6a7' if theme=='dark' else '#1b5e20'}'>{name}</b>：{line}"
                f"</div>",
                unsafe_allow_html=True,
            )


def _show_results(theme):
    """展示上次扫描的完整结果"""
    all_results = st.session_state._ds_results
    failed_symbols = st.session_state._ds_failed
    signal_filter = st.session_state._ds_signal_filter

    if signal_filter == "仅买入":
        signals_of_interest = ["买入信号", "持有中"]
    elif signal_filter == "仅卖出":
        signals_of_interest = ["卖出信号"]
    else:
        signals_of_interest = ["买入信号", "卖出信号", "持有中"]

    raw_filtered = [r for r in all_results if r['signal'] in signals_of_interest]
    # 按标的去重合并（同一标的只显示一条）
    filtered = _dedupe_by_symbol(raw_filtered)

    st.markdown("---")
    st.subheader(f"扫描结果（共 {len(filtered)} 个标的）")

    if not filtered:
        st.info("今日暂无符合条件的信号")
        if failed_symbols:
            st.caption(f"数据获取失败: {', '.join(failed_symbols)}")
        return

    # ---- 智能洞察线索汇总（规则之外，顶部重点提示）----
    _render_insight_brief(filtered, theme)

    buy_signals = [r for r in filtered if r['signal'] == '买入信号']
    sell_signals = [r for r in filtered if r['signal'] == '卖出信号']
    hold_signals = [r for r in filtered if r['signal'] == '持有中']
    fail_signals = [r for r in all_results if r['signal'] == '扫描失败']

    if buy_signals:
        st.markdown("### 📈 买入机会")
        st.caption(f"共 {len(buy_signals)} 条")
        cols = st.columns(2)
        for idx, r in enumerate(buy_signals):
            with cols[idx % 2]:
                st.markdown(_render_card(r, theme), unsafe_allow_html=True)

    if sell_signals:
        st.markdown("### 📉 卖出信号")
        st.caption(f"共 {len(sell_signals)} 条")
        cols = st.columns(2)
        for idx, r in enumerate(sell_signals):
            with cols[idx % 2]:
                st.markdown(_render_card(r, theme), unsafe_allow_html=True)

    if hold_signals:
        st.markdown("### 📊 当前持有")
        st.caption(f"共 {len(hold_signals)} 条")
        cols = st.columns(2)
        for idx, r in enumerate(hold_signals):
            with cols[idx % 2]:
                st.markdown(_render_card(r, theme), unsafe_allow_html=True)

    if fail_signals:
        with st.expander(f"扫描失败（共 {len(fail_signals)} 条）"):
            fail_df = pd.DataFrame([
                {"标的": r['symbol'], "策略": r['strategy'], "错误": r['signal_desc']}
                for r in fail_signals
            ])
            st.dataframe(fail_df, use_container_width=True, hide_index=True)

    if failed_symbols:
        st.caption(f"数据获取失败: {', '.join(failed_symbols)}")


# ============================================================
#  render()
# ============================================================
def render():
    run_logger.log_run("discover_page", "render", ok=True, detail="页面渲染开始")
    theme = st.session_state.get("_theme_mode", "dark")
    _init_scan_state()

    # ========== 标题 ==========
    st.title("发现")
    st.caption("用最新行情运行全部策略，扫描今日信号")

    # ========== 每日市场复盘 ==========
    # 扫描进行中不渲染复盘（避免与扫描 rerun 抢资源）；空闲时展示。
    if not st.session_state._ds_running:
        _render_daily_review(theme)

    # ========== 筛选区 ==========
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        market_options = ["全部市场", "A股", "美股", "加密货币", "板块指数", "基金"]
        selected_market = st.selectbox(
            "市场", market_options, index=0,
            help="筛选要扫描的标的类型：股票（A股/美股/加密货币）、行业板块指数、或基金",
            disabled=st.session_state._ds_running
        )
    with col2:
        signal_options = ["全部", "仅买入", "仅卖出"]
        selected_signal = st.selectbox(
            "信号方向", signal_options, index=0,
            help="按信号方向过滤结果",
            disabled=st.session_state._ds_running
        )
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        scan_btn = st.button(
            "扫描中..." if st.session_state._ds_running else "开始扫描",
            type="primary",
            use_container_width=True,
            disabled=st.session_state._ds_running
        )

    # ========== 扫描状态机路由 ==========

    # 情况 1：正在扫描中 → 继续处理
    if st.session_state._ds_running:
        # _continue_scan 内部已处理 rerun（中间批次 rerun 继续；最后一批 rerun 进入结果展示），
        # 因此这里无需再 rerun；用 return 防止脚本继续往下走（避免重复渲染筛选区）。
        _continue_scan()
        return

    # 情况 2：用户点击扫描按钮
    if scan_btn:
        pool_items = []
        for name, code, atype in DISCOVER_POOL:
            cat = _classify_symbol(code, atype)
            if selected_market == "全部市场" or cat == selected_market:
                pool_items.append((name, code, atype))

        if not pool_items:
            st.warning("没有符合条件的标的")
            return

        strategies = list(STRATEGY_REGISTRY.keys())
        _start_scan(pool_items, strategies, selected_market, selected_signal)
        st.rerun()

    # 情况 3：空闲状态 — 有历史结果则展示，否则提示
    if st.session_state._ds_results:
        _show_results(theme)
    else:
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
    run_logger.log_run("discover_page", "render", ok=True, detail="页面渲染完成")
