# -*- coding: utf-8 -*-
"""
回测引擎 v3 — 策略名称 + 触发原因 + 情绪模式过滤
"""

import sys
import backtrader as bt
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

from core.sentiment import get_sentiment_for_date, format_sentiment_tag

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
    "卡尔曼滤波趋势": {
        "summary": "卡尔曼滤波从噪声价格中估计出隐藏的「速度」信号——速度>0 说明内在趋势向上，速度<0 说明趋势向下。",
        "buy_logic": "卡尔曼滤波估计的速度（一阶导数）转正，意味着价格背后存在向上的驱动力，此时入场做多。",
        "sell_logic": "速度转负（趋势反转）或股价从最高点回落超过跟踪止损线（默认 4%）。先减仓锁定利润，再顺势离场。",
        "pros": "基于状态空间模型对趋势方向做一阶预测，比均线类指标更早感知趋势拐点。",
        "cons": "参数（过程噪声/测量噪声）固定，对剧烈波动市可能产生延迟；震荡市中速度频繁正负翻转会导致反复进出。",
    },
    "HMA 低延迟均线": {
        "summary": "HMA（赫尔移动均线）通过加权平均组合大幅降低传统均线的滞后，能更快检测到趋势拐点。叠加 EMA 信号线过滤假突破。",
        "buy_logic": "HMA 上穿 EMA 信号线形成金叉——均线本身滞后极低，金叉一出就是趋势启动的确认信号。",
        "sell_logic": "HMA 下穿 EMA 信号线（死叉）或亏损超过止损线（默认 3%）。死叉确认后就撤，不吃鱼尾。",
        "pros": "滞后极小，趋势启动时跟得比 SMA/EMA 都快；信号线再做平滑，假突破少。",
        "cons": "快也意味着对微小波动敏感，窄幅横盘时可能频繁假信号。",
    },
    "线性回归斜率": {
        "summary": "对最近 N 期价格拟合一条回归直线——斜率>0 表示趋势在加速向上，斜率<0 表示趋势在加速向下。",
        "buy_logic": "平滑后的回归斜率由负转正——价格从「跌在减速」进入「开始涨」的拐点区域，是左侧埋伏信号。",
        "sell_logic": "斜率转负（上涨动能衰竭）或亏损超过止损线（默认 3%）。斜率领先价格本身，能在价格见顶前提前离场。",
        "pros": "斜率是领先指标，比价格本身更早反映趋势方向的变化；EMA 平滑避免斜率毛刺。",
        "cons": "滞后于突变行情——极端事件中斜率还在正值时价格可能已经跌了不少。",
    },
    "一目均衡表": {
        "summary": "一目均衡表的核心是「云层」——云层被投影到未来 26 期，是少有的直接向未来延伸的指标。价格在云上是多头，在云下是空头。",
        "buy_logic": "价格站上云层（Senkou Span A/B 的上沿）且 Tenkan 线上穿 Kijun 线形成金叉——趋势+动能双重确认。",
        "sell_logic": "价格跌破云层下沿（支撑被破）或 Tenkan 下穿 Kijun（动能衰竭）或触发止损（默认 4%）。云层破了就不再留恋。",
        "pros": "多维度信号（趋势/动能/支撑阻力）同时校验，假信号少；云层的「未来投影」提供天然的目标位和止损参考。",
        "cons": "参数多（9/26/52），对短周期品种不一定适合；盘整期云层收窄时信号模糊。",
    },
    "唐奇安通道突破": {
        "summary": "经典海龟交易法则——价格突破N日最高点说明趋势启动，跌破N日最低点说明趋势终结。",
        "buy_logic": "收盘价突破过去 N 日的最高点（上轨），意味着多头力量打破了近期阻力，新趋势可能开启，立即跟进。",
        "sell_logic": "收盘价跌破过去 N 日最低点（下轨）或从最高点回落超过跟踪止损线（默认 4%）。通道被反向突破就认赔走人。",
        "pros": "经典海龟法则，逻辑简单直接；牛市里能完整吃到主升浪。",
        "cons": "震荡市反复假突破，来回止损；通道宽度随 N 增大而变宽，N 太小容易过度交易。",
    },
    "ADX 趋势强度": {
        "summary": "ADX 不判方向只判「趋势有多强」，方向由 +DI/-DI 决定。ADX>25 且 +DI>-DI 代表强上升趋势，才是做多窗口。",
        "buy_logic": "ADX 高于阈值（默认 25）且 +DI 线在 -DI 线上方——确认当前处于强上涨趋势中，顺势入场。",
        "sell_logic": "ADX 高于阈值但 -DI 反超 +DI（趋势转为强下跌）或亏损超过止损线（默认 3%）。趋势转了就撤。",
        "pros": "只参与强趋势行情，过滤弱势震荡，假信号少；ADX 阈值可调节灵敏度。",
        "cons": "ADX 是滞后指标——确认强趋势时可能已涨了一段；横盘市 ADX 长期低于阈值，可能长时间不开仓。",
    },
    "抛物线 SAR": {
        "summary": "PSAR 是动态的止损/反转点，像一条随趋势移动的「保本线」。翻到价格下方做多，翻到价格上方平仓。",
        "buy_logic": "PSAR 点从价格上方翻转到下方——前一根 K 线 PSAR 在价格上方，当前 K 线 PSAR 落到价格下方，趋势确认转多。",
        "sell_logic": "PSAR 翻转到价格上方（趋势转空）或亏损超过止损线（默认 5%）。PSAR 自身就有止损属性，叠加固定止损双保险。",
        "pros": "动态跟踪，趋势不破就不走；不需要主观判断，信号明确。",
        "cons": "横盘震荡时 PSAR 紧贴价格反复翻转，来回亏损；急速反转行情中滞后于价格本身。",
    },
    "成交量加权 MACD": {
        "summary": "用 VWAP（成交量加权均价）替代收盘价计算 MACD——反映资金真实成本，减少尾盘异动的干扰。金叉买死叉卖。",
        "buy_logic": "基于 VWAP 的 MACD 线上穿信号线形成金叉——资金的平均成本线在抬头，说明大资金在进场推升。",
        "sell_logic": "MACD 下穿信号线（死叉）或亏损超过止损线（默认 3%）。大资金成本线拐头就跟着撤。",
        "pros": "VWAP 比收盘价更能反映日内资金的真实意图，过滤尾盘拉抬/砸盘的噪声；逻辑和普通 MACD 一样好用。",
        "cons": "VWAP 依赖成交量数据，低成交量品种（如冷门股）偏差大；金叉/死叉天然滞后。",
    },
}

