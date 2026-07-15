# -*- coding: utf-8 -*-
"""
量策 —— 扫描流程「单帧无重复」冒烟门禁

目的：防止 discover_page 扫描流程出现「筛选区/扫描按钮在单帧内重复渲染」问题
      （用户截图反馈：扫描时市场/信号方向/扫描按钮出现两行）。

方法：用 streamlit.testing.v1.AppTest 无头运行一个最小复现 app，
      模拟「扫描完成」状态，断言单帧内每个关键 widget 只出现一次。

运行方式：
    .venv/Scripts/python.exe core/scan_smoke.py
    （由 run_selfcheck.py 收尾自动调用）
"""

import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)


def run_check(timeout: int = 15) -> dict:
    """执行扫描流程单帧无重复门禁。

    Returns:
        {"ok": bool, "details": str, "frames_checked": int}
    """
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError as e:
        return {"ok": False, "details": f"streamlit AppTest 不可用: {e}", "frames_checked": 0}

    # 最小复现 app：复制 discover_page 的扫描状态机 + 渲染，但用内存 demo 数据避开网络
    minimal_app_path = os.path.join(PROJECT_ROOT, "_diag_minimal_app.py")
    if not os.path.exists(minimal_app_path):
        return {"ok": False, "details": f"缺少最小复现 app: {minimal_app_path}",
                "frames_checked": 0}

    frames_checked = 0
    failures = []

    def assert_no_dup(at, label, frame_name):
        sb = [s for s in at.selectbox if s.label == label]
        btn = [b for b in at.button if (b.label or "") == label or label in (b.label or "")]
        total = len(sb) + len(btn)
        if total > 1:
            failures.append(
                f"{frame_name}: 「{label}」重复 {total} 次 "
                f"(selectbox={[(s.label,s.value) for s in sb]}, "
                f"button={[b.label for b in btn]})"
            )

    def dump(at):
        return (f"selectbox={[(s.label,s.value) for s in at.selectbox]} "
                f"button={[b.label for b in at.button]} "
                f"info={len(at.info)}")

    # --- 帧 A: 空闲态 ---
    at = AppTest.from_file(minimal_app_path, default_timeout=timeout)
    at.session_state["_ds_running"] = False
    at.session_state["_ds_results"] = []
    at.session_state["_ds_failed"] = []
    at.session_state["_ds_cursor"] = 0
    at.session_state["_ds_pool"] = []
    at.session_state["_ds_strategies"] = []
    at.session_state["_ds_total"] = 0
    at.run()
    frames_checked += 1
    assert_no_dup(at, "市场", "帧A-空闲")
    assert_no_dup(at, "信号方向", "帧A-空闲")
    assert_no_dup(at, "开始扫描", "帧A-空闲")
    assert_no_dup(at, "扫描中...", "帧A-空闲")

    # --- 帧 B: 扫描完成 + 结果展示（核心回归场景）---
    at = AppTest.from_file(minimal_app_path, default_timeout=timeout)
    at.session_state["_ds_running"] = False
    at.session_state["_ds_results"] = [
        {"symbol": "A", "signal": "买入信号", "strategy": "X",
         "signal_date": "2024-01-01", "signal_desc": "test",
         "recent_price": 10.0, "category": "A股"},
    ]
    at.session_state["_ds_failed"] = []
    at.session_state["_ds_cursor"] = 2
    at.session_state["_ds_pool"] = []
    at.session_state["_ds_strategies"] = []
    at.session_state["_ds_total"] = 2
    at.run()
    frames_checked += 1
    assert_no_dup(at, "市场", "帧B-完成")
    assert_no_dup(at, "信号方向", "帧B-完成")
    assert_no_dup(at, "开始扫描", "帧B-完成")
    assert_no_dup(at, "扫描中...", "帧B-完成")

    if failures:
        return {
            "ok": False,
            "details": "扫描流程单帧重复渲染：\n  - " + "\n  - ".join(failures),
            "frames_checked": frames_checked,
        }
    return {
        "ok": True,
        "details": f"已检查 {frames_checked} 个关键帧，筛选区/扫描按钮均无重复",
        "frames_checked": frames_checked,
    }


if __name__ == "__main__":
    res = run_check()
    print(f"[SCAN_SMOKE] ok={res['ok']} | frames={res['frames_checked']}")
    print(f"[SCAN_SMOKE] {res['details']}")
    sys.exit(0 if res["ok"] else 1)
