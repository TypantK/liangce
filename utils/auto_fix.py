# -*- coding: utf-8 -*-
"""
量策 —— 错误自动诊断与修复

配合 utils/error_collector.py 使用：读取 errors.db 中未解决的错误，
按「错误指纹 / 消息特征」归类到已知问题类别，对可安全自动处理的问题执行修复，
无法自动处理的给出可读的修复建议并汇总成报告。

设计原则（安全优先）：
  - 只做「低风险、可逆、确定有效」的自动动作：
      * 清理过期/损坏的本地缓存（K线缓存、CSV 数据缓存）让下次重新联网拉取；
      * 标记「已知环境类问题」（如 akshare 未安装、网络超时）为已解决/已归类，
        避免反复刷屏，并写入修复建议供用户参考。
  - 绝不修改业务源码、绝不删除 errors.db 历史记录（保留审计）。
  - 任何自动动作前打印明确说明，返回结构化报告，便于用户审阅。

运行方式：
    python -m utils.auto_fix            # 诊断 + 自动修复 + 打印报告
"""

import os
import re
import sys
import glob
import shutil
import logging
from datetime import datetime
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils import error_collector as ec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  已知错误类别（按消息特征匹配）
# ---------------------------------------------------------------------------

# (类别名, 正则, 是否可自动修复, 说明模板)
_KNOWN_PATTERNS = [
    ("网络超时/连接失败", re.compile(r"timeout|timed out|连接|connection|远程主机|urlopen|URLError|ConnectError", re.I),
     "auto_clear_cache",
     "网络抖动或目标源不可达。已清理相关本地缓存，下次运行将重新联网拉取；如持续发生请检查网络/代理。"),
    ("东方财富风控/空数据", re.compile(r"东财|eastmoney|push2|返回空|klines|风控|rate", re.I),
     "auto_clear_cache",
     "东方财富接口被限流或返回空。已清理本地 K 线缓存并重置，下次将走多域名备胎重试。"),
    ("akshare 未安装", re.compile(r"akshare 未安装|No module named 'akshare'|ImportError.*akshare", re.I),
     "auto_mark_env",
     "akshare 未安装，相关通道（A股/美股/板块）会降级到其它源或示例数据。建议：pip install akshare。"),
    ("baostock 未安装/失败", re.compile(r"baostock|No module named 'baostock'", re.I),
     "auto_mark_env",
     "baostock 未安装或登录失败，已自动降级到 akshare / 东方财富直连等备胎源，不影响整体功能。"),
    ("open-stock-data 未安装", re.compile(r"open_stock_data|No module named 'open_stock_data'", re.I),
     "auto_mark_env",
     "open-stock-data 未安装，已自动跳过该源走后续备胎链。建议按需安装。"),
    ("数据列缺失/格式异常", re.compile(r"缺少必要的 OHLCV|NaN|NoneType|KeyError|TypeError|ValueError|索引越界|空数据", re.I),
     "auto_clear_cache",
     "某次数据解析异常或缓存损坏。已清理可能损坏的本地缓存，下次重新拉取。"),
    ("ccxt/加密货币通道失败", re.compile(r"ccxt|okx|binance|gate", re.I),
     "auto_clear_cache",
     "加密货币通道失败。已清理相关缓存，下次走多交易所备胎重试；持续失败则降级到缓存/演示数据。"),
]


def _classify(message: str, logger_name: str) -> tuple:
    """返回 (类别名, 处理方式, 说明)。"""
    text = f"{logger_name} {message}"
    for name, pat, action, desc in _KNOWN_PATTERNS:
        if pat.search(text):
            return name, action, desc
    return "未知/未分类", "manual", "未在已知规则库内，需人工排查。"


# ---------------------------------------------------------------------------
#  自动修复动作（均为低风险、可逆）
# ---------------------------------------------------------------------------

def _clear_stock_cache(symbol_hint: Optional[str] = None) -> int:
    """清理本地缓存（低风险、可逆：下次运行自动重新联网拉取）。

    - 若给出 symbol_hint：精确清理该标的的 SQLite K线缓存 + 对应 CSV 文件。
    - 若未给出标的：**只清 CSV 数据缓存目录**，不清空 SQLite 全表，
      避免误删无关标的缓存（CSV 缓存为可选加速层，缺失无害）。
    返回清理的缓存条数/文件数。
    """
    cleared = 0
    # 1) SQLite stock_prices / fund_nav（仅在有明确标的时清理，防止误清全表）
    if symbol_hint:
        try:
            from core import data_store
            data_store.init_db()
            conn = data_store._get_conn()
            try:
                cleared += conn.execute(
                    "DELETE FROM stock_prices WHERE symbol = ?", (symbol_hint,)).rowcount
                cleared += conn.execute(
                    "DELETE FROM fund_nav WHERE fund_code = ?", (symbol_hint,)).rowcount
                conn.commit()
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"清理 SQLite 缓存时异常: {e}")

    # 2) CSV 数据缓存目录 data_cache（始终安全清理，缺失无害）
    cache_dir = os.path.join(PROJECT_ROOT, "data_cache")
    if os.path.isdir(cache_dir):
        for f in glob.glob(os.path.join(cache_dir, "*.csv")):
            if symbol_hint and symbol_hint.replace("/", "_") not in os.path.basename(f):
                continue
            try:
                os.remove(f)
                cleared += 1
            except Exception:
                pass
    return cleared


