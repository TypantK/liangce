# -*- coding: utf-8 -*-
"""
策略回测页面 v4 — 统一数据源选择器 + 智能拼音搜索 + 自动判断图表类型
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from core.strategies import STRATEGY_REGISTRY
from core.position_sizer import SIZER_REGISTRY
from core.data_fetcher import STOCK_POOL, get_stock_data, generate_demo_data, fund_nav_to_ohlcv
from core.engine import run_backtest
from core.sentiment import parse_events_from_search, summarize_news, generate_events_from_price
from core.sentiment_fetcher import fetch_news
from utils.chart import plot_backtest, render_strategy_card, plot_fund_backtest


def _parse_pct(val):
    """解析百分比字符串如 '12.34%' 为 float；已是数字则直接返回"""
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace("%", "").strip())
    except (ValueError, AttributeError):
        return 0.0


# ---- pypinyin 智能搜索 ----
try:
    from pypinyin import lazy_pinyin
    _PY_AVAIL = True
except ImportError:
    _PY_AVAIL = False

# 用户持仓基金（按净值降序）
_USER_FUNDS = [
    ("270023", "广发全球精选股票(QDII)A",     6.909),
    ("024239", "华夏全球科技先锋混合(QDII)C",  3.675),
    ("011172", "广发利鑫灵活配置混合C",         3.633),
    ("000217", "华安黄金ETF联接C",             3.282),
    ("002611", "博时黄金ETF联接C",             3.058),
    ("016453", "南方纳斯达克100指数(QDII)C",   2.382),
    ("021750", "易方达创业板成长ETF联接C",      2.320),
    ("008254", "华宝致远混合(QDII)C",          2.134),
    ("016874", "广发远见智选混合C",             1.971),
    ("025653", "大成创业板人工智能ETF联接C",    1.703),
    ("016186", "广发电力公用事业ETF联接C",      1.291),
    ("021378", "兴业中证港股通互联网ETF联接C",  1.124),
    ("014111", "嘉实中证稀有金属主题ETF联接C",  1.076),
    ("013528", "嘉实中证细分化工产业主题ETF联接C", 1.002),
    ("015998", "大成中证电池主题ETF联接C",      0.951),
]

# 预置基金数据（排除已在用户持仓中的）
_FUNDS_RAW = [
    ("000001", "华夏成长混合"),
    ("001933", "华商新兴活力混合"),
    ("005827", "易方达蓝筹精选混合"),
    ("161725", "招商中证白酒指数(LOF)A"),
    ("270002", "广发稳健增长混合A"),
    ("110011", "易方达中小盘混合"),
    ("002001", "华夏回报混合A"),
    ("519674", "银河创新成长混合A"),
    ("163406", "兴全合润混合(LOF)"),
    ("320007", "诺安成长混合"),
    ("000083", "汇添富消费行业混合"),
]


def _make_pinyin(name):
    """生成拼音全拼和首字母"""
    if _PY_AVAIL:
        py = ''.join(lazy_pinyin(name))
        pyf = ''.join([p[0] for p in lazy_pinyin(name)])
    else:
        py = name.lower()
        pyf = ''.join([w[0] for w in name])
    return py, pyf


def _make_unified_pool():
    """构建统一数据池：用户基金(净值排序) + 预置基金 + 股票"""
    pool = []
    # 用户持仓基金（优先展示）
    for code, name, _ in _USER_FUNDS:
        py, pyf = _make_pinyin(name)
        pool.append({"type": "fund", "code": code, "name": name,
                     "pinyin": py, "pinyin_first": pyf})
    # 预置基金
    for code, name in _FUNDS_RAW:
        py, pyf = _make_pinyin(name)
        pool.append({"type": "fund", "code": code, "name": name,
                     "pinyin": py, "pinyin_first": pyf})
    # 股票
    for name, code in STOCK_POOL.items():
        py, pyf = _make_pinyin(name)
        pool.append({"type": "stock", "code": code, "name": name,
                     "pinyin": py, "pinyin_first": pyf})
    return pool


UNIFIED_POOL = _make_unified_pool()
TYPE_TAGS = {"demo": "演示", "stock": "股票", "fund": "基金"}


def get_fund_nav(code):
    """通过 akshare 获取基金净值历史"""
    try:
        import akshare as ak
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")

        # 列名容错：尝试多种常见列名格式
        date_col = None
        nav_col = None
        for col in df.columns:
            col_lower = col.strip()
            if col_lower in ("净值日期", "date", "nav_date", "净值日", "日期"):
                date_col = col
            elif col_lower in ("单位净值", "nav", "net_value", "净值", "累计净值"):
                nav_col = col

        if date_col is None:
            raise ValueError(
                f"基金 {code} 净值数据中未找到日期列，"
                f"现有列: {list(df.columns)}"
            )
        if nav_col is None:
            raise ValueError(
                f"基金 {code} 净值数据中未找到净值列，"
                f"现有列: {list(df.columns)}"
            )

        df = df.rename(columns={date_col: "date", nav_col: "nav"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return None


# ---- Plotly 深色主题配色 ----
BG      = '#131520'
GRID_C  = '#1f2335'
FG      = '#c8cce0'
FG_SOFT = '#6b7094'
LINE_C  = '#2a2d3e'
CN_FONT = 'PingFang SC, Microsoft YaHei, SimHei, Arial Unicode MS, sans-serif'


def _build_chart_html(fig, version=0, theme="dark", auto_zoom=False):
    """Generate HTML with embedded JS for click-to-zoom."""
    import uuid
    chart_id = f"chart_{uuid.uuid4().hex[:8]}"

    if theme == "light":
        _body_bg = '#ffffff'
        _body_color = '#1f2937'
    else:
        _body_bg = '#131520'
        _body_color = '#fff'

    fig_html = fig.to_html(
        include_plotlyjs='cdn',
        full_html=False,
        config={
            'doubleClick': 'reset',
            'displayModeBar': True,
            'displaylogo': False,
            'modeBarButtons': [
                ['zoom2d', 'pan2d', 'autoScale2d', 'zoomIn2d', 'zoomOut2d'],
            ],
        },
        div_id=chart_id,
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ margin: 0; padding: 0; background: {_body_bg}; color: {_body_color}; font-family: sans-serif; }}
        #{chart_id} {{ width: 100%; }}
    </style>
</head>
<body>
{fig_html}
<script>
window.__chartAutoZoom = {'true' if auto_zoom else 'false'};
(function() {{
    var gd = null;
    var clickCount = 0;
    var zoomReady = false;

    function findDateIndex(allX, targetX) {{
        if (!allX || !allX.length) return -1;
        var idx = -1, minDist = Infinity;
        for (var i = 0; i < allX.length; i++) {{
            var dist = Math.abs(new Date(allX[i]) - new Date(targetX));
            if (dist < minDist) {{ minDist = dist; idx = i; }}
        }}
        return idx;
    }}

    function zoomToRange(allX, startIdx, endIdx) {{
        if (!gd) return;
        startIdx = Math.max(0, startIdx);
        endIdx = Math.min(allX.length - 1, endIdx);
        if (startIdx < endIdx) {{
            var relayoutObj = {{
                'xaxis.autorange': false,
                'yaxis.autorange': false,
                'xaxis.range': [allX[startIdx], allX[endIdx]]
            }};
            var fullTraces = gd._fullData || gd.data;
            var found = false;
            // 1) Candlestick/OHLC → use high/low
            for (var t = 0; t < fullTraces.length; t++) {{
                var tr = fullTraces[t];
                if ((tr.type === 'candlestick' || tr.type === 'ohlc') && tr.high && tr.low) {{
                    var yHi = -Infinity, yLo = Infinity;
                    for (var i = startIdx; i <= endIdx; i++) {{
                        var hi = tr.high[i], lo = tr.low[i];
                        if (hi != null && hi > yHi) yHi = hi;
                        if (lo != null && lo < yLo) yLo = lo;
                    }}
                    if (isFinite(yHi) && isFinite(yLo) && yHi > yLo) {{
                        var pad = (yHi - yLo) * 0.08;
                        relayoutObj['yaxis.range'] = [yLo - pad, yHi + pad];
                    }}
                    found = true;
                    break;
                }}
            }}
            // 2) Fallback: Scatter/line trace → use y values
            if (!found) {{
                for (var t = 0; t < fullTraces.length; t++) {{
                    var tr2 = fullTraces[t];
                    if (tr2.type === 'scatter' && tr2.y && tr2.y.length > 0) {{
                        var yHi = -Infinity, yLo = Infinity;
                        for (var i = startIdx; i <= endIdx; i++) {{
                            var v = tr2.y[i];
                            if (v != null && isFinite(v)) {{
                                if (v > yHi) yHi = v;
                                if (v < yLo) yLo = v;
                            }}
                        }}
                        if (isFinite(yHi) && isFinite(yLo) && yHi > yLo) {{
                            var pad = (yHi - yLo) * 0.08;
                            relayoutObj['yaxis.range'] = [yLo - pad, yHi + pad];
                        }}
                        break;
                    }}
                }}
            }}
            Plotly.relayout(gd, relayoutObj);
        }}
    }}

    function bindClickHandlers() {{
        gd.removeAllListeners('plotly_click');
        gd.removeAllListeners('plotly_selected');
        gd.removeAllListeners('plotly_doubleclick');

        gd.on('plotly_click', function(data) {{
            clickCount++;
            var pts = (data && data.points) ? data.points.length : 0;
            if (!pts) return;
            var pt = data.points[0];
            var allX = pt.data.x;
            if (!allX || allX.length === 0) return;
            var idx = findDateIndex(allX, pt.x);
            if (idx < 0) return;
            zoomToRange(allX, idx - 30, idx + 30);
            // ---- 回传点击日期给 Streamlit ----
            try {{
                var clickedDate = pt.data.x[idx];
                var d = new Date(clickedDate);
                if (!isNaN(d.getTime())) {{
                    var yyyy = d.getFullYear();
                    var mm = String(d.getMonth() + 1).padStart(2, '0');
                    var dd = String(d.getDate()).padStart(2, '0');
                    var dateStr = yyyy + '-' + mm + '-' + dd;
                    var url = new URL(window.top.location.href);
                    url.searchParams.set('marvis_chart_date', dateStr);
                    window.top.location.href = url.toString();
                }}
            }} catch(e) {{}}
        }});

        gd.on('plotly_selected', function(data) {{
            if (!data || !data.range || !data.range.x) return;
            if (!data.points || !data.points.length) {{
                Plotly.relayout(gd, {{'xaxis.range': [data.range.x[0], data.range.x[1]]}});
                return;
            }}
            var allX = data.points[0].data.x;
            if (!allX || !allX.length) return;
            var startIdx = findDateIndex(allX, data.range.x[0]);
            var endIdx = findDateIndex(allX, data.range.x[1]);
            if (startIdx >= 0 && endIdx >= 0) zoomToRange(allX, startIdx, endIdx);
        }});
    }}

    function setupZoom() {{
        if (zoomReady || !gd) return;
        zoomReady = true;
        bindClickHandlers();

        var rebindLock = false;
        gd.on('plotly_relayout', function(eventData) {{
            if (rebindLock) return;
            rebindLock = true;
            var isAutoscale = eventData && ('xaxis.autorange' in eventData || 'yaxis.autorange' in eventData);
            var delay = isAutoscale ? 300 : 80;
            setTimeout(function() {{
                if (isAutoscale) {{
                    Plotly.relayout(gd, {{'xaxis.autorange': false, 'yaxis.autorange': false}});
                    bindClickHandlers();
                    var cd = (gd._fullLayout || {{}}).dragmode || 'pan';
                    Plotly.relayout(gd, {{dragmode: cd}});
                    setTimeout(function() {{ rebindLock = false; }}, 150);
                }} else {{
                    bindClickHandlers();
                    var cd = (gd._fullLayout || {{}}).dragmode || 'pan';
                    Plotly.relayout(gd, {{dragmode: cd}});
                    setTimeout(function() {{ rebindLock = false; }}, 150);
                }}
            }}, delay);
        }});

        var currentDrag = (gd._fullLayout || {{}}).dragmode || 'pan';

        if (window.__chartAutoZoom) {{
            Plotly.relayout(gd, {{'xaxis.autorange': true, 'yaxis.autorange': true}});
            setTimeout(function() {{
                var btn = gd.querySelector('.modebar-btn[data-attr="zoom"][data-val="out"]');
                if (btn) btn.click();
            }}, 150);
        }} else {{
            Plotly.relayout(gd, {{'xaxis.autorange': false, 'yaxis.autorange': false, dragmode: currentDrag}});
        }}
    }}

    function tryInit() {{
        gd = document.getElementById('{chart_id}');
        if (!gd) gd = document.querySelector('.js-plotly-plot');
        if (!gd) gd = document.querySelector('.plotly-graph-div');
        if (!gd) gd = document.querySelector('[id^="chart_"]');
        if (!gd) {{ setTimeout(tryInit, 300); return; }}
        if (gd._fullLayout && gd._fullLayout._initialized) {{
            setupZoom();
        }} else {{
            gd.once && gd.once('plotly_afterplot', setupZoom);
            gd.on('plotly_afterplot', setupZoom);
            setTimeout(function() {{ if (!zoomReady) setupZoom(); }}, 2000);
        }}
    }}

    setTimeout(tryInit, 200);

    window.__chartDebug = {{
        getGd: function() {{ return gd; }},
        getClickCount: function() {{ return clickCount; }}
    }};
}})();
</script>
<!-- cv:{version} -->
<script>
(function() {{
    document.addEventListener('keydown', function(e) {{
        var tag = (document.activeElement || {{}}).tagName || '';
        if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
        var gd = window.__chartDebug && window.__chartDebug.getGd();
        if (!gd) return;
        var key = e.key.toLowerCase();
        if (key === 'q') {{
            e.preventDefault();
            Plotly.relayout(gd, {{dragmode: 'zoom'}});
        }} else if (key === 'w') {{
            e.preventDefault();
            Plotly.relayout(gd, {{dragmode: 'pan'}});
        }} else if (key === 'e') {{
            e.preventDefault();
            Plotly.relayout(gd, {{'xaxis.autorange': true, 'yaxis.autorange': true}});
            setTimeout(function() {{
                var zoomOutBtn = gd.querySelector('.modebar-btn[data-attr="zoom"][data-val="out"]');
                if (zoomOutBtn) zoomOutBtn.click();
            }}, 150);
        }} else if (key === 'a') {{
            e.preventDefault();
            var zin = gd.querySelector('.modebar-btn[data-attr="zoom"][data-val="in"]');
            if (zin) zin.click();
        }} else if (key === 's') {{
            e.preventDefault();
            var zout = gd.querySelector('.modebar-btn[data-attr="zoom"][data-val="out"]');
            if (zout) zout.click();
        }}
    }});
}})();
</script>
</body>
</html>"""
    return html


