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
from core.data_fetcher import STOCK_POOL, get_stock_data, generate_demo_data, fund_nav_to_ohlcv
from core.engine import run_backtest
from utils.chart import plot_backtest, render_strategy_card, plot_fund_backtest

# ---- pypinyin 智能搜索 ----
try:
    from pypinyin import lazy_pinyin
    _PY_AVAIL = True
except ImportError:
    _PY_AVAIL = False

# 基金原始数据
_FUNDS_RAW = [
    ("011172", "广发利鑫混合C"),
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
    """构建统一数据池：演示数据 + 股票 + 基金"""
    pool = []
    # 股票
    for name, code in STOCK_POOL.items():
        py, pyf = _make_pinyin(name)
        pool.append({"type": "stock", "code": code, "name": name,
                     "pinyin": py, "pinyin_first": pyf})
    # 基金
    for code, name in _FUNDS_RAW:
        py, pyf = _make_pinyin(name)
        pool.append({"type": "fund", "code": code, "name": name,
                     "pinyin": py, "pinyin_first": pyf})
    return pool


UNIFIED_POOL = _make_unified_pool()
TYPE_TAGS = {"demo": "演示", "stock": "股票", "fund": "基金"}


def get_fund_nav(code):
    """通过 akshare 获取基金净值历史"""
    try:
        import akshare as ak
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        df = df.rename(columns={"净值日期": "date", "单位净值": "nav"})
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
        #_dbg {{ display: none; }}
    </style>
</head>
<body>
<div id="_dbg">...</div>
{fig_html}
<script>
window.__chartAutoZoom = {'true' if auto_zoom else 'false'};
(function() {{
    var gd = null;
    var dbg = document.getElementById('_dbg');
    var clickCount = 0;
    var zoomReady = false;

    function log(msg) {{
        dbg.textContent = msg;
        console.log('[chart] ' + msg);
    }}

    var _vLog = [];
    function vlog(tag, payload) {{
        var ts = new Date().toISOString().slice(11,23);
        var entry = '[' + ts + '] ' + tag;
        if (payload !== undefined) {{
            try {{ entry += ' ' + JSON.stringify(payload).slice(0,500); }} catch(e) {{ entry += ' ' + String(payload).slice(0,500); }}
        }}
        _vLog.unshift(entry);
        if (_vLog.length > 40) _vLog.length = 40;
        console.log('[chart-d] ' + entry);
        dbg.textContent = _vLog.slice(0, 15).join('\\n');
        scheduleDump();
    }}
    function dumpLog() {{ console.table(_vLog.map(function(s) {{ return {{entry:s}}; }})); }}

    var _dumpUrl = 'http://127.0.0.1:19876/log';
    function dumpToFile() {{
        var payload = JSON.stringify({{time: new Date().toISOString(),
            autorange: {{x:(gd._fullLayout||{{}}).xaxis||{{}}.autorange, y:(gd._fullLayout||{{}}).yaxis||{{}}.autorange}},
            dragmode: (gd._fullLayout||{{}}).dragmode, clickCount: clickCount, log: _vLog}});
        var img = new Image();
        img.src = _dumpUrl + '?d=' + encodeURIComponent(payload);
        img.onerror = function(){{}};
    }}
    document.addEventListener('keydown', function(e) {{
        if (e.key === 'd' && !e.ctrlKey && !e.metaKey && !e.altKey) {{ dumpToFile(); }}
    }});
    var _dumpTimer = null;
    function scheduleDump() {{
        if (_dumpTimer) clearTimeout(_dumpTimer);
        _dumpTimer = setTimeout(dumpToFile, 1000);
    }}

    function spyPlotlyEvents() {{
        var origEmit = gd.emit;
        gd.emit = function() {{
            var eventName = arguments[0];
            if (eventName === 'plotly_click' || eventName === 'plotly_relayout' ||
                eventName === 'plotly_doubleclick' || eventName === 'plotly_afterplot') {{
                var hasPoints = '???';
                if (eventName === 'plotly_click') {{
                    try {{ hasPoints = arguments[1] && arguments[1].points ? arguments[1].points.length : 0; }} catch(e) {{ hasPoints = 'err'; }}
                }}
                vlog('EMIT:' + eventName + ' pts=' + hasPoints);
            }}
            return origEmit.apply(this, arguments);
        }};
        vlog('spy-installed');
    }}

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
        vlog('bindClickHandlers BEGIN');
        gd.removeAllListeners('plotly_click');
        gd.removeAllListeners('plotly_selected');
        gd.removeAllListeners('plotly_doubleclick');

        gd.on('plotly_click', function(data) {{
            clickCount++;
            var pts = (data && data.points) ? data.points.length : 0;
            vlog('CLICK#' + clickCount + ' pts=' + pts);
            if (!pts) return;
            var pt = data.points[0];
            var allX = pt.data.x;
            if (!allX || allX.length === 0) return;
            var idx = findDateIndex(allX, pt.x);
            if (idx < 0) return;
            vlog('ZOOM from=' + idx);
            zoomToRange(allX, idx - 30, idx + 30);
        }});

        gd.on('plotly_selected', function(data) {{
            vlog('SELECT range=' + (data && data.range ? JSON.stringify(data.range) : 'null'));
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

        vlog('bindClickHandlers DONE');
    }}

    function dumpAutorangeState(tag) {{
        try {{
            var la = gd._fullLayout || {{}};
            var xa = la.xaxis || {{}}, ya = la.yaxis || {{}};
            vlog('AUTORANGE:' + tag + ' x=' + xa.autorange + ' y=' + ya.autorange +
                 ' dm=' + la.dragmode + ' xrange=' + JSON.stringify(xa.range).slice(0,80));
        }} catch(e) {{ vlog('AUTORANGE:' + tag + ' err'); }}
    }}

    function setupZoom() {{
        if (zoomReady || !gd) {{ vlog('setupZoom skip ready=' + zoomReady + ' gd=' + !!gd); return; }}
        zoomReady = true;
        vlog('setupZoom START');
        spyPlotlyEvents();
        bindClickHandlers();
        dumpAutorangeState('initial');

        var rebindLock = false;
        gd.on('plotly_relayout', function(eventData) {{
            if (rebindLock) {{ vlog('RELAYOUT skip (locked)'); return; }}
            rebindLock = true;
            var isAutoscale = eventData && ('xaxis.autorange' in eventData || 'yaxis.autorange' in eventData);
            var delay = isAutoscale ? 300 : 80;
            setTimeout(function() {{
                if (isAutoscale) {{
                    Plotly.relayout(gd, {{'xaxis.autorange': false, 'yaxis.autorange': false}});
                    dumpAutorangeState('after-disable-autorange');
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

        log('ready');
        var currentDrag = (gd._fullLayout || {{}}).dragmode || 'pan';
        vlog('setupZoom warm-up dragmode=' + currentDrag);

        if (window.__chartAutoZoom) {{
            vlog('auto-zoom START (skip warm-up)');
            Plotly.relayout(gd, {{'xaxis.autorange': true, 'yaxis.autorange': true}});
            setTimeout(function() {{
                var btn = gd.querySelector('.modebar-btn[data-attr="zoom"][data-val="out"]');
                if (btn) {{ btn.click(); vlog('auto-zoom zoomout click OK'); }}
                else {{ vlog('auto-zoom zoomout btn missing'); }}
            }}, 150);
        }} else {{
            Plotly.relayout(gd, {{'xaxis.autorange': false, 'yaxis.autorange': false, dragmode: currentDrag}});
        }}
        dumpAutorangeState('after-init-disable');
        vlog('setupZoom DONE');
    }}

    function tryInit() {{
        gd = document.getElementById('{chart_id}');
        if (!gd) gd = document.querySelector('.js-plotly-plot');
        if (!gd) gd = document.querySelector('.plotly-graph-div');
        if (!gd) gd = document.querySelector('[id^="chart_"]');
        if (!gd) {{ log('no-div'); setTimeout(tryInit, 300); return; }}
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
        getLog: function() {{ return _vLog; }},
        dumpLog: dumpLog, dumpToFile: dumpToFile,
        getGd: function() {{ return gd; }},
        dumpAutorange: function() {{ dumpAutorangeState('manual'); }},
        getClickCount: function() {{ return clickCount; }}
    }};
    console.log('[chart] Debug API at window.__chartDebug');
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
        var dbg = document.getElementById('_dbg');
        if (key === 'q') {{
            e.preventDefault();
            Plotly.relayout(gd, {{dragmode: 'zoom'}});
            if (dbg) {{ dbg.textContent = 'Tool: ZOOM'; setTimeout(function(){{dbg.textContent='...'}},1200); }}
        }} else if (key === 'w') {{
            e.preventDefault();
            Plotly.relayout(gd, {{dragmode: 'pan'}});
            if (dbg) {{ dbg.textContent = 'Tool: PAN'; setTimeout(function(){{dbg.textContent='...'}},1200); }}
        }} else if (key === 'e') {{
            e.preventDefault();
            Plotly.relayout(gd, {{'xaxis.autorange': true, 'yaxis.autorange': true}});
            setTimeout(function() {{
                var zoomOutBtn = gd.querySelector('.modebar-btn[data-attr="zoom"][data-val="out"]');
                if (zoomOutBtn) zoomOutBtn.click();
            }}, 150);
            if (dbg) {{ dbg.textContent = 'AUTOSCALE'; setTimeout(function(){{dbg.textContent='...'}},1200); }}
        }} else if (key === 'a') {{
            e.preventDefault();
            var zin = gd.querySelector('.modebar-btn[data-attr="zoom"][data-val="in"]');
            if (zin) zin.click();
            if (dbg) {{ dbg.textContent = 'ZOOM IN (A)'; setTimeout(function(){{dbg.textContent='...'}},800); }}
        }} else if (key === 's') {{
            e.preventDefault();
            var zout = gd.querySelector('.modebar-btn[data-attr="zoom"][data-val="out"]');
            if (zout) zout.click();
            if (dbg) {{ dbg.textContent = 'ZOOM OUT (S)'; setTimeout(function(){{dbg.textContent='...'}},800); }}
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

    # ---- 侧边栏指标列自适应宽度 ----
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
    }
    section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        min-width: 105px !important;
        flex: 1 1 auto !important;
    }
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
def _render_fund(item, theme):
    """收益指标置顶 → 策略/参数/收益指标 → 侧边栏；净值图/交易明细 → 主区域"""

    # ---- 侧边栏顶部占位（回测后填入收益指标） ----
    metrics_placeholder = st.sidebar.empty()

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**{item['name']}**  ({item['code']})\n\n*[基金]*")

    # ---- 侧边栏：策略选择 ----
    strategy_name = st.sidebar.selectbox("选择策略", list(STRATEGY_REGISTRY.keys()), key="fund_s")
    strat_info = STRATEGY_REGISTRY[strategy_name]
    st.sidebar.caption(strat_info["desc"])

    # ---- 侧边栏：日期与资金 ----
    st.sidebar.markdown("**回测参数**")
    backtest_start = st.sidebar.date_input(
        "起始日期", value=datetime.now() - timedelta(days=365 * 3),
        min_value=datetime(2000, 1, 1), max_value=datetime.now(), key="fund_bs_start",
    )
    backtest_end = st.sidebar.date_input(
        "结束日期", value=datetime.now(),
        min_value=datetime(2000, 1, 1), max_value=datetime.now(), key="fund_bs_end",
    )
    initial_cash = st.sidebar.number_input("初始资金（元）", 1000, 10000000, 100000, 10000, key="fund_cash")

    # ---- 侧边栏：策略参数滑块 ----
    st.sidebar.markdown("**策略参数**")
    params = {}
    labels = strat_info.get("param_labels", {})
    for pn, (pmin, pmax, pdef) in strat_info["params"].items():
        step = 0.1 if isinstance(pdef, float) else 1
        label = labels.get(pn, pn)
        params[pn] = st.sidebar.slider(label, pmin, pmax, pdef, step, key=f"fund_p_{pn}")

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

    # ---- 日期过滤 ----
    start_dt = pd.Timestamp(backtest_start)
    end_dt = pd.Timestamp(backtest_end) + pd.Timedelta(days=1)
    data = full_data[(full_data.index >= start_dt) & (full_data.index < end_dt)]
    if data.empty:
        st.warning(f"回测日期 {backtest_start} ~ {backtest_end} 内无可用数据")
        return

    # ---- 参数指纹 → 图表版本 ----
    fp = f"{strategy_name}|{sorted(params.items())}|{backtest_start}|{backtest_end}|{initial_cash}"
    if st.session_state.get("_fund_fp") != fp:
        st.session_state.fund_chart_version = st.session_state.get("fund_chart_version", 0) + 1
        st.session_state["_fund_fp"] = fp

    # ---- 运行回测 ----
    with st.spinner(f"运行「{strategy_name}」..."):
        result = run_backtest(data, strat_info["class"], params,
                              initial_cash=initial_cash, strategy_name=strategy_name)

    # ---- 侧边栏顶部：收益指标 ----
    with metrics_placeholder.container():
        m = result["metrics"]
        c1, c2 = st.columns(2)
        c1.metric("总收益率", m["总收益率"], delta=m.get("超额收益", ""))
        c2.metric("最大回撤", m["最大回撤"])
        c3, c4 = st.columns(2)
        c3.metric("夏普比率", m["夏普比率"])
        c4.metric("胜率", m["胜率"])
        c5, c6 = st.columns(2)
        c5.metric("交易次数", m["交易次数"])
        c6.metric("最终资金", m["最终资金"])

    # ======== 主区域：图表 + 明细 ========
    st.caption(
        f"全量数据：{full_data.index[0].strftime('%Y-%m-%d')} ~ {full_data.index[-1].strftime('%Y-%m-%d')}"
        f"，共 {len(full_data)} 日 | 回测区间 {len(data)} 日"
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

    if result["trades"]:
        st.subheader("交易明细")
        trade_df = pd.DataFrame(result["trades"])
        display_cols = [c for c in
                        ["买入时间", "买入价", "买入原因", "卖出时间", "卖出价", "卖出原因", "盈亏"]
                        if c in trade_df.columns]
        st.dataframe(
            trade_df[display_cols], use_container_width=True, hide_index=True,
            column_config={
                "买入价": st.column_config.NumberColumn(format="%.4f"),
                "卖出价": st.column_config.NumberColumn(format="%.4f"),
            }
        )
    else:
        st.info("本次回测期间无交易记录")


# ============================================================
#  _render_backtest  — 股票回测（侧边栏参数 + 主区 K 线）
# ============================================================
def _render_backtest(item, theme):
    """收益指标置顶 → 策略/参数/收益指标 → 侧边栏；K 线/交易明细 → 主区域"""
    is_demo = item["type"] == "demo"

    # ---- 侧边栏顶部占位（回测后填入收益指标） ----
    metrics_placeholder = st.sidebar.empty()

    # ---- 侧边栏：标的标识 ----
    if not is_demo:
        st.sidebar.markdown(f"**{item['name']}**  ({item['code']})\n\n*[股票]*")
    else:
        st.sidebar.markdown("*[演示数据 — 模拟走势]*")

    # ---- 侧边栏：策略选择 ----
    strategy_name = st.sidebar.selectbox("选择策略", list(STRATEGY_REGISTRY.keys()), key="s")
    strat_info = STRATEGY_REGISTRY[strategy_name]
    st.sidebar.caption(strat_info["desc"])

    # ---- 侧边栏：日期与资金 ----
    st.sidebar.markdown("**回测参数**")
    backtest_start = st.sidebar.date_input(
        "起始日期", value=datetime.now() - timedelta(days=365),
        min_value=datetime(2000, 1, 1), max_value=datetime.now(), key="bs_start",
    )
    backtest_end = st.sidebar.date_input(
        "结束日期", value=datetime.now(),
        min_value=datetime(2000, 1, 1), max_value=datetime.now(), key="bs_end",
    )
    initial_cash = st.sidebar.number_input("初始资金（元）", 10000, 10000000, 100000, 10000, key="cash")

    # ---- 侧边栏：策略参数滑块 ----
    st.sidebar.markdown("**策略参数**")
    params = {}
    labels = strat_info.get("param_labels", {})
    for pn, (pmin, pmax, pdef) in strat_info["params"].items():
        step = 0.1 if isinstance(pdef, float) else 1
        label = labels.get(pn, pn)
        params[pn] = st.sidebar.slider(label, pmin, pmax, pdef, step, key=f"p_{pn}")

    # ---- 数据获取（缓存，仅切换标的时重新拉取） ----
    if is_demo:
        data = generate_demo_data(300)
    else:
        stock_cache_key = f"stock_data_{item['code']}"
        if stock_cache_key not in st.session_state:
            with st.spinner(f"获取 {item['name']} ({item['code']}) 数据..."):
                raw = get_stock_data(item["code"])
            if raw is None or raw.empty:
                st.error(f"获取 {item['name']} 数据失败")
                return
            st.session_state[stock_cache_key] = raw
        data = st.session_state[stock_cache_key]

    # ---- 日期过滤 ----
    start_dt = pd.Timestamp(backtest_start)
    end_dt = pd.Timestamp(backtest_end) + pd.Timedelta(days=1)
    data = data[(data.index >= start_dt) & (data.index < end_dt)]
    if data.empty:
        st.warning(f"回测日期 {backtest_start} ~ {backtest_end} 内无可用数据")
        return

    # ---- 参数指纹 → 图表版本 ----
    fp = f"{strategy_name}|{sorted(params.items())}|{backtest_start}|{backtest_end}|{initial_cash}"
    if st.session_state.get("_stock_fp") != fp:
        st.session_state.chart_version = st.session_state.get("chart_version", 0) + 1
        st.session_state["_stock_fp"] = fp

    # ---- 运行回测 ----
    with st.spinner(f"运行「{strategy_name}」..."):
        result = run_backtest(data, strat_info["class"], params,
                              initial_cash=initial_cash, strategy_name=strategy_name)

    # ---- 侧边栏顶部：收益指标 ----
    with metrics_placeholder.container():
        m = result["metrics"]
        c1, c2 = st.columns(2)
        c1.metric("总收益率", m["总收益率"], delta=m.get("超额收益", ""))
        c2.metric("最大回撤", m["最大回撤"])
        c3, c4 = st.columns(2)
        c3.metric("夏普比率", m["夏普比率"])
        c4.metric("胜率", m["胜率"])
        c5, c6 = st.columns(2)
        c5.metric("交易次数", m["交易次数"])
        c6.metric("最终资金", m["最终资金"])

    # ======== 主区域：K 线 + 明细 ========
    if is_demo:
        st.caption("演示数据（模拟走势）")
    else:
        st.caption(
            f"数据范围：{data.index[0].strftime('%Y-%m-%d')} ~ {data.index[-1].strftime('%Y-%m-%d')}"
            f"，共 {len(data)} 个交易日"
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

    if result["trades"]:
        st.subheader("交易明细")
        trade_df = pd.DataFrame(result["trades"])
        display_cols = [c for c in
                        ["买入时间", "买入价", "买入原因", "卖出时间", "卖出价", "卖出原因", "盈亏"]
                        if c in trade_df.columns]
        st.dataframe(
            trade_df[display_cols], use_container_width=True, hide_index=True,
            column_config={
                "买入价": st.column_config.NumberColumn(format="¥%.2f"),
                "卖出价": st.column_config.NumberColumn(format="¥%.2f"),
            }
        )
    else:
        st.info("本次回测期间无交易记录")
