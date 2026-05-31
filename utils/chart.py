# -*- coding: utf-8 -*-
"""
图表工具 v2 — Plotly 交互式蜡烛图 + 买卖信号 + 悬停浮窗 + 策略人话解释
参考: anyplot.ai/stock-event-flags, OriginalNils/TradingStrategyBacktester
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============ 深色主题配色 ============
BG        = '#131520'
GRID_C    = '#1f2335'
# 中国习惯：红涨绿跌
UP_GREEN  = '#e7505a'  # 阳线 = 红
DN_RED    = '#26c281'  # 阴线 = 绿
BUY_TRI   = '#00e5ff'
SELL_TRI  = '#ff6e40'
FG        = '#c8cce0'
FG_SOFT   = '#6b7094'
MA5_COLOR = '#f5a623'
MA20_COLOR = '#4da6ff'
CARD_BG   = '#1a1d2e'

# ============ 浅色主题配色 ============
LIGHT_BG        = '#ffffff'
LIGHT_GRID_C    = '#e5e7eb'
LIGHT_FG        = '#1f2937'
LIGHT_FG_SOFT   = '#6b7280'
LIGHT_CARD_BG   = '#f3f4f6'
LIGHT_LINE_C    = '#d1d5db'

# 中文字体栈：macOS 优先 PingFang SC，降级到跨平台字体
CN_FONT = 'PingFang SC, Microsoft YaHei, SimHei, Arial Unicode MS, sans-serif'


def plot_backtest(data, strategy_name, chart_mode="K线图",
                  buy_points=None, sell_points=None,
                  trades=None, yaxis_range=None, xaxis_range=None,
                  theme="dark"):
    """
    生成 Plotly 交互式回测图表。

    Parameters
    ----------
    yaxis_range : tuple (min, max) or None
        纵轴价格范围，用于缩放 K 线高度。None 时自动适配。
    xaxis_range : tuple (str, str) or None
        横轴日期范围（'YYYY-MM-DD' 格式），传入后覆盖默认最近 90 根 K 线。

    Returns
    -------
    plotly.graph_objects.Figure
    """
    buy_points = buy_points or []
    sell_points = sell_points or []
    trades = trades or []

    df = data[['open', 'high', 'low', 'close', 'volume']].copy()
    df.index = pd.to_datetime(df.index)
    dti = df.index
    n = len(df)

    # ---- 主题配色选择 ----
    if theme == "light":
        _bg      = LIGHT_BG
        _grid_c  = LIGHT_GRID_C
        _fg      = LIGHT_FG
        _fg_soft = LIGHT_FG_SOFT
        _card_bg = LIGHT_CARD_BG
        _line_c  = LIGHT_LINE_C
        _template = 'plotly_white'
        _legend_bg = 'rgba(243,244,246,0.92)'
        _rangeslider_bg = '#f3f4f6'
        _inv_marker_color = 'rgba(0,0,0,0.01)'
    else:
        _bg      = BG
        _grid_c  = GRID_C
        _fg      = FG
        _fg_soft = FG_SOFT
        _card_bg = CARD_BG
        _line_c  = '#2a2d3e'
        _template = 'plotly_dark'
        _legend_bg = 'rgba(26,29,46,0.92)'
        _rangeslider_bg = '#1c1f2e'
        _inv_marker_color = 'rgba(255,255,255,0.01)'

    # ---- 均线 ----
    ma5  = df['close'].rolling(5).mean()
    ma20 = df['close'].rolling(20).mean()

    # ---- 成交量颜色 ----
    vol_colors = [
        UP_GREEN if df['close'].iloc[i] >= df['open'].iloc[i] else DN_RED
        for i in range(n)
    ]

    # ---- 构建买卖点 scatter 数据 ----
    bp_idx = [dti[idx] for idx, _ in buy_points if idx < n]
    bp_val = [p for idx, p in buy_points if idx < n]
    sp_idx = [dti[idx] for idx, _ in sell_points if idx < n]
    sp_val = [p for idx, p in sell_points if idx < n]

    # ---- 构建 hover 浮窗文本 ----
    # 将 trades 按买入/卖出时间建立索引，方便 hover 时匹配到具体盈亏
    trade_by_entry = {}  # key: 日期前缀
    trade_by_exit = {}
    for t in trades:
        ed = t.get("买入时间", "")[:10]
        sd = t.get("卖出时间", "")[:10]
        if ed:
            trade_by_entry[ed] = t
        if sd:
            trade_by_exit[sd] = t

    buy_hover = []
    for idx, price in buy_points:
        if 0 <= idx < n:
            date_str = dti[idx].strftime('%Y-%m-%d')
            t = trade_by_entry.get(date_str)
            if t:
                reason = t.get("买入原因", "策略信号")
                buy_hover.append(
                    f"<b>买入</b> | {date_str}<br>"
                    f"价格: ¥{t['买入价']}<br>"
                    f"<b>触发条件:</b> {reason}"
                )
            else:
                buy_hover.append(
                    f"<b>买入</b> | {date_str}<br>"
                    f"价格: ¥{price:.2f}<br>"
                    f"触发条件: {strategy_name}买入信号"
                )

    sell_hover = []
    for idx, price in sell_points:
        if 0 <= idx < n:
            date_str = dti[idx].strftime('%Y-%m-%d')
            t = trade_by_exit.get(date_str)
            if t:
                reason = t.get("卖出原因", "策略信号")
                sell_hover.append(
                    f"<b>卖出</b> | {date_str}<br>"
                    f"价格: ¥{t['卖出价']}<br>"
                    f"盈亏: {t['盈亏']}<br>"
                    f"<b>触发条件:</b> {reason}"
                )
            else:
                sell_hover.append(
                    f"<b>卖出</b> | {date_str}<br>"
                    f"价格: ¥{price:.2f}<br>"
                    f"触发条件: {strategy_name}卖出信号"
                )

    # ---- Chart Mode ----
    if chart_mode == "折线图":
        chart_type = "折线图"
    else:
        chart_type = "K线图"

    # ---- 构建子图 (K线上 / 成交量下) ----
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.72, 0.28],
    )

    # ---- 默认可视范围：最近 90 根 K 线，保证蜡烛有足够宽度 ----
    if xaxis_range is not None:
        default_x0, default_x1 = xaxis_range[0], xaxis_range[1]
    elif n > 90:
        default_x0 = dti[n - 90]
        default_x1 = dti[-1]
    else:
        default_x0 = dti[0]
        default_x1 = dti[-1]

    # ===== Row 1: 主图 =====
    fig.add_trace(go.Candlestick(
        x=dti,
        open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        name='K线',
        increasing_line_color=UP_GREEN, decreasing_line_color=DN_RED,
        increasing_fillcolor=UP_GREEN, decreasing_fillcolor=DN_RED,
        increasing_line_width=1.2, decreasing_line_width=1.2,
        whiskerwidth=0.8,
        showlegend=False,
        hoverinfo='x',
        hoverlabel=dict(font=dict(size=10)),
    ), row=1, col=1)

    # ---- 点击捕获层：每根 K 线 high 和 low 各放一个不可见大 marker ----
    # 覆盖整根影线范围，确保点击蜡烛任意位置都能命中
    # 参考 test_click.html 的方案：high/low 双排 marker + size 28
    click_x_hi, click_y_hi, click_text_hi = [], [], []
    click_x_lo, click_y_lo, click_text_lo = [], [], []
    for i in range(n):
        t = dti[i].strftime('%Y-%m-%d')
        click_x_hi.append(dti[i]); click_y_hi.append(float(df['high'].iloc[i])); click_text_hi.append(t)
        click_x_lo.append(dti[i]); click_y_lo.append(float(df['low'].iloc[i]));  click_text_lo.append(t)

    marker_opts = dict(size=40, opacity=0.01, color=_inv_marker_color)
    fig.add_trace(go.Scatter(
        x=click_x_hi, y=click_y_hi, mode='markers', marker=marker_opts,
        hoverinfo='skip', showlegend=False, name='_click_cap_hi', text=click_text_hi,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=click_x_lo, y=click_y_lo, mode='markers', marker=marker_opts,
        hoverinfo='skip', showlegend=False, name='_click_cap_lo', text=click_text_lo,
    ), row=1, col=1)

    # MA5
    fig.add_trace(go.Scatter(
        x=dti, y=ma5, name='MA5',
        line=dict(color=MA5_COLOR, width=1.3, dash='dot'),
        hovertemplate='MA5: ¥%{y:.2f}<extra></extra>',
    ), row=1, col=1)

    # MA20
    fig.add_trace(go.Scatter(
        x=dti, y=ma20, name='MA20',
        line=dict(color=MA20_COLOR, width=1.3, dash='dot'),
        hovertemplate='MA20: ¥%{y:.2f}<extra></extra>',
    ), row=1, col=1)

    # ---- 买卖信号：竖虚线 + 微型标记（TradingView 事件标注风格）----
    # 竖线不遮挡蜡烛；微型标记与单根 K 线同宽，悬停浮窗保留
    for x_date, y_price in zip(bp_idx, bp_val):
        fig.add_vline(x=x_date, line_dash='dash', line_color=BUY_TRI,
                       line_width=1.2, opacity=0.65, row=1, col=1)
    for x_date, y_price in zip(sp_idx, sp_val):
        fig.add_vline(x=x_date, line_dash='dash', line_color=SELL_TRI,
                       line_width=1.2, opacity=0.65, row=1, col=1)

    # 买入微型标记（size=8，与单根 K 线同宽）
    if bp_idx:
        fig.add_trace(go.Scatter(
            x=bp_idx, y=bp_val, name='买入',
            mode='markers',
            marker=dict(
                symbol='triangle-down', size=8,
                color=BUY_TRI,
                line=dict(color='white', width=1),
            ),
            text=buy_hover,
            hoverinfo='text',
            hoverlabel=dict(
                bgcolor=_card_bg, font=dict(color=_fg, size=13, family=CN_FONT),
                bordercolor=_line_c,
            ),
        ), row=1, col=1)

    # 卖出微型标记
    if sp_idx:
        fig.add_trace(go.Scatter(
            x=sp_idx, y=sp_val, name='卖出',
            mode='markers',
            marker=dict(
                symbol='triangle-up', size=8,
                color=SELL_TRI,
                line=dict(color='white', width=1),
            ),
            text=sell_hover,
            hoverinfo='text',
            hoverlabel=dict(
                bgcolor=_card_bg, font=dict(color=_fg, size=13, family=CN_FONT),
                bordercolor=_line_c,
            ),
        ), row=1, col=1)

    # ===== Row 2: 成交量 =====
    fig.add_trace(go.Bar(
        x=dti, y=df['volume'], name='成交量',
        marker_color=vol_colors, opacity=0.45,
        showlegend=False,
        hovertemplate='成交量: %{y:,.0f}<extra></extra>',
    ), row=2, col=1)

    # ============ Layout ============
    title = f'<b>{strategy_name}</b> — {chart_type}'
    fig.update_layout(
        template=_template,
        paper_bgcolor=_bg,
        plot_bgcolor=_bg,
        font=dict(color=_fg, size=11, family=CN_FONT),

        # --- Title ---
        title=dict(text=title, font=dict(color=_fg, size=17, family=CN_FONT), x=0.01, xanchor='left'),
        height=700,

        # --- Hover ---
        hovermode='closest',

        # --- 范围滑块：拖拽缩放时间轴，蜡烛宽度自适应变化 ---
        xaxis_rangeslider_thickness=0.06,

        # --- Legend ---
        showlegend=True,
        legend=dict(
            orientation='h', yanchor='top', y=1.06, xanchor='left', x=0.01,
            bgcolor=_legend_bg, bordercolor=_grid_c, borderwidth=1,
            font=dict(color=_fg_soft, size=10, family=CN_FONT),
        ),

        # --- Margins ---
        margin=dict(l=60, r=30, t=55, b=40),

        # --- Drag mode ---
        dragmode='pan',
        clickmode='event',
    )

    # X axis — rangeslider 初始范围通过 xaxis.range 设，rangeslider 内部不硬编码 range，
    # 配合 autorange=False 避免拖动后回弹。
    fig.update_xaxes(
        gridcolor=_grid_c, showgrid=True, zeroline=False,
        linecolor=_line_c, linewidth=1,
        title_font=dict(color=_fg_soft, family=CN_FONT),
        autorange=False,
        range=[default_x0, default_x1],
        rangeslider=dict(
            visible=True,
            thickness=0.06,
            bgcolor=_rangeslider_bg,
            bordercolor=_grid_c,
            borderwidth=1,
        ),
    )

    # Y axes
    fig.update_yaxes(
        title_text='价格 (¥)', row=1, col=1,
        gridcolor=_grid_c, showgrid=True, zeroline=False,
        linecolor=_line_c, linewidth=1,
        title_font=dict(color=_fg_soft, size=10, family=CN_FONT),
        fixedrange=False,
        range=yaxis_range,
    )
    fig.update_yaxes(
        title_text='成交量', row=2, col=1,
        gridcolor=_grid_c, showgrid=True, zeroline=False,
        linecolor=_line_c, linewidth=1,
        title_font=dict(color=_fg_soft, size=10, family=CN_FONT),
        fixedrange=False,
    )

    # X axis (shared, bottom)
    fig.update_xaxes(
        row=2, col=1,
        gridcolor=_grid_c, showgrid=True,
    )

    # ---- 显式缩放：仅在点击 K 线触发缩放时覆盖横轴范围 ----
    if xaxis_range is not None:
        fig.update_layout(xaxis_range=[xaxis_range[0], xaxis_range[1]])

    return fig


def render_strategy_card(strategy_name, explanation):
    """生成策略大白话解释的 Markdown/HTML 文本（Streamlit 侧渲染）"""
    if not explanation:
        return ""

    lines = [
        f"### 📈 {strategy_name} — 大白话解释",
        "",
        f"**一句话：** {explanation.get('summary', '')}",
        "",
        "---",
        "",
        f"🟢 **为什么买？** {explanation.get('buy_logic', '')}",
        "",
        f"🔴 **为什么卖？** {explanation.get('sell_logic', '')}",
        "",
        "---",
        "",
        f"✅ **优势：** {explanation.get('pros', '')}",
        "",
        f"⚠️  **劣势：** {explanation.get('cons', '')}",
    ]
    return "\n".join(lines)