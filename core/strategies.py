# -*- coding: utf-8 -*-
"""
策略库 - 所有可切换的策略定义

策略分类：
  【滞后型】基于已发生数据的趋势/震荡指标
    - 双均线交叉、RSI超买超卖、MACD策略、布林带策略

  【预测型】尝试从噪声中推断未来趋势方向
    - 卡尔曼滤波趋势：状态空间模型估计隐藏价格速度
    - HMA 低延迟均线：大幅减少滞后，更快捕捉拐点
    - 线性回归斜率：拟合斜率作为领先指标
    - 一目均衡表：云层投影 26 期到未来，形成前瞻参考区
"""

import backtrader as bt
import numpy as np

# ============================================================
#  自研预测型指标
# ============================================================

class KalmanFilterIndicator(bt.Indicator):
    """
    卡尔曼滤波指标：从噪声价格观测中估计"真实价格"和"价格速度"。
    - kf_price:  滤波后的估计价格
    - kf_velocity: 估计的价格变化速度（趋势强度）

    状态空间模型（恒速模型）：
      状态 [price, velocity]
      状态转移: price[t] = price[t-1] + velocity[t-1]
               velocity[t] = velocity[t-1]
      观测:     z[t] = price[t] + noise

    过程噪声 Q 越小 → 滤波更平滑但响应慢
    测量噪声 R 越小 → 更相信观测值，响应更快
    """
    lines = ('kf_price', 'kf_velocity')
    params = (
        ('process_noise', 1e-4),
        ('measurement_noise', 1e-1),
    )

    def __init__(self):
        self.addminperiod(2)

    def prenext(self):
        # 前两根 bar 尚未足够数据做初始化
        pass

    def nextstart(self):
        # 有足够数据后，初始化卡尔曼滤波器状态
        self._x = np.array([[self.data.close[0]], [0.0]])  # [price, velocity]
        self._P = np.eye(2) * 0.1
        self._F = np.array([[1.0, 1.0], [0.0, 1.0]])       # 状态转移
        self._H = np.array([[1.0, 0.0]])                    # 观测矩阵
        self._Q = np.eye(2) * self.p.process_noise          # 过程噪声
        self._R = np.eye(1) * self.p.measurement_noise      # 测量噪声

    def next(self):
        if not hasattr(self, '_x'):
            # 第一次 next() 时初始化（兼容不同数据预热阶段）
            self._x = np.array([[self.data.close[0]], [0.0]])
            self._P = np.eye(2) * 0.1
            self._F = np.array([[1.0, 1.0], [0.0, 1.0]])
            self._H = np.array([[1.0, 0.0]])
            self._Q = np.eye(2) * self.p.process_noise
            self._R = np.eye(1) * self.p.measurement_noise

        # ---- 预测 ----
        x_pred = self._F @ self._x
        P_pred = self._F @ self._P @ self._F.T + self._Q

        # ---- 更新 ----
        z = np.array([[self.data.close[0]]])
        y = z - self._H @ x_pred            # 测量残差
        S = self._H @ P_pred @ self._H.T + self._R
        K = P_pred @ self._H.T @ np.linalg.inv(S)   # 卡尔曼增益

        self._x = x_pred + K @ y
        self._P = (np.eye(2) - K @ self._H) @ P_pred

        self.lines.kf_price[0] = self._x[0, 0]
        self.lines.kf_velocity[0] = self._x[1, 0]


class LinearRegressionSlope(bt.Indicator):
    """
    线性回归斜率：对最近 N 期收盘价做线性回归，返回斜率。
    斜率 > 0 表示上升趋势（加速度），斜率 < 0 表示下跌趋势。
    比均线金叉更早捕捉趋势方向变化。
    """
    lines = ('slope',)
    params = (('period', 20),)

    def __init__(self):
        self.addminperiod(self.p.period)

    def next(self):
        if len(self.data) < self.p.period:
            self.lines.slope[0] = 0.0
            return
        y = np.array([self.data.close[-i] for i in range(self.p.period)])
        x = np.arange(self.p.period, dtype=float)
        x_mean = x.mean()
        y_mean = y.mean()
        slope = np.sum((x - x_mean) * (y - y_mean)) / np.sum((x - x_mean) ** 2)
        # 归一化到 y_mean 百分比，使不同价位可比
        self.lines.slope[0] = slope / (y_mean + 1e-10)


