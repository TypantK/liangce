# -*- coding: utf-8 -*-
"""
策略回测页面 v3 — Plotly 交互式图表 + 基金净值浏览 + 智能拼音搜索
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from core.strategies import STRATEGY_REGISTRY
from core.data_fetcher import STOCK_POOL, get_stock_data, generate_demo_data
from core.engine import run_backtest
from utils.chart import plot_backtest, render_strategy_card

# ---- pypinyin 智能搜索 ----
try:
    from pypinyin import lazy_pinyin
    _PY_AVAIL = True
except ImportError:
    _PY_AVAIL = False


def _make_fund_pool():
    """构建带拼音的基金池"""
    funds_raw = [
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
    pool = []
    for code, name in funds_raw:
        if _PY_AVAIL:
            py = ''.join(lazy_pinyin(name))
            pyf = ''.join([p[0] for p in lazy_pinyin(name)])
        else:
            py = name.lower()
            pyf = ''.join([w[0] for w in name])
        pool.append({"code": code, "name": name, "pinyin": py, "pinyin_first": pyf})
    return pool


FUND_POOL = _make_fund_pool()


def search_funds(query):
    """拼音/中文/代码智能搜索"""
    if not query or not query.strip():
        return FUND_POOL
    q = query.strip().lower()
    results = []
    for f in FUND_POOL:
        if (q in f["code"] or q in f["name"].lower() or
                q in f["pinyin"] or q in f["pinyin_first"]):
            results.append(f)
    return results


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
        config={'doubleClick': 'reset', 'displayModeBar': True, 'displaylogo': False},
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
    st.title("策略回测")

    # ========== 侧边栏 ==========
    theme_label = st.sidebar.radio("主题", ["夜间", "白天"], key="theme")
    theme = "dark" if theme_label == "夜间" else "light"

    data_type = st.sidebar.radio("数据类型", ["股票回测", "基金浏览"], key="data_type")

    # ================================================================
    #  模式 1：股票回测（保持全部原有逻辑）
    # ================================================================
    if data_type == "股票回测":
        c1, c2 = st.columns([1, 1])
        with c1:
            strategy_name = st.selectbox("选择策略", list(STRATEGY_REGISTRY.keys()), key="s")
        with c2:
            data_source = st.selectbox("数据源", ["演示数据"] + list(STOCK_POOL.keys()), key="d")

        c4, c5 = st.columns([1, 1])
        with c4:
            backtest_start = st.date_input(
                "回测起始日期",
                value=datetime.now() - timedelta(days=365),
                min_value=datetime(2000, 1, 1),
                max_value=datetime.now(),
                key="bs_start",
            )
        with c5:
            backtest_end = st.date_input(
                "回测结束日期",
                value=datetime.now(),
                min_value=datetime(2000, 1, 1),
                max_value=datetime.now(),
                key="bs_end",
            )

        initial_cash = st.number_input("初始资金（元）", 10000, 10000000, 100000, 10000, key="cash")

        strat_info = STRATEGY_REGISTRY[strategy_name]
        st.caption(strat_info["desc"])

        params = {}
        labels = strat_info.get("param_labels", {})
        pcols = st.columns(len(strat_info["params"]))
        for i, (pn, (pmin, pmax, pdef)) in enumerate(strat_info["params"].items()):
            with pcols[i]:
                step = 0.1 if isinstance(pdef, float) else 1
                label = labels.get(pn, pn)
                params[pn] = st.slider(label, pmin, pmax, pdef, step, key=f"p_{pn}")

        # ===== 回测按钮 =====
        if st.button("开始回测", type="primary", use_container_width=True):
            st.session_state.chart_version = st.session_state.get("chart_version", 0) + 1
            with st.spinner("获取数据..."):
                if data_source == "演示数据":
                    data = generate_demo_data(300)
                else:
                    data = get_stock_data(STOCK_POOL[data_source])
                    if data is None or data.empty:
                        st.error(f"获取 {data_source} 数据失败，请检查网络")
                        return

                if data_source != "演示数据":
                    first_date = data.index[0].strftime('%Y-%m-%d')
                    last_date = data.index[-1].strftime('%Y-%m-%d')
                    st.info(f"数据范围：{first_date} ~ {last_date}，共 {len(data)} 个交易日")

                start_dt = pd.Timestamp(backtest_start)
                end_dt = pd.Timestamp(backtest_end) + pd.Timedelta(days=1)
                data = data[(data.index >= start_dt) & (data.index < end_dt)]
                if data.empty:
                    st.warning(f"回测日期 {backtest_start} ~ {backtest_end} 内无可用数据")
                    return

            with st.spinner(f"运行「{strategy_name}」..."):
                result = run_backtest(
                    data, strat_info["class"], params,
                    initial_cash=initial_cash,
                    strategy_name=strategy_name,
                )

            st.session_state.backtest_result = result
            st.session_state.auto_zoom_pending = True
            st.session_state.full_data = data
            st.session_state.bp_params = params
            st.session_state.bp_strat_class = strat_info["class"]
            st.session_state.bp_strat_name = strategy_name
            st.session_state.bp_cash = initial_cash

        # ===== 渲染回测结果 =====
        if "backtest_result" not in st.session_state or st.session_state.backtest_result is None:
            st.info("点击「开始回测」查看结果")
            return

        result = st.session_state.backtest_result
        st.divider()

        m = result["metrics"]
        mn1, mn2, mn3 = st.columns(3)
        mn1.metric("总收益率", m["总收益率"], delta=m.get("超额收益", ""))
        mn2.metric("最大回撤", m["最大回撤"])
        mn3.metric("夏普比率", m["夏普比率"])
        mn4, mn5, mn6 = st.columns(3)
        mn4.metric("胜率", m["胜率"])
        mn5.metric("交易次数", m["交易次数"])
        mn6.metric("最终资金", m["最终资金"])

        st.divider()

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
            value=(full_low, full_high),
            step=0.5,
            key="price_slider",
        )

        # 自动判断：有 OHLC → K 线
        chart_mode = "K线图"

        fig = plot_backtest(
            result["data"], result["strategy_name"],
            chart_mode=chart_mode,
            buy_points=result["buy_points"],
            sell_points=result["sell_points"],
            trades=result["trades"],
            yaxis_range=(price_lo, price_hi),
            theme=theme,
        )

        if "chart_version" not in st.session_state:
            st.session_state.chart_version = 0

        chart_html = _build_chart_html(
            fig, version=st.session_state.chart_version, theme=theme,
            auto_zoom=st.session_state.get("auto_zoom_pending", False),
        )
        st.session_state.auto_zoom_pending = False
        st.components.v1.html(chart_html, height=780)

        st.caption("提示：点击任意 K 线 → 放大前后约一个月 | 双击空白 → 重置缩放 | Q=缩放 W=平移 E=全览")

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
                trade_df[display_cols],
                use_container_width=True, hide_index=True,
                column_config={
                    "买入价": st.column_config.NumberColumn(format="¥%.2f"),
                    "卖出价": st.column_config.NumberColumn(format="¥%.2f"),
                }
            )
        else:
            st.info("本次回测期间无交易记录")
        return

    # ================================================================
    #  模式 2：基金浏览
    # ================================================================
    st.subheader("基金净值浏览")

    # ---- 基金搜索 ----
    search_query = st.text_input(
        "搜索基金（名称/代码/拼音）",
        placeholder="例如：广发、011172、gflx、yfdl...",
        key="fund_search",
    )
    candidates = search_funds(search_query)

    if not candidates:
        st.warning("无匹配基金")
        return

    # 构建 selectbox 选项
    candidate_labels = [f"{f['name']} ({f['code']})" for f in candidates]
    # 默认选中第一个（广发利鑫 011172）
    default_idx = 0
    for i, f in enumerate(candidates):
        if f["code"] == "011172":
            default_idx = i
            break
    selected_label = st.selectbox(
        "选择基金",
        candidate_labels,
        index=default_idx,
        key="fund_select",
    )

    selected_idx = candidate_labels.index(selected_label)
    fund = candidates[selected_idx]

    # ---- 侧边栏基金信息 ----
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"""
**基金名称**: {fund['name']}  
**基金代码**: {fund['code']}  
""")

    # ---- 获取净值数据 ----
    if "fund_data" not in st.session_state or st.session_state.get("fund_code") != fund["code"]:
        with st.spinner(f"获取 {fund['name']} ({fund['code']}) 净值数据..."):
            nav_df = get_fund_nav(fund["code"])
        if nav_df is None or nav_df.empty:
            st.error(f"获取 {fund['name']} 净值数据失败，请检查网络或代码是否正确")
            return
        st.session_state.fund_data = nav_df
        st.session_state.fund_code = fund["code"]
        st.session_state.fund_chart_version = st.session_state.get("fund_chart_version", 0) + 1

    nav_df = st.session_state.fund_data
    start_nav = nav_df["nav"].iloc[0]
    latest_nav = nav_df["nav"].iloc[-1]
    total_return = (latest_nav / start_nav - 1) * 100
    date_start = nav_df["date"].iloc[0].strftime('%Y-%m-%d')
    date_end = nav_df["date"].iloc[-1].strftime('%Y-%m-%d')

    # ---- 指标 ----
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("最新净值", f"{latest_nav:.4f}")
    mc2.metric("成立以来", f"{total_return:+.1f}%")
    mc3.metric("数据范围", f"{date_start} ~ {date_end}")
    mc4.metric("交易日数", str(len(nav_df)))

    # ---- 净值折线图 ----
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=nav_df["date"], y=nav_df["nav"],
        mode='lines', name='单位净值',
        line=dict(color='#e7505a', width=2),
        hovertemplate='%{{x|%Y-%m-%d}}<br>净值: %{{y:.4f}}<extra></extra>',
    ))
    fig.update_layout(
        template='plotly_dark',
        paper_bgcolor=BG, plot_bgcolor=BG,
        font=dict(color=FG, size=11, family=CN_FONT),
        title=dict(
            text=f"<b>{fund['name']} ({fund['code']})</b> — 单位净值走势",
            font=dict(color=FG, size=17, family=CN_FONT),
            x=0.01, xanchor='left',
        ),
        height=650,
        hovermode='closest',
        showlegend=False,
        margin=dict(l=60, r=30, t=55, b=40),
        dragmode='pan',
        clickmode='event',
    )
    fig.update_xaxes(
        gridcolor=GRID_C, showgrid=True, zeroline=False,
        linecolor=LINE_C, linewidth=1,
        autorange=False,
        title_font=dict(color=FG_SOFT, family=CN_FONT),
        rangeslider=dict(
            visible=True, thickness=0.06,
            bgcolor='#1c1f2e', bordercolor=GRID_C, borderwidth=1,
        ),
    )
    fig.update_yaxes(
        title_text='单位净值 (元)',
        gridcolor=GRID_C, showgrid=True, zeroline=False,
        linecolor=LINE_C, linewidth=1,
        title_font=dict(color=FG_SOFT, size=10, family=CN_FONT),
        fixedrange=False,
    )

    if "fund_chart_version" not in st.session_state:
        st.session_state.fund_chart_version = 0

    chart_html = _build_chart_html(
        fig, version=st.session_state.fund_chart_version, theme=theme,
    )
    st.components.v1.html(chart_html, height=730)

    st.caption("提示：点击折线 → 放大前后约 60 个数据点 | 双击空白 → 重置缩放 | Q=缩放 W=平移 E=全览")

    if st.button("重置缩放", key="fund_reset_zoom"):
        st.session_state.fund_chart_version += 1
        st.rerun()