# ============================================================
#  render()
# ============================================================
def render():
    # ========== 顶部栏：标题 + 主题切换按钮 ==========
    col_title, col_theme = st.columns([6, 1])
    with col_title:
        st.title("策略回测")
    with col_theme:
        if "_theme_mode" not in st.session_state:
            st.session_state._theme_mode = "dark"

        if st.session_state._theme_mode == "dark":
            btn_label, btn_help = "☀️", "切换到白天模式"
        else:
            btn_label, btn_help = "🌙", "切换到夜间模式"

        if st.button(btn_label, key="theme_toggle", help=btn_help):
            st.session_state._theme_mode = "light" if st.session_state._theme_mode == "dark" else "dark"
            st.rerun()

    theme = st.session_state._theme_mode

    if theme == "light":
        st.markdown("""
        <style>
        /* ── 背景 ── */
        [data-testid="stAppViewContainer"], [data-testid="stHeader"],
        .stApp { background: #ffffff !important; }
        [data-testid="stSidebar"] { background: #f8f9fa !important; }

        /* ── 主区域文本 ── */
        h1, h2, h3, h4, p, label, .stMarkdown, .stCaption,
        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] .stMarkdown { color: #1f2937 !important; }

        /* ── 控件标签 ── */
        .stSelectbox label, .stDateInput label, .stNumberInput label, .stSlider label,
        .stRadio label, .stCheckbox label { color: #1f2937 !important; }

        /* ── 输入框内文字 ── */
        [data-testid="stNumberInput"] input { color: #1f2937 !important; background: #ffffff !important; border-color: #d1d5db !important; }
        [data-testid="stDateInput"] input { color: #1f2937 !important; background: #ffffff !important; border-color: #d1d5db !important; }
        [data-testid="stSelectbox"] [data-baseweb="select"] [data-baseweb="input"] { color: #1f2937 !important; background: #ffffff !important; }
        [data-testid="stSelectbox"] [data-baseweb="popover"] li { color: #1f2937 !important; }

        /* ── 滑块值 ── */
        .stSlider [data-testid="stThumbValue"] { color: #1f2937 !important; background: #e5e7eb !important; }

        /* ── Metric ── */
        [data-testid="stMetricValue"] { color: #1f2937 !important; }
        [data-testid="stMetricDelta"] { color: #059669 !important; }

        /* ── DataFrame ── */
        .stDataFrame, .stDataFrame * { color: #1f2937 !important; }
        .stDataFrame th { background: #f3f4f6 !important; }

        /* ── Alert / Info / Warning ── */
        .stAlert { color: #1f2937 !important; }
        div[data-testid="stNotification"] { color: #1f2937 !important; }

        /* ── Button ── */
        .stButton > button[kind="primary"] { color: #ffffff !important; }

        /* ── Spinner ── */
        .stSpinner > div { border-top-color: #3b82f6 !important; }

        /* ── 分隔线 ── */
        hr { border-color: #e5e7eb !important; }

        /* ── 侧边栏 ── */
        section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] .stMarkdown,
        section[data-testid="stSidebar"] .stCaption, section[data-testid="stSidebar"] .stSelectbox label,
        section[data-testid="stSidebar"] .stDateInput label, section[data-testid="stSidebar"] .stNumberInput label,
        section[data-testid="stSidebar"] .stSlider label, section[data-testid="stSidebar"] [data-testid="stMetricValue"],
        section[data-testid="stSidebar"] [data-testid="stMetricDelta"],
        section[data-testid="stSidebar"] [data-testid="stNumberInput"] input,
        section[data-testid="stSidebar"] [data-testid="stDateInput"] input,
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] [data-baseweb="input"],
        section[data-testid="stSidebar"] .stSlider [data-testid="stThumbValue"],
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="popover"] li
        { color: #1f2937 !important; }

        section[data-testid="stSidebar"] [data-testid="stNumberInput"] input,
        section[data-testid="stSidebar"] [data-testid="stDateInput"] input,
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] [data-baseweb="input"]
        { background: #ffffff !important; border-color: #d1d5db !important; }
        </style>
        """, unsafe_allow_html=True)

    # ========== 统一数据源选择 ==========
    all_labels = []
    for it in UNIFIED_POOL:
        tag = TYPE_TAGS.get(it["type"], "?")
        if it["code"]:
            all_labels.append(f"[{tag}] {it['name']} ({it['code']})")
        else:
            all_labels.append(f"[{tag}] {it['name']}")

    # label → item 映射，避免 index 匹配
    label_map = dict(zip(all_labels, UNIFIED_POOL))

    # 默认选中演示数据
    default_idx = 0
    for i, it in enumerate(UNIFIED_POOL):
        if it["type"] == "demo":
            default_idx = i
            break

    selected_label = st.selectbox("数据源", all_labels, index=default_idx, key="ds_select")
    item = label_map[selected_label]

    # ========== 按类型分支 ==========
    if item["type"] == "fund":
        _render_fund(item, theme)
    else:
        _render_backtest(item, theme)


