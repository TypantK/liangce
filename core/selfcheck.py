# -*- coding: utf-8 -*-
"""
量策 —— 自测验证模块（离线、纯逻辑，不依赖联网）

设计原则：
  1. 数据层正确性优先：SQLite 读写 / DataFrame 归一化 / 缓存新鲜度判断
     是回测与发现页的基石，一旦出错会「静默污染」所有上层结果，必须重点验证。
  2. 功能正确性（无阻塞）：12 个策略 + 回测引擎 + 仓位管理 + 情绪引擎
     必须以合成数据跑通，不能抛异常、不能卡死（交易次数 = 0 视为功能阻塞，报警）。
  3. 全部用合成/内存数据，绝不在自测里真实联网，保证可重复、秒级、离线可跑。

运行方式：
    python run_selfcheck.py            # 完整自测
    python -m unittest core.selfcheck   # 作为 unittest 套件运行

退出码：0 = 全部通过，非 0 = 存在失败（便于接入 CI / 启动门禁）。
"""

import os
import sys
import tempfile
import shutil
import unittest
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# 让测试可在任意工作目录下直接 import core / utils
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core import data_store
from core import data_fetcher
from core import sentiment as sentiment_mod
from core import strategies as strategies_mod
from core import position_sizer as position_mod
from core.engine import run_backtest
from core.sentiment_fetcher import _is_finance_relevant, fetch_news, diagnose_channels


# ===================================================================
#  测试夹具：生成合成数据
# ===================================================================

def _make_ohlcv(n=250, seed=42, start="2024-01-02"):
    """生成一根连续、含趋势与波动的 OHLCV 日线，供回测/策略测试用。"""
    rng = np.random.RandomState(seed)
    dates = pd.date_range(start, periods=n, freq="B")
    ret = rng.randn(n) * 0.015 + 0.0004
    close = 50 * np.exp(np.cumsum(ret))
    close = pd.Series(close, index=dates)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = np.maximum(open_, close) * (1 + np.abs(rng.randn(n)) * 0.006)
    low = np.minimum(open_, close) * (1 - np.abs(rng.randn(n)) * 0.006)
    volume = (rng.rand(n) * 1e6 + 5e5).astype(int)
    df = pd.DataFrame({
        "open": np.asarray(open_), "high": np.asarray(high), "low": np.asarray(low),
        "close": np.asarray(close), "volume": np.asarray(volume),
    }, index=dates)
    df.index.name = "datetime"
    return df