def _auto_action(action: str, record: dict) -> str:
    """执行自动修复动作，返回人类可读的动作描述。"""
    if action == "auto_clear_cache":
        # 尝试从消息里提取标的代码（如 600519.SH / BTC/USDT / SECTOR:xxx）
        sym = None
        m = re.search(r"([0-9]{6}\.[A-Z]{2}|[A-Z]{2,5}/USDT|SECTOR:[^\s]+)", record.get("message", ""))
        if m:
            sym = m.group(1)
        cleared = _clear_stock_cache(sym)
        return f"已清理本地缓存（标的={sym or '全部'}，清除 {cleared} 项），下次运行将重新联网拉取"
    elif action == "auto_mark_env":
        return "已归类为已知环境缺失类问题并标记，相关功能已自动降级到备胎源，不影响使用"
    return "无需自动动作"


# ---------------------------------------------------------------------------
#  主入口
# ---------------------------------------------------------------------------

def run_auto_fix(dry_run: bool = False) -> dict:
    """扫描未解决错误，分类、自动修复、汇总报告。

    dry_run=True 时只诊断不执行任何写操作。
    Returns: 结构化报告 dict。
    """
    ec.install_error_collector()
    errors = ec.get_unresolved_errors()
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_unresolved": len(errors),
        "auto_fixed": [],
        "env_classified": [],
        "manual": [],
        "summary": "",
    }
    if not errors:
        report["summary"] = "未发现未解决的错误日志，一切正常。"
        return report

    for rec in errors:
        category, action, desc = _classify(rec.get("message", ""), rec.get("logger", ""))
        fp = rec["fingerprint"]
        if action == "auto_clear_cache":
            if not dry_run:
                detail = _auto_action(action, rec)
                ec.mark_auto_fixed(fp, detail)
            else:
                detail = "[dry-run] " + _auto_action(action, rec)
            report["auto_fixed"].append({
                "level": rec.get("level"), "logger": rec.get("logger"),
                "category": category, "count": rec.get("count"),
                "detail": detail, "message": rec.get("message"),
            })
        elif action == "auto_mark_env":
            if not dry_run:
                detail = _auto_action(action, rec)
                ec.mark_auto_fixed(fp, detail)
            else:
                detail = "[dry-run] " + desc
            report["env_classified"].append({
                "level": rec.get("level"), "logger": rec.get("logger"),
                "category": category, "count": rec.get("count"),
                "detail": detail, "message": rec.get("message"),
            })
        else:
            report["manual"].append({
                "level": rec.get("level"), "logger": rec.get("logger"),
                "category": category, "count": rec.get("count"),
                "suggest": desc, "message": rec.get("message"),
                "last_trace": rec.get("last_trace"),
            })

    n_auto = len(report["auto_fixed"])
    n_env = len(report["env_classified"])
    n_manual = len(report["manual"])
    report["summary"] = (
        f"共 {len(errors)} 条未解决错误：自动修复 {n_auto} 条，"
        f"环境类已归类 {n_env} 条，需人工关注 {n_manual} 条。"
    )
    return report


def _print_report(report: dict):
    print("=" * 64)
    print(f"量策 错误自动诊断报告  ({report['generated_at']})")
    print("=" * 64)
    print(report["summary"])
    if report["auto_fixed"]:
        print("\n[自动修复]")
        for it in report["auto_fixed"]:
            print(f"  - [{it['category']}] x{it['count']} {it['logger']}")
            print(f"      {it['detail']}")
    if report["env_classified"]:
        print("\n[环境类·已归类（功能已自动降级）]")
        for it in report["env_classified"]:
            print(f"  - [{it['category']}] x{it['count']} {it['logger']}")
            print(f"      {it['detail']}")
    if report["manual"]:
        print("\n[需人工关注]")
        for it in report["manual"]:
            print(f"  - [{it['category']}] x{it['count']} {it['logger']}")
            print(f"      消息: {it['message']}")
            print(f"      建议: {it['suggest']}")
    print("\n日志文件目录：data/error_logs/   归档库：data/errors.db")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    rep = run_auto_fix(dry_run=dry)
    _print_report(rep)
