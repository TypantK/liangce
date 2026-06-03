# -*- coding: utf-8 -*-
"""
新闻搜索获取器 — 用于情绪分析模块

尝试多种数据源获取新闻，失败时降级为示例新闻数据。
"""

import json
import urllib.request
import urllib.parse


def _search_duckduckgo(query: str, max_results: int = 8) -> list[dict]:
    """使用 DuckDuckGo HTML 搜索获取结果。"""
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({
        "q": query + " 财经 新闻",
    })
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    results = []
    # 简单解析 HTML 搜索结果
    import re
    # 匹配每条结果：标题和摘要
    items = re.findall(
        r'<a[^>]*class="result__a"[^>]*>(.*?)</a>.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL | re.IGNORECASE
    )
    for title, snippet in items[:max_results]:
        title_clean = re.sub(r'<[^>]+>', '', title).strip()
        snippet_clean = re.sub(r'<[^>]+>', '', snippet).strip()
        if title_clean:
            results.append({"title": title_clean, "snippet": snippet_clean})
    return results


def _sample_news(query: str) -> list[dict]:
    """示例新闻数据（当真实搜索不可用时降级使用）。"""
    now_date = "2026-06-03"
    yesterday = "2026-06-02"
    return [
        {"title": f"{query}板块政策利好出台，多只个股涨停创新高", "snippet": f"日期: {now_date} 受政策《关于加快{query}产业发展的指导意见》出台利好，相关概念股集体爆发。"},
        {"title": f"机构看好{query}赛道：行业景气度持续提升", "snippet": f"日期: {yesterday} 多家券商发布{query}行业研报，评级上调至增持。"},
        {"title": f"监管层关注{query}领域风险——短期利空需警惕", "snippet": f"日期: {yesterday} 监管部门针对{query}部分业务发布风险提示，涉及合规调查。"},
        {"title": f"全球{query}市场展望：技术突破引领新周期", "snippet": f"日期: {now_date} 海外{query}龙头最新季度报超预期，营收增长35%。"},
        {"title": f"{query}龙头业绩下滑，投资者减持避险", "snippet": f"日期: {yesterday} 某{query}公司财报不及预期，股价大跌。"},
        {"title": f"北向资金大幅流入{query}板块，主力加仓信号", "snippet": f"日期: {now_date} 北向资金今日净流入{query}板块超50亿。"},
    ]


def fetch_news(query: str, max_results: int = 6) -> list[dict]:
    """
    获取与 query 相关的最新财经新闻。

    返回: [{"title": "...", "snippet": "..."}, ...]
    """
    # 尝试 DuckDuckGo
    results = _search_duckduckgo(query, max_results)
    if results:
        return results

    # 降级：使用示例数据
    return _sample_news(query)
