# -*- coding: utf-8 -*-
"""
回测引擎 - notify_trade + trade.ref 精确捕获买卖信号
"""

import backtrader as bt
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")


def _make_logged_strategy(base_class):
    class LoggedStrategy(base_class):
        def __init__(self):
            super().__init__()
            self._trade_log = []
            self._open_info = {}

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
                self._trade_log.append({
                    'baropen': info['baropen'], 'barclose': trade.barclose,
                    'entry': trade.price, 'exit': exit_p, 'pnl': trade.pnl,
                })
    return LoggedStrategy


def run_backtest(data, strategy_class, strategy_params,
                 initial_cash=100000, commission=0.0005):
    LoggedCls = _make_logged_strategy(strategy_class)

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

    ret = strat.analyzers.returns.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    dd = strat.analyzers.drawdown.get_analysis()

    metrics = {
        "初始资金": f"¥{initial_cash:,.0f}",
        "最终资金": f"¥{final_value:,.0f}",
        "总收益率": f"{total_return:+.2f}%",
        "买入持有": f"{buy_hold:+.2f}%",
        "超额收益": f"{total_return - buy_hold:+.2f}%",
        "最大回撤": f"{dd['max']['drawdown']:.2f}%" if 'max' in dd else "N/A",
    }
    sr = sharpe.get('sharperatio')
    metrics["夏普比率"] = f"{sr:.3f}" if sr is not None else "N/A"

    trade_log = getattr(strat, '_trade_log', [])
    trades, buy_pts, sell_pts = [], [], []

    for tl in trade_log:
        bi, si = tl['baropen'], tl['barclose']
        buy_pts.append((bi, tl['entry']))
        sell_pts.append((si, tl['exit']))
        trades.append({
            "买入时间": data.index[bi].strftime('%Y-%m-%d %H:%M'),
            "买入价": round(tl['entry'], 2),
            "卖出时间": data.index[si].strftime('%Y-%m-%d %H:%M'),
            "卖出价": round(tl['exit'], 2),
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
    }