# ============================================================
# ============================================================
#  _render_fund  — 基金策略回测（侧边栏参数 + 主区图表）
# ============================================================


# ============================================================
#  共享组件 — _render_fund / _render_backtest 复用
# ============================================================

def _get_common_sidebar_params(prefix="", default_sentiment=True, min_cash=1000):
    """共同侧边栏参数组件。prefix 用于 session_state key 隔离。"""
    strategy_name = st.sidebar.selectbox(
        "选择策略", list(STRATEGY_REGISTRY.keys()), key=f"{prefix}s")
    strat_info = STRATEGY_REGISTRY[strategy_name]
    st.sidebar.caption(strat_info["desc"])

    st.sidebar.markdown("**回测参数**")
    backtest_start = st.sidebar.date_input(
        "起始日期", value=datetime.now() - timedelta(days=365 * 3),
        min_value=datetime(2000, 1, 1), max_value=datetime.now(), key=f"{prefix}bs_start")
    backtest_end = st.sidebar.date_input(
        "结束日期", value=datetime.now(),
        min_value=datetime(2000, 1, 1), max_value=datetime.now(), key=f"{prefix}bs_end")
    initial_cash = st.sidebar.number_input(
        "初始资金（元）", min_cash, 10000000, 100000, 10000, key=f"{prefix}cash")

    st.sidebar.markdown("**策略参数**")
    params = {}
    labels = strat_info.get("param_labels", {})
    for pn, (pmin, pmax, pdef) in strat_info["params"].items():
        label = labels.get(pn, pn)
        step = 0.1 if isinstance(pdef, float) else 1
        params[pn] = st.sidebar.slider(label, pmin, pmax, pdef, step, key=f"{prefix}p_{pn}")

    st.sidebar.markdown("**仓位管理**")
    sizer_name = st.sidebar.selectbox(
        "仓位管理器", list(SIZER_REGISTRY.keys()), key=f"{prefix}sizer")
    sizer_info = SIZER_REGISTRY[sizer_name]
    st.sidebar.caption(sizer_info["desc"])

    sizer_params = {}
    sizer_labels = sizer_info.get("param_labels", {})
    for pn, pdef in sizer_info["params"].items():
        label = sizer_labels.get(pn, pn)
        if isinstance(pdef, tuple):
            pmin, pmax, pval = pdef
            if pn in ("fraction", "risk_pct", "avg_win", "avg_loss", "win_rate", "stop_pct"):
                pct_val = st.sidebar.slider(
                    f"{label} (%)", int(pmin * 100), int(pmax * 100), int(pval * 100),
                    1, key=f"{prefix}sizer_{pn}")
                sizer_params[pn] = pct_val / 100.0
            else:
                step_sz = 0.5 if isinstance(pval, float) else 1
                sizer_params[pn] = st.sidebar.slider(
                    label, pmin, pmax, pval, step_sz, key=f"{prefix}sizer_{pn}")
    sizer_flags = sizer_info.get("flags", {})
    for fn, fl in sizer_flags.items():
        sizer_params[fn] = st.sidebar.checkbox(fl, value=False, key=f"{prefix}sizer_{fn}")
    sizer_instance = sizer_info["class"](**sizer_params)

    st.sidebar.markdown("**情绪增强**")
    sentiment_mode = st.sidebar.checkbox(
        "情绪模式", value=default_sentiment,
        help="开启后实时抓取市场新闻，根据情绪得分过滤交易信号：利好时正常交易，利空时暂停入场",
        key=f"{prefix}sentiment")

    return {
        "strategy_name": strategy_name, "strat_info": strat_info,
        "backtest_start": backtest_start, "backtest_end": backtest_end,
        "initial_cash": initial_cash, "params": params,
        "sizer_instance": sizer_instance, "sentiment_mode": sentiment_mode,
    }


