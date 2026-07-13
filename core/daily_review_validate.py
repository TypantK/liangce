# -*- coding: utf-8 -*-
# 本文件属于「量策 / liangce」项目，以 GNU GPL v3.0 发布。
# Copyright (C) 2026  TypantK
#
# 每日复盘轻量校验 (daily_review_validate)
# ============================================================
# 借鉴 quantskills/skill-market-daily-review 的 validate_report.py「交付前 Quality Gate」
# 思路：对 build_daily_review() 产出的结构化 dict 做校验，确保必备章节齐全、
# 含 T+1 数据口径标注、并保留「只述不荐」免责声明。校验不通过时产出 FAIL 清单，
# 供 UI / 日志提示，但不阻断页面渲染（数据缺失本身已优雅降级为占位）。
#
# 注意：本项目数据层产出的不是 Markdown 报告文件，而是结构化 dict，因此校验对象
# 是 dict 而非 .md 文本；校验维度与 daily-review 的 9 项门禁对齐（章节/数据日/
# 截止时间/T+1 标注/非投资建议声明）。

from __future__ import annotations

from typing import Dict, Any, List


# 必备章节键（对应 daily_review.build_daily_review 的产出结构）
REQUIRED_SECTIONS = ("indices", "breadth", "sectors", "capital")

# 免责声明关键字（出现任一即视为已声明「只述不荐」）
DISCLAIMER_KEYWORDS = ("不构成", "投资建议", "只述不荐", "仅供参考", "研究参考")

# 数据口径 / T+1 标注关键字
T_PLUS_1_KEYWORDS = ("T+1", "交易日", "收盘", "数据日", "口径", "截止")


def validate_daily_review(review: Dict[str, Any]) -> Dict[str, Any]:
    """校验一份每日复盘数据。

    Args:
        review: build_daily_review() 的返回值（dict）

    Returns:
        {
          "ok": bool,            # 是否通过门禁
          "errors": [str, ...],  # 缺失项 / 规则违反清单
          "warnings": [str, ...],# 非阻断提示（如某章节数据为空）
          "is_after_close": bool,# 是否盘后数据（影响 T+1 标注含义）
          "as_of": str,          # 数据对应交易日
        }
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(review, dict):
        return {
            "ok": False,
            "errors": ["复盘数据不是合法的 dict"],
            "warnings": [],
            "is_after_close": False,
            "as_of": "",
        }

    # ---- 1. 必备章节 ----
    for sec in REQUIRED_SECTIONS:
        if sec not in review:
            errors.append(f"缺失必备章节：{sec}")
        elif not isinstance(review.get(sec), dict):
            warnings.append(f"章节 {sec} 类型异常，可能未正常产出")

    # ---- 2. 数据对应交易日（as_of）----
    as_of = review.get("as_of", "")
    if not as_of:
        errors.append("缺失数据对应交易日 (as_of)")
    else:
        # 简单格式校验：YYYY-MM-DD
        parts = str(as_of).split("-")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            warnings.append(f"as_of 格式非标准 YYYY-MM-DD：{as_of}")

    # ---- 3. 生成时间（截止时间标注）----
    if not review.get("generated_at"):
        warnings.append("缺失生成时间 (generated_at)，截止时间标注不完整")

    # ---- 4. T+1 / 数据口径标注 ----
    # 资金面章节的 note 或北向 note 应包含口径说明
    capital = review.get("capital", {}) or {}
    notes_blob = " ".join(
        str(v) for v in (capital.get("north_note", ""), capital.get("note", ""))
    )
    has_t1 = any(k in notes_blob for k in T_PLUS_1_KEYWORDS)
    if not has_t1:
        warnings.append("资金面章节缺少数据口径/T+1 标注说明")

    # ---- 5. 免责声明 ----
    # 免责声明文本由 UI 层渲染，这里仅校验数据层是否携带 available 标志位；
    # 真正文本校验在 discover_page 渲染侧。为兼容无标志位场景，不强制阻断。
    if "disclaimer" in review and not review.get("disclaimer"):
        warnings.append("已声明 disclaimer 标志但为空，UI 需补全「只述不荐」声明")

    # ---- 6. 各章节数据可用性提示（非阻断）----
    for sec in REQUIRED_SECTIONS:
        blk = review.get(sec, {}) or {}
        if isinstance(blk, dict) and blk.get("note") is None and not blk:
            warnings.append(f"章节 {sec} 无数据且无说明，建议补全降级备注")

    is_after_close = bool(review.get("is_after_close", False))
    ok = len(errors) == 0
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "is_after_close": is_after_close,
        "as_of": as_of,
    }


def format_validation(report: Dict[str, Any]) -> str:
    """把校验报告格式化为可读文本（供 UI / 日志展示）。"""
    if report["ok"]:
        head = "✅ 复盘数据校验通过"
    else:
        head = "❌ 复盘数据校验未通过"
    lines = [head]
    if report["errors"]:
        lines.append("缺失项：")
        lines += [f"  - {e}" for e in report["errors"]]
    if report["warnings"]:
        lines.append("提示项：")
        lines += [f"  - {w}" for w in report["warnings"]]
    if not report["errors"] and not report["warnings"]:
        lines.append("  所有必备项与口径标注均就绪")
    return "\n".join(lines)
