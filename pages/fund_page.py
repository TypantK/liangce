# -*- coding: utf-8 -*-
"""
基金净值走势页面 — 广发利鑫混合C (011172)
复用 backtest_page 交互 JS：Q/Zoom、W/Pan、E/AutoScale+ZoomOut、点击缩放、双击重置
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np

# ---- 基金数据路径 ----
CSV_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '广发利鑫混合C_011172_净值.csv'))

# ---- Plotly 深色主题配色（与 chart.py 中 plotly_dark 模板一致） ----
BG        = '#131520'
GRID_C    = '#1f2335'
NAV_COLOR = '#e7505a'  # 净值红色
FG        = '#c8cce0'
FG_SOFT   = '#6b7094'
LINE_C    = '#2a2d3e'
CN_FONT   = 'PingFang SC, Microsoft YaHei, SimHei, Arial Unicode MS, sans-serif'


def _build_chart_html(fig, version=0):
    """构建带交互 JS 的完整 HTML（复用 backtest_page 键盘+点击缩放逻辑）"""
    import uuid
    chart_id = f"fund_{uuid.uuid4().hex[:8]}"

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
        body {{ margin: 0; padding: 0; background: {BG}; color: #fff; font-family: sans-serif; }}
        #{chart_id} {{ width: 100%; }}
        #_dbg {{ display: none; }}
    </style>
</head>
<body>
<div id="_dbg">...</div>
{fig_html}
<script>
(function() {{
    var gd = null;
    var dbg = document.getElementById('_dbg');
    var clickCount = 0;
    var zoomReady = false;

    function log(msg) {{
        dbg.textContent = msg;
        console.log('[fund] ' + msg);
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

    function zoomToRange(allX, allY, startIdx, endIdx) {{
        if (!gd) return;
        startIdx = Math.max(0, startIdx);
        endIdx = Math.min(allX.length - 1, endIdx);
        if (startIdx >= endIdx) return;

        // 取 Scatter 折线 trace 在区间内 y 的 min/max + 8% padding
        var yHi = -Infinity, yLo = Infinity;
        for (var i = startIdx; i <= endIdx; i++) {{
            var v = allY[i];
            if (v != null && isFinite(v)) {{
                if (v > yHi) yHi = v;
                if (v < yLo) yLo = v;
            }}
        }}
        if (!isFinite(yHi) || !isFinite(yLo) || yHi <= yLo) return;

        var pad = (yHi - yLo) * 0.08;
        Plotly.relayout(gd, {{
            'xaxis.autorange': false,
            'yaxis.autorange': false,
            'xaxis.range': [allX[startIdx], allX[endIdx]],
            'yaxis.range': [yLo - pad, yHi + pad]
        }});
    }}

    function bindClickHandlers() {{
        log('bindClickHandlers');
        gd.removeAllListeners('plotly_click');
        gd.removeAllListeners('plotly_doubleclick');

        gd.on('plotly_click', function(data) {{
            clickCount++;
            var pts = (data && data.points) ? data.points.length : 0;
            if (!pts) return;
            var pt = data.points[0];
            var allX = pt.data.x;
            var allY = pt.data.y;
            if (!allX || !allX.length) return;
            var idx = findDateIndex(allX, pt.x);
            if (idx < 0) return;
            zoomToRange(allX, allY, idx - 30, idx + 30);
        }});

        log('bindClickHandlers DONE');
    }}

    function setupZoom() {{
        if (zoomReady || !gd) {{ return; }}
        zoomReady = true;
        log('setupZoom START');

        bindClickHandlers();

        // Re-bind after autoscale / zoom / rangeslider (relayout resets drag layer)
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
                    setTimeout(function() {{ rebindLock = false; }}, 150);
                }} else {{
                    bindClickHandlers();
                    setTimeout(function() {{ rebindLock = false; }}, 150);
                }}
            }}, delay);
        }});

        // INIT: disable autorange so plotly_click events fire
        Plotly.relayout(gd, {{'xaxis.autorange': false, 'yaxis.autorange': false}});
        log('setupZoom DONE');
    }}

    function tryInit() {{
        gd = document.getElementById('{chart_id}');
        if (!gd) gd = document.querySelector('.js-plotly-plot');
        if (!gd) gd = document.querySelector('.plotly-graph-div');
        if (!gd) {{
            setTimeout(tryInit, 300);
            return;
        }}
        if (gd._fullLayout && gd._fullLayout._initialized) {{
            setupZoom();
        }} else {{
            gd.once && gd.once('plotly_afterplot', setupZoom);
            gd.on('plotly_afterplot', setupZoom);
            setTimeout(function() {{
                if (!zoomReady) setupZoom();
            }}, 2000);
        }}
    }}

    setTimeout(tryInit, 200);
}})();
</script>
<!-- cv:{version} -->
<script>
(function() {{
    document.addEventListener('keydown', function(e) {{
        var tag = (document.activeElement || {{}}).tagName || '';
        if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
        var gd = document.querySelector('.js-plotly-plot');
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
        }}
    }});
}})();
</script>
</body>
</html>"""
    return html


def render():
    st.set_page_config(page_title="基金净值", layout="wide")
    st.title("基金净值走势")

    # ---- 读取数据 ----
    df = pd.read_csv(CSV_PATH, parse_dates=['date'])
    df = df.sort_values('date').reset_index(drop=True)

    start_nav = df['nav'].iloc[0]
    latest_nav = df['nav'].iloc[-1]
    total_return = (latest_nav / start_nav - 1) * 100
    date_start = df['date'].iloc[0].strftime('%Y-%m-%d')
    date_end = df['date'].iloc[-1].strftime('%Y-%m-%d')
    n_days = len(df)

    # ---- 侧边栏：基金基本信息 ----
    st.sidebar.title("基金信息")
    st.sidebar.markdown(f"""
| 项目 | 值 |
|---|---|
| **基金名称** | 广发利鑫混合C |
| **基金代码** | 011172 |
| **最新净值** | {latest_nav:.3f} |
| **成立以来** | {total_return:+.1f}% |
| **数据范围** | {date_start} ~ {date_end} |
| **交易日数** | {n_days} |
""")

    # ---- 构建 Plotly 折线图 ----
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df['date'],
        y=df['nav'],
        mode='lines',
        name='单位净值',
        line=dict(color=NAV_COLOR, width=2),
        hovertemplate='%{x|%Y-%m-%d}<br>净值: %{y:.4f}<extra></extra>',
    ))

    # ---- Layout（对齐 plotly_dark 模板风格） ----
    fig.update_layout(
        template='plotly_dark',
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(color=FG, size=11, family=CN_FONT),
        title=dict(
            text='<b>广发利鑫混合C (011172)</b> — 单位净值走势',
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

    # ---- 渲染交互式图表 ----
    if "fund_chart_version" not in st.session_state:
        st.session_state.fund_chart_version = 0

    chart_html = _build_chart_html(fig, version=st.session_state.fund_chart_version)
    st.components.v1.html(chart_html, height=730)

    st.caption("提示：点击折线 → 放大前后约 60 个数据点 | 双击空白 → 重置缩放 | Q=缩放 W=平移 E=全览")

    # ---- 重置缩放 ----
    if st.button("重置缩放", key="fund_reset"):
        st.session_state.fund_chart_version += 1
        st.rerun()