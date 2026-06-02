# -*- coding: utf-8 -*-
"""
回测引擎 v2 — 增加策略名称和触发原因捕获
"""

import sys
import backtrader as bt
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

# ---- 各策略的人话解释 ----
STRATEGY_EXPLANATIONS = {
    "双均线交叉": {
        "summary": "用两根均线判断趋势方向——快线在上=上涨趋势，快线在下=下跌趋势。",
        "buy_logic": "快线（短期均线）从下方向上穿过慢线（长期均线），俗称「金叉」。意思是近期涨势压倒长期趋势，短期资金正在入场，该跟了。",
        "sell_logic": "快线从上方向下穿过慢线，即「死叉」。或者股价涨/跌到预设的止盈/止损线时自动平仓，避免贪心或恐慌。",
        "pros": "牛市中跟得紧，不容易踏空；逻辑简单，看两根线交叉就行。",
        "cons": "震荡市会被反复打脸——假金叉假死叉频繁出现，来回亏手续费。",
    },
    "RSI 超买超卖": {
        "summary": "RSI 在 0-100 波动，低于 35 说明「跌过头了」该抄底，高于 65 说明「涨过头了」该跑。",
        "buy_logic": "RSI 跌破超卖线（默认 35），市场恐慌抛售过头，价格大概率会反弹。在恐慌中买入。",
        "sell_logic": "RSI 升破超买线（默认 65），市场兴奋过度，该落袋为安。或者触发跟踪止损——股价从最高点回落超过一定幅度就自动卖。",
        "pros": "震荡市里反复低吸高抛，胜率高；跟踪止损保护利润。",
        "cons": "单边大行情会过早下车——RSI 可以长期维持超买/超卖，错过主升浪。",
    },
    "MACD 策略": {
        "summary": "MACD 是「均线的均线」，比普通金叉更平滑、假信号更少。金叉买、死叉卖。",
        "buy_logic": "MACD 线（快慢均线差值）上穿信号线，即「MACD 金叉」。比普通金叉滞后一点，但过滤了大量噪声假信号。",
        "sell_logic": "MACD 线下穿信号线（死叉），或者亏损超过止损线自动割肉。",
        "pros": "假信号远少于双均线，可靠性高；趋势跟踪效果稳定。",
        "cons": "信号滞后——等 MACD 金叉确认，股价可能已经涨了一段了。",
    },
    "布林带策略": {
        "summary": "布林带像一个「价格通道」——价格碰到下轨说明跌到了极端位置该反弹，碰到中轨就该撤。",
        "buy_logic": "收盘价跌破布林带下轨——统计学上 95% 的价格应该在上轨和下轨之间，跌破下轨意味着超跌，反弹概率大。",
        "sell_logic": "价格回到布林带中轨（20日均线），或跌破止损线。中轨止损的意思是「不吃全段，吃反弹那一段」。",
        "pros": "震荡市精准抄底，反弹获利就跑，胜率高、利润稳定。",
        "cons": "单边下跌趋势中，价格可以沿下轨一路滑，不断抄底不断亏。",
    },
}

# ---- 各策略的买卖信号触发原因映射 ----
TRIGGER_MAP = {
    "双均线交叉": {"buy": "快线上穿慢线（金叉）", "sell_default": "快线下穿慢线（死叉）", "sell_tp": "触发止盈", "sell_sl": "触发止损"},
    "RSI 超买超卖": {"buy": "RSI 跌破超卖线", "sell_default": "RSI 升破超买线", "sell_trail": "触发跟踪止损"},
    "MACD 策略": {"buy": "MACD 金叉", "sell_default": "MACD 死叉", "sell_sl": "触发止损"},
    "布林带策略": {"buy": "价格触及布林带下轨", "sell_default": "价格回归布林中轨", "sell_sl": "触发止损"},
}