def _render_common_metrics(m):
    """指标卡片展示（2行 × 4列）"""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("总收益率", m["总收益率"], delta=m.get("超额收益", ""))
    c2.metric("最大回撤", m["最大回撤"])
    c3.metric("夏普比率", m["夏普比率"])
    c4.metric("胜率", m["胜率"])
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("交易次数", m["交易次数"])
    c6.metric("最终资金", m["最终资金"])
    c7.metric("年化收益率", m["年化收益率"])
    c8.metric("买入持有", m["买入持有"])


def _render_trade_table(result, sentiment_mode=False, raw_news=None, sentiment_summary=""):
    """交易明细表格（HTML 带颜色区分买卖方向）"""
    if not result["trades"]:
        st.info("本次回测期间无交易记录")
        return

    st.subheader("交易明细")

    init_cash_str = result["metrics"].get("初始资金", "¥100,000")
    running_cash = float(init_cash_str.replace("¥", "").replace(",", "").replace("N/A", "100000"))

    trade_rows = []
    for t in result["trades"]:
        buy_qty = t.get("买入数量", 0)
        sent_mult = t.get("情绪乘数", 1.0)
        sent_score = t.get("情绪得分", 0.0)
        sent_desc = t.get("情绪说明", "")
        base_qty = int(buy_qty / sent_mult) if sent_mult > 0 else int(buy_qty)
        trade_rows.append({
            "时间": t["买入时间"], "方向": "buy", "价格": t["买入价"],
            "计划数量": str(base_qty), "实际数量": str(int(buy_qty)),
            "情绪得分": sent_score, "情绪乘数": sent_mult, "仓位调整": sent_desc if sent_desc else "",
            "原因": t.get("买入原因", ""), "余额": f"¥{running_cash:,.0f}",
        })
        pnl_str = t["盈亏"]
        pnl_val = float(pnl_str) if pnl_str else 0.0
        running_cash += pnl_val
        trade_rows.append({
            "时间": t["卖出时间"], "方向": "sell", "价格": t["卖出价"],
            "计划数量": "", "实际数量": str(int(buy_qty)),
            "情绪得分": 0.0, "情绪乘数": 1.0, "仓位调整": "",
            "原因": t.get("卖出原因", ""),
            "余额": f"¥{running_cash:,.0f}",
            "盈亏金额": f"{pnl_val:+,.2f}",
        })

    html_parts = [
        '<table style="width:100%;table-layout:fixed;border-collapse:collapse;font-size:13px">',
        '<colgroup>'
        '<col style="width:10%"><col style="width:4%"><col style="width:6%">'
        '<col style="width:10%"><col style="width:10%"><col style="width:12%">'
        '<col style="width:28%"><col style="width:10%"><col style="width:10%">'
        '</colgroup>',
        '<tr style="background:#e0e0e0;font-weight:bold;color:#1a1a1a">'
        '<th style="padding:6px 8px;text-align:left">时间</th>'
        '<th style="padding:6px 8px;text-align:center">方向</th>'
        '<th style="padding:6px 8px;text-align:right">价格</th>'
        '<th style="padding:6px 8px;text-align:center">计划数量</th>'
        '<th style="padding:6px 8px;text-align:center">实际数量</th>'
        '<th style="padding:6px 8px;text-align:center">情绪强度</th>'
        '<th style="padding:6px 8px;text-align:left">原因</th>'
        '<th style="padding:6px 8px;text-align:center">仓位调整</th>'
        '<th style="padding:6px 8px;text-align:right">余额</th>'
        '</tr>',
    ]

    for r in trade_rows:
        if r["方向"] == "buy":
            bg = "#a5d6a7"
            dir_html = '<span style="color:#2e7d32;font-weight:bold">买</span>'
        else:
            bg = "#ef9a9a"
            dir_html = '<span style="color:#c62828;font-weight:bold">卖</span>'

        bal = r["余额"]
        pnl_delta = r.get("盈亏金额", "")
        if pnl_delta:
            is_profit = pnl_delta.startswith("+")
            bal_color = "#2e7d32" if is_profit else "#c62828"
            bal_html = f'{bal} <span style="color:{bal_color};font-size:11px">({pnl_delta})</span>'
        else:
            bal_html = bal

        plan_qty = r.get("计划数量", "")
        actual_qty = r.get("实际数量", "")

        sent_html = ""
        if r["方向"] == "buy":
            sc = r.get("情绪得分", 0.0)
            sm = r.get("情绪乘数", 1.0)
            if sc != 0.0 or sm != 1.0:
                abs_sc = min(abs(sc), 3.0)
                lightness = 60 - (35 / 3.0) * abs_sc
                if sc > 0:
                    color = f"hsl(140,70%,{lightness:.0f}%)"
                else:
                    color = f"hsl(0,70%,{lightness:.0f}%)"
                sent_html = f'<span style="color:{color};font-weight:bold">{sc:+.1f}(×{sm:.1f})</span>'

        adj = r.get("仓位调整", "")

        row = f'<tr style="background:{bg};color:#1a1a1a">'
        row += f'<td style="padding:6px 8px;color:#1a1a1a">{r["时间"]}</td>'
        row += f'<td style="padding:6px 8px;text-align:center">{dir_html}</td>'
        row += f'<td style="padding:6px 8px;text-align:right;color:#1a1a1a">{r["价格"]}</td>'
        row += f'<td style="padding:6px 8px;text-align:center;color:#1a1a1a">{plan_qty}</td>'
        row += f'<td style="padding:6px 8px;text-align:center;color:#1a1a1a">{actual_qty}</td>'
        row += f'<td style="padding:6px 8px;text-align:center">{sent_html}</td>'
        row += f'<td style="padding:6px 8px;color:#1a1a1a">{r["原因"]}</td>'
        row += f'<td style="padding:6px 8px;color:#1a1a1a;font-size:12px;white-space:nowrap">{adj}</td>'
        row += f'<td style="padding:6px 8px;text-align:right;white-space:nowrap">{bal_html}</td>'
        row += '</tr>'
        html_parts.append(row)

    html_parts.append('</table>')
    st.markdown('\n'.join(html_parts), unsafe_allow_html=True)

    if sentiment_mode and raw_news:
        with st.expander(f"情绪事件来源：{sentiment_summary}"):
            for item in raw_news:
                title = item.get("title", "")
                url = item.get("url", "")
                snippet = item.get("snippet", "")
                if url:
                    link_text = title if title else (snippet[:60] + "…" if snippet else "查看原文")
                    st.markdown(f"- [{link_text}]({url})")
                elif title:
                    st.markdown(f"- {title}")
                if snippet:
                    st.caption(snippet[:150])


