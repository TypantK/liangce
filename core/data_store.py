# -*- coding: utf-8 -*-
"""
SQLite 持久化存储模块 — K线/基金净值/情绪事件的本地缓存。
纯标准库 sqlite3，无外部依赖。
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict

import pandas as pd


# 数据库文件路径（项目根目录下的 data/cache.db）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "cache.db")


def _get_conn() -> sqlite3.Connection:
    """获取数据库连接，自动创建 data 目录。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
#  初始化
# ---------------------------------------------------------------------------

def init_db():
    """初始化数据库和所有表（幂等，表已存在则跳过）。"""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS stock_prices (
                symbol  TEXT    NOT NULL,
                date    TEXT    NOT NULL,
                open    REAL,
                high    REAL,
                low     REAL,
                close   REAL,
                volume  REAL,
                PRIMARY KEY (symbol, date)
            );

            CREATE TABLE IF NOT EXISTS fund_nav (
                fund_code TEXT NOT NULL,
                date      TEXT NOT NULL,
                nav       REAL,
                acc_nav   REAL,
                PRIMARY KEY (fund_code, date)
            );

            CREATE TABLE IF NOT EXISTS sentiment_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                date       TEXT    NOT NULL,
                symbol     TEXT,
                sector     TEXT,
                title      TEXT    NOT NULL,
                summary    TEXT,
                sentiment  TEXT,
                score      INTEGER,
                source     TEXT,
                url        TEXT,
                created_at TEXT    NOT NULL,
                UNIQUE(date, title)
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
#  stock_prices — K线缓存
# ---------------------------------------------------------------------------

def save_stock_prices(symbol: str, df: pd.DataFrame) -> int:
    """保存 DataFrame 到 stock_prices 表。已存在的 (symbol, date) 跳过不覆盖。
    返回实际写入行数。"""
    if df is None or df.empty:
        return 0

    conn = _get_conn()
    try:
        rows = []
        for idx, row in df.iterrows():
            date_str = _to_date_str(idx)
            rows.append((
                symbol,
                date_str,
                _safe_float(row.get("open")),
                _safe_float(row.get("high")),
                _safe_float(row.get("low")),
                _safe_float(row.get("close")),
                _safe_float(row.get("volume")),
            ))

        count = 0
        for r in rows:
            try:
                conn.execute(
                    "INSERT INTO stock_prices (symbol, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    r,
                )
                count += 1
            except sqlite3.IntegrityError:
                pass  # 主键冲突，跳过
        conn.commit()
        return count
    finally:
        conn.close()


def load_stock_prices(symbol: str, start: Optional[str] = None,
                      end: Optional[str] = None) -> pd.DataFrame:
    """读取指定符号和时间范围的 K线数据，返回 DataFrame（DatetimeIndex）。"""
    conn = _get_conn()
    try:
        sql = "SELECT * FROM stock_prices WHERE symbol = ?"
        params = [symbol]
        if start:
            sql += " AND date >= ?"
            params.append(start)
        if end:
            sql += " AND date <= ?"
            params.append(end)
        sql += " ORDER BY date ASC"

        rows = conn.execute(sql, params).fetchall()
        if not rows:
            return pd.DataFrame()

        data = []
        for r in rows:
            data.append({
                "datetime": pd.Timestamp(r["date"]),
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "volume": r["volume"],
            })
        df = pd.DataFrame(data).set_index("datetime")
        df.index.name = "datetime"
        return df
    finally:
        conn.close()


def has_stock_data(symbol: str, start: Optional[str] = None,
                   end: Optional[str] = None) -> bool:
    """检查是否已有指定范围的完整数据（至少有一条记录）。"""
    conn = _get_conn()
    try:
        sql = "SELECT COUNT(*) AS cnt FROM stock_prices WHERE symbol = ?"
        params = [symbol]
        if start:
            sql += " AND date >= ?"
            params.append(start)
        if end:
            sql += " AND date <= ?"
            params.append(end)
        row = conn.execute(sql, params).fetchone()
        return row is not None and row["cnt"] > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