# ============================================================
#  策略 1：双均线交叉
# ============================================================
class DualMAStrategy(bt.Strategy):
    """双均线交叉 + 止盈止损"""
    params = (
        ('fast', 5),
        ('slow', 20),
        ('stop_loss', 2.0),
        ('take_profit', 5.0),
        ('position_pct', 0.95),
    )

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.params.fast)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.params.slow)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        self.order = None
        self.entry_price = 0

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self.order = None

    def next(self):
        if self.order:
            return
        if not self.position:
            if self.crossover > 0:
                size = self.broker.getcash() * self.params.position_pct / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_price = self.data.close[0]
        else:
            pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price * 100
            if self.crossover < 0 or pnl_pct >= self.params.take_profit or pnl_pct <= -self.params.stop_loss:
                self.order = self.sell(size=self.position.size)


# ============================================================
#  策略 2：RSI 超买超卖
# ============================================================
class RSIStrategy(bt.Strategy):
    """RSI + 跟踪止损"""
    params = (
        ('rsi_period', 14),
        ('oversold', 35),
        ('overbought', 65),
        ('trailing_stop', 3.0),
        ('position_pct', 0.95),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.params.rsi_period)
        self.order = None
        self.highest = 0

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self.order = None

    def next(self):
        if self.order:
            return
        if not self.position:
            if self.rsi < self.params.oversold:
                size = self.broker.getcash() * self.params.position_pct / self.data.close[0]
                self.order = self.buy(size=size)
                self.highest = self.data.close[0]
        else:
            self.highest = max(self.highest, self.data.close[0])
            trailing = self.highest * (1 - self.params.trailing_stop / 100)
            if self.rsi > self.params.overbought or self.data.close[0] < trailing:
                self.order = self.sell(size=self.position.size)


# ============================================================
#  策略 3：MACD 策略
# ============================================================
class MACDStrategy(bt.Strategy):
    """MACD 金叉死叉"""
    params = (
        ('macd_fast', 12),
        ('macd_slow', 26),
        ('macd_signal', 9),
        ('stop_loss', 3.0),
        ('position_pct', 0.95),
    )

    def __init__(self):
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.params.macd_fast,
            period_me2=self.params.macd_slow,
            period_signal=self.params.macd_signal
        )
        self.crossover = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)
        self.order = None
        self.entry_price = 0

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self.order = None

    def next(self):
        if self.order:
            return
        if not self.position:
            if self.crossover > 0:
                size = self.broker.getcash() * self.params.position_pct / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_price = self.data.close[0]
        else:
            pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price * 100
            if self.crossover < 0 or pnl_pct <= -self.params.stop_loss:
                self.order = self.sell(size=self.position.size)


# ============================================================
#  策略 4：布林带策略
# ============================================================
class BollingerStrategy(bt.Strategy):
    """布林带下轨买入、中轨卖出"""
    params = (
        ('period', 20),
        ('devfactor', 2.0),
        ('stop_loss', 2.0),
        ('position_pct', 0.95),
    )

    def __init__(self):
        self.boll = bt.indicators.BollingerBands(
            self.data.close,
            period=self.params.period,
            devfactor=self.params.devfactor
        )
        self.order = None
        self.entry_price = 0

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self.order = None

    def next(self):
        if self.order:
            return
        if not self.position:
            if self.data.close[0] <= self.boll.lines.bot:
                size = self.broker.getcash() * self.params.position_pct / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_price = self.data.close[0]
        else:
            pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price * 100
            if self.data.close[0] >= self.boll.lines.mid or pnl_pct <= -self.params.stop_loss:
                self.order = self.sell(size=self.position.size)


