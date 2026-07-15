# -*- coding: utf-8 -*-
"""
量策 —— 综合项目健康检查

覆盖维度：
  1. 数据获取 —— 各行情源是否可用（含降级）
  2. UI 元素 —— 各页面按钮/selectbox 等关键 widget 是否正常渲染
  3. 核心功能 —— 策略回测、情绪引擎、数据层读写
  4. 运行留痕 —— run_logger 是否正常写入
  5. 端到端 —— streamlit 启动 + HTTP 探测

用法：
    .venv/Scripts/python.exe check_project.py              # 全部检查
    .venv/Scripts/python.exe check_project.py --quick      # 仅关键项（跳过联网）
    .venv/Scripts/python.exe check_project.py --ui-only    # 仅 UI 检查

退出码：0 = 全部通过，非 0 = 存在失败
"""

import os
import sys
import time
import json
import socket
import subprocess
import traceback
import importlib
import threading
from datetime import datetime
from io import StringIO

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

_RESULTS = []  # [(name, ok, detail), ...]

def _record(name, ok, detail=""):
    _RESULTS.append((name, ok, detail))
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}")
    if detail and not ok:
        for line in detail.split("\n"):
            print(f"     {line}")
    return ok

def _summary():
    total = len(_RESULTS)
    ok = sum(1 for _, o, _ in _RESULTS if o)
    fail = total - ok
    print(f"\n{'='*56}")
    print(f"量策综合健康检查：共 {total} 项，通过 {ok} 项，失败 {fail} 项")
    if fail == 0:
        print("[OK] 项目健康：数据获取 / UI 元素 / 核心功能 / 运行留痕 / 端到端 全部通过。")
        return 0
    print("[FAIL] 存在失败项，请排查上述 ❌ 详情。")
    return 1


# ---------------------------------------------------------------------------
# 1. 数据获取检查
# ---------------------------------------------------------------------------

