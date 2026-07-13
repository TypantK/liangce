# -*- coding: utf-8 -*-
"""
量策 —— 错误日志收集器

目标：在用户使用过程中「偷偷」把所有 WARNING / ERROR 级别日志收集起来，
写入本地日志文件与 SQLite 归档库（按指纹去重），供 utils/auto_fix.py 自动诊断修复，
无需用户手动提醒或贴日志。

特性：
  1. 全局挂载：install_error_collector() 给 root logger 挂一个 Handler，
     捕获项目内所有 logger 输出的告警/错误（包括第三方库 akshare/backtrader 等）。
  2. 文件落盘：按天滚动的纯文本日志，便于人肉排查。
  3. SQLite 归档：errors.db 中按 (level, logger, fingerprint) 去重，
     记录首次/最近出现时间、出现次数、最近一条完整 traceback，避免重复刷屏污染。
  4. 指纹稳定：用「logger名 + 去掉动态数字/日期后的消息」做指纹，
     同一类错误合并，方便 auto_fix 按类别给出修复建议。

注意：本模块只做「收集 + 归档」，不擅自修改任何业务代码；修复动作由 auto_fix 完成。
"""

import os
import re
import sqlite3
import logging
import hashlib
import threading
from datetime import datetime
from typing import Optional

# 项目根目录与数据目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LOG_DIR = os.path.join(DATA_DIR, "error_logs")
DB_PATH = os.path.join(DATA_DIR, "errors.db")

# 收集级别：WARNING 及以上
COLLECT_LEVEL = logging.WARNING

# 线程锁，保护 SQLite 写入
_db_lock = threading.Lock()

# 已安装标志，避免重复挂载
_installed = False


# ---------------------------------------------------------------------------
#  目录 / 库初始化
# ---------------------------------------------------------------------------

def _ensure_dirs():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)