def _render_compare_section(full_data, initial_cash, strategy_name, start_dt, end_dt,
                            sentiment_events, sizer_instance, sentiment_mode, item_label):
    """策略横向对比：所有策略默认参数 vs 买入持有基准"""
    st.markdown("---")
    st.subheader("策略横向对比")
    st.caption(f"同一{item_label}、同一时段、同一初始资金下，各策略使用默认参数的回测表现")

    compare_rows = []
    total_strategies = len(STRATEGY_REGISTRY)
    compare_progress = st.progress(0)
    compare_status = st.empty()
    for i, (s_name, s_info) in enumerate(STRATEGY_REGISTRY.items()):
        default_params = {pn: prange[2] for pn, prange in s_info["params"].items()}
        try:
            s_result = run_backtest(
                full_data, s_info["class"], default_params,
                initial_cash=initial_cash, strategy_name=s_name,
                trade_start=start_dt, trade_end=end_dt,
                sentiment_events=sentiment_events,
                position_sizer=sizer_instance)
            m = s_result["metrics"]
        except Exception:
            continue
        is_current = (s_name == strategy_name)
        compare_rows.append({
            "策略": f"{'★ ' if is_current else ''}{s_name}",
            "总收益率": m["总收益率"],
            "年化收益率": m["年化收益率"],
            "最大回撤": m["最大回撤"],
            "夏普比率": m["夏普比率"],
            "胜率": m["胜率"],
            "交易次数": m["交易次数"],
            "最终资金": m["最终资金"],
            "买入持有": m["买入持有"],
            "_current": is_current,
            "_return_val": _parse_pct(m["总收益率"]),
        })
        compare_progress.progress((i + 1) / total_strategies)
        compare_status.text(f"正在对比策略... {i + 1}/{total_strategies}")

    compare_progress.empty()
    compare_status.empty()

    bh_data = full_data[(full_data.index >= start_dt) & (full_data.index < end_dt)]
    bh_return = 0.0
    bh_annual_return = 0.0
    bh_max_dd = 0.0
    bh_final_cash = initial_cash
    if len(bh_data) > 1:
        first_close = float(bh_data.iloc[0]["close"])
        last_close = float(bh_data.iloc[-1]["close"])
        if first_close > 0:
            bh_return = (last_close - first_close) / first_close * 100
            days = (bh_data.index[-1] - bh_data.index[0]).days
            years = max(days / 365.25, 1 / 365.25)
            bh_annual_return = (((last_close / first_close) ** (1 / years)) - 1) * 100
            close_prices = bh_data["close"].values
            peak = float(close_prices[0])
            bh_max_dd = 0.0
            for p in close_prices:
                p_val = float(p)
                if p_val > peak:
                    peak = p_val
                dd = (peak - p_val) / peak * 100
                if dd > bh_max_dd:
                    bh_max_dd = dd
            bh_final_cash = initial_cash * (1 + bh_return / 100)

    compare_rows.append({
        "策略": "📊 买入持有",
        "总收益率": f"{bh_return:.2f}%",
        "年化收益率": f"{bh_annual_return:.2f}%",
        "最大回撤": f"{bh_max_dd:.2f}%",
        "夏普比率": "—",
        "胜率": "—",
        "交易次数": "0",
        "最终资金": f"¥{bh_final_cash:,.2f}",
        "买入持有": f"{bh_return:.2f}%",
        "_current": False,
        "_return_val": bh_return,
    })

    compare_rows.sort(key=lambda r: r["_return_val"], reverse=True)
    compare_df = pd.DataFrame(compare_rows)
    display_cols = ["策略", "总收益率", "年化收益率", "最大回撤", "夏普比率", "胜率", "交易次数", "最终资金", "买入持有"]
    st.dataframe(
        compare_df[display_cols], use_container_width=True, hide_index=True,
        column_config={
            "总收益率": st.column_config.NumberColumn(format="%.2f%%", help="策略回测期间的总盈亏百分比，已扣除交易费用"),
            "年化收益率": st.column_config.NumberColumn(format="%.2f%%", help="按复利折算的年均收益率"),
            "最大回撤": st.column_config.NumberColumn(format="%.2f%%", help="期间净值从最高点到最低点的最大跌幅"),
            "夏普比率": st.column_config.NumberColumn(format="%.2f", help="风险调整后收益，越大越好"),
            "胜率": st.column_config.NumberColumn(format="%.1f%%", help="盈利交易次数占总交易次数的比例"),
            "最终资金": st.column_config.NumberColumn(format="¥%.2f"),
            "买入持有": st.column_config.NumberColumn(format="%.2f%%", help="不进行任何交易，从期初持有到期末的收益率"),
        })
    st.caption("★ 标记为当前选中的策略  |  📊 买入持有 = 不进行任何交易，从期初持有到期末")

    _render_comparison_analysis(compare_df, sentiment_mode, sentiment_events, bh_return, start_dt, end_dt)
