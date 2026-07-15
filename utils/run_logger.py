# -*- coding: utf-8 -*-
"""
量策 —— 运行留痕日志

目标：让「每一次页面运行 / 关键函数调用」都在本地留一份可读日志，
便于事后排查「打开后报错但错误收集器没抓到」这类问题。

与 utils.error_collector 的区别：
  - error_collector：只收集 WARNING/ERROR，落 errors.db（结构化、按指纹去重）。
  - run_logger：        记录每一次运行的「成功/失败 + 耗时 + 详情」，落 run_logs/ 纯文本，
                         不挑级别，覆盖 INFO 级留痕，且对失败会同步触发 error_collector 归档。

设计原则：本模块绝对不抛异常，任何失败都静默降级，绝不能影响业务主流程。
"""

import os
import sys
import time
import logging
import threading
import traceback
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RUN_LOG_DIR = os.path.join(DATA_DIR, "run_logs")

_write_lock = threading.Lock()


def _ensure_dir():
    try:
        os.makedirs(RUN_LOG_DIR, exist_ok=True)
    except Exception:
        pass


def _run_log_path():
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(RUN_LOG_DIR, f"run_{today}.log")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def log_run(page, action, ok=True, detail="", elapsed_ms=None, exc=None):
    """记录一次运行/函数调用留痕。

    Args:
        page:    页面/模块名（如 "discover_page"）。
        action:  动作描述（如 "import" / "render" / "_classify_symbol"）。
        ok:      是否成功。
        detail:  附加信息（成功时的返回摘要 / 失败时的异常类型）。
        elapsed_ms: 耗时（毫秒），可选。
        exc:     异常对象，可选；若提供则把 traceback 一并写入，并触发 error_collector 归档。
    """
    _ensure_dir()
    status = "OK " if ok else "ERR"
    elapsed = f" [{elapsed_ms:.1f}ms]" if elapsed_ms is not None else ""
    line = f"{_now()} | {status} | {page} | {action}{elapsed} | {detail}"

    # 1) 写运行留痕日志（始终写，不挑级别）
    try:
        with _write_lock:
            with open(_run_log_path(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
                if exc is not None:
                    f.write("".join(
                        traceback.format_exception(type(exc), exc, exc.__traceback__)
                    ) + "\n")
    except Exception:
        pass

    # 2) 失败时同步触发全局错误收集器（WARNING/ERROR 落盘 + errors.db 归档）
    if not ok:
        try:
            logging.getLogger(f"run.{page}").error(f"{action} 失败: {detail}")
        except Exception:
            pass


def timed_call(page, action, func, *args, **kwargs):
    """带留痕地调用一个函数，返回其结果；异常会重新抛出（调用方自行决定如何处理）。

    用法：
        result = run_logger.timed_call("discover_page", "_classify_symbol", _classify_symbol, "600000.SH")
    """
    t0 = time.perf_counter()
    try:
        ret = func(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        # 成功留痕（detail 仅取前 120 字符，避免日志膨胀）
        try:
            detail = repr(ret)
        except Exception:
            detail = "<unrepr>"
        log_run(page, action, ok=True, detail=detail[:120], elapsed_ms=elapsed_ms)
        return ret
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log_run(page, action, ok=False, detail=f"{type(e).__name__}: {e}",
                elapsed_ms=elapsed_ms, exc=e)
        raise


def get_run_log_path():
    """返回今天的运行日志路径（供 UI 展示/下载用）。"""
    return _run_log_path()
