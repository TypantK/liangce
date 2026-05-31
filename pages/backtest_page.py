# -*- coding: utf-8 -*-
"""
策略回测页面 v2 — Plotly 交互式图表 + 大白话策略解释
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import streamlit as st
import pandas as pd
from core.strategies import STRATEGY_REGISTRY
from core.data_fetcher import STOCK_POOL, get_stock_data, generate_demo_data
from core.engine import run_backtest
from utils.chart import plot_backtest, render_strategy_card


def _build_chart_html(fig):
    """Generate HTML with embedded JS for click-to-zoom (mirrors test_click.html approach)."""
    import uuid
    chart_id = f"chart_{uuid.uuid4().hex[:8]}"

    fig_html = fig.to_html(
        include_plotlyjs='cdn',
        full_html=False,
        config={'doubleClick': False, 'displayModeBar': True, 'displaylogo': False},
        div_id=chart_id,
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ margin: 0; padding: 0; background: #131520; }}
        #{chart_id} {{ width: 100%; }}
    </style>
</head>
<body>
{fig_html}
<script>
(function() {{
    var gd = document.getElementById('{chart_id}');
    if (!gd) return;

    function findDateIndex(allX, targetX) {{
        var idx = -1, minDist = Infinity;
        for (var i = 0; i < allX.length; i++) {{
            var dist = Math.abs(new Date(allX[i]) - new Date(targetX));
            if (dist < minDist) {{ minDist = dist; idx = i; }}
        }}
        return idx;
    }}

    function zoomToRange(gd, allX, startIdx, endIdx) {{
        startIdx = Math.max(0, startIdx);
        endIdx = Math.min(allX.length - 1, endIdx);
        if (startIdx < endIdx) {{
            Plotly.relayout(gd, {{'xaxis.range': [allX[startIdx], allX[endIdx]]}});
        }}
    }}

    function initClickZoom() {{
        gd.removeAllListeners('plotly_click');
        gd.removeAllListeners('plotly_selected');

        gd.on('plotly_click', function(data) {{
            if (!data || !data.points || data.points.length === 0) return;
            var pt = data.points[0];
            var allX = pt.data.x;
            if (!allX || allX.length === 0) return;
            var idx = findDateIndex(allX, pt.x);
            if (idx < 0) return;
            zoomToRange(gd, allX, idx - 15, idx + 15);
        }});

        gd.on('plotly_selected', function(data) {{
            if (!data || !data.range || !data.range.x) return;
            var allX = data.points && data.points.length ? data.points[0].data.x : null;
            if (!allX || allX.length === 0) {{
                Plotly.relayout(gd, {{'xaxis.range': [data.range.x[0], data.range.x[1]]}});
                return;
            }}
            var startIdx = findDateIndex(allX, data.range.x[0]);
            var endIdx = findDateIndex(allX, data.range.x[1]);
            if (startIdx >= 0 && endIdx >= 0) {{
                zoomToRange(gd, allX, startIdx, endIdx);
            }}
        }});
    }}

    if (gd._fullLayout && gd._fullLayout._initialized) {{
        initClickZoom();
    }} else {{
        gd.on('plotly_afterplot', function() {{ initClickZoom(); }});
    }}
}})();
</script>
</body>
</html>"""
    return html


def render():
    st.title("策略回测")

    # ========== 控制面板 ==========
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        strategy_name = st.selectbox("选择策略", list(STRATEGY_REGISTRY.keys()), key="s")
    with c2:
        data_source = st.selectbox("数据源", ["演示数据"] + list(STOCK_POOL.keys()), key="d")
    with c3:
        chart_mode = st.radio("图表类型", ["K线图", "折线图"], horizontal=True, key="cm")

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

    # ========== 回测 ==========
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

        with st.spinner(f"运行「{strategy_name}」..."):
            result = run_backtest(
                data, strat_info["class"], params,
                initial_cash=initial_cash,
                strategy_name=strategy_name,
            )

        st.session_state.backtest_result = result

    # ========== 渲染结果 ==========
    if "backtest_result" not in st.session_state or st.session_state.backtest_result is None:
        st.info("点击「开始回测」查看结果")
        return

    result = st.session_state.backtest_result

    st.divider()

    # ===== 指标面板 =====
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

    # ===== 策略大白话解释（可折叠） =====
    explanation = result.get("explanation", {})
    if explanation:
        with st.expander(f"「{strategy_name}」大白话解释", expanded=False):
            st.markdown(render_strategy_card(strategy_name, explanation))

    # ===== 纵轴范围滑块 =====
    import numpy as np
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

    # ===== Plotly 交互式图表（JS 客户端缩放，对齐 test_click.html 方案） =====
    fig = plot_backtest(
        result["data"],
        result["strategy_name"],
        chart_mode=chart_mode,
        buy_points=result["buy_points"],
        sell_points=result["sell_points"],
        trades=result["trades"],
        yaxis_range=(price_lo, price_hi),
    )

    if "chart_version" not in st.session_state:
        st.session_state.chart_version = 0

    chart_html = _build_chart_html(fig)
    st.components.v1.html(
        chart_html, height=780,
        key=f"kline_v{st.session_state.chart_version}",
    )

    st.caption("提示：点击任意 K 线 → 放大前后约一个月 | 工具栏框选 → 精确区间 | 双击空白 → 重置缩放")

    # ===== 重置缩放按钮 =====
    if st.button("重置缩放", key="reset_zoom"):
        st.session_state.chart_version += 1
        st.rerun()

    # ===== 交易明细 =====
    if result["trades"]:
        st.subheader("交易明细")
        trade_df = pd.DataFrame(result["trades"])
        display_cols = [c for c in ["买入时间", "买入价", "买入原因", "卖出时间", "卖出价", "卖出原因", "盈亏"] if c in trade_df.columns]
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