def check_data_fetching(quick=False):
    print("\n" + "=" * 56)
    print("📡 1. 数据获取检查")
    print("-" * 40)

    # --- 1.1 STOCK_POOL 完整性 ---
    try:
        from core.data_fetcher import STOCK_POOL
        count = len(STOCK_POOL)
        ok = count >= 10  # 预期至少 10 只
        _record("STOCK_POOL 标的数", ok,
                f"{count} 只" if ok else f"仅 {count} 只（预期 ≥10）")
    except Exception as e:
        _record("STOCK_POOL 加载", False, str(e))

    # --- 1.2 演示数据可用（离线）---
    try:
        from core.data_fetcher import generate_demo_data
        df = generate_demo_data(30)
        ok = len(df) == 30 and "close" in df.columns and "open" in df.columns
        _record("generate_demo_data(30)", ok,
                f"返回 {len(df)} 行, 列: {list(df.columns)[:6]}" if ok else f"行数异常: {len(df)}")
    except Exception as e:
        _record("generate_demo_data", False, str(e))

    # --- 1.3 SQLite 数据层 ---
    try:
        from core import data_store
        df = _make_test_ohlcv(10)
        n = data_store.save_stock_prices("CHECK_TEST.SH", df)
        loaded = data_store.load_stock_prices("CHECK_TEST.SH")
        ok = len(loaded) == 10
        _record("data_store 读写", ok,
                f"写入 {n} 行，读出 {len(loaded)} 行" if ok else f"写入 {n}，读出 {len(loaded)}")
    except Exception as e:
        _record("data_store 读写", False, str(e))

    # --- 1.3b data_store 基金/情绪表 ---
    try:
        from core import data_store as ds
        ds.save_fund_nav("CHK_FUND", [{"date": "2024-01-02", "nav": 1.0, "acc_nav": 1.0}])
        nav_df = ds.load_fund_nav("CHK_FUND")
        ok_nav = len(nav_df) >= 1
        _record("data_store fund_nav", ok_nav, f"{len(nav_df)} 行" if ok_nav else "空")
    except Exception as e:
        _record("data_store fund_nav", False, str(e))

    try:
        from core import data_store as ds
        ds.save_sentiment_events([{"date": "2024-01-02", "title": "测试", "score": 3, "source": "x"}])
        ev = ds.load_sentiment_events()
        _record("data_store sentiment_events", len(ev) >= 1, f"{len(ev)} 行")
    except Exception as e:
        _record("data_store sentiment_events", False, str(e))

    # --- 1.4 情绪引擎 ---
    try:
        from core import sentiment as sm
        s1 = sm.score_headline("业绩超预期涨停")
        s2 = sm.score_headline("暴跌退市调查")
        ok = s1 > 0 and s2 < 0
        _record("情绪打分 (利好/利空)", ok,
                f"利好={s1}, 利空={s2}" if ok else f"利好={s1}, 利空={s2}（预期利好>0,利空<0）")
    except Exception as e:
        _record("情绪打分", False, str(e))

    # --- 1.5 策略注册表 ---
    try:
        from core.strategies import STRATEGY_REGISTRY
        count = len(STRATEGY_REGISTRY)
        ok = count >= 10
        _record("STRATEGY_REGISTRY 策略数", ok,
                f"{count} 个" if ok else f"仅 {count} 个（预期 ≥10）")
    except Exception as e:
        _record("STRATEGY_REGISTRY 加载", False, str(e))

    # --- 1.6 回测引擎 + 多策略冒烟 ---
    try:
        from core.engine import run_backtest
        from core.strategies import STRATEGY_REGISTRY
        from core.position_sizer import FixedFractionSizer
        df = _make_test_ohlcv(250)
        # 选 4 个代表性策略：均线类、MACD、RSI、布林带（覆盖滞后+摆动型）
        smoke_strategies = ["双均线交叉", "MACD 策略", "RSI 超买超卖", "布林带策略"]
        failed_strategies = []
        for sname in smoke_strategies:
            if sname not in STRATEGY_REGISTRY:
                failed_strategies.append(f"{sname} 未注册")
                continue
            reg = STRATEGY_REGISTRY[sname]
            params = {k: v[2] for k, v in reg["params"].items()}
            try:
                res = run_backtest(df.copy(), reg["class"], params,
                                   strategy_name=sname,
                                   position_sizer=FixedFractionSizer())
                trades = int(res.get("metrics", {}).get("交易次数", 0))
                if trades <= 0:
                    failed_strategies.append(f"{sname} 交易次数=0")
            except Exception as e:
                failed_strategies.append(f"{sname}: {e}")
        ok = len(failed_strategies) == 0
        _record("回测引擎 (4策略冒烟)", ok,
                f"通过: {[s for s in smoke_strategies if s not in [f.split(':')[0] for f in failed_strategies]]}"
                if ok else f"失败: {failed_strategies}")
    except Exception as e:
        _record("回测引擎", False, str(e))

    # --- 1.7 板块发现页标的池 ---
    try:
        from pages.discover_page import DISCOVER_POOL, _classify_symbol
        ok = len(DISCOVER_POOL) >= 20
        _record("DISCOVER_POOL 标的数", ok,
                f"{len(DISCOVER_POOL)} 个" if ok else f"仅 {len(DISCOVER_POOL)} 个（预期 ≥20）")
        # 验证 _classify_symbol 对每种类型正确
        tests = [
            ("600000.SH", "A股"),
            ("AAPL", "美股"),
            ("BTC/USDT", "加密货币"),
            ("SECTOR:白酒", "板块指数"),
            ("510300", "基金"),  # 基金代码不含 .SZ/.SH，需配合 asset_type
        ]
        for code, expected in tests:
            atype = "基金" if code == "510300" else None
            cat = _classify_symbol(code, asset_type=atype)
            if cat != expected:
                _record(f"_classify_symbol({code})", False,
                        f"返回 {cat!r}，预期 {expected!r}")
    except Exception as e:
        _record("DISCOVER_POOL 加载", False, str(e))

    if quick:
        print("\n  [--quick 模式：跳过联网数据检查]")
        return

    # --- 1.8 联网数据获取（各通道探测，失败仅 WARN 不阻塞）---
    _check_network_sources()


def _check_network_sources():
    """逐一探测各行情源可用性。网络源失败仅 WARN（受环境影响），不阻塞整体健康检查。"""
    sources = {}

    # akshare（东方财富）— A股行情
    try:
        from core.data_fetcher import get_stock_data
        df = get_stock_data("600000.SH", start="2026-07-08", end="2026-07-15")
        ok = df is not None and len(df) > 0
        sources["akshare A股 (600000.SH)"] = (ok, f"{len(df)} 行" if ok else "返回空")
    except Exception as e:
        sources["akshare A股 (600000.SH)"] = (False, str(e)[:120])

    # yfinance — 美股行情
    try:
        df = get_stock_data("AAPL", start="2026-07-08", end="2026-07-15")
        ok = df is not None and len(df) > 0
        sources["yfinance 美股 (AAPL)"] = (ok, f"{len(df)} 行" if ok else "返回空")
    except Exception as e:
        sources["yfinance 美股 (AAPL)"] = (False, str(e)[:120])

    # 基金净值
    try:
        from core.data_fetcher import get_fund_nav
        df = get_fund_nav("510300", start="2026-07-08", end="2026-07-15")
        ok = df is not None and len(df) > 0
        sources["基金净值 (510300)"] = (ok, f"{len(df)} 行" if ok else "返回空")
    except Exception as e:
        sources["基金净值 (510300)"] = (False, str(e)[:120])

    # 新闻 / 情绪抓取（网络依赖，仅 WARN）
    try:
        from core.sentiment_fetcher import fetch_news, diagnose_channels
        diag = diagnose_channels()
        available = [k for k, v in diag.items() if v.get("available")]
        ok = len(available) > 0
        if not ok:
            print(f"  ⚠️ 新闻通道诊断: 所有通道不可用（网络问题，不阻塞）")
    except Exception as e:
        print(f"  ⚠️ 新闻通道诊断: {e}（网络问题，不阻塞）")

    # 统一记录（网络源失败仅 WARN，不阻塞）
    for name, (ok, detail) in sources.items():
        _record(name, ok, detail)


