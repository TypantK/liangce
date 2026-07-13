# -*- coding: utf-8 -*-
"""
板块走势预测 —— 基于技术指标推演后续三种情景路径
参考风格：小红书截图中的「分段（数据预测）」界面
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go

from core.data_fetcher import STOCK_POOL, get_stock_data
from utils.chart import (UP_GREEN, DN_RED, CN_FONT)


# ============================================================
#  板块/标的选项
# ============================================================
# 板块类使用 SECTOR: 前缀（走申万行业板块指数接口）
# 格式：SECTOR:行业名#板块代码  → 带 #代码 可精准匹配东方财富行业板块
# 个股类直接使用 A股/美股/加密货币代码
SECTOR_OPTIONS = {
    # ── 真实行业板块指数（同花顺行业名，走独立域名不受东财限流）──
    "AI 半导体": "SECTOR:半导体",
    "半导体":     "SECTOR:半导体",
    "新能源":     "SECTOR:其他电源设备",
    "光伏":       "SECTOR:光伏设备",
    "白酒":       "SECTOR:白酒",
    "饮料":       "SECTOR:饮料制造",
    "银行":       "SECTOR:银行",
    "保险":       "SECTOR:保险",
    "证券":       "SECTOR:证券",
    "电池":       "SECTOR:电池",
    "汽车整车":   "SECTOR:汽车整车",
    "汽车零部件": "SECTOR:汽车零部件",
    "软件开发":   "SECTOR:软件开发",
    "消费电子":   "SECTOR:消费电子",
    "通信设备":   "SECTOR:通信设备",
    "军工":       "SECTOR:军工装备",
    "房地产":     "SECTOR:房地产",
    "医药":       "SECTOR:中药",
    "煤炭":       "SECTOR:煤炭开采加工",
    "钢铁":       "SECTOR:钢铁",
    # ── 个股（保持原样，便于个股级预测）──
    "比亚迪":     "002594.SZ",
    "贵州茅台":   "600519.SH",
    "平安银行":   "000001.SZ",
    "万科A":      "000002.SZ",
    "招商银行":   "600036.SH",
    "中国平安":   "601318.SH",
    "特斯拉":     "TSLA",
    "苹果":       "AAPL",
    "BTC/USDT":   "BTC/USDT",
    "ETH/USDT":   "ETH/USDT",
}


# ============================================================
#  预测引擎
# ============================================================

def _biz_days(start, n):
    """生成 n 个未来交易日（跳过周末）"""
    dates = []
    d = pd.Timestamp(start)
    while len(dates) < n:
        d += pd.Timedelta(days=1)
        if d.weekday() < 5:
            dates.append(d)
    return dates


def _compute_tech_score(df):
    """基于技术指标计算三种情景概率"""
    close = df['close'].values
    n = len(close)
    if n < 65:
        return {
            'bull': 40, 'base': 35, 'bear': 25,
            'bull_sig': '数据不足，中性假设', 'base_sig': '数据不足',
            'bear_sig': '数据不足', 'summary': '数据不足，建议观望',
            'ma20': 0, 'ma60': 0, 'price': close[-1] if n else 0,
            'slope_pct': 0, 'vol_ratio': 1.0,
        }

    ma20 = pd.Series(close).rolling(20).mean().iloc[-1]
    ma60 = pd.Series(close).rolling(60).mean().iloc[-1]
    price = close[-1]

    recent = close[-20:]
    x = np.arange(20)
    log_p = np.log(recent)
    slope, _ = np.polyfit(x, log_p, 1)
    slope_pct = slope * 100

    returns = np.diff(np.log(close[-21:]))
    vol = np.std(returns) if len(returns) > 1 else 0.01

    if 'volume' in df.columns and len(df) >= 25:
        vol_recent = df['volume'].tail(5).mean()
        vol_before = df['volume'].tail(25).head(20).mean()
        vol_ratio = vol_recent / vol_before if vol_before > 0 else 1.0
    else:
        vol_ratio = 1.0

    up_streak = 0
    for i in range(n-1, max(n-10, -1), -1):
        if close[i] > close[i-1]:
            up_streak += 1
        else:
            break

    score_bull = 0
    score_base = 0
    score_bear = 0

    # 价格 vs 均线
    if price > ma20 > ma60:
        score_bull += 30
        score_base += 10
    elif price > ma20 and ma20 < ma60:
        score_bull += 15
        score_base += 20
    elif ma20 > price > ma60:
        score_bull += 10
        score_base += 30
    elif price < ma60:
        score_bear += 30
        score_base += 15
    else:
        score_base += 25

    # 趋势斜率
    if slope_pct > 0.15:
        score_bull += 20
    elif slope_pct > 0.05:
        score_bull += 10
    elif slope_pct < -0.15:
        score_bear += 20
    elif slope_pct < -0.05:
        score_bear += 10
    else:
        score_base += 15

    # 成交量
    if vol_ratio > 1.5:
        if slope_pct > 0:
            score_bull += 15
        else:
            score_bear += 15
    elif vol_ratio < 0.7:
        score_base += 10

    # 连续涨跌
    if up_streak >= 3:
        score_bull += 10
    if up_streak >= 5:
        score_base += 10

    # 波动率
    if vol > 0.03:
        score_base += 5
        score_bear += 5

    total = score_bull + score_base + score_bear
    if total == 0:
        total = 1
    bull = round(score_bull / total * 100)
    base = round(score_base / total * 100)
    bear = max(0, 100 - bull - base)

    diff = 100 - (bull + base + bear)
    if diff > 0:
        base += diff
    elif diff < 0:
        base += diff
    bear = max(0, 100 - bull - base)

    # 信号文字
    bull_sig = []
    base_sig = []
    bear_sig = []

    if price > ma20 > ma60:
        bull_sig.append("多头排列确认")
    if slope_pct > 0.10:
        bull_sig.append("上升趋势强劲")
    if vol_ratio > 1.3 and slope_pct > 0:
        bull_sig.append("量能持续放大")
    if up_streak >= 3:
        bull_sig.append(f"连续{up_streak}日上涨")

    if abs(price - ma20) / price < 0.03:
        base_sig.append("价格接近MA20")
    if -0.05 < slope_pct < 0.05:
        base_sig.append("短期横盘整理")
    if vol_ratio < 1.0:
        base_sig.append("回调缩量")
    if ma20 > ma60 and price < ma20:
        base_sig.append("MA60支撑未破")

    if price < ma60:
        bear_sig.append("已跌破MA60")
    if slope_pct < -0.10:
        bear_sig.append("下降趋势加速")
    if vol_ratio > 1.5 and slope_pct < 0:
        bear_sig.append("放量杀跌")

    if bull >= base and bull >= bear:
        summary = f"强势格局，{bull_sig[0] if bull_sig else '多头趋势'}"
    elif base >= bull and base >= bear:
        summary = f"中性整理，{base_sig[0] if base_sig else '技术性回调'}"
    else:
        summary = f"偏弱格局，{bear_sig[0] if bear_sig else '关注支撑位'}"

    return {
        'bull': bull, 'base': base, 'bear': bear,
        'bull_sig': '、'.join(bull_sig) if bull_sig else '量能持续放大、情绪点燃',
        'base_sig': '、'.join(base_sig) if base_sig else '回调缩量、MA60不破即确认中继',
        'bear_sig': '、'.join(bear_sig) if bear_sig else '放量跌破关键支撑则趋势转弱',
        'summary': summary,
        'ma20': ma20, 'ma60': ma60, 'price': price,
        'slope_pct': slope_pct, 'vol_ratio': vol_ratio,
    }


def _path_to_ohlc(path, vol):
    """从 close 路径模拟 OHLC"""
    n = len(path)
    o = np.concatenate([[path[0]], path[:-1]])
    c = path
    h = np.maximum(o, c) * (1 + vol * 0.35)
    l = np.minimum(o, c) * (1 - vol * 0.35)
    return pd.DataFrame({'open': o, 'high': h, 'low': l, 'close': c})


def _generate_paths(df, n_days=60):
    """生成三种预测路径（OHLCV + 日期）"""
    close = df['close'].values
    last_price = close[-1]
    last_date = df.index[-1]
    ma20 = pd.Series(close).rolling(20).mean().iloc[-1]
    ma60 = pd.Series(close).rolling(60).mean().iloc[-1]

    recent = close[-20:]
    x = np.arange(20)
    log_p = np.log(recent)
    slope, _ = np.polyfit(x, log_p, 1)
    slope_price = slope * last_price

    returns = np.diff(np.log(close[-41:]))
    vol = np.std(returns) if len(returns) > 1 else 0.012

    future_dates = _biz_days(last_date, n_days)
    t = np.arange(1, n_days + 1)

    # 1. 直接突破
    bull_close = last_price + slope_price * 1.4 * t + last_price * vol * 0.4 * np.sqrt(t)
    bull_close = np.maximum(bull_close, last_price * (1 - 0.02 * t / n_days))
    bull_ohlc = _path_to_ohlc(bull_close, vol)

    # 2. 基准回调
    pullback_days = min(15, n_days // 3)
    recovery_days = n_days - pullback_days

    pullback_target = max(min(ma20, ma60), last_price * 0.93)
    pullback_target = min(pullback_target, last_price * 0.98)

    pullback_t = np.arange(1, pullback_days + 1)
    pullback_close = last_price + (pullback_target - last_price) * pullback_t / pullback_days
    pullback_close += last_price * vol * 0.2 * np.sin(pullback_t * 0.5)

    recovery_t = np.arange(1, recovery_days + 1)
    recovery_start = pullback_close[-1]
    recovery_close = recovery_start + slope_price * 0.8 * recovery_t + last_price * vol * 0.3 * np.sqrt(recovery_t)
    recovery_close = np.maximum(recovery_close, recovery_start * 0.98)

    base_close = np.concatenate([pullback_close, recovery_close])
    base_ohlc = _path_to_ohlc(base_close, vol)

    # 3. 趋势转弱
    bear_close = last_price - abs(slope_price) * 0.6 * t - last_price * vol * 0.5 * np.sqrt(t)
    bear_target = min(ma60 * 0.92, last_price * 0.88)
    if bear_close[-1] > bear_target:
        bear_close = bear_close * (bear_target / bear_close[-1])
    bear_close = np.maximum(bear_close, last_price * 0.70)
    bear_ohlc = _path_to_ohlc(bear_close, vol)

    return future_dates, bull_ohlc, base_ohlc, bear_ohlc


# ============================================================
#  绘图
# ============================================================

def _plot_prediction(df, future_dates, bull_ohlc, base_ohlc, bear_ohlc, tech, theme="dark"):
    """绘制历史K线 + 三种预测路径的交互式图表"""

    if theme == "light":
        _bg = '#ffffff'
        _grid_h = 'rgba(229,231,235,0.35)'
        _fg = '#1f2937'
        _fg_soft = '#6b7280'
        _line_c = '#d1d5db'
        _template = 'plotly_white'
        _legend_bg = 'rgba(243,244,246,0.92)'
    else:
        _bg = '#131520'
        _grid_h = 'rgba(31,35,53,0.30)'
        _fg = '#c8cce0'
        _fg_soft = '#6b7094'
        _line_c = '#2a2d3e'
        _template = 'plotly_dark'
        _legend_bg = 'rgba(26,29,46,0.92)'

    dti = pd.to_datetime(df.index)
    n = len(df)
    ma20_hist = df['close'].rolling(20).mean()
    ma60_hist = df['close'].rolling(60).mean()

    PATH_COLORS = {
        'bull': '#f5a623',
        'base': '#4da6ff',
        'bear': '#e7505a',
    }

    pivot_date = dti[-1]
    pivot_price = float(df['close'].iloc[-1])

    fig = go.Figure()

    # 历史 K 线
    fig.add_trace(go.Candlestick(
        x=dti,
        open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        name='历史行情',
        increasing_line_color=UP_GREEN, decreasing_line_color=DN_RED,
        increasing_fillcolor=UP_GREEN, decreasing_fillcolor=DN_RED,
        increasing_line_width=1.2, decreasing_line_width=1.2,
        whiskerwidth=0.8,
        showlegend=True,
        hoverinfo='x',
    ))

    # 预测半透明 K 线（基准路径）
    fig.add_trace(go.Candlestick(
        x=future_dates,
        open=base_ohlc['open'], high=base_ohlc['high'],
        low=base_ohlc['low'], close=base_ohlc['close'],
        name='基准预测（回调后）',
        increasing_line_color=PATH_COLORS['base'], decreasing_line_color=PATH_COLORS['base'],
        increasing_fillcolor=f"rgba(77,166,255,0.25)", decreasing_fillcolor=f"rgba(77,166,255,0.15)",
        increasing_line_width=1.0, decreasing_line_width=1.0,
        whiskerwidth=0.7,
        showlegend=True,
        hoverinfo='x',
    ))

    # MA20（历史 + 向前延伸用最后值）
    all_dates = list(dti) + list(future_dates)
    all_ma20 = list(ma20_hist.values) + [np.nan] * len(future_dates)
    all_ma60 = list(ma60_hist.values) + [np.NaN] * len(future_dates)

    fig.add_trace(go.Scatter(
        x=all_dates, y=all_ma20, name='MA20',
        line=dict(color='#f5a623', width=1.5),
        hovertemplate='MA20: %{y:.2f}<extra></extra>',
        connectgaps=False,
    ))

    fig.add_trace(go.Scatter(
        x=all_dates, y=all_ma60, name='MA60',
        line=dict(color='#4da6ff', width=1.5),
        hovertemplate='MA60: %{y:.2f}<extra></extra>',
        connectgaps=False,
    ))

    # 预测路径虚线
    for name, ohlc, color_key in [
        ('直接突破', bull_ohlc, 'bull'),
        ('基准回调', base_ohlc, 'base'),
        ('趋势转弱', bear_ohlc, 'bear'),
    ]:
        # 只画 close 线，不画K线（K线已经画了基准的）
        if name == '基准回调':
            # 基准已经画了半透明K线，这里只画虚线辅助
            fig.add_trace(go.Scatter(
                x=future_dates, y=ohlc['close'].values,
                name=f'{name}（路径）',
                mode='lines',
                line=dict(color=PATH_COLORS[color_key], width=1.5, dash='dash'),
                hovertemplate=f'{name}: %{{y:.2f}}<extra></extra>',
                showlegend=True,
            ))
        else:
            fig.add_trace(go.Scatter(
                x=future_dates, y=ohlc['close'].values,
                name=f'{name}',
                mode='lines',
                line=dict(color=PATH_COLORS[color_key], width=1.5, dash='dash'),
                hovertemplate=f'{name}: %{{y:.2f}}<extra></extra>',
                showlegend=True,
            ))

    # 预测起点垂直线
    fig.add_vline(
        x=pivot_date, line_dash='dash', line_color='#e5e7eb' if theme == 'light' else '#6b7094',
        line_width=1.5, opacity=0.7,
    )

    # 预测起点标注
    fig.add_annotation(
        x=pivot_date, y=pivot_price * 1.12,
        text=f"今日 {pivot_date.strftime('%m/%d')} · 预测起点",
        showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.5,
        arrowcolor='#f5a623',
        ax=40, ay=-40,
        font=dict(size=12, color='#f5a623', family=CN_FONT),
        bgcolor='rgba(20,20,30,0.85)' if theme != 'light' else 'rgba(255,255,255,0.9)',
        bordercolor='#f5a623', borderwidth=1,
    )

    # 预估回调标注（如果回调概率不是最低）
    if tech['base'] > 15:
        pullback_idx = min(len(future_dates) // 3, 14)
        if pullback_idx < len(future_dates):
            px = future_dates[pullback_idx]
            py = base_ohlc['close'].iloc[pullback_idx]
            fig.add_annotation(
                x=px, y=py * 1.06,
                text="预估阶段性回调",
                showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.5,
                arrowcolor=PATH_COLORS['base'],
                ax=-50, ay=-30,
                font=dict(size=11, color=PATH_COLORS['base'], family=CN_FONT),
                bgcolor='rgba(20,20,30,0.85)' if theme != 'light' else 'rgba(255,255,255,0.9)',
                bordercolor=PATH_COLORS['base'], borderwidth=1,
            )

    # 直接突破标注
    if tech['bull'] > 30:
        bull_idx = min(len(future_dates) * 3 // 4, len(future_dates)-1)
        px = future_dates[bull_idx]
        py = bull_ohlc['close'].iloc[bull_idx]
        fig.add_annotation(
            x=px, y=py * 1.03,
            text="预估新一轮上行",
            showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.5,
            arrowcolor=PATH_COLORS['bull'],
            ax=40, ay=-30,
            font=dict(size=11, color=PATH_COLORS['bull'], family=CN_FONT),
            bgcolor='rgba(20,20,30,0.85)' if theme != 'light' else 'rgba(255,255,255,0.9)',
            bordercolor=PATH_COLORS['bull'], borderwidth=1,
        )

    # Layout
    fig.update_layout(
        template=_template,
        paper_bgcolor=_bg,
        plot_bgcolor=_bg,
        font=dict(color=_fg, size=11, family=CN_FONT),
        title=dict(
            text=f'<b>分段走势预测</b> — 数据推演',
            font=dict(color=_fg, size=17, family=CN_FONT),
            x=0.01, xanchor='left',
        ),
        height=620,
        hovermode='closest',
        showlegend=True,
        legend=dict(
            orientation='h', yanchor='top', y=1.06, xanchor='left', x=0.01,
            bgcolor=_legend_bg, bordercolor=_line_c, borderwidth=1,
            font=dict(color=_fg_soft, size=10, family=CN_FONT),
        ),
        margin=dict(l=60, r=30, t=55, b=40),
        dragmode='pan',
    )

    fig.update_xaxes(
        showgrid=False, zeroline=False,
        linecolor=_line_c, linewidth=1,
        tickformat='%Y-%m',
        tickfont=dict(color=_fg_soft, size=10, family=CN_FONT),
    )
    fig.update_yaxes(
        title_text='价格',
        gridcolor=_grid_h, griddash='dash', gridwidth=0.8,
        showgrid=True, zeroline=False,
        linecolor=_line_c, linewidth=1,
        title_font=dict(color=_fg_soft, size=10, family=CN_FONT),
        tickformat='.2f',
        tickfont=dict(color=_fg_soft, size=10, family=CN_FONT),
    )

    return fig


# ============================================================
#  UI 渲染
# ============================================================

def render():
    theme = st.session_state.get("_theme_mode", "dark")

    # ========== 标题 ==========
    st.title('板块走势预测')
    st.caption('基于技术指标推演后续三种情景路径，辅助判断操作策略')

    st.markdown('---')

    # ========== 控制区 ==========
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        sector_name = st.selectbox(
            '选择板块/标的', list(SECTOR_OPTIONS.keys()),
            help='板块类走申万行业指数，个股类走对应行情接口',
        )
    with col2:
        predict_days = st.selectbox('预测天数', [30, 45, 60, 90], index=2)
    with col3:
        st.markdown('<br>', unsafe_allow_html=True)
        run_btn = st.button('开始预测', type='primary', use_container_width=True)

    if not run_btn:
        st.info('请选择板块并点击「开始预测」生成推演路径')
        return

    # ========== 数据获取 ==========
    symbol = SECTOR_OPTIONS[sector_name]
    is_sector = symbol.startswith('SECTOR:')
    price_unit = '点' if is_sector else '¥'
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

    with st.spinner('正在刷新行情数据并计算预测路径...'):
        # 点击「开始预测」强制重新联网拉取最新行情，避免一直显示旧缓存数据
        df = get_stock_data(symbol, start=start, end=end, force_refresh=True)

    if df is None or df.empty or len(df) < 65:
        st.error('数据不足或获取失败，无法生成预测。请尝试其他标的。')
        return

    # ========== 计算预测 ==========
    tech = _compute_tech_score(df)
    future_dates, bull_ohlc, base_ohlc, bear_ohlc = _generate_paths(df, n_days=predict_days)

    # ========== 图表 ==========
    fig = _plot_prediction(df, future_dates, bull_ohlc, base_ohlc, bear_ohlc, tech, theme=theme)
    st.plotly_chart(fig, use_container_width=True, key='sector_pred_chart')

    # ========== 预测起点信息 ==========
    last_price = df['close'].iloc[-1]
    last_date = df.index[-1]

    st.markdown('---')
    st.markdown(f"### 预测起点 · {last_date.strftime('%Y-%m-%d')} 收盘 {price_unit}{last_price:.2f}")

    # 图例说明
    hist_label = '历史板块指数' if is_sector else '历史行情'
    st.markdown(f"""
    **图例说明：**
    - <span style='color:#e7505a'>红色实心蜡烛</span> = {hist_label}（已发生）
    - <span style='color:#4da6ff'>蓝色半透明蜡烛</span> = 基准预测（回调后情景）
    - <span style='color:#f5a623'>金色虚线</span> = 直接突破路径
    - <span style='color:#e7505a'>红色虚线</span> = 趋势转弱路径
    """, unsafe_allow_html=True)

    # ========== 概率分析表格 ==========
    st.markdown('---')
    st.markdown('### 概率分析 · 触发信号')

    prob_data = [
        {'情景': '直接突破', '概率': f"~{tech['bull']}%", '触发/验证信号': tech['bull_sig']},
        {'情景': '基准回调', '概率': f"~{tech['base']}%", '触发/验证信号': tech['base_sig']},
        {'情景': '趋势转弱', '概率': f"~{tech['bear']}%", '触发/验证信号': tech['bear_sig']},
    ]
    prob_df = pd.DataFrame(prob_data)

    # 自定义样式表格
    if theme == 'dark':
        st.markdown(
            prob_df.to_html(
                index=False, escape=False,
                classes='prediction-table',
            ).replace(
                '<table', '<table style="width:100%;border-collapse:collapse;font-family:PingFang SC,Microsoft YaHei,sans-serif;font-size:14px;"'
            ).replace(
                '<th', '<th style="background:#1a1d2e;color:#c8cce0;padding:12px 16px;text-align:left;border-bottom:2px solid #2a2d3e;font-weight:600;"'
            ).replace(
                '<td', '<td style="color:#c8cce0;padding:10px 16px;border-bottom:1px solid #2a2d3e;"'
            ),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            prob_df.to_html(
                index=False, escape=False,
                classes='prediction-table',
            ).replace(
                '<table', '<table style="width:100%;border-collapse:collapse;font-family:PingFang SC,Microsoft YaHei,sans-serif;font-size:14px;"'
            ).replace(
                '<th', '<th style="background:#f3f4f6;color:#1f2937;padding:12px 16px;text-align:left;border-bottom:2px solid #e5e7eb;font-weight:600;"'
            ).replace(
                '<td', '<td style="color:#1f2937;padding:10px 16px;border-bottom:1px solid #e5e7eb;"'
            ),
            unsafe_allow_html=True,
        )

    # ========== 分析文字 ==========
    st.markdown('---')
    st.markdown('### 推演分析')

    ma20 = tech['ma20']
    ma60 = tech['ma60']
    price = tech['price']
    slope_pct = tech['slope_pct']
    vol_ratio = tech['vol_ratio']

    # 基准分析
    base_analysis = f"""
    **基准预估（回调后）：** 当前价格 {price_unit}{price:.2f} 处于 MA20({price_unit}{ma20:.2f}) / MA60({price_unit}{ma60:.2f}) 附近。
    """
    if price > ma20 > ma60:
        base_analysis += f"""
    多头排列完好，若后续回踩 MA20（约 {price_unit}{ma20:.2f}）且缩量不破，则消化短期获利盘后有望再起新一轮上行。
    """
    elif ma20 > price > ma60:
        base_analysis += f"""
    价格已回落至 MA20 与 MA60 之间，短期技术性回调概率较高。若 MA60（约 {price_unit}{ma60:.2f}）支撑有效，则有望企稳反弹。
    """
    elif price < ma60:
        base_analysis += f"""
    价格已跌破 MA60（约 {price_unit}{ma60:.2f}），短期趋势偏弱。需关注能否快速收复，否则可能进一步下探。
    """
    else:
        base_analysis += f"""
    价格在均线附近盘整，方向尚不明确。关注后续放量方向选择。
    """

    # 直接突破分析
    if slope_pct > 0.05:
        bull_analysis = f"""
    **不调整直接突破：** 近期日斜率 {slope_pct:.2f}%，上升趋势明确。若量能持续放大（当前量比 {vol_ratio:.2f}），则有望沿当前 momentum 继续上攻，跳过回调阶段。
    """
    else:
        bull_analysis = f"""
    **不调整直接突破：** 当前趋势斜率偏低（{slope_pct:.2f}%），直接突破需等待放量信号确认。
    """

    st.markdown(base_analysis)
    st.markdown(bull_analysis)

    # 关键价位
    st.markdown('---')
    st.markdown('### 关键价位参考')

    key_levels = []
    key_levels.append({'类型': 'MA20 支撑', '价位': f'{price_unit}{ma20:.2f}', '意义': '短期回调第一支撑'})
    key_levels.append({'类型': 'MA60 支撑', '价位': f'{price_unit}{ma60:.2f}', '意义': '中期趋势分界线'})
    key_levels.append({'类型': '当前收盘', '价位': f'{price_unit}{price:.2f}', '意义': '预测起点'})
    key_levels.append({'类型': '预测高点（突破）', '价位': f'{price_unit}{bull_ohlc["close"].iloc[-1]:.2f}', '意义': f'{predict_days}日后直接突破情景'})
    key_levels.append({'类型': '预测低点（转弱）', '价位': f'{price_unit}{bear_ohlc["close"].iloc[-1]:.2f}', '意义': f'{predict_days}日后趋势转弱情景'})

    key_df = pd.DataFrame(key_levels)
    if theme == 'dark':
        st.markdown(
            key_df.to_html(index=False, escape=False).replace(
                '<table', '<table style="width:100%;border-collapse:collapse;font-family:PingFang SC,Microsoft YaHei,sans-serif;font-size:14px;"'
            ).replace(
                '<th', '<th style="background:#1a1d2e;color:#c8cce0;padding:12px 16px;text-align:left;border-bottom:2px solid #2a2d3e;font-weight:600;"'
            ).replace(
                '<td', '<td style="color:#c8cce0;padding:10px 16px;border-bottom:1px solid #2a2d3e;"'
            ),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            key_df.to_html(index=False, escape=False).replace(
                '<table', '<table style="width:100%;border-collapse:collapse;font-family:PingFang SC,Microsoft YaHei,sans-serif;font-size:14px;"'
            ).replace(
                '<th', '<th style="background:#f3f4f6;color:#1f2937;padding:12px 16px;text-align:left;border-bottom:2px solid #e5e7eb;font-weight:600;"'
            ).replace(
                '<td', '<td style="color:#1f2937;padding:10px 16px;border-bottom:1px solid #e5e7eb;"'
            ),
            unsafe_allow_html=True,
        )

    st.caption('⚠️ 以上推演基于历史数据与技术指标，不构成投资建议。市场走势受多重因素影响，请结合基本面与宏观环境独立判断。')


if __name__ == '__main__':
    render()