def _make_logged_strategy(base_class, strategy_name):
    class LoggedStrategy(base_class):
        def __init__(self):
            super().__init__()
            self._trade_log = []
            self._open_info = {}
            self._strategy_name = strategy_name

        def notify_trade(self, trade):
            if not trade.isclosed:
                self._open_info[trade.ref] = {
                    'size': trade.size, 'baropen': trade.baropen}
            else:
                info = self._open_info.pop(trade.ref, None)
                if info is None:
                    return
                sz = info['size']
                exit_p = trade.price + trade.pnl / sz if sz else trade.price

                # 尝试推断触发原因
                entry_reason = TRIGGER_MAP.get(strategy_name, {}).get("buy", "策略买入信号")
                exit_reason = TRIGGER_MAP.get(strategy_name, {}).get("sell_default", "策略卖出信号")

                # 如果是止损/止盈卖出（亏损或盈利超过阈值），推断更精确的原因
                entry_price = trade.price
                if sz and entry_price:
                    pnl_pct = (exit_p - entry_price) / entry_price * 100
                    if pnl_pct < -1.5:
                        exit_reason = TRIGGER_MAP.get(strategy_name, {}).get("sell_sl",
                                        TRIGGER_MAP.get(strategy_name, {}).get("sell_trail", "止损"))
                    elif pnl_pct > 3.5 and strategy_name == "双均线交叉":
                        exit_reason = TRIGGER_MAP[strategy_name]["sell_tp"]

                self._trade_log.append({
                    'baropen': info['baropen'], 'barclose': trade.barclose,
                    'entry': trade.price, 'exit': exit_p, 'pnl': trade.pnl,
                    'entry_reason': entry_reason, 'exit_reason': exit_reason,
                })
    # 让 backtrader 在 sys.modules 中找到策略类的模块
    import inspect, importlib
    mod = inspect.getmodule(base_class)
    target_module = mod.__name__ if mod is not None else getattr(base_class, '__module__', None)

    if target_module is not None:
        LoggedStrategy.__module__ = target_module
        if mod is not None:
            sys.modules[target_module] = mod
        elif target_module not in sys.modules:
            try:
                importlib.import_module(target_module)
            except Exception:
                pass

    # 最后防线：Streamlit hot-reload 可能导致目标模块始终不在 sys.modules，
    # 回退到 backtrader（一定已导入，保证 backtrader 内部不报 KeyError）
    if LoggedStrategy.__module__ not in sys.modules:
        LoggedStrategy.__module__ = 'backtrader'

    return LoggedStrategy


def run_backtest(data, strategy_class, strategy_params,
                 initial_cash=100000, commission=0.0005,
                 strategy_name=""):
    # 统一列名为小写（兼容 yfinance 大写列名）
    data = data.rename(columns=str.lower).copy()
    data.columns = [c.lower() for c in data.columns]
    LoggedCls = _make_logged_strategy(strategy_class, strategy_name)

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)
    cerebro.adddata(bt.feeds.PandasData(dataname=data))
    cerebro.addstrategy(LoggedCls, **strategy_params)

    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.02)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    total_return = (final_value - initial_cash) / initial_cash * 100
    buy_hold = (data['close'].iloc[-1] - data['close'].iloc[0]) / data['close'].iloc[0] * 100

    # 年化收益率 = (最终净值 / 初始净值)^(365 / 回测天数) - 1
    backtest_days = (data.index[-1] - data.index[0]).days
    if backtest_days > 0:
        annualized_return = ((final_value / initial_cash) ** (365 / backtest_days) - 1) * 100
    else:
        annualized_return = 0.0

    ret = strat.analyzers.returns.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    dd = strat.analyzers.drawdown.get_analysis()

    metrics = {
        "初始资金": f"¥{initial_cash:,.0f}",
        "最终资金": f"¥{final_value:,.0f}",
        "总收益率": f"{total_return:+.2f}%",
        "买入持有": f"{buy_hold:+.2f}%",
        "超额收益": f"{total_return - buy_hold:+.2f}%",
        "年化收益率": f"{annualized_return:+.2f}%",
        "最大回撤": f"{dd['max']['drawdown']:.2f}%" if 'max' in dd else "N/A",
    }
    sr = sharpe.get('sharperatio')
    metrics["夏普比率"] = f"{sr:.3f}" if sr is not None else "N/A"

    trade_log = getattr(strat, '_trade_log', [])
    trades, buy_pts, sell_pts = [], [], []

    max_idx = len(data) - 1
    for tl in trade_log:
        bi = min(tl['baropen'], max_idx)
        si = min(tl['barclose'], max_idx)
        buy_pts.append((bi, tl['entry']))
        sell_pts.append((si, tl['exit']))
        trades.append({
            "买入时间": data.index[bi].strftime('%Y-%m-%d %H:%M'),
            "买入价": round(tl['entry'], 2),
            "买入原因": tl.get('entry_reason', ''),
            "卖出时间": data.index[si].strftime('%Y-%m-%d %H:%M'),
            "卖出价": round(tl['exit'], 2),
            "卖出原因": tl.get('exit_reason', ''),
            "盈亏": f"{tl['pnl']:+.2f}",
        })

    n = len(trades)
    if n > 0:
        won = sum(1 for tl in trade_log if tl['pnl'] > 0)
        metrics["交易次数"] = str(n)
        metrics["胜率"] = f"{won / n * 100:.1f}%"
    else:
        metrics["交易次数"] = "0"
        metrics["胜率"] = "N/A"

    return {
        "metrics": metrics, "trades": trades, "data": data,
        "buy_points": buy_pts, "sell_points": sell_pts,
        "strategy_name": strategy_name,
        "explanation": STRATEGY_EXPLANATIONS.get(strategy_name, {}),
    }