# ---------------------------------------------------------------------------
# 2. UI 元素检查（用 streamlit.testing.v1.AppTest）
# ---------------------------------------------------------------------------

def check_ui_elements():
    print("\n" + "=" * 56)
    print("🖥️ 2. UI 元素检查（streamlit.testing.v1.AppTest）")
    print("-" * 40)

    try:
        from streamlit.testing.v1 import AppTest
    except ImportError as e:
        _record("AppTest 可用性", False, str(e))
        print("  ⚠️ 跳过 UI 检查（需要 streamlit >= 1.28）")
        return

    # --- 2.1 发现页：空闲态 ---
    try:
        at = AppTest.from_file("_diag_minimal_app.py", default_timeout=15)
        at.session_state["_ds_running"] = False
        at.session_state["_ds_results"] = []
        at.session_state["_ds_failed"] = []
        at.session_state["_ds_cursor"] = 0
        at.session_state["_ds_pool"] = []
        at.session_state["_ds_strategies"] = []
        at.session_state["_ds_total"] = 0
        at.run()

        # 检查关键 widget
        checks = [
            ("市场 selectbox", _has_selectbox(at, "市场")),
            ("信号方向 selectbox", _has_selectbox(at, "信号方向")),
            ("开始扫描 button", _has_button(at, "开始扫描")),
            ("筛选区不重复 (市场)", _count_selectbox(at, "市场") == 1),
            ("筛选区不重复 (信号方向)", _count_selectbox(at, "信号方向") == 1),
            ("筛选区不重复 (按钮)", _count_button(at, "开始扫描") == 1),
        ]
        for name, ok in checks:
            _record(f"发现页-空闲: {name}", ok, "出现多次!" if not ok else "")
    except Exception as e:
        _record("发现页-空闲 AppTest", False, str(e)[:150])

    # --- 2.2 发现页：扫描完成态 ---
    try:
        at2 = AppTest.from_file("_diag_minimal_app.py", default_timeout=15)
        at2.session_state["_ds_running"] = False
        at2.session_state["_ds_results"] = [
            {"symbol": "A", "signal": "买入信号", "strategy": "X",
             "signal_date": "2024-01-01", "signal_desc": "test",
             "recent_price": 10.0, "category": "A股"},
        ]
        at2.session_state["_ds_failed"] = []
        at2.session_state["_ds_cursor"] = 2
        at2.session_state["_ds_pool"] = []
        at2.session_state["_ds_strategies"] = []
        at2.session_state["_ds_total"] = 2
        at2.run()

        checks = [
            ("市场 selectbox", _has_selectbox(at2, "市场")),
            ("信号方向 selectbox", _has_selectbox(at2, "信号方向")),
            ("开始扫描 button", _has_button(at2, "开始扫描")),
            ("筛选区不重复 (市场)", _count_selectbox(at2, "市场") == 1),
            ("筛选区不重复 (按钮)", _count_button(at2, "开始扫描") == 1),
            ("结果已展示", len(at2.markdown) >= 3),  # 标题+"---"+"结果" markdown 块
        ]
        for name, ok in checks:
            _record(f"发现页-完成: {name}", ok, "出现多次!" if not ok else "")
    except Exception as e:
        _record("发现页-完成 AppTest", False, str(e)[:150])


def _has_selectbox(at, label):
    return any(s.label == label for s in at.selectbox)

def _count_selectbox(at, label):
    return sum(1 for s in at.selectbox if s.label == label)

def _has_button(at, label):
    return any((b.label or "") == label or label in (b.label or "") for b in at.button)