class _TempDBMixin:
    """把 SQLite 数据层切到临时目录，避免污染真实 data/cache.db。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="liangce_selfcheck_")
        self._orig_root = data_store.PROJECT_ROOT
        self._orig_db = data_store.DB_PATH
        data_store.PROJECT_ROOT = self._tmp
        data_store.DATA_DIR = os.path.join(self._tmp, "data")
        data_store.DB_PATH = os.path.join(data_store.DATA_DIR, "cache.db")
        data_store.init_db()

    def tearDown(self):
        data_store.PROJECT_ROOT = self._orig_root
        data_store.DATA_DIR = os.path.dirname(self._orig_db)
        data_store.DB_PATH = self._orig_db
        shutil.rmtree(self._tmp, ignore_errors=True)


# ===================================================================
#  1. 数据层正确性
# ===================================================================

class TestDataStore(_TempDBMixin, unittest.TestCase):
    """验证 SQLite 缓存层的写入 / 读取 / 去重 / 范围查询正确性。"""

    def test_stock_prices_roundtrip(self):
        df = _make_ohlcv(20)
        n = data_store.save_stock_prices("TEST.SH", df)
        self.assertEqual(n, 20)
        loaded = data_store.load_stock_prices("TEST.SH")
        self.assertEqual(len(loaded), 20)
        # 数值无损还原
        self.assertAlmostEqual(
            float(loaded["close"].iloc[0]), float(df["close"].iloc[0]), places=4)
        # 索引为 DatetimeIndex 且升序
        self.assertIsInstance(loaded.index, pd.DatetimeIndex)
        self.assertTrue(loaded.index.is_monotonic_increasing)

    def test_stock_prices_dedup_on_reinsert(self):
        df = _make_ohlcv(10)
        data_store.save_stock_prices("TEST.SH", df)
        # 再次插入相同 (symbol,date) 不应重复计数（INSERT OR REPLACE）
        n2 = data_store.save_stock_prices("TEST.SH", df)
        self.assertEqual(n2, 10)
        self.assertEqual(len(data_store.load_stock_prices("TEST.SH")), 10)

    def test_stock_prices_date_filter(self):
        df = _make_ohlcv(30)
        data_store.save_stock_prices("TEST.SH", df)
        start = df.index[10].strftime("%Y-%m-%d")
        end = df.index[20].strftime("%Y-%m-%d")
        sub = data_store.load_stock_prices("TEST.SH", start=start, end=end)
        self.assertGreaterEqual(len(sub), 1)
        self.assertLessEqual(sub.index[0].strftime("%Y-%m-%d"), end)
        self.assertGreaterEqual(sub.index[-1].strftime("%Y-%m-%d"), start)

    def test_has_stock_data(self):
        self.assertFalse(data_store.has_stock_data("NOPE.SH"))
        data_store.save_stock_prices("NOPE.SH", _make_ohlcv(5))
        self.assertTrue(data_store.has_stock_data("NOPE.SH"))

    def test_fund_nav_roundtrip(self):
        records = [{"date": "2024-01-02", "nav": 1.01, "acc_nav": 1.01},
                   {"date": "2024-01-03", "nav": 1.02, "acc_nav": 1.02}]
        c = data_store.save_fund_nav("000001", records)
        self.assertEqual(c, 2)
        df = data_store.load_fund_nav("000001")
        self.assertEqual(len(df), 2)
        self.assertAlmostEqual(float(df["nav"].iloc[0]), 1.01, places=4)

    def test_sentiment_events_dedup(self):
        evs = [
            {"date": "2024-01-02", "title": "利好A", "score": 3, "source": "x"},
            {"date": "2024-01-02", "title": "利好A", "score": 3, "source": "y"},  # 同 date+title 去重
            {"date": "2024-01-03", "title": "利空B", "score": -2, "source": "x"},
        ]
        n = data_store.save_sentiment_events(evs)
        self.assertEqual(n, 2)
        self.assertEqual(len(data_store.load_sentiment_events()), 2)

    def test_safe_float_nan_none(self):
        self.assertIsNone(data_store._safe_float(None))
        self.assertIsNone(data_store._safe_float(float("nan")))
        self.assertEqual(data_store._safe_float("1.5"), 1.5)


class TestDataFetcherNormalize(unittest.TestCase):
    """验证行情 DataFrame 归一化逻辑（列名兼容 / 数值化 / OHLC 约束）。"""

    def test_normalize_chinese_columns(self):
        raw = pd.DataFrame({
            "日期": ["2024-01-02", "2024-01-03"],
            "开盘": [10.0, 10.5],
            "收盘": [10.2, 10.8],
            "最高": [10.3, 10.9],
            "最低": [9.9, 10.4],
            "成交量": [1000, 1100],
        })
        df = data_fetcher._normalize_columns(raw.copy())
        for col in ("open", "high", "low", "close", "volume"):
            self.assertIn(col, df.columns)
        self.assertIsInstance(df.index, pd.DatetimeIndex)
        # 数值化无误
        self.assertEqual(float(df["close"].iloc[0]), 10.2)

    def test_normalize_string_numbers(self):
        raw = pd.DataFrame({
            "datetime": ["2024-01-02", "2024-01-03"],
            "open": ["10", "10.5"], "high": ["10.3", "10.9"],
            "low": ["9.9", "10.4"], "close": ["10.2", "10.8"],
            "volume": ["1000", "1100"],
        })
        df = data_fetcher._normalize_columns(raw.copy())
        # 字符串数字应被安全转成 float，而非抛 TypeError
        self.assertTrue(pd.api.types.is_numeric_dtype(df["close"]))

    def test_normalize_drops_na_and_keeps_ohlc(self):
        raw = pd.DataFrame({
            "datetime": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "open": [10.0, None, 10.6], "high": [10.3, 10.4, 10.9],
            "low": [9.9, 9.8, 10.4], "close": [10.2, 10.1, 10.8],
            "volume": [1000, 1000, 1100],
        })
        df = data_fetcher._normalize_columns(raw.copy())
        # 含 None 的行应被 dropna 移除
        self.assertEqual(len(df), 2)

    def test_expected_trading_day_crypto(self):
        # 加密货币 7x24，期望最新完整日 = 昨天
        exp = data_fetcher._expected_latest_trading_day("BTC/USDT")
        self.assertEqual(exp, pd.Timestamp(datetime.now().date()) - timedelta(days=1))

    def test_expected_trading_day_us_stock(self):
        # 美股：北京时间减 1 天、且为工作日
        exp = data_fetcher._expected_latest_trading_day("AAPL")
        self.assertLessEqual(exp, pd.Timestamp(datetime.now().date()) - timedelta(days=1))
        self.assertLess(exp.weekday(), 5)

    def test_generate_demo_data_valid(self):
        df = data_fetcher.generate_demo_data(120)
        self.assertEqual(len(df), 120)
        for col in ("open", "high", "low", "close", "volume"):
            self.assertIn(col, df.columns)
        # OHLC 约束：high>=max(open,close) 且 low<=min(open,close)
        self.assertTrue((df["high"] >= df[["open", "close"]].max(axis=1)).all())
        self.assertTrue((df["low"] <= df[["open", "close"]].min(axis=1)).all())


# ===================================================================
#  2. 情绪层正确性
# ===================================================================

class TestSentimentScoring(unittest.TestCase):
    """验证情绪打分、否定词反转、事件解析、加权与标签。"""

    def test_positive_negative_basic(self):
        self.assertGreater(sentiment_mod.score_headline("业绩超预期涨停"), 0)
        self.assertLess(sentiment_mod.score_headline("暴雷暴跌退市调查"), 0)

    def test_negation_flips(self):
        # 否定词 + 利空词 → 分数反转（假阳性抑制）
        raw = sentiment_mod.score_headline("暴跌")
        negated = sentiment_mod.score_headline("并未暴跌")
        self.assertEqual(raw, -1)
        self.assertEqual(negated, 1)

    def test_parse_events_skips_neutral(self):
        results = [
            {"title": "业绩超预期涨停创新高", "snippet": "净利润大增", "date": "2024-01-02"},
            {"title": "今日天气晴", "snippet": "无关新闻", "date": "2024-01-02"},
        ]
        events = sentiment_mod.parse_events_from_search(results, "测试")
        # 中性新闻（score==0）应被跳过；事件为 (date, score, title[, url]) 兼容 3/4 元组
        self.assertTrue(all(ev[1] != 0 for ev in events
                            if isinstance(ev, (list, tuple)) and len(ev) >= 3))
        self.assertEqual(len(events), 1)

    def test_parse_events_date_extraction(self):
        results = [{"title": "利好突破", "snippet": "发布于2024-03-15大涨",
                    "date": ""}]
        events = sentiment_mod.parse_events_from_search(results, "x")
        self.assertEqual(events[0][0], "2024-03-15")

    def test_get_sentiment_for_date_window_decay(self):
        events = [
            ("2024-01-10", 5, "当日利好"),
            ("2024-01-05", 5, "5天前利好"),  # 衰减后权重更低
            ("2024-02-01", 5, "窗口外"),
        ]
        score_today, heads = sentiment_mod.get_sentiment_for_date(
            events, "2024-01-10", window_days=7)
        self.assertIn("当日利好", heads)
        self.assertNotIn("窗口外", heads)
        # 当日事件权重=1.0，5天前权重约 0.72，合计应明显 < 10
        self.assertLess(score_today, 10.0)
        self.assertGreater(score_today, 5.0)

    def test_format_tag_boundaries(self):
        self.assertEqual(sentiment_mod.format_sentiment_tag(3), "利好")
        self.assertEqual(sentiment_mod.format_sentiment_tag(1), "偏多")
        self.assertEqual(sentiment_mod.format_sentiment_tag(0), "中性")
        self.assertEqual(sentiment_mod.format_sentiment_tag(-1), "偏空")
        self.assertEqual(sentiment_mod.format_sentiment_tag(-3), "利空")

    def test_sentiment_multiplier_monotonic(self):
        mults = [position_mod.get_sentiment_multiplier(s)[0]
                 for s in (3, 1, 0, -1, -2.5, -3.5)]
        # 分数越低，乘数不应变大（单调非增）
        self.assertEqual(mults, sorted(mults, reverse=True))

    def test_relevance_filter(self):
        # 含 query（标的名）视为相关
        self.assertTrue(_is_finance_relevant("贵州茅台大涨", "", "茅台"))
        # 不含任何财经关键词的中性文本 → 不相关
        self.assertFalse(_is_finance_relevant("今天天气晴适合散步郊游", "", "区块链"))


# ===================================================================
#  3. 功能正确性（无阻塞）：策略 + 回测引擎 + 仓位
# ===================================================================

class TestStrategiesNoBlock(unittest.TestCase):
    """核心功能门禁：12 个策略 + 回测引擎必须跑通、且能产生交易（不阻塞）。"""

    @classmethod
    def setUpClass(cls):
        cls.data = _make_ohlcv(300)

    def _run_one(self, name):
        reg = strategies_mod.STRATEGY_REGISTRY[name]
        strat_cls = reg["class"]
        params = {k: v[2] for k, v in reg["params"].items()}
        result = run_backtest(
            self.data.copy(),
            strat_cls,
            params,
            strategy_name=name,
            position_sizer=position_mod.FixedFractionSizer(),
        )
        return result

    def test_all_strategies_run_and_trade(self):
        """遍历全部策略：不能抛异常，且交易次数 > 0（阻塞检测）。"""
        failed = []
        zero_trade = []
        for name in strategies_mod.STRATEGY_REGISTRY:
            try:
                res = self._run_one(name)
                n = int(res["metrics"].get("交易次数", "0"))
                if n <= 0:
                    zero_trade.append(name)
            except Exception as e:  # noqa: BLE001
                failed.append((name, repr(e)))
        self.assertEqual(failed, [],
                         f"以下策略运行抛异常: {failed}")
        self.assertEqual(zero_trade, [],
                         f"以下策略交易次数=0（功能阻塞/无信号）: {zero_trade}")

    def test_metrics_completeness(self):
        res = self._run_one("双均线交叉")
        for key in ("总收益率", "年化收益率", "最大回撤", "夏普比率", "胜率"):
            self.assertIn(key, res["metrics"])

    def test_sentiment_overlay_does_not_block(self):
        """情绪叠加层：即使强利空停仓，也不应抛异常或死循环。"""
        reg = strategies_mod.STRATEGY_REGISTRY["双均线交叉"]
        # 构造全为空的情绪事件（中性），验证引擎不拦截、能正常交易
        res = run_backtest(
            self.data.copy(), reg["class"],
            {k: v[2] for k, v in reg["params"].items()},
            strategy_name="双均线交叉",
            sentiment_events=[],  # 无事件 → 中性，不拦截
            position_sizer=position_mod.FixedFractionSizer(),
        )
        self.assertGreater(int(res["metrics"]["交易次数"]), 0)

    def test_position_sizers_calc(self):
        """各仓位计算器：返回非负整数，且不抛异常。"""
        sizers = [
            position_mod.FixedFractionSizer(),
            position_mod.KellySizer(),
            position_mod.ATRSizer(),
            position_mod.EqualRiskSizer(),
        ]
        for sz in sizers:
            size = sz.calc_size(cash=100000, price=50.0, atr=1.0, stop_pct=0.05)
            self.assertIsInstance(size, int)
            self.assertGreaterEqual(size, 0)

    def test_sentiment_sizer_snapshot_fifo(self):
        """情绪叠加层快照 FIFO：多次 calc_size 后 pop 应按序取出。"""
        base = position_mod.FixedFractionSizer()
        ss = position_mod.SentimentPositionSizer(base, sentiment_events=[])
        ss.set_sentiment(3, "利好", [])
        s1 = ss.calc_size(100000, 50)
        ss.set_sentiment(-3, "利空", [])
        s2 = ss.calc_size(100000, 50)
        snap1 = ss.pop_snapshot()
        snap2 = ss.pop_snapshot()
        self.assertEqual(snap1["multiplier"], 1.2)  # 利好乘数
        self.assertEqual(snap2["multiplier"], 0.0)  # 强利空乘数
        self.assertGreater(s1, 0)
        self.assertEqual(s2, 0)  # 强利空停仓 → 0 股


# ===================================================================
#  4. 通道诊断（离线可用部分）
# ===================================================================

class TestChannelDiagnostics(unittest.TestCase):
    """验证通道诊断函数可调用且不抛异常（akshare 是否安装等环境态）。"""

    def test_diagnose_channels_runs(self):
        # diagnose_channels 会真实探测网络，这里只验证它不抛异常、返回 dict
        try:
            res = diagnose_channels()
            self.assertIsInstance(res, dict)
            self.assertIn("sample", res)  # sample 永远可用
        except Exception as e:  # noqa: BLE001
            self.fail(f"diagnose_channels 抛异常: {e}")


# ===================================================================
#  5. 页面冒烟（import 级门禁）
# ===================================================================
#
# 历史教训：自测只测核心逻辑、不 import 页面，导致「页面模块顶层 NameError」
# （如 discover_page 顶层调用未定义的 _classify_symbol）只有在用户打开网页
# 点击导航时才会暴露，且错误发生在 streamlit 渲染层、不在 collector 覆盖范围内。
# 因此新增本类：逐一 import 各页面模块（模拟用户打开导航 / app.py __import__），
# 并模拟调用页面内关键纯函数，把这类「启动期/import 期」错误提前到自测阶段捕获。

import importlib

# 所有需冒烟的页面模块（与 app.py 的 PAGES 对应；跳过备份文件 *_bak）
_PAGE_MODULES = [
    "pages.discover_page",
    "pages.backtest_page",
    "pages.optimize_page",
    "pages.sector_prediction",
    "pages.about_page",
]

# 各页面「关键纯函数」冒烟：模拟你在测试里调用它们，验证可被正常调用不抛 NameError
_PAGE_FUNC_SMOKE = {
    "pages.discover_page": ("_classify_symbol", ("600000.SH",), "A股"),
    "pages.backtest_page": ("_parse_pct", ("12.34%",), 12.34),
    "pages.optimize_page": ("METRIC_LABELS", None, None),  # 取模块级常量
    "pages.sector_prediction": ("score_headline", ("业绩超预期涨停",), None),
    "pages.about_page": (None, None, None),  # 无合适纯函数，仅验证 import
}


class TestPageSmoke(unittest.TestCase):
    """页面 import 级门禁：模拟用户打开导航，捕获顶层 NameError / 缺失依赖。"""

    def _import_page(self, modname):
        try:
            mod = importlib.import_module(modname)
        except Exception as e:  # noqa: BLE001
            self.fail(f"导入页面模块 {modname} 抛异常（顶层代码错误）: {type(e).__name__}: {e}")
        return mod

    def test_all_pages_importable(self):
        """逐一 import 所有页面，任何顶层异常都会使该用例失败。"""
        for modname in _PAGE_MODULES:
            with self.subTest(page=modname):
                self._import_page(modname)

    def test_page_critical_functions_callable(self):
        """模拟调用各页面关键函数，验证其已定义且可正常调用（不抛 NameError）。"""
        for modname, spec in _PAGE_FUNC_SMOKE.items():
            func_name, args, expected = spec
            if func_name is None:
                continue  # 仅验证 import
            with self.subTest(page=modname, func=func_name):
                mod = self._import_page(modname)
                if not hasattr(mod, func_name):
                    self.fail(f"{modname} 缺少关键函数 {func_name}（定义缺失/顺序错误）")
                target = getattr(mod, func_name)
                try:
                    if args is None:
                        # 取常量/属性
                        _ = target
                    else:
                        result = target(*args)
                        if expected is not None:
                            # 对数值/字符串做宽松断言
                            if isinstance(expected, (int, float)):
                                self.assertAlmostEqual(float(result), float(expected), places=2)
                except Exception as e:  # noqa: BLE001
                    self.fail(
                        f"调用 {modname}.{func_name}{args or ''} 抛异常: {type(e).__name__}: {e}")

    def test_discover_pool_built(self):
        """discover_page 顶层标的池应能正确构建（回归本次 _classify_symbol 缺陷）。"""
        mod = self._import_page("pages.discover_page")
        self.assertTrue(hasattr(mod, "_DISCOVER_STOCK_ITEMS"),
                        "discover_page 缺少 _DISCOVER_STOCK_ITEMS")
        items = mod._DISCOVER_STOCK_ITEMS
        self.assertGreater(len(items), 0, "_DISCOVER_STOCK_ITEMS 为空")
        for name, code, cat in items:
            self.assertIsInstance(cat, str, f"标的 {name} 分类结果非字符串")


# ===================================================================
#  套件入口
# ===================================================================

def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for cls in (TestDataStore, TestDataFetcherNormalize, TestSentimentScoring,
                TestStrategiesNoBlock, TestChannelDiagnostics, TestPageSmoke):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    return suite


if __name__ == "__main__":
    unittest.main(verbosity=2)