# ============================================================
#  策略 5：卡尔曼滤波趋势（预测型）
# ============================================================
class KalmanTrendStrategy(bt.Strategy):
    """
    卡尔曼滤波 + 跟踪止损。
    核心理念：卡尔曼滤波从噪声价格中估计出隐藏的"速度"信号。
    速度 > 0 意味着价格内在趋势向上（预测型买入），
    速度 < 0 意味着趋势向下（预测型卖出）。
    相比均线等指标，卡尔曼滤波通过状态空间模型对未来有一阶预测。
    """
    params = (
        ('process_noise', 1e-4),
        ('measurement_noise', 1e-1),
        ('trail_percent', 4.0),
        ('position_pct', 0.95),
    )

    def __init__(self):
        self.kf = KalmanFilterIndicator(
            process_noise=self.p.process_noise,
            measurement_noise=self.p.measurement_noise
        )
        self.kf_velocity = self.kf.lines.kf_velocity
        self.order = None
        self.highest = 0

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self.order = None

    def next(self):
        if self.order:
            return
        if len(self.kf_velocity) == 0:
            return
        vel = self.kf_velocity[0]
        if not self.position:
            if vel > 0:
                size = self.broker.getcash() * self.params.position_pct / self.data.close[0]
                self.order = self.buy(size=size)
                self.highest = self.data.close[0]
        else:
            self.highest = max(self.highest, self.data.close[0])
            trailing = self.highest * (1 - self.p.trail_percent / 100)
            if vel < 0 or self.data.close[0] < trailing:
                self.order = self.sell(size=self.position.size)


# ============================================================
#  策略 6：HMA 低延迟均线（预测型）
# ============================================================
class HMAStrategy(bt.Strategy):
    """
    Hull Moving Average + EMA 信号线交叉。
    HMA 通过加权移动平均组合大幅降低了传统均线的滞后，
    能更快检测到趋势拐点。叠加 EMA 信号线过滤假突破。
    """
    params = (
        ('hma_period', 20),
        ('signal_period', 9),
        ('stop_loss', 3.0),
        ('position_pct', 0.95),
    )

    def __init__(self):
        self.hma = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.hma_period
        )
        self.signal = bt.indicators.EMA(self.hma, period=self.p.signal_period)
        self.crossover = bt.indicators.CrossOver(self.hma, self.signal)
        self.order = None
        self.entry_price = 0

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self.order = None

    def next(self):
        if self.order:
            return
        if not self.position:
            if self.crossover > 0:
                size = self.broker.getcash() * self.params.position_pct / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_price = self.data.close[0]
        else:
            pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price * 100
            if self.crossover < 0 or pnl_pct <= -self.p.stop_loss:
                self.order = self.sell(size=self.position.size)


# ============================================================
#  策略 7：线性回归斜率（预测型）
# ============================================================
class LinearRegressionSlopeStrategy(bt.Strategy):
    """
    线性回归斜率趋势策略。
    对最近 N 期价格拟合回归直线，斜率 > 0 表示上升趋势在加速，
    斜率 < 0 表示下跌趋势在加速。
    斜率作为领先指标，比均线交叉更早捕捉趋势方向转变。
    使用斜率平滑值避免频繁翻转。
    """
    params = (
        ('lr_period', 20),
        ('smooth_period', 5),
        ('stop_loss', 3.0),
        ('position_pct', 0.95),
    )

    def __init__(self):
        self.slope_raw = LinearRegressionSlope(period=self.p.lr_period)
        self.slope_smooth = bt.indicators.EMA(self.slope_raw, period=self.p.smooth_period)
        self.order = None
        self.entry_price = 0

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self.order = None

    def next(self):
        if self.order:
            return
        slope = self.slope_smooth[0]
        if not self.position:
            if slope > 0:
                size = self.broker.getcash() * self.params.position_pct / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_price = self.data.close[0]
        else:
            pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price * 100
            if slope < 0 or pnl_pct <= -self.p.stop_loss:
                self.order = self.sell(size=self.position.size)


