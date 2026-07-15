# -*- coding: utf-8 -*-
"""
关于页面 - 预留后续扩展入口；新增「系统自检 & 日志修复」面板
"""

import os
import sys
import subprocess
import streamlit as st

from utils import run_logger

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def render():
    run_logger.log_run("about_page", "render", ok=True, detail="页面渲染开始")
    st.title("关于「量策」")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        ### 当前功能
        - **策略回测**：12 种策略（双均线、RSI、MACD、布林带、卡尔曼滤波、HMA、线性回归斜率、一目均衡表、唐奇安通道、ADX、抛物线 SAR、成交量加权 MACD），参数可调
        - 支持 A 股、美股、加密货币、基金历史数据
        - 多策略横向对比
        - 参数网格寻优
        - 基金定投模拟
        - 完整绩效指标：夏普比率、最大回撤、胜率

        ### 技术栈
        - Python + Streamlit + Backtrader
        - 跨平台兼容（Windows / macOS / Linux）
        """)

    with col2:
        st.markdown("""
        ### 计划中的功能
        - 选股策略（基本面 + 技术面筛选）
        - 持仓管理 / 记账
        - 资产配置分析
        - 财务报表可视化
        """)

    st.divider()
    st.caption("v1.0 — 由 Marvis 搭建 | 运行在本地")

    # ===================================================================
    #  系统自检 & 日志修复面板
    # ===================================================================
    with st.expander("🛠️ 系统自检 & 错误日志修复", expanded=False):
        st.markdown(
            "本面板用于验证数据层与核心功能正确性，并自动收集/修复运行期间产生的错误日志。"
            "自测为**离线运行**（不联网），约 2 秒内完成。"
        )

        from utils import error_collector as ec
        ec.install_error_collector()
        stats = ec.get_error_stats()
        c1, c2, c3 = st.columns(3)
        c1.metric("累计错误", stats["total"])
        c2.metric("未解决", stats["unresolved"])
        c3.metric("已自动修复/归类",
                  stats["total"] - stats["unresolved"])

        b1, b2, b3 = st.columns(3)
        run_check = b1.button("▶️ 运行自测验证", key="btn_selfcheck")
        run_fix = b2.button("🔧 运行自动修复", key="btn_autofix")
        run_fix_dry = b3.button("🔍 诊断(不修改)", key="btn_autofix_dry")

        if run_check:
            with st.spinner("正在运行离线自测…"):
                try:
                    ret = subprocess.run(
                        [sys.executable, "run_selfcheck.py"],
                        cwd=PROJECT_ROOT, capture_output=True, text=True,
                        encoding="utf-8", errors="replace",
                    )
                    out = (ret.stdout or "") + (ret.stderr or "")
                    if ret.returncode == 0:
                        st.success("✅ 自测全部通过：数据层与核心功能正确性已验证。")
                    else:
                        st.error(f"❌ 自测存在失败项（退出码 {ret.returncode}），请查看详情：")
                    with st.expander("自测输出", expanded=(ret.returncode != 0)):
                        st.code(out[-4000:] if out else "(无输出)", language="text")
                except Exception as e:  # noqa: BLE001
                    st.error(f"运行自测时发生异常：{e}")

        if run_fix or run_fix_dry:
            with st.spinner("正在诊断错误日志…"):
                try:
                    from utils import auto_fix
                    rep = auto_fix.run_auto_fix(dry_run=run_fix_dry)
                    st.info(rep["summary"])
                    if rep["auto_fixed"]:
                        for it in rep["auto_fixed"][:8]:
                            st.success(f"[{it['category']}] ×{it['count']}：{it['detail']}")
                    if rep["env_classified"]:
                        for it in rep["env_classified"][:8]:
                            st.warning(f"[{it['category']}] ×{it['count']}：{it['detail']}")
                    if rep["manual"]:
                        st.error(f"需人工关注的错误 {len(rep['manual'])} 条：")
                        for it in rep["manual"][:8]:
                            with st.expander(f"[{it['category']}] ×{it['count']} {it['logger']}"):
                                st.write("消息：", it["message"])
                                st.write("建议：", it["suggest"])
                                if it.get("last_trace"):
                                    st.code(it["last_trace"][-2000:], language="text")
                    if run_fix_dry:
                        st.caption("当前为「诊断(不修改)」模式，未执行任何写操作。")
                except Exception as e:  # noqa: BLE001
                    st.error(f"运行自动修复时发生异常：{e}")

        with st.expander("查看最近未解决错误", expanded=False):
            errs = ec.get_unresolved_errors(limit=30)
            if not errs:
                st.caption("暂无未解决错误。")
            else:
                for e in errs[:30]:
                    st.write(
                        f"• **{e['level']}** `{e['logger']}` ×{e['count']} "
                        f"（{e['last_seen']}）：{e['message'][:120]}"
                    )
                st.caption("完整日志见 data/error_logs/ 与归档库 data/errors.db")

        with st.expander("查看运行留痕日志（最近 30 行）", expanded=False):
            try:
                path = run_logger.get_run_log_path()
                if not os.path.exists(path):
                    st.caption("暂无运行留痕日志（还没有打开过页面 / 跑过自测）。")
                else:
                    with open(path, "r", encoding="utf-8") as f:
                        lines = f.readlines()[-30:]
                    st.code("".join(lines) or "（空）", language="text")
                    st.caption(f"完整运行留痕见 {path}")
            except Exception as e:  # noqa: BLE001
                st.error(f"读取运行留痕失败：{e}")