def _count_button(at, label):
    return sum(1 for b in at.button if (b.label or "") == label or label in (b.label or ""))


# ---------------------------------------------------------------------------
# 3. 运行留痕检查
# ---------------------------------------------------------------------------

def check_run_log():
    print("\n" + "=" * 56)
    print("📋 3. 运行留痕检查")
    print("-" * 40)

    # 先写一条测试记录
    try:
        from utils import run_logger
        run_logger.log_run("check_project", "test", ok=True, detail="综合健康检查测试记录")
        path = run_logger.get_run_log_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            ok = any("check_project" in ln for ln in lines[-10:])
            _record("run_logger 写入", ok,
                    f"日志路径: {path}, 共 {len(lines)} 行" if ok else "未找到测试记录")
        else:
            _record("run_logger 写入", False, f"日志文件不存在: {path}")
    except Exception as e:
        _record("run_logger 写入", False, str(e))

    # timed_call 验证
    try:
        from utils import run_logger
        def _test_func(x):
            return x * 2
        result = run_logger.timed_call("check_project", "timed_call_test", _test_func, 21)
        ok = result == 42
        _record("run_logger.timed_call", ok, f"返回 {result}" if ok else f"预期 42, 实际 {result}")
    except Exception as e:
        _record("run_logger.timed_call", False, str(e))

    # 错误收集器
    try:
        from utils.error_collector import install_error_collector, get_unresolved_errors
        install_error_collector()
        errs = get_unresolved_errors(limit=50)
        # 排除网络相关错误（非代码问题，受环境/墙/限流影响）
        _NET_KEYWORDS = ["timeout", "timed out", "connection", "httperror",
                         "urlerror", "maxretry", "sslerror", "remotedisconnected",
                         "400 bad request", "name or service not known",
                         "无法连接", "failed download", "网络", "连接失败",
                         "尝试失败", "搜索失败", "雪球", "rate limit",
                         "无法自动检测", "too many requests"]
        def _is_network_err(msg):
            msg_lower = (msg or "").lower()
            return any(kw in msg_lower for kw in _NET_KEYWORDS)
        non_network = [e for e in errs if not _is_network_err(e["message"])]
        ok = len(non_network) == 0
        _record("errors.db 无代码级未解决错误", ok,
                f"{len(non_network)} 条非网络错误" if not ok else "通过")
        if not ok and non_network:
            for e in non_network[:5]:
                print(f"     [{e['level']}] {e['logger']}: {e['message'][:80]}")
    except Exception as e:
        _record("errors.db 查询", False, str(e))


# ---------------------------------------------------------------------------
# 4. 端到端检查
# ---------------------------------------------------------------------------

def check_end_to_end():
    print("\n" + "=" * 56)
    print("🚀 4. 端到端检查 (streamlit 启动 + HTTP 探测)")
    print("-" * 40)

    # 动态分配端口
    port = _find_free_port()
    print(f"  使用端口: {port}")

    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app.py",
             "--server.headless", "true", "--server.port", str(port),
             "--server.enableCORS", "false", "--server.enableXsrfProtection", "false"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=PROJECT_ROOT,
        )

        # 指数退避重试（最多 20 秒）
        import urllib.request
        max_attempts = 8
        wait = 3
        last_error = None
        for attempt in range(1, max_attempts + 1):
            time.sleep(wait)
            try:
                resp = urllib.request.urlopen(f"http://localhost:{port}/", timeout=5)
                status = resp.getcode()
                if status == 200:
                    _record(f"streamlit HTTP 探测 (:{port})", True,
                            f"HTTP 200 (第 {attempt} 次尝试, {wait*attempt}s)")
                    return
            except Exception as e:
                last_error = e
            wait = min(wait * 1.5, 5)
        _record(f"streamlit HTTP 探测 (:{port})", False,
                f"重试 {max_attempts} 次后仍失败: {last_error}"[:120])

    except Exception as e:
        _record("streamlit 启动", False, str(e)[:150])
    finally:
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _find_free_port():
    """找一个可用端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_test_ohlcv(n=100, seed=42):
    import numpy as np
    import pandas as pd
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2024-01-02", periods=n, freq="B")
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


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    quick = "--quick" in sys.argv
    ui_only = "--ui-only" in sys.argv

    print(f"\n{'='*56}")
    print(f"量策 综合健康检查 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"模式: {'快速(离线)' if quick else 'UI-only' if ui_only else '完整'}")

    if not ui_only:
        check_data_fetching(quick=quick)

    check_ui_elements()
    check_run_log()

    if not quick and not ui_only:
        check_end_to_end()

    return _summary()


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 2
    sys.exit(code)