# ============================================================
#  策略 8：一目均衡表（预测型）
# ============================================================
class IchimokuStrategy(bt.Strategy):
    """
    一目均衡表（Ichimoku Kinko Hyo）。
    核心预测特性：Senkou Span A/B 形成的"云层"被投影到未来 26 期，
    是少有的直接向未来延伸的技术指标。
    - 价格在云上方 → 上升趋势，云层充当下方支撑
    - 价格在云下方 → 下降趋势，云层充当上方阻力
    - 云层变色（A/B 交叉）→ 趋势可能反转
    同时用 Tenkan/Kijun 交叉确认入场时机。
    """
    params = (
        ('tenkan', 9),
        ('kijun', 26),
        ('senkou', 52),
        ('stop_loss', 4.0),
        ('position_pct', 0.95),
    )

    def __init__(self):
        self.ichimoku = bt.indicators.Ichimoku(
            tenkan=self.p.tenkan,
            kijun=self.p.kijun,
            senkou=self.p.senkou,
        )
        # 引用各条线
        self.tenkan = self.ichimoku.lines.tenkan_sen
        self.kijun = self.ichimoku.lines.kijun_sen
        self.senkou_a = self.ichimoku.lines.senkou_span_a
        self.senkou_b = self.ichimoku.lines.senkou_span_b
        self.order = None
        self.entry_price = 0

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self.order = None

    def next(self):
        if self.order:
            return
        # Senkou Span 需要足够数据才能形成
        if len(self.senkou_a) < 1 or len(self.senkou_b) < 1:
            return
        current_close = self.data.close[0]
        cloud_top = max(self.senkou_a[0], self.senkou_b[0])
        cloud_bottom = min(self.senkou_a[0], self.senkou_b[0])
        tenkan_cross_up = self.tenkan[0] > self.kijun[0] and self.tenkan[-1] <= self.kijun[-1]

        if not self.position:
            # 价格在云上方 且 Tenkan 上穿 Kijun → 做多
            if current_close > cloud_top and tenkan_cross_up:
                size = self.broker.getcash() * self.params.position_pct / current_close
                self.order = self.buy(size=size)
                self.entry_price = current_close
        else:
            pnl_pct = (current_close - self.entry_price) / self.entry_price * 100
            tenkan_cross_down = self.tenkan[0] < self.kijun[0] and self.tenkan[-1] >= self.kijun[-1]
            # 跌破云底支撑 / Tenkan 下穿 Kijun / 止损
            if (current_close < cloud_bottom or
                tenkan_cross_down or
                pnl_pct <= -self.p.stop_loss):
                self.order = self.sell(size=self.position.size)