# ---- 各策略的买卖信号触发原因映射 ----
TRIGGER_MAP = {
    "双均线交叉": {"buy": "快线上穿慢线（金叉）", "sell_default": "快线下穿慢线（死叉）", "sell_tp": "触发止盈", "sell_sl": "触发止损"},
    "RSI 超买超卖": {"buy": "RSI 跌破超卖线", "sell_default": "RSI 升破超买线", "sell_trail": "触发跟踪止损"},
    "MACD 策略": {"buy": "MACD 金叉", "sell_default": "MACD 死叉", "sell_sl": "触发止损"},
    "布林带策略": {"buy": "价格触及布林带下轨", "sell_default": "价格回归布林中轨", "sell_sl": "触发止损"},
    "卡尔曼滤波趋势": {"buy": "滤波趋势向上且价格突破上轨", "sell_default": "滤波趋势转下跌", "sell_sl": "触发止损"},
    "HMA 低延迟均线": {"buy": "HMA 金叉信号", "sell_default": "HMA 死叉信号", "sell_sl": "触发止损"},
    "线性回归斜率": {"buy": "回归斜率向上且突破信号线", "sell_default": "斜率转负", "sell_sl": "触发止损"},
    "一目均衡表": {"buy": "云层之上且转上行 → 做多", "sell_default": "价格跌破云层", "sell_sl": "触发止损"},
    "唐奇安通道突破": {"buy": "价格突破N日最高点", "sell_default": "价格跌破N日最低点", "sell_trail": "触发跟踪止损"},
    "ADX 趋势强度": {"buy": "ADX>阈值且+DI>-DI", "sell_default": "ADX>阈值且-DI>+DI", "sell_sl": "触发止损"},
    "抛物线 SAR": {"buy": "PSAR 翻转到价格下方", "sell_default": "PSAR 翻转到价格上方", "sell_sl": "触发止损"},
    "成交量加权 MACD": {"buy": "VWAP-MACD 金叉", "sell_default": "VWAP-MACD 死叉", "sell_sl": "触发止损"},
}


