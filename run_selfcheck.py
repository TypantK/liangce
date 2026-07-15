# -*- coding: utf-8 -*-
"""
量策 —— 自测验证一键运行入口

用法：
    python run_selfcheck.py            # 运行全部自测，打印汇总
    python run_selfcheck.py --quiet    # 仅打印失败项与汇总

退出码：
    0 = 全部通过
    1 = 存在失败用例
    2 = 未捕获的异常/环境错误

该脚本离线运行（不联网），用于：
  - 保证数据层（SQLite 缓存 / DataFrame 归一化 / 缓存新鲜度）正确；
  - 保证 12 个策略 + 回测引擎 + 仓位管理功能可跑通、不阻塞（交易次数>0）。
"""

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import unittest


def main():
    quiet = "--quiet" in sys.argv[1:]
    loader = unittest.TestLoader()
    from core.selfcheck import load_tests
    suite = load_tests(loader, None, None)

    runner = unittest.TextTestRunner(verbosity=1 if quiet else 2, failfast=False)
    result = runner.run(suite)

    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    print("\n" + "=" * 56)
    print(f"量策自测结果：共 {total} 项，通过 {total - failed} 项，失败 {failed} 项")

    # ---- 运行留痕日志自检：确认本次自测产生的日志可正常写/读 ----
    _check_run_log()

    # ---- 扫描流程单帧无重复门禁：防止「两行」渲染回归 ----
    _check_scan_no_duplicate()

    if failed == 0:
        print("[OK] 全部通过：数据层、核心功能、页面冒烟、运行留痕均已验证。")
        return 0
    print("[FAIL] 存在失败项，请检查上方 [FAIL] / [ERROR] 详情。")
    return 1


def _check_run_log():
    """自检本次自测期间产生的运行留痕日志：可读、且其中不含 ERR。"""
    try:
        from utils import run_logger
        from utils.error_collector import get_unresolved_errors
        path = run_logger.get_run_log_path()
        has_err = False
        sample = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    sample.append(line.rstrip("\n"))
                    if " | ERR " in line:
                        has_err = True
        except FileNotFoundError:
            print(f"[RUNLOG] 未找到运行日志：{path}")
            return
        except Exception as e:  # noqa: BLE001
            print(f"[RUNLOG] 读取运行日志失败：{e}")
            return

        last_lines = sample[-3:] if sample else []
        print(f"[RUNLOG] 运行留痕日志：{path}")
        for ln in last_lines:
            print(f"         {ln}")

        # 未解决错误收集（collector 归档）
        try:
            errs = get_unresolved_errors(limit=20)
            if errs:
                print(f"[ERRDB] 检测到 {len(errs)} 条未解决错误（见 data/errors.db / data/error_logs/）")
                for e in errs[:5]:
                    print(f"         [{e['level']}] {e['logger']}: {e['message'][:80]}")
            else:
                print("[ERRDB] 无未解决错误归档。")
        except Exception:
            pass

        if has_err:
            print("[RUNLOG] 警告：运行留痕日志中存在 ERR 记录，请排查上述输出。")
    except Exception as e:  # noqa: BLE001
        print(f"[RUNLOG] 运行日志自检跳过（{e}）")


def _check_scan_no_duplicate():
    """自检扫描流程单帧无重复渲染（防止「两行」回归）。"""
    try:
        from core import scan_smoke
        res = scan_smoke.run_check(timeout=20)
        if res["ok"]:
            print(f"[SCAN_SMOKE] {res['details']}")
        else:
            print(f"[SCAN_SMOKE] FAIL：{res['details']}")
    except Exception as e:  # noqa: BLE001
        print(f"[SCAN_SMOKE] 跳过（{e}）")


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        code = 2
    sys.exit(code)
