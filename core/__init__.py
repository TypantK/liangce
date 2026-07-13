# -*- coding: utf-8 -*-
"""
量策 core 包初始化 —— 副作用：挂载全局错误日志收集器。

任何模块 `import core` 时都会自动安装 utils.error_collector 的全局 Handler，
从而「偷偷」收集运行期间的 WARNING/ERROR 日志，写入 data/error_logs/ 与
data/errors.db，供 utils.auto_fix 自动诊断修复（无需用户手动贴日志）。
"""

import logging

try:
    from utils.error_collector import install_error_collector
    # 仅在主进程/脚本入口挂载一次，避免 Streamlit 热重载反复挂载
    install_error_collector()
    logging.getLogger(__name__).debug("量策错误收集器已挂载")
except Exception as e:  # noqa: BLE001
    # 收集器自身失败绝不能影响业务
    logging.getLogger(__name__).warning(f"错误收集器挂载失败（不影响主流程）: {e}")