def _make_logged_strategy(base_class, strategy_name, sentiment_events=None):
    """创建带日志的策略类。sentiment_events 为 [(date, score, title), ...]"""

    class LoggedStrategy(base_class):
        params = (
            ('trade_start', None),
            ('trade_end', None),
        )

        def __init__(self):
            super().__init__()
            self._trade_log = []
            self._open_info = {}
            self._strategy_name = strategy_name
            self._sentiment_events = sentiment_events or []
            self._sentiment_force_news = []  # 极空利空强制平仓时的新闻标题
            self._last_sentiment_score = 0.0

        def _check_sentiment(self, dt_str):
            """返回 (分数, 标签, 新闻列表)。
            先查指定日期附近事件；无匹配时降级为全局情绪（所有事件平均分 + 全部标题）。"""
            if not self._sentiment_events:
                return 0.0, "", []
            score, headlines = get_sentiment_for_date(
                self._sentiment_events, dt_str, window_days=3)
            if score == 0.0 and not headlines:
                # 无日期匹配 → 降级为全局情绪
                all_scores = [s for _, s, _ in self._sentiment_events]
                global_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0
                all_titles = [t for _, _, t in self._sentiment_events]
                tag = format_sentiment_tag(global_score)
                return global_score, tag, all_titles[:3]
            tag = format_sentiment_tag(score)
            return score, tag, headlines

        def next(self):
            dt = self.datas[0].datetime.date(0)
            dt_ts = pd.Timestamp(dt)
            dt_str = dt_ts.strftime("%Y-%m-%d")

            # 交易窗口之前：只积累指标，不下单
            if self.p.trade_start is not None and dt_ts < self.p.trade_start:
                return
            # 交易窗口之后：平掉所有持仓，不再下单
            if self.p.trade_end is not None and dt_ts > self.p.trade_end:
                if self.position:
                    self.close()
                return

            # --- 情绪模式：检查市场情绪，影响入场决策 ---
            if self._sentiment_events:
                sent_score, sent_tag, sent_news = self._check_sentiment(dt_str)
                self._last_sentiment_score = sent_score
                # 利空情绪 → 暂停买入（不执行 super().next()，策略不会下单）
                if sent_score < 0:
                    return
                # 极端利空 → 强制平仓，记录触发新闻供 notify_trade 使用
                if sent_score < -3 and self.position:
                    self._sentiment_force_news = list(sent_news[:3])
                    self.close()
                    return

            super().next()

        def notify_trade(self, trade):
            if not trade.isclosed:
                # 建仓时直接存日期字符串，避免后续用 bar 索引查询 datetime 时越界
                entry_dt = self.data.datetime.date(0)
                self._open_info[trade.ref] = {
                    'size': trade.size, 'baropen': trade.baropen,
                    'entry_date': entry_dt.strftime("%Y-%m-%d")}
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

                # 情绪极端利空强制平仓：将新闻标题编号写入卖出原因
                if self._sentiment_force_news:
                    numbered = "; ".join(f"({i+1}){n}" for i, n in enumerate(self._sentiment_force_news))
                    exit_reason = f"情绪极端利空强制平仓 {numbered}"
                    self._sentiment_force_news = []

                # 读取仓位叠加层的调整信息
                sizer = getattr(self.cerebro, 'position_sizer', None)
                sent_mult = 1.0
                sent_label = ""
                sent_desc = ""
                if sizer and hasattr(sizer, '_last_multiplier'):
                    sent_mult = sizer._last_multiplier
                    sent_label = sizer._last_label
                    sent_desc = sizer._last_desc

                self._trade_log.append({
                    'baropen': info['baropen'], 'barclose': trade.barclose,
                    'entry': trade.price, 'exit': exit_p, 'pnl': trade.pnl,
                    'size': sz,
                    'entry_reason': entry_reason, 'exit_reason': exit_reason,
                    'entry_news': '', 'exit_news': '',
                    'sentiment_score': self._last_sentiment_score,
                    'sentiment_multiplier': sent_mult,
                    'sentiment_label': sent_label,
                    'sentiment_desc': sent_desc,
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
                 strategy_name="", trade_start=None, trade_end=None,
                 sentiment_events=None, position_sizer=None):
    """
    运行回测。

    sentiment_events: 可选，情绪事件列表 [(date_str, score, title), ...]
                      开启后，利空日暂停买入，极端利空强制平仓。
    position_sizer:   可选，仓位管理器实例，策略通过 cerebro.position_sizer 访问。
    """
    # 统一列名为小写（兼容 yfinance 大写列名）
    data = data.rename(columns=str.lower).copy()
    data.columns = [c.lower() for c in data.columns]
    LoggedCls = _make_logged_strategy(strategy_class, strategy_name,
                                      sentiment_events=sentiment_events)

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)
    cerebro.adddata(bt.feeds.PandasData(dataname=data))

    # 挂载仓位管理器到 cerebro，策略通过 self.cerebro.position_sizer 访问
    cerebro.position_sizer = position_sizer

    cerebro.addstrategy(LoggedCls, trade_start=trade_start, trade_end=trade_end, **strategy_params)

    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.02)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    results = cerebro.run()
    strat = results[0]

    # 按交易窗口截取数据用于指标计算和图表
    if trade_start is not None and trade_end is not None:
        trade_data = data[(data.index >= trade_start) & (data.index <= trade_end)]
    else:
        trade_data = data

    final_value = cerebro.broker.getvalue()
    total_return = (final_value - initial_cash) / initial_cash * 100
    buy_hold = (trade_data['close'].iloc[-1] - trade_data['close'].iloc[0]) / trade_data['close'].iloc[0] * 100

    # 年化收益率 = (最终净值 / 初始净值)^(365 / 回测天数) - 1
    backtest_days = (trade_data.index[-1] - trade_data.index[0]).days
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
            "买入数量": tl['size'],
            "买入原因": tl.get('entry_reason', ''),
            "卖出时间": data.index[si].strftime('%Y-%m-%d %H:%M'),
            "卖出价": round(tl['exit'], 2),
            "卖出原因": tl.get('exit_reason', ''),
            "盈亏": f"{tl['pnl']:+.2f}",
            "买入情绪事件": tl.get('entry_news', ''),
            "卖出情绪事件": tl.get('exit_news', ''),
            "情绪得分": tl.get('sentiment_score', 0.0),
            "情绪乘数": tl.get('sentiment_multiplier', 1.0),
            "情绪标签": tl.get('sentiment_label', ''),
            "情绪说明": tl.get('sentiment_desc', ''),
        })

    # 将买卖点索引从全量 data 空间重映射到 trade_data 空间
    if trade_start is not None and trade_end is not None:
        buy_pts = [
            (trade_data.index.get_loc(data.index[bi]), entry)
            for bi, entry in buy_pts
        ]
        sell_pts = [
            (trade_data.index.get_loc(data.index[si]), exit_p)
            for si, exit_p in sell_pts
        ]

    n = len(trades)
    if n > 0:
        won = sum(1 for tl in trade_log if tl['pnl'] > 0)
        metrics["交易次数"] = str(n)
        metrics["胜率"] = f"{won / n * 100:.1f}%"
    else:
        metrics["交易次数"] = "0"
        metrics["胜率"] = "N/A"

    return {
        "metrics": metrics, "trades": trades, "data": trade_data,
        "buy_points": buy_pts, "sell_points": sell_pts,
        "strategy_name": strategy_name,
        "explanation": STRATEGY_EXPLANATIONS.get(strategy_name, {}),
        "raw": {
            "total_return": total_return,
            "annualized_return": annualized_return,
            "sharpe": sr,
            "win_rate": (won / n * 100) if n > 0 else None,
            "max_drawdown": dd['max']['drawdown'] if 'max' in dd else None,
        },
    }