def _render_comparison_analysis(compare_df, sentiment_mode, sentiment_events, bh_return, start_dt, end_dt):
    """横向对比复盘分析：解释排名原因"""
    if compare_df.empty or len(compare_df) < 2:
        return

    # 提取策略行（排除买入持有基准行），按总收益率排序
    strategy_rows = compare_df[compare_df["策略"] != "📊 买入持有"].copy()
    if strategy_rows.empty:
        return

    # 提取数值
    strategy_rows["_return_val"] = strategy_rows["_return_val"].astype(float)
    ranked = strategy_rows.sort_values("_return_val", ascending=False)

    top = ranked.iloc[0]
    bottom = ranked.iloc[-1]

    top_name = top["策略"].replace("★ ", "")
    top_ret = float(top["_return_val"])
    bottom_name = bottom["策略"].replace("★ ", "")
    bottom_ret = float(bottom["_return_val"])
    strategy_count = len(ranked)

    # ---- 市场环境判断 ----
    days = (end_dt - start_dt).days
    months = max(days / 30, 1)
    if bh_return > 8:
        market_label = "单边上涨牛市"
        market_verdict = "趋势类策略普遍优于均值回归类策略"
    elif bh_return > 2:
        market_label = "温和上涨"
        market_verdict = "趋势策略略有优势，但震荡策略也能低吸高抛获利"
    elif bh_return > -2:
        market_label = "横盘震荡"
        market_verdict = "均值回归类策略（RSI、布林带）反复低吸高抛占优，趋势策略容易被反复打脸"
    elif bh_return > -8:
        market_label = "温和下跌"
        market_verdict = "做多策略普遍承压；能捕捉反弹的震荡策略和止损机制严的策略相对抗跌"
    else:
        market_label = "单边下跌熊市"
        market_verdict = "所有做多策略都难逃亏损，差异主要来自止损是否及时"

    # ---- 策略类型分析 ----
    trend_strategies = {"双均线交叉", "MACD 策略", "卡尔曼滤波趋势", "HMA 低延迟均线",
                        "线性回归斜率", "一目均衡表", "唐奇安通道突破", "ADX 趋势强度",
                        "抛物线 SAR", "成交量加权 MACD"}
    mean_reversion_strategies = {"RSI 超买超卖", "布林带策略"}

    top_is_trend = top_name in trend_strategies
    top_is_mr = top_name in mean_reversion_strategies
    bottom_is_trend = bottom_name in trend_strategies
    bottom_is_mr = bottom_name in mean_reversion_strategies

    # ---- 分段解释 ----
    lines = [
        f"### 横向对比复盘",
        "",
        f"**回测区间**：{start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}（约 {int(months)} 个月）",
        f"**市场环境**：{market_label}（买入持有收益 {bh_return:+.1f}%）",
        f"**参评策略**：{strategy_count} 个",
        "",
        f"**{market_verdict}**",
        "",
    ]

    # 冠军分析
    if top_is_trend:
        stype = "趋势跟踪"
    elif top_is_mr:
        stype = "均值回归"
    else:
        stype = "混合型"

    lines.append(f"**冠军**「{top_name}」({stype}型) 收益率 {top_ret:+.1f}%：")
    if top_is_trend and bh_return > 2:
        lines.append(f"- 牛市中趋势策略能完整吃到主升浪，{top_name} 的趋势识别机制在上涨段开仓积极、持仓坚定")
    elif top_is_trend and bh_return <= 2:
        lines.append(f"- 震荡/下跌市中{top_name}仍能跑赢，可能归因于其止损机制及时控制亏损，或捕捉到个别反弹波段")
    elif top_is_mr and abs(bh_return) < 5:
        lines.append(f"- 震荡市中{top_name}反复低吸高抛，积小胜为大胜，资金利用率高")
    elif top_is_mr:
        lines.append(f"- {top_name} 在非典型行情中仍能通过精确的入场/离场点捕捉到波段机会")

    # 垫底分析
    if bottom_is_trend:
        stype_b = "趋势跟踪"
    elif bottom_is_mr:
        stype_b = "均值回归"
    else:
        stype_b = "混合型"

    lines.append("")
    lines.append(f"**垫底**「{bottom_name}」({stype_b}型) 收益率 {bottom_ret:+.1f}%：")
    if bottom_is_trend and bh_return < 2:
        lines.append(f"- 震荡/下跌市中趋势策略容易被反复假突破磨损，{bottom_name} 可能在横盘期频繁开平仓导致手续费侵蚀利润")
    elif bottom_is_trend:
        lines.append(f"- 牛市里趋势策略垫底通常是因为参数偏保守（止损过紧、信号确认太晚），未充分吃到趋势段")
    elif bottom_is_mr and bh_return > 5:
        lines.append(f"- 单边牛市中均值回归策略会过早离场，{bottom_name} 吃到反弹就卖，错过主升浪")
    elif bottom_is_mr:
        lines.append(f"- 下跌市中均值回归策略抄底后价格继续跌，屡抄屡亏")

    # 情绪模式补充
    if sentiment_mode and sentiment_events:
        scores = [s for _, s, _ in sentiment_events]
        avg_score = sum(scores) / len(scores) if scores else 0
        if avg_score > 0.3:
            sent_desc = "整体偏乐观"
        elif avg_score > -0.3:
            sent_desc = "情绪中性"
        else:
            sent_desc = "整体偏悲观"
        pos_count = sum(1 for s in scores if s > 0)
        neg_count = sum(1 for s in scores if s < 0)
        lines.append("")
        lines.append(f"**情绪信号**：{sent_desc}（正面事件 {pos_count} 条，负面事件 {neg_count} 条，平均分 {avg_score:+.2f}）")
        if avg_score > 0:
            lines.append("- 乐观情绪下策略普遍持仓更积极，趋势策略受益更明显")
        else:
            lines.append("- 悲观情绪触发空仓机制，对趋势策略的保护优于均值回归策略")

    lines.append("")
    lines.append("*以上分析基于默认参数回测结果，参数优化后可改变排名。市场环境判断依赖于买入持有收益，不代表未来走势。*")

    st.info("\n".join(lines))