def _get_conn() -> sqlite3.Connection:
    _ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_error_db():
    """创建错误归档表（幂等）。"""
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS error_records (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint  TEXT    NOT NULL,
                level        TEXT    NOT NULL,
                logger       TEXT    NOT NULL,
                category     TEXT,
                message      TEXT,
                last_trace   TEXT,
                first_seen   TEXT    NOT NULL,
                last_seen    TEXT    NOT NULL,
                count        INTEGER NOT NULL DEFAULT 1,
                resolved     INTEGER NOT NULL DEFAULT 0,
                UNIQUE(fingerprint)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS error_notes (
                fingerprint TEXT NOT NULL,
                note        TEXT,
                updated_at  TEXT NOT NULL,
                PRIMARY KEY (fingerprint)
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
#  指纹算法：去掉消息中的动态数字/日期，归并同类错误
# ---------------------------------------------------------------------------

_NUM_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}:\d{2}|\b\d+\b")


def _fingerprint(level: str, logger_name: str, message: str) -> str:
    """生成稳定指纹：logger + 去动态量后的消息 + 级别。"""
    norm = _NUM_DATE_RE.sub("#", message)
    raw = f"{level}|{logger_name}|{norm}"
    return hashlib.md5(raw.encode("utf-8", "replace")).hexdigest()


# ---------------------------------------------------------------------------
#  归档
# ---------------------------------------------------------------------------

def record_error(level: str, logger_name: str, message: str,
                  trace: Optional[str] = None, category: Optional[str] = None):
    """将一条错误归档（按指纹去重计数）。线程安全。"""
    fp = _fingerprint(level, logger_name, message)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _db_lock:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT id, count FROM error_records WHERE fingerprint = ?",
                (fp,)).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO error_records
                       (fingerprint, level, logger, category, message, last_trace,
                        first_seen, last_seen, count, resolved)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)""",
                    (fp, level, logger_name, category, message, trace, now, now))
            else:
                conn.execute(
                    """UPDATE error_records
                       SET count = count + 1, last_seen = ?, last_trace = ?,
                           level = ?, message = ?
                       WHERE fingerprint = ?""",
                    (now, trace, level, message, fp))
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
#  自定义 Handler
# ---------------------------------------------------------------------------

class _ErrorCollectHandler(logging.Handler):
    """把 WARNING/ERROR 记录落盘 + 归档。"""

    def __init__(self, file_handler: logging.FileHandler):
        super().__init__(level=COLLECT_LEVEL)
        self._file = file_handler
        # 格式：与文件日志一致，archive 只存结构化字段
        self._fmt = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    def emit(self, record: logging.LogRecord):
        try:
            # 1) 写文本日志
            self._file.emit(record)
            # 2) 归档到 SQLite
            trace = None
            if record.exc_info:
                import traceback
                trace = "".join(traceback.format_exception(*record.exc_info))
            elif getattr(record, "stack_info", None):
                trace = record.stack_info
            msg = record.getMessage()
            record_error(
                level=record.levelname,
                logger_name=record.name,
                message=msg,
                trace=trace,
            )
        except Exception:
            # 收集器自身绝不能影响主流程
            self.handleError(record)


# ---------------------------------------------------------------------------
#  挂载 / 查询 API
# ---------------------------------------------------------------------------

def install_error_collector(force: bool = False) -> bool:
    """给 root logger 挂全局错误收集 Handler（幂等）。

    Returns: 是否本次新挂载。
    """
    global _installed
    if _installed and not force:
        return False
    _ensure_dirs()
    init_error_db()

    # 当天日志文件
    today = datetime.now().strftime("%Y-%m-%d")
    log_path = os.path.join(LOG_DIR, f"errors_{today}.log")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(COLLECT_LEVEL)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

    handler = _ErrorCollectHandler(file_handler)
    handler.setLevel(COLLECT_LEVEL)

    root = logging.getLogger()
    # 避免重复挂载：检查是否已有同类 handler
    for h in root.handlers:
        if isinstance(h, _ErrorCollectHandler):
            _installed = True
            return False
    root.addHandler(handler)
    # 确保 root 能传播到我们（默认 propagate=True 即可）
    if root.level == logging.NOTSET or root.level > COLLECT_LEVEL:
        root.setLevel(min(root.level, COLLECT_LEVEL) if root.level != logging.NOTSET
                      else COLLECT_LEVEL)
    _installed = True
    return True


def get_unresolved_errors(limit: int = 200) -> list:
    """返回未解决的错误记录列表（按最近出现时间倒序）。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM error_records WHERE resolved = 0 "
            "ORDER BY last_seen DESC, count DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_error_stats() -> dict:
    """汇总统计：总数 / 未解决 / 各级别计数。"""
    conn = _get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) c FROM error_records").fetchone()["c"]
        unresolved = conn.execute(
            "SELECT COUNT(*) c FROM error_records WHERE resolved = 0").fetchone()["c"]
        by_level = {}
        for r in conn.execute(
                "SELECT level, COUNT(*) c FROM error_records GROUP BY level"):
            by_level[r["level"]] = r["c"]
        return {"total": total, "unresolved": unresolved, "by_level": by_level}
    finally:
        conn.close()


def mark_resolved(fingerprint: str, note: str = ""):
    """标记某指纹已解决（auto_fix 修复后调用）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE error_records SET resolved = 1 WHERE fingerprint = ?",
                (fingerprint,))
            if note:
                conn.execute(
                    """INSERT INTO error_notes (fingerprint, note, updated_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(fingerprint) DO UPDATE SET
                           note = excluded.note, updated_at = excluded.updated_at""",
                    (fingerprint, note, now))
            conn.commit()
        finally:
            conn.close()


def mark_auto_fixed(fingerprint: str, action: str):
    """标记某指纹已被自动修复（写入备注，但保留记录供审计）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE error_records SET resolved = 1 WHERE fingerprint = ?",
                (fingerprint,))
            conn.execute(
                """INSERT INTO error_notes (fingerprint, note, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(fingerprint) DO UPDATE SET
                       note = excluded.note, updated_at = excluded.updated_at""",
                (fingerprint, f"[自动修复] {action}（{now}）", now))
            conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    install_error_collector()
    logging.warning("测试收集器：这是一条示例告警")
    print("已安装错误收集器。未解决错误：", get_error_stats())
