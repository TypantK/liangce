# -*- coding: utf-8 -*-
"""
图表工具 — mplfinance 蜡烛图 + 买卖信号标注
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import mplfinance as mpf
from io import BytesIO
import base64

plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'Arial Unicode MS', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

# --- 配色 ---
BG       = '#131520'
GRID_C   = '#1f2335'
UP_GREEN = '#26c281'
DN_RED   = '#e7505a'
BUY_TRI  = '#00e5ff'
SELL_TRI = '#ff6e40'
FG       = '#c8cce0'

MC = mpf.make_marketcolors(up=UP_GREEN, down=DN_RED, edge='inherit', wick='inherit', volume='inherit')
STYLE = mpf.make_mpf_style(
    marketcolors=MC, facecolor=BG, figcolor=BG,
    gridcolor=GRID_C, gridstyle='-', gridaxis='both',
    rc={'font.size': 9, 'axes.labelcolor': FG, 'axes.edgecolor': '#2a2d3e',
        'xtick.color': '#6b7094', 'ytick.color': '#6b7094'}
)


def plot_backtest(data, strategy_name, chart_mode="K线图",
                  buy_points=None, sell_points=None):
    buy_points = buy_points or []
    sell_points = sell_points or []

    df = data[['open', 'high', 'low', 'close', 'volume']].copy()
    df.index = pd.to_datetime(df.index)

    # MA addplots
    ap_ma5 = mpf.make_addplot(
        df['close'].rolling(5).mean(), color='#f5a623', width=0.9, linestyle='--')
    ap_ma20 = mpf.make_addplot(
        df['close'].rolling(20).mean(), color='#4da6ff', width=0.9, linestyle='--')

    # 买卖信号
    dti, n = df.index, len(df)
    bp_idx = [dti[idx] for idx, _ in buy_points if 0 <= idx < n]
    bp_val = [p for idx, p in buy_points if 0 <= idx < n]
    sp_idx = [dti[idx] for idx, _ in sell_points if 0 <= idx < n]
    sp_val = [p for idx, p in sell_points if 0 <= idx < n]

    bs = pd.Series(np.nan, index=df.index)
    ss = pd.Series(np.nan, index=df.index)
    if bp_idx:
        bs.loc[bp_idx] = bp_val
    if sp_idx:
        ss.loc[sp_idx] = sp_val

    ap_buy = mpf.make_addplot(
        bs, type='scatter', marker='^', markersize=160,
        color=BUY_TRI, edgecolors='white', linewidths=1.3)
    ap_sell = mpf.make_addplot(
        ss, type='scatter', marker='v', markersize=160,
        color=SELL_TRI, edgecolors='white', linewidths=1.3)

    candle_type = 'line' if chart_mode == '折线图' else 'candle'
    title = f'{strategy_name} — {chart_mode}'

    fig, axes = mpf.plot(
        df, type=candle_type, style=STYLE, volume=True,
        addplot=[ap_ma5, ap_ma20, ap_buy, ap_sell],
        title=title, ylabel='价格 (¥)', ylabel_lower='成交量',
        figsize=(16, 9), returnfig=True,
        datetime_format='%m-%d', xrotation=0,
    )

    ax1 = axes[0]

    # 自定义图例
    from matplotlib.lines import Line2D
    ax1.legend(handles=[
        Line2D([0], [0], color='#f5a623', ls='--', lw=1.5, label='MA5'),
        Line2D([0], [0], color='#4da6ff', ls='--', lw=1.5, label='MA20'),
        Line2D([0], [0], marker='^', color='w', mfc=BUY_TRI, ms=11, mew=1.3, label='买入'),
        Line2D([0], [0], marker='v', color='w', mfc=SELL_TRI, ms=11, mew=1.3, label='卖出'),
    ], loc='upper left', facecolor='#1c1f2e', edgecolor='#2a2d3e',
       labelcolor=FG, fontsize=9, framealpha=0.95)

    ax1.set_facecolor(BG)

    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=140, bbox_inches='tight',
                facecolor=BG, edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()