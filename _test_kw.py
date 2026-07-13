# -*- coding: utf-8 -*-
import sys, types, importlib
sys.modules["pandas"] = types.ModuleType("pandas")
importlib.invalidate_caches()
sys.path.insert(0, r"x:\Personal\Project\liangce")
from core import sentiment as S
import inspect
print("signature:", inspect.signature(S.search_and_parse_events))

pairs = S.build_search_keywords("贵州茅台", "白酒", "600519.SH")
print("=== keywords ===")
for label, q in pairs:
    print(f"  [{label}] {q}")
print("  共", len(pairs), "组")

def mock_fetch(query, max_results=8):
    return [
        {"title": f"{query} 业绩超预期大涨", "snippet": "净利润增长", "url": "", "source": "mock", "date": "2026-07-01"},
        {"title": f"{query} 遭遇监管调查利空", "snippet": "被调查", "url": "", "source": "mock", "date": "2026-07-02"},
    ]

events = S.search_and_parse_events(mock_fetch, "贵州茅台", "白酒", code="600519.SH", max_per_query=8)
print("=== events ===")
for d, s, t in events:
    print(f"  ({d}, {s:+d}) {t}")
print("  共", len(events), "条事件")