# ============================================================
#  _render_fund  — 基金策略回测（侧边栏参数 + 主区图表）
# ============================================================
def _render_fund(item, theme):
    """策略/参数 → 侧边栏；收益指标 + 净值图/交易明细 → 主区域"""

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**{item['name']}**  ({item['code']})\n\n*[基金]*")

    # ---- 侧边栏：共享参数组件 ----
    sb = _get_common_sidebar_params(prefix="fund_", default_sentiment=True, min_cash=1000)
    strategy_name = sb["strategy_name"]
    strat_info = sb["strat_info"]
    backtest_start = sb["backtest_start"]
    backtest_end = sb["backtest_end"]
    initial_cash = sb["initial_cash"]
    params = sb["params"]
    sizer_instance = sb["sizer_instance"]
    sentiment_mode = sb["sentiment_mode"]

    # ---- 情绪事件抓取（基金特有） ----
    sentiment_events = None
    raw_news = None
    sentiment_summary = ""
    if sentiment_mode:
        with st.spinner(f"抓取 {item['name']} 相关市场新闻..."):
            try:
                raw_news = fetch_news(item["name"], max_results=12)
                sentiment_events = parse_events_from_search(raw_news, item["name"])
                if sentiment_events:
                    sentiment_summary = summarize_news(raw_news)
                else:
                    st.sidebar.warning("未获取到相关新闻")
            except Exception:
                st.sidebar.warning("新闻抓取失败，已关闭情绪模式")
                sentiment_mode = False

    # ---- 净值数据获取（缓存，仅切换基金时重新拉取） ----
    nav_cache_key = f"fund_nav_{item['code']}"
    if nav_cache_key not in st.session_state:
        with st.spinner(f"获取 {item['name']} ({item['code']}) 净值数据..."):
            nav_df = get_fund_nav(item["code"])
        if nav_df is None or nav_df.empty:
            st.error(f"获取 {item['name']} 净值数据失败")
            return
        st.session_state[nav_cache_key] = nav_df

    nav_df = st.session_state[nav_cache_key]
    full_data = fund_nav_to_ohlcv(nav_df)

    # 情绪模式：从价格数据补充合成事件，覆盖全回测区间
    if sentiment_mode and sentiment_events is not None:
        price_events = generate_events_from_price(full_data, item["name"], target_count=30)
        sentiment_events.extend(price_events)
        seen = set()
        deduped = []
        for e in sorted(sentiment_events, key=lambda x: x[0]):
            key = (e[0], e[2])
            if key not in seen:
                seen.add(key)
                deduped.append(e)
        sentiment_events = deduped
        st.sidebar.caption(f"已抓取 {len(sentiment_events)} 条情绪事件（含价格驱动）")

    # ---- 交易窗口检查 ----
    start_dt = pd.Timestamp(backtest_start)
    end_dt = pd.Timestamp(backtest_end) + pd.Timedelta(days=1)
    trade_check = full_data[(full_data.index >= start_dt) & (full_data.index < end_dt)]
    if trade_check.empty:
        st.warning(f"回测日期 {backtest_start} ~ {backtest_end} 内无可用数据")
        return

    # ---- 参数指纹 → 图表版本 ----
    fp = f"{strategy_name}|{sorted(params.items())}|{backtest_start}|{backtest_end}|{initial_cash}"
    if st.session_state.get("_fund_fp") != fp:
        st.session_state.fund_chart_version = st.session_state.get("fund_chart_version", 0) + 1
        st.session_state["_fund_fp"] = fp

    # ---- 运行回测 ----
    with st.spinner(f"运行「{strategy_name}」..."):
        result = run_backtest(full_data, strat_info["class"], params,
                              initial_cash=initial_cash, strategy_name=strategy_name,
                              trade_start=start_dt, trade_end=end_dt,
                              sentiment_events=sentiment_events,
                              position_sizer=sizer_instance)

    # ---- 指标卡片 ----
    _render_common_metrics(result["metrics"])

    # ======== 主区域：图表 + 明细 ========
    st.caption(
        f"全量数据：{full_data.index[0].strftime('%Y-%m-%d')} ~ {full_data.index[-1].strftime('%Y-%m-%d')}"
        f"，共 {len(full_data)} 日 | 交易区间 {len(result['data'])} 日"
    )

    explanation = result.get("explanation", {})
    if explanation:
        with st.expander(f"「{strategy_name}」大白话解释", expanded=False):
            st.markdown(render_strategy_card(strategy_name, explanation))

    full_high = float(result["data"]["close"].max())
    full_low = float(result["data"]["close"].min())
    pad = (full_high - full_low) * 0.15
    price_lo, price_hi = st.slider(
        "纵轴（净值）范围",
        min_value=round(full_low - pad, 4),
        max_value=round(full_high + pad, 4),
        value=(round(full_low, 4), round(full_high, 4)), step=0.0001, key="fund_price_slider",
    )

    fig = plot_fund_backtest(
        result["data"], result["strategy_name"],
        buy_points=result["buy_points"], sell_points=result["sell_points"],
        trades=result["trades"], yaxis_range=(price_lo, price_hi), theme=theme,
    )

    if "fund_chart_version" not in st.session_state:
        st.session_state.fund_chart_version = 0

    chart_html = _build_chart_html(
        fig, version=st.session_state.fund_chart_version, theme=theme,
        auto_zoom=False,
    )
    st.components.v1.html(chart_html, height=730)
    st.caption("点击折线放大 | 双击重置 | Q=缩放 W=平移 E=全览")

    if st.button("重置缩放", key="fund_reset_zoom"):
        st.session_state.fund_chart_version += 1
        st.rerun()

    # ---- 当日新闻（点击图表日期触发） ----
    clicked_date = st.query_params.get("marvis_chart_date", None)
    if clicked_date:
        st.markdown("---")
        st.subheader(f"📰 {clicked_date} 当日资讯")
        if sentiment_events:
            day_events = [e for e in sentiment_events if e[0] == clicked_date]
            if day_events:
                for _date_str, _score, _title in day_events:
                    if _score > 0:
                        st.markdown(
                            f'<div style="background:#e8f5e9;padding:8px 12px;border-radius:6px;margin:4px 0;'
                            f'border-left:4px solid #2e7d32">'
                            f'📈 <b>利好</b> (+{_score}) &nbsp; {_title}</div>',
                            unsafe_allow_html=True)
                    elif _score < 0:
                        st.markdown(
                            f'<div style="background:#ffebee;padding:8px 12px;border-radius:6px;margin:4px 0;'
                            f'border-left:4px solid #c62828">'
                            f'📉 <b>利空</b> ({_score}) &nbsp; {_title}</div>',
                            unsafe_allow_html=True)
                    else:
                        st.markdown(
                            f'<div style="color:#888;padding:4px 12px;margin:2px 0">'
                            f'➖ 中性 &nbsp; {_title}</div>',
                            unsafe_allow_html=True)
            else:
                st.info("当日无相关新闻")
        else:
            st.info("当日无相关新闻（请先开启情绪模式）")

    # ---- 交易明细 ----
    _render_trade_table(result, sentiment_mode, raw_news, sentiment_summary)

    # ---- 策略横向对比 ----
    _render_compare_section(full_data, initial_cash, strategy_name, start_dt, end_dt,
                            sentiment_events, sizer_instance, sentiment_mode, "基金")

