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
    if failed == 0:
        print("[OK] 全部通过：数据层与核心功能正确性已验证。")
        return 0
    print("[FAIL] 存在失败项，请检查上方 [FAIL] / [ERROR] 详情。")
    return 1


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        code = 2
    sys.exit(code)