# ============================================================
#  策略注册表
# ============================================================
STRATEGY_REGISTRY = {
    "双均线交叉": {
        "class": DualMAStrategy,
        "params": {"fast": (3, 15, 5), "slow": (10, 60, 20),
                    "stop_loss": (0.5, 5.0, 2.0), "take_profit": (1.0, 10.0, 5.0),
                    "position_pct": (0.1, 1.0, 0.95)},
        "param_labels": {"fast": "快线周期（天）", "slow": "慢线周期（天）",
                         "stop_loss": "止损线（%）", "take_profit": "止盈线（%）",
                         "position_pct": "仓位比例"},
        "desc": "快线（SMA）上穿慢线买入，下穿/止盈/止损卖出。适合趋势行情。"
    },
    "RSI 超买超卖": {
        "class": RSIStrategy,
        "params": {"rsi_period": (7, 28, 14), "oversold": (20, 40, 35),
                    "overbought": (60, 80, 65), "trailing_stop": (1.0, 8.0, 3.0),
                    "position_pct": (0.1, 1.0, 0.95)},
        "param_labels": {"rsi_period": "RSI 周期（天）", "oversold": "超卖线",
                         "overbought": "超买线", "trailing_stop": "跟踪止损（%）",
                         "position_pct": "仓位比例"},
        "desc": "RSI 低于超卖线买入，高于超买线或触发跟踪止损卖出。适合震荡行情。"
    },
    "MACD 策略": {
        "class": MACDStrategy,
        "params": {"macd_fast": (8, 20, 12), "macd_slow": (20, 40, 26),
                    "macd_signal": (5, 15, 9), "stop_loss": (1.0, 8.0, 3.0),
                    "position_pct": (0.1, 1.0, 0.95)},
        "param_labels": {"macd_fast": "快线周期", "macd_slow": "慢线周期",
                         "macd_signal": "信号线周期", "stop_loss": "止损线（%）",
                         "position_pct": "仓位比例"},
        "desc": "MACD 金叉买入、死叉卖出，带固定止损。趋势跟踪经典策略。"
    },
    "布林带策略": {
        "class": BollingerStrategy,
        "params": {"period": (10, 40, 20), "devfactor": (1.5, 3.0, 2.0),
                    "stop_loss": (1.0, 5.0, 2.0),
                    "position_pct": (0.1, 1.0, 0.95)},
        "param_labels": {"period": "布林带周期（天）", "devfactor": "标准差倍数",
                         "stop_loss": "止损线（%）",
                         "position_pct": "仓位比例"},
        "desc": "价格触及布林带下轨买入，回归中轨卖出。适合均值回归行情。"
    },
    # ---- 预测型策略 ----
    "卡尔曼滤波趋势": {
        "class": KalmanTrendStrategy,
        "params": {"process_noise": (1e-6, 1e-2, 1e-4),
                    "measurement_noise": (1e-3, 1.0, 1e-1),
                    "trail_percent": (1.0, 8.0, 4.0),
                    "position_pct": (0.1, 1.0, 0.95)},
        "param_labels": {"process_noise": "过程噪声 Q",
                         "measurement_noise": "测量噪声 R",
                         "trail_percent": "跟踪止损（%）",
                         "position_pct": "仓位比例"},
        "desc": "卡尔曼滤波估计隐藏价格速度，速度>0做多，速度<0平仓。从噪声中推断趋势方向，具有前瞻性。"
    },
    "HMA 低延迟均线": {
        "class": HMAStrategy,
        "params": {"hma_period": (10, 40, 20), "signal_period": (5, 20, 9),
                    "stop_loss": (1.0, 8.0, 3.0),
                    "position_pct": (0.1, 1.0, 0.95)},
        "param_labels": {"hma_period": "HMA 周期", "signal_period": "信号线周期",
                         "stop_loss": "止损线（%）",
                         "position_pct": "仓位比例"},
        "desc": "Hull Moving Average 大幅减少滞后，配合 EMA 信号线交叉。比传统均线更早捕捉拐点。"
    },
    "线性回归斜率": {
        "class": LinearRegressionSlopeStrategy,
        "params": {"lr_period": (10, 40, 20), "smooth_period": (3, 15, 5),
                    "stop_loss": (1.0, 8.0, 3.0),
                    "position_pct": (0.1, 1.0, 0.95)},
        "param_labels": {"lr_period": "回归周期（天）", "smooth_period": "平滑周期",
                         "stop_loss": "止损线（%）",
                         "position_pct": "仓位比例"},
        "desc": "对价格拟合回归直线，斜率作为领先指标。斜率>0做多，<0平仓。提前反映趋势加速度。"
    },
    "一目均衡表": {
        "class": IchimokuStrategy,
        "params": {"tenkan": (7, 15, 9), "kijun": (20, 40, 26),
                    "senkou": (40, 65, 52), "stop_loss": (2.0, 10.0, 4.0),
                    "position_pct": (0.1, 1.0, 0.95)},
        "param_labels": {"tenkan": "转换线周期", "kijun": "基准线周期",
                         "senkou": "先行带周期", "stop_loss": "止损线（%）",
                         "position_pct": "仓位比例"},
        "desc": "云层投影到未来 26 期形成前瞻参考。价格在云上做多，跌破云底平仓。独特的预测性指标。"
    },
}