# ============================================================
#  _render_backtest  — 股票回测（侧边栏参数 + 主区 K 线）
# ============================================================
def _render_backtest(item, theme):
    """策略/参数 → 侧边栏；收益指标 + K 线/交易明细 → 主区域"""
    is_demo = item["type"] == "demo"

    # ---- 侧边栏：标的标识 ----
    if not is_demo:
        st.sidebar.markdown(f"**{item['name']}**  ({item['code']})\n\n*[股票]*")
    else:
        st.sidebar.markdown("*[演示数据 — 模拟走势]*")

    # ---- 侧边栏：共享参数组件 ----
    sb = _get_common_sidebar_params(prefix="", default_sentiment=False, min_cash=10000)
    strategy_name = sb["strategy_name"]
    strat_info = sb["strat_info"]
    backtest_start = sb["backtest_start"]
    backtest_end = sb["backtest_end"]
    initial_cash = sb["initial_cash"]
    params = sb["params"]
    sizer_instance = sb["sizer_instance"]
    sentiment_mode = sb["sentiment_mode"]

    # ---- 情绪事件抓取（股票特有） ----
    sentiment_events = None
    raw_news = None
    sentiment_summary = ""
    if sentiment_mode:
        with st.spinner(f"抓取 {item['name']} 相关市场新闻..."):
            try:
                raw_news = fetch_news(item["name"], max_results=12)
                sentiment_events = parse_events_from_search(raw_news, item["name"])
                if sentiment_events:
                    sentiment_summary = summarize_news(raw_news)
                else:
                    st.sidebar.warning("未获取到相关新闻")
            except Exception:
                st.sidebar.warning("新闻抓取失败，已关闭情绪模式")
                sentiment_mode = False

    # ---- 数据获取（缓存，仅切换标的时重新拉取） ----
    if is_demo:
        full_data = generate_demo_data(300)
    else:
        stock_cache_key = f"stock_data_{item['code']}"
        if stock_cache_key not in st.session_state:
            with st.spinner(f"获取 {item['name']} ({item['code']}) 数据..."):
                raw = get_stock_data(item["code"])
            if raw is None or raw.empty:
                st.error(f"获取 {item['name']} 数据失败")
                return
            st.session_state[stock_cache_key] = raw
        full_data = st.session_state[stock_cache_key]

    # 情绪模式：从价格数据补充合成事件，覆盖全回测区间
    if sentiment_mode and sentiment_events is not None:
        price_events = generate_events_from_price(full_data, item["name"], target_count=30)
        sentiment_events.extend(price_events)
        seen = set()
        deduped = []
        for e in sorted(sentiment_events, key=lambda x: x[0]):
            key = (e[0], e[2])
            if key not in seen:
                seen.add(key)
                deduped.append(e)
        sentiment_events = deduped
        st.sidebar.caption(f"已抓取 {len(sentiment_events)} 条情绪事件（含价格驱动）")

    # ---- 交易窗口检查 ----
    start_dt = pd.Timestamp(backtest_start)
    end_dt = pd.Timestamp(backtest_end) + pd.Timedelta(days=1)
    trade_check = full_data[(full_data.index >= start_dt) & (full_data.index < end_dt)]
    if trade_check.empty:
        st.warning(f"回测日期 {backtest_start} ~ {backtest_end} 内无可用数据")
        return

    # ---- 参数指纹 → 图表版本 ----
    fp = f"{strategy_name}|{sorted(params.items())}|{backtest_start}|{backtest_end}|{initial_cash}"
    if st.session_state.get("_stock_fp") != fp:
        st.session_state.chart_version = st.session_state.get("chart_version", 0) + 1
        st.session_state["_stock_fp"] = fp

    # ---- 运行回测 ----
    with st.spinner(f"运行「{strategy_name}」..."):
        result = run_backtest(full_data, strat_info["class"], params,
                              initial_cash=initial_cash, strategy_name=strategy_name,
                              trade_start=start_dt, trade_end=end_dt,
                              sentiment_events=sentiment_events,
                              position_sizer=sizer_instance)

    # ---- 指标卡片 ----
    _render_common_metrics(result["metrics"])

    # ======== 主区域：K 线 + 明细 ========
    if is_demo:
        st.caption("演示数据（模拟走势）")
    else:
        st.caption(
            f"全量数据：{full_data.index[0].strftime('%Y-%m-%d')} ~ {full_data.index[-1].strftime('%Y-%m-%d')}"
            f"，共 {len(full_data)} 个交易日 | 交易区间 {len(result['data'])} 日"
        )

    explanation = result.get("explanation", {})
    if explanation:
        with st.expander(f"「{strategy_name}」大白话解释", expanded=False):
            st.markdown(render_strategy_card(strategy_name, explanation))

    full_high = float(result["data"]["high"].max())
    full_low = float(result["data"]["low"].min())
    pad = (full_high - full_low) * 0.15
    price_lo, price_hi = st.slider(
        "纵轴（价格）范围",
        min_value=float(int(full_low - pad)),
        max_value=float(int(full_high + pad) + 1),
        value=(full_low, full_high), step=0.5, key="price_slider",
    )

    fig = plot_backtest(
        result["data"], result["strategy_name"], chart_mode="K线图",
        buy_points=result["buy_points"], sell_points=result["sell_points"],
        trades=result["trades"], yaxis_range=(price_lo, price_hi), theme=theme,
    )

    if "chart_version" not in st.session_state:
        st.session_state.chart_version = 0

    chart_html = _build_chart_html(
        fig, version=st.session_state.chart_version, theme=theme,
        auto_zoom=False,
    )
    st.components.v1.html(chart_html, height=780)
    st.caption("点击 K 线 → 放大 60 天 | 双击空白 → 重置 | Q=缩放 W=平移 E=全览")

    if st.button("重置缩放", key="reset_zoom"):
        st.session_state.chart_version += 1
        st.rerun()

    # ---- 当日新闻（点击图表日期触发） ----
    clicked_date = st.query_params.get("marvis_chart_date", None)
    if clicked_date:
        st.markdown("---")
        st.subheader(f"📰 {clicked_date} 当日资讯")
        if sentiment_events:
            day_events = [e for e in sentiment_events if e[0] == clicked_date]
            if day_events:
                for _date_str, _score, _title in day_events:
                    if _score > 0:
                        st.markdown(
                            f'<div style="background:#e8f5e9;padding:8px 12px;border-radius:6px;margin:4px 0;'
                            f'border-left:4px solid #2e7d32">'
                            f'📈 <b>利好</b> (+{_score}) &nbsp; {_title}</div>',
                            unsafe_allow_html=True)
                    elif _score < 0:
                        st.markdown(
                            f'<div style="background:#ffebee;padding:8px 12px;border-radius:6px;margin:4px 0;'
                            f'border-left:4px solid #c62828">'
                            f'📉 <b>利空</b> ({_score}) &nbsp; {_title}</div>',
                            unsafe_allow_html=True)
                    else:
                        st.markdown(
                            f'<div style="color:#888;padding:4px 12px;margin:2px 0">'
                            f'➖ 中性 &nbsp; {_title}</div>',
                            unsafe_allow_html=True)
            else:
                st.info("当日无相关新闻")
        else:
            st.info("当日无相关新闻（请先开启情绪模式）")

    # ---- 交易明细 ----
    _render_trade_table(result, sentiment_mode, raw_news, sentiment_summary)

    # ---- 策略横向对比 ----
    _render_compare_section(full_data, initial_cash, strategy_name, start_dt, end_dt,
                            sentiment_events, sizer_instance, sentiment_mode, "股票")
