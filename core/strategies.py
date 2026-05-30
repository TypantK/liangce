# -*- coding: utf-8 -*-
"""
策略库 - 所有可切换的策略定义
"""

import backtrader as bt

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
                size = self.broker.getcash() * 0.95 / self.data.close[0]
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
        ('oversold', 30),
        ('overbought', 70),
        ('trailing_stop', 3.0),
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
                size = self.broker.getcash() * 0.95 / self.data.close[0]
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
                size = self.broker.getcash() * 0.95 / self.data.close[0]
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
                size = self.broker.getcash() * 0.95 / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_price = self.data.close[0]
        else:
            pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price * 100
            if self.data.close[0] >= self.boll.lines.mid or pnl_pct <= -self.params.stop_loss:
                self.order = self.sell(size=self.position.size)


# ============================================================
#  策略注册表
# ============================================================
STRATEGY_REGISTRY = {
    "双均线交叉": {
        "class": DualMAStrategy,
        "params": {"fast": (3, 15, 5), "slow": (10, 60, 20),
                    "stop_loss": (0.5, 5.0, 2.0), "take_profit": (1.0, 10.0, 5.0)},
        "param_labels": {"fast": "快线周期（天）", "slow": "慢线周期（天）",
                         "stop_loss": "止损线（%）", "take_profit": "止盈线（%）"},
        "desc": "快线（SMA）上穿慢线买入，下穿/止盈/止损卖出。适合趋势行情。"
    },
    "RSI 超买超卖": {
        "class": RSIStrategy,
        "params": {"rsi_period": (7, 28, 14), "oversold": (20, 40, 30),
                    "overbought": (60, 80, 70), "trailing_stop": (1.0, 8.0, 3.0)},
        "param_labels": {"rsi_period": "RSI 周期（天）", "oversold": "超卖线",
                         "overbought": "超买线", "trailing_stop": "跟踪止损（%）"},
        "desc": "RSI 低于超卖线买入，高于超买线或触发跟踪止损卖出。适合震荡行情。"
    },
    "MACD 策略": {
        "class": MACDStrategy,
        "params": {"macd_fast": (8, 20, 12), "macd_slow": (20, 40, 26),
                    "macd_signal": (5, 15, 9), "stop_loss": (1.0, 8.0, 3.0)},
        "param_labels": {"macd_fast": "快线周期", "macd_slow": "慢线周期",
                         "macd_signal": "信号线周期", "stop_loss": "止损线（%）"},
        "desc": "MACD 金叉买入、死叉卖出，带固定止损。趋势跟踪经典策略。"
    },
    "布林带策略": {
        "class": BollingerStrategy,
        "params": {"period": (10, 40, 20), "devfactor": (1.5, 3.0, 2.0),
                    "stop_loss": (1.0, 5.0, 2.0)},
        "param_labels": {"period": "布林带周期（天）", "devfactor": "标准差倍数",
                         "stop_loss": "止损线（%）"},
        "desc": "价格触及布林带下轨买入，回归中轨卖出。适合均值回归行情。"
    },
}