#  fund_nav — 基金净值缓存
# ---------------------------------------------------------------------------

def save_fund_nav(fund_code: str, records: List[Dict]) -> int:
    """保存基金净值记录列表。每条 record 含 date / nav / acc_nav。
    已存在的主键冲突跳过。返回实际写入行数。"""
    if not records:
        return 0

    conn = _get_conn()
    try:
        count = 0
        for r in records:
            try:
                conn.execute(
                    "INSERT INTO fund_nav (fund_code, date, nav, acc_nav) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        fund_code,
                        str(r.get("date", "")),
                        _safe_float(r.get("nav")),
                        _safe_float(r.get("acc_nav")),
                    ),
                )
                count += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        return count
    finally:
        conn.close()


def load_fund_nav(fund_code: str, start: Optional[str] = None,
                  end: Optional[str] = None) -> pd.DataFrame:
    """读取指定基金代码和时间范围的净值数据。"""
    conn = _get_conn()
    try:
        sql = "SELECT * FROM fund_nav WHERE fund_code = ?"
        params = [fund_code]
        if start:
            sql += " AND date >= ?"
            params.append(start)
        if end:
            sql += " AND date <= ?"
            params.append(end)
        sql += " ORDER BY date ASC"

        rows = conn.execute(sql, params).fetchall()
        if not rows:
            return pd.DataFrame()

        data = []
        for r in rows:
            data.append({
                "date": pd.Timestamp(r["date"]),
                "nav": r["nav"],
                "acc_nav": r["acc_nav"],
            })
        df = pd.DataFrame(data).set_index("date")
        df.index.name = "date"
        return df
    finally:
        conn.close()


# ---------------------------------------------------------------------------
#  sentiment_events — 情绪事件
# ---------------------------------------------------------------------------

def save_sentiment_events(events: List[Dict]) -> int:
    """批量保存情绪事件。按 (date, title) 去重，已存在则跳过。返回实际写入行数。"""
    if not events:
        return 0

    conn = _get_conn()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        count = 0
        for ev in events:
            try:
                conn.execute(
                    "INSERT INTO sentiment_events "
                    "(date, symbol, sector, title, summary, sentiment, score, source, url, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(ev.get("date", "")),
                        ev.get("symbol"),
                        ev.get("sector"),
                        str(ev.get("title", "")),
                        ev.get("summary"),
                        ev.get("sentiment"),
                        ev.get("score"),
                        ev.get("source"),
                        ev.get("url"),
                        now,
                    ),
                )
                count += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        return count
    finally:
        conn.close()


def load_sentiment_events(date: Optional[str] = None,
                          symbol: Optional[str] = None,
                          sector: Optional[str] = None) -> List[Dict]:
    """按条件查询情绪事件，返回 dict 列表。"""
    conn = _get_conn()
    try:
        conditions = []
        params = []
        if date:
            conditions.append("date = ?")
            params.append(date)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if sector:
            conditions.append("sector = ?")
            params.append(sector)

        sql = "SELECT * FROM sentiment_events"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY date DESC, id DESC"

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_sentiment_for_date(date: str) -> List[Dict]:
    """获取某日所有情绪事件。"""
    return load_sentiment_events(date=date)


def get_sentiment_date_range(start: str, end: str) -> List[Dict]:
    """获取日期范围内的所有情绪事件。"""
    conn = _get_conn()
    try:
        sql = "SELECT * FROM sentiment_events WHERE date >= ? AND date <= ? ORDER BY date ASC, id ASC"
        rows = conn.execute(sql, (start, end)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
#  辅助
# ---------------------------------------------------------------------------

def _to_date_str(val) -> str:
    """将 pandas Timestamp / datetime / str 统一转为 YYYY-MM-DD。"""
    if isinstance(val, pd.Timestamp):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    return str(val)[:10]


def _safe_float(val) -> Optional[float]:
    """安全转 float，None / NaN 返回 None。"""
    if val is None:
        return None
    try:
        f = float(val)
        if pd.isna(f):
            return None
        return f
    except (ValueError, TypeError):
        return None
