# -*- coding: utf-8 -*-
"""
情绪事件存储与检索 — 基于 data_store 的情绪事件表提供高层接口。

使用方式：
    from core.sentiment_store import SentimentStore
    store = SentimentStore()
    store.add_events([...])
    events = store.get_events_by_date("2026-06-24")
"""

from typing import Optional, List, Dict
from datetime import datetime, timedelta
from collections import Counter

from . import data_store


class SentimentStore:
    """情绪事件的高层查询与摘要接口。"""

    # ------------------------------------------------------------------
    #  写入
    # ------------------------------------------------------------------

    @staticmethod
    def add_events(events_list: List[Dict]) -> int:
        """批量添加情绪事件。自动按 (date, title) 去重。返回实际入库数量。"""
        data_store.init_db()
        return data_store.save_sentiment_events(events_list)

    # ------------------------------------------------------------------
    #  按维度查询
    # ------------------------------------------------------------------

    @staticmethod
    def get_events_by_date(date_str: str) -> List[Dict]:
        """获取某日所有情绪事件（利好/利空/中性混合）。"""
        data_store.init_db()
        return data_store.get_sentiment_for_date(date_str)

    @staticmethod
    def get_events_by_symbol(symbol: str, days: int = 30) -> List[Dict]:
        """获取某股票最近 N 天的情绪事件。"""
        data_store.init_db()
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
        events = data_store.get_sentiment_date_range(start, end)
        return [e for e in events if e.get("symbol") == symbol]

    @staticmethod
    def get_events_by_sector(sector: str, days: int = 30) -> List[Dict]:
        """获取某板块/行业最近 N 天的情绪事件。"""
        data_store.init_db()
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
        events = data_store.get_sentiment_date_range(start, end)
        return [e for e in events if e.get("sector") == sector]

    # ------------------------------------------------------------------
    #  摘要 / 概览
    # ------------------------------------------------------------------

    @staticmethod
    def get_daily_digest(date_str: str) -> Dict:
        """
        获取某日的情绪摘要。

        Returns:
            {
                "date": "2026-06-24",
                "total": 12,
                "bullish": [...],     # 利好事件（最多 5 条）
                "bearish": [...],     # 利空事件（最多 5 条）
                "neutral": [...],     # 中性事件（最多 5 条）
                "bullish_count": 5,
                "bearish_count": 3,
                "neutral_count": 4,
                "avg_score": 1.2,
                "tilt": "偏多"        # 总体倾向：偏多 / 偏空 / 中性
            }
        """
        events = SentimentStore.get_events_by_date(date_str)

        bullish = [e for e in events if e.get("sentiment") == "利好"]
        bearish = [e for e in events if e.get("sentiment") == "利空"]
        neutral = [e for e in events if e.get("sentiment") == "中性"]

        scores = [e.get("score", 0) or 0 for e in events]
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0

        if avg_score > 0.5:
            tilt = "偏多"
        elif avg_score < -0.5:
            tilt = "偏空"
        else:
            tilt = "中性"

        return {
            "date": date_str,
            "total": len(events),
            "bullish": bullish[:5],
            "bearish": bearish[:5],
            "neutral": neutral[:5],
            "bullish_count": len(bullish),
            "bearish_count": len(bearish),
            "neutral_count": len(neutral),
            "avg_score": avg_score,
            "tilt": tilt,
        }

    @staticmethod
    def get_date_range_summary(start: str, end: str) -> Dict:
        """
        获取日期范围内的情绪概览。

        Returns:
            {
                "start": "2026-06-01",
                "end": "2026-06-24",
                "total_events": 86,
                "bullish": 38,
                "bearish": 22,
                "neutral": 26,
                "top_sentiment": "利好" / "利空" / "中性",
                "by_date": {           # 每日摘要
                    "2026-06-24": {"total": 5, "bullish": 3, "bearish": 1, "neutral": 1, "tilt": "偏多"},
                    ...
                },
                "top_symbols": [       # 事件最多的前 5 个标的
                    ("000001.SZ", 8),
                    ("300750.SZ", 6),
                    ...
                ],
                "top_sectors": [       # 事件最多的前 5 个板块
                    ("半导体", 12),
                    ("新能源", 9),
                    ...
                ]
            }
        """
        data_store.init_db()
        events = data_store.get_sentiment_date_range(start, end)

        bullish = [e for e in events if e.get("sentiment") == "利好"]
        bearish = [e for e in events if e.get("sentiment") == "利空"]
        neutral = [e for e in events if e.get("sentiment") == "中性"]

        # 判断总体多空
        bc = len(bullish)
        brc = len(bearish)
        if bc > brc:
            top_sentiment = "利好"
        elif brc > bc:
            top_sentiment = "利空"
        else:
            top_sentiment = "中性"

        # 按日期聚合
        by_date: Dict[str, Dict] = {}
        for e in events:
            d = e.get("date", "")
            if d not in by_date:
                by_date[d] = {"total": 0, "bullish": 0, "bearish": 0, "neutral": 0, "tilt": "中性"}
            by_date[d]["total"] += 1
            s = e.get("sentiment", "中性")
            if s == "利好":
                by_date[d]["bullish"] += 1
            elif s == "利空":
                by_date[d]["bearish"] += 1
            else:
                by_date[d]["neutral"] += 1

        for d, stats in by_date.items():
            if stats["bullish"] > stats["bearish"]:
                stats["tilt"] = "偏多"
            elif stats["bearish"] > stats["bullish"]:
                stats["tilt"] = "偏空"
            else:
                stats["tilt"] = "中性"

        # 按标的聚合
        symbol_counter = Counter()
        for e in events:
            sym = e.get("symbol")
            if sym:
                symbol_counter[sym] += 1
        top_symbols = symbol_counter.most_common(5)

        # 按板块聚合
        sector_counter = Counter()
        for e in events:
            sec = e.get("sector")
            if sec:
                sector_counter[sec] += 1
        top_sectors = sector_counter.most_common(5)

        return {
            "start": start,
            "end": end,
            "total_events": len(events),
            "bullish": bc,
            "bearish": brc,
            "neutral": len(neutral),
            "top_sentiment": top_sentiment,
            "by_date": by_date,
            "top_symbols": top_symbols,
            "top_sectors": top_sectors,
        }
