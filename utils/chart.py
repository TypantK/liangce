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
        _grid_h  = 'rgba(229,231,235,0.35)'   # 水平虚线网格：半透明
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
        _grid_h  = 'rgba(31,35,53,0.30)'      # 水平虚线网格：暗色半透明
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
    # 买入标记：绿三角 ▲，标在最低价下方 0.5% 处
    # 卖出标记：红三角 ▼，标在最高价上方 0.5% 处
    _offset_pct = 0.005
    bp_idx = [dti[idx] for idx, _ in buy_points if idx < n]
    bp_val = [float(df['low'].iloc[idx]) * (1 - _offset_pct) for idx, _ in buy_points if idx < n]
    sp_idx = [dti[idx] for idx, _ in sell_points if idx < n]
    sp_val = [float(df['high'].iloc[idx]) * (1 + _offset_pct) for idx, _ in sell_points if idx < n]

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

    # ---- 买卖信号：竖虚线 + 三角标记（TradingView 事件标注风格）----
    # 买入：绿色虚线 ｜ 卖出：红色虚线
    for x_date in bp_idx:
        fig.add_vline(x=x_date, line_dash='dash', line_color=DN_RED,
                       line_width=1.2, opacity=0.50, row=1, col=1)
    for x_date in sp_idx:
        fig.add_vline(x=x_date, line_dash='dash', line_color=UP_GREEN,
                       line_width=1.2, opacity=0.50, row=1, col=1)

    # 买入三角标记：红 ▼，在 K 线最低价下方
    if bp_idx:
        fig.add_trace(go.Scatter(
            x=bp_idx, y=bp_val, name='买入',
            mode='markers',
            marker=dict(
                symbol='triangle-down', size=11,
                color=DN_RED,
                line=dict(color='white', width=1.2),
            ),
            text=buy_hover,
            hoverinfo='text',
            hoverlabel=dict(
                bgcolor=_card_bg, font=dict(color=_fg, size=13, family=CN_FONT),
                bordercolor=_line_c,
            ),
        ), row=1, col=1)

    # 卖出三角标记：绿 ▲，在 K 线最高价上方
    if sp_idx:
        fig.add_trace(go.Scatter(
            x=sp_idx, y=sp_val, name='卖出',
            mode='markers',
            marker=dict(
                symbol='triangle-up', size=11,
                color=UP_GREEN,
                line=dict(color='white', width=1.2),
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
    # 垂直网格线隐藏，保留轴线和刻度
    fig.update_xaxes(
        showgrid=False, zeroline=False,
        linecolor=_line_c, linewidth=1,
        title_font=dict(color=_fg_soft, family=CN_FONT),
        autorange=False,
        range=[default_x0, default_x1],
        tickformat="%Y-%m-%d",
        tickfont=dict(color=_fg_soft, size=10, family=CN_FONT),
        rangeslider=dict(
            visible=True,
            thickness=0.06,
            bgcolor=_rangeslider_bg,
            bordercolor=_grid_c,
            borderwidth=1,
        ),
    )

    # Y axes — 水平网格线改为虚线半透明
    fig.update_yaxes(
        title_text='价格 (¥)', row=1, col=1,
        gridcolor=_grid_h, griddash='dash', gridwidth=0.8,
        showgrid=True, zeroline=False,
        linecolor=_line_c, linewidth=1,
        title_font=dict(color=_fg_soft, size=10, family=CN_FONT),
        tickformat=".2f",
        tickfont=dict(color=_fg_soft, size=10, family=CN_FONT),
        fixedrange=False,
        range=yaxis_range,
    )
    fig.update_yaxes(
        title_text='成交量', row=2, col=1,
        gridcolor=_grid_h, griddash='dash', gridwidth=0.8,
        showgrid=True, zeroline=False,
        linecolor=_line_c, linewidth=1,
        title_font=dict(color=_fg_soft, size=10, family=CN_FONT),
        fixedrange=False,
    )

    # X axis (shared, bottom)
    fig.update_xaxes(
        row=2, col=1,
        showgrid=False,
    )

    # ---- 显式缩放：仅在点击 K 线触发缩放时覆盖横轴范围 ----
    if xaxis_range is not None:
        fig.update_layout(xaxis_range=[xaxis_range[0], xaxis_range[1]])

    return fig


def plot_fund_backtest(data, strategy_name, buy_points=None, sell_points=None,
                       trades=None, yaxis_range=None, theme="dark"):
    """
    基金回测净值折线图 + 买卖信号标注。
    与 plot_backtest 风格一致，但用折线图代替 K 线，不显示成交量。
    """
    buy_points = buy_points or []
    sell_points = sell_points or []
    trades = trades or []

    df = data[["close"]].copy()
    df.index = pd.to_datetime(df.index)
    dti = df.index
    n = len(df)

    # ---- 主题配色 ----
    if theme == "light":
        _bg      = LIGHT_BG
        _grid_c  = LIGHT_GRID_C
        _grid_h  = 'rgba(229,231,235,0.35)'   # 水平虚线网格：半透明
        _fg      = LIGHT_FG
        _fg_soft = LIGHT_FG_SOFT
        _card_bg = LIGHT_CARD_BG
        _line_c  = LIGHT_LINE_C
        _template = 'plotly_white'
        _legend_bg = 'rgba(243,244,246,0.92)'
    else:
        _bg      = BG
        _grid_c  = GRID_C
        _grid_h  = 'rgba(31,35,53,0.30)'      # 水平虚线网格：暗色半透明
        _fg      = FG
        _fg_soft = FG_SOFT
        _card_bg = CARD_BG
        _line_c  = '#2a2d3e'
        _template = 'plotly_dark'
        _legend_bg = 'rgba(26,29,46,0.92)'

    # ---- 均线 ----
    ma5  = df["close"].rolling(5).mean()
    ma20 = df["close"].rolling(20).mean()

    # ---- 买卖点 scatter ----
    # 买入标记：绿三角 ▲，净值下方 0.35%
    # 卖出标记：红三角 ▼，净值上方 0.35%
    _fund_offset = 0.0035
    bp_idx = [dti[idx] for idx, _ in buy_points if idx < n]
    bp_val = [float(df["close"].iloc[idx]) * (1 - _fund_offset) for idx, _ in buy_points if idx < n]
    sp_idx = [dti[idx] for idx, _ in sell_points if idx < n]
    sp_val = [float(df["close"].iloc[idx]) * (1 + _fund_offset) for idx, _ in sell_points if idx < n]

    # ---- hover 浮窗 ----
    trade_by_entry = {}
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
                    f"净值: {t['买入价']}<br>"
                    f"<b>触发条件:</b> {reason}"
                )
            else:
                buy_hover.append(
                    f"<b>买入</b> | {date_str}<br>"
                    f"净值: {price:.4f}<br>"
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
                    f"净值: {t['卖出价']}<br>"
                    f"盈亏: {t['盈亏']}<br>"
                    f"<b>触发条件:</b> {reason}"
                )
            else:
                sell_hover.append(
                    f"<b>卖出</b> | {date_str}<br>"
                    f"净值: {price:.4f}<br>"
                    f"触发条件: {strategy_name}卖出信号"
                )

    # ---- 默认可视范围 ----
    if n > 90:
        default_x0 = dti[n - 90]
        default_x1 = dti[-1]
    else:
        default_x0 = dti[0]
        default_x1 = dti[-1]

    fig = go.Figure()

    # 净值折线
    fig.add_trace(go.Scatter(
        x=dti, y=df["close"], name="单位净值",
        mode="lines+markers",
        line=dict(color="#e7505a", width=1.8),
        marker=dict(size=5, color="#e7505a"),
        hovertemplate='%{x|%Y-%m-%d}<br>净值: %{y:.4f}<extra></extra>',
    ))

    # 点击捕获层：每个数据点放不可见大 marker，与 plot_backtest 交互一致
    _inv_color = 'rgba(0,0,0,0.01)' if theme == "light" else 'rgba(255,255,255,0.01)'
    click_x, click_y, click_text = [], [], []
    for i in range(n):
        t = dti[i].strftime('%Y-%m-%d')
        click_x.append(dti[i])
        click_y.append(float(df['close'].iloc[i]))
        click_text.append(t)
    fig.add_trace(go.Scatter(
        x=click_x, y=click_y, mode='markers',
        marker=dict(size=40, opacity=0.01, color=_inv_color),
        hoverinfo='skip', showlegend=False, name='_click_cap', text=click_text,
    ))

    # MA5
    fig.add_trace(go.Scatter(
        x=dti, y=ma5, name="MA5",
        line=dict(color=MA5_COLOR, width=1.3, dash="dot"),
        hovertemplate='MA5: %{y:.4f}<extra></extra>',
    ))

    # MA20
    fig.add_trace(go.Scatter(
        x=dti, y=ma20, name="MA20",
        line=dict(color=MA20_COLOR, width=1.3, dash="dot"),
        hovertemplate='MA20: %{y:.4f}<extra></extra>',
    ))

    # 买入/卖出竖虚线
    for x_date in bp_idx:
        fig.add_vline(x=x_date, line_dash="dash", line_color=DN_RED,
                       line_width=1.2, opacity=0.50)
    for x_date in sp_idx:
        fig.add_vline(x=x_date, line_dash="dash", line_color=UP_GREEN,
                       line_width=1.2, opacity=0.50)

    # 买入三角标记：红 ▼，在净值下方
    if bp_idx:
        fig.add_trace(go.Scatter(
            x=bp_idx, y=bp_val, name="买入",
            mode="markers",
            marker=dict(
                symbol="triangle-down", size=11,
                color=DN_RED,
                line=dict(color="white", width=1.2),
            ),
            text=buy_hover,
            hoverinfo="text",
            hoverlabel=dict(
                bgcolor=_card_bg, font=dict(color=_fg, size=13, family=CN_FONT),
                bordercolor=_line_c,
            ),
        ))

    # 卖出三角标记：绿 ▲，在净值上方
    if sp_idx:
        fig.add_trace(go.Scatter(
            x=sp_idx, y=sp_val, name="卖出",
            mode="markers",
            marker=dict(
                symbol="triangle-up", size=11,
                color=UP_GREEN,
                line=dict(color="white", width=1.2),
            ),
            text=sell_hover,
            hoverinfo="text",
            hoverlabel=dict(
                bgcolor=_card_bg, font=dict(color=_fg, size=13, family=CN_FONT),
                bordercolor=_line_c,
            ),
        ))

    fig.update_layout(
        template=_template,
        paper_bgcolor=_bg, plot_bgcolor=_bg,
        font=dict(color=_fg, size=11, family=CN_FONT),
        title=dict(
            text=f"<b>{strategy_name}</b> — 基金净值",
            font=dict(color=_fg, size=17, family=CN_FONT),
            x=0.01, xanchor="left",
        ),
        height=650, hovermode="closest",
        showlegend=True,
        legend=dict(
            orientation="h", yanchor="top", y=1.06, xanchor="left", x=0.01,
            bgcolor=_legend_bg, bordercolor=_grid_c, borderwidth=1,
            font=dict(color=_fg_soft, size=10, family=CN_FONT),
        ),
        margin=dict(l=60, r=30, t=55, b=40),
        dragmode="pan",
        clickmode="event",
    )

    # 垂直网格线隐藏，保留轴线和刻度
    fig.update_xaxes(
        showgrid=False, zeroline=False,
        linecolor=_line_c, linewidth=1,
        autorange=False,
        range=[default_x0, default_x1],
        tickformat="%Y-%m-%d",
        tickfont=dict(color=_fg_soft, size=10, family=CN_FONT),
        rangeslider=dict(
            visible=True, thickness=0.06,
            bgcolor=("#f3f4f6" if theme == "light" else "#1c1f2e"),
            bordercolor=_grid_c, borderwidth=1,
        ),
    )

    # 水平网格线：虚线半透明
    fig.update_yaxes(
        title_text="单位净值 (元)",
        gridcolor=_grid_h, griddash='dash', gridwidth=0.8,
        showgrid=True, zeroline=False,
        linecolor=_line_c, linewidth=1,
        title_font=dict(color=_fg_soft, size=10, family=CN_FONT),
        tickformat=".4f",
        tickfont=dict(color=_fg_soft, size=10, family=CN_FONT),
        fixedrange=False,
        range=yaxis_range,
    )

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


# ============================================================
#  统一图表增强：快捷键 + 点击/双击 K 线自动调整范围
#  所有页面的 Plotly 图表都通过本模块渲染，保证 mac/win 行为一致。
# ============================================================
def build_enhanced_chart_html(fig, version=0, theme="dark", auto_zoom=False,
                               enable_date_jump=False):
    """
    生成带交互增强的图表 HTML（用于 st.components.v1.html 注入 iframe）。

    增强能力：
      - 点击 K 线/折线 → 以该点为中心放大 60 天窗口
      - 双击主图 → 放大；双击空白 → 重置全览
      - 快捷键（焦点在图表内或父页面均可）：
          Q=缩放  W=平移  E=全览  A=放大  S=缩小

    enable_date_jump : bool (默认 False)
      是否在点击 K 线时把日期写入 URL 查询参数（?marvis_chart_date=YYYY-MM-DD）
      并整页刷新，用于回测页「点击日期看当日新闻」的情绪联动特性。
      板块预测/优化等不消费该参数的页面应保持 False，否则点击会整页刷新、
      丢失当前选择（表现为「不知道跳转到哪里去了」）。
    跨平台关键点：iframe 内同时监听自身 keydown 与父页 postMessage，
    父页桥接由 inject_hotkey_bridge_once() 注入（见下），从而无论焦点
    落在 iframe 还是父页面（Windows 常见情况）都能触发。
    """
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
            # 关闭 Plotly 自带双击重置，交给我们自己的 doubleclick 处理
            'doubleClick': False,
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
window.__chartHotkey = true;
window.__chartAutoZoom = {'true' if auto_zoom else 'false'};
window.__chartDateJump = {'true' if enable_date_jump else 'false'};
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
            // 2) Fallback: Scatter/line/heatmap → use y values
            if (!found) {{
                for (var t = 0; t < fullTraces.length; t++) {{
                    var tr2 = fullTraces[t];
                    if (tr2.y && tr2.y.length > 0) {{
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
        if (!gd) return;
        gd.removeAllListeners('plotly_click');
        gd.removeAllListeners('plotly_selected');
        gd.removeAllListeners('plotly_doubleclick');

        gd.on('plotly_doubleclick', function(data) {{
            if (!gd) return;
            var onMain = !!(data && data.points && data.points.length > 0);
            if (onMain) {{
                var pt = data.points[0];
                var allX = pt.data.x;
                if (!allX || !allX.length) return;
                var idx = findDateIndex(allX, pt.x);
                if (idx < 0) return;
                zoomToRange(allX, idx - 30, idx + 30);
            }} else {{
                Plotly.relayout(gd, {{'xaxis.autorange': true, 'yaxis.autorange': true}});
            }}
        }});

        gd.on('plotly_click', function(data) {{
            clickCount++;
            var pts = (data && data.points) ? data.points.length : 0;
            if (!pts) return;
            var pt = data.points[0];
            var allX = pt.data.x;
            if (!allX || !allX.length) return;
            var idx = findDateIndex(allX, pt.x);
            if (idx < 0) return;
            zoomToRange(allX, idx - 30, idx + 30);
            // 仅当开启日期联动（回测页情绪联动）时，才把日期写入 URL 并整页刷新
            if (!window.__chartDateJump) return;
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
                bindClickHandlers();
                var cd = (gd._fullLayout || {{}}).dragmode || 'pan';
                Plotly.relayout(gd, {{dragmode: cd}});
                setTimeout(function() {{ rebindLock = false; }}, 150);
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

    // ===== 快捷键处理（在 iframe 正确上下文内执行）=====
    function handleHotkey(e) {{
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        if (e.isComposing || (e.key === 'Process')) return;
        var tag = (document.activeElement || {{}}).tagName || '';
        if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
        var localGd = gd || (window.__chartDebug && window.__chartDebug.getGd && window.__chartDebug.getGd());
        if (!localGd) return;
        var key = (e.key || '').toLowerCase();
        var handled = true;
        if (key === 'q') {{
            Plotly.relayout(localGd, {{dragmode: 'zoom'}});
        }} else if (key === 'w') {{
            Plotly.relayout(localGd, {{dragmode: 'pan'}});
        }} else if (key === 'e') {{
            Plotly.relayout(localGd, {{'xaxis.autorange': true, 'yaxis.autorange': true}});
            setTimeout(function() {{
                var zoomOutBtn = localGd.querySelector('.modebar-btn[data-attr="zoom"][data-val="out"]');
                if (zoomOutBtn) zoomOutBtn.click();
            }}, 150);
        }} else if (key === 'a') {{
            var zin = localGd.querySelector('.modebar-btn[data-attr="zoom"][data-val="in"]');
            if (zin) zin.click();
        }} else if (key === 's') {{
            var zout = localGd.querySelector('.modebar-btn[data-attr="zoom"][data-val="out"]');
            if (zout) zout.click();
        }} else {{
            handled = false;
        }}
        if (handled && e.preventDefault) e.preventDefault();
        return handled;
    }}

    // 1) 焦点在 iframe 内部时，直接监听本页 keydown
    document.addEventListener('keydown', function(e) {{
        handleHotkey(e);
    }});

    // 2) 焦点在父页面（Streamlit 主框架）时：父页桥接通过 postMessage 转发，
    //    在本 iframe 正确的上下文里执行（跨平台关键，解决 Windows 失效）。
    window.addEventListener('message', function(ev) {{
        try {{
            var d = ev.data;
            if (!d || d.__chartHotkey !== true) return;
            handleHotkey({{
                key: d.key,
                ctrlKey: d.ctrlKey, metaKey: d.metaKey, altKey: d.altKey,
                isComposing: false, preventDefault: function() {{}}
            }});
        }} catch (err) {{}}
    }});
}})();
</script>
<!-- cv:{version} -->
</body>
</html>"""
    return html


def inject_hotkey_bridge_once():
    """
    把「父页面按键桥接」注入 Streamlit 主框架（真正的父页面上下文）。

    必须在调用 st.components.v1.html 渲染增强图表之前/之后调用一次。
    通过 st.markdown(unsafe_allow_html=True) 注入，确保不论焦点在父页面
    还是图表 iframe，快捷键都能触发（Windows 常见焦点在父页面的情况）。
    用 session_state 保证整页只注入一次。
    """
    import streamlit as st
    if st.session_state.get("_chart_hotkey_bridge_injected"):
        return
    st.session_state._chart_hotkey_bridge_injected = True

    bridge = """
<script>
(function() {
    if (window.__chartHotkeyBridgeInjected) return;
    window.__chartHotkeyBridgeInjected = true;
    document.addEventListener('keydown', function(e) {
        var tag = (document.activeElement || {}).tagName || '';
        if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        // 转发给所有含 __chartHotkey 标记的图表 iframe
        var frames = document.querySelectorAll('iframe[srcdoc]');
        for (var i = 0; i < frames.length; i++) {
            var f = frames[i];
            if (!f.contentWindow) continue;
            if (f.srcdoc && f.srcdoc.indexOf('__chartHotkey') !== -1) {
                try {
                    f.contentWindow.postMessage({
                        __chartHotkey: true,
                        key: e.key,
                        ctrlKey: e.ctrlKey, metaKey: e.metaKey, altKey: e.altKey
                    }, '*');
                } catch (err) {}
            }
        }
    }, true);
})();
</script>
"""
    st.markdown(bridge, unsafe_allow_html=True)