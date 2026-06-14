# -*- coding: utf-8 -*-
"""
新闻搜索获取器 — 用于情绪分析模块

尝试多种数据源获取新闻，失败时降级为示例新闻数据。
"""

import json
import urllib.request
import urllib.parse
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


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
    except Exception as e:
        logger.warning(f"DuckDuckGo 搜索请求失败: {e}")
        return []

    results = []
    # 简单解析 HTML 搜索结果
    import re
    # 匹配每条结果：链接、标题和摘要
    items = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL | re.IGNORECASE
    )
    if not items:
        logger.warning(f"DuckDuckGo HTML 解析未匹配到结果项，页面结构可能已变更(query={query})")
    for url, title, snippet in items[:max_results]:
        title_clean = re.sub(r'<[^>]+>', '', title).strip()
        snippet_clean = re.sub(r'<[^>]+>', '', snippet).strip()
        if title_clean:
            results.append({"title": title_clean, "snippet": snippet_clean, "url": url, "source": "web"})
    return results


def _search_google_news_rss(query: str, max_results: int = 8) -> list[dict]:
    """使用 Google News RSS 搜索新闻。"""
    encoded_query = urllib.parse.quote(query + " 财经")
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"

    # 尝试 feedparser
    try:
        import feedparser
        feed = feedparser.parse(rss_url)
        if feed.entries:
            results = []
            for entry in feed.entries[:max_results]:
                results.append({
                    "title": entry.get("title", ""),
                    "snippet": entry.get("summary", ""),
                    "url": entry.get("link", ""),
                    "source": "news",
                })
            if results:
                return results
    except ImportError:
        pass
    except Exception:
        pass

    # 降级：urllib + xml.etree.ElementTree 解析 RSS
    try:
        import xml.etree.ElementTree as ET
        req = urllib.request.Request(rss_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read().decode("utf-8", errors="replace")
        root = ET.fromstring(xml_data)
        channel = root.find("channel")
        if channel is None:
            return []
        results = []
        for item in channel.findall("item")[:max_results]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            description = item.findtext("description", "")
            if title:
                results.append({
                    "title": title,
                    "snippet": description or "",
                    "url": link or "",
                    "source": "news",
                })
        return results
    except Exception:
        return []


def _fetch_weibo_hot() -> list[dict]:
    """从微博热搜 API 抓取实时热门话题。"""
    try:
        req = urllib.request.Request(
            "https://weibo.com/ajax/side/hotSearch",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://weibo.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        results = []
        realtime = data.get("data", {}).get("realtime", [])
        for item in realtime[:20]:
            word = item.get("word", "")
            if word:
                item_url = item.get("word_scheme", "")
                if not item_url:
                    item_url = "https://s.weibo.com/weibo?q=" + urllib.parse.quote(word)
                results.append({
                    "title": word,
                    "snippet": f"微博热搜 - 热度: {item.get('raw_hot', 'N/A')}",
                    "url": item_url,
                    "source": "weibo",
                })
        logger.info(f"微博热搜抓取成功，共 {len(results)} 条")
        return results
    except Exception as e:
        logger.warning(f"微博热搜抓取失败: {e}")
        return []


def _sample_news(query: str) -> list[dict]:
    """示例新闻数据（当真实搜索不可用时降级使用）。

    使用相对于当前日期的动态偏移，分散在 7 天内确保 3 日窗口不会互相污染：
      day-7 ~ day-5: 利好密集，策略正常买入
      day-3 ~ day-2: 利空初现，买入暂停
      day-1 ~ today: 强利空爆发(sentiment < -3)，触发极端利空强制平仓

    URL 使用 Google News RSS 搜索链接，点击可查看相关新闻。
    """
    def _search_url(title: str) -> str:
        return "https://news.google.com/rss/search?q=" + urllib.parse.quote(title) + "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"

    now = datetime.now()
    d7 = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    d6 = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    d5 = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    d3 = (now - timedelta(days=3)).strftime("%Y-%m-%d")
    d2 = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    d1 = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    d0 = now.strftime("%Y-%m-%d")

    return [
        # ---- day-7 ~ day-5: 纯利好 ----
        {"title": f"机构看好{query}赛道：行业景气度持续提升", "snippet": f"日期: {d7} 多家券商发布{query}行业研报，评级上调至增持。", "url": _search_url(f"机构看好{query} 行业景气度"), "source": "sample-bull"},
        {"title": f"{query}龙头业绩超预期，盈利大幅增长", "snippet": f"日期: {d7} {query}龙头公布季报，净利润同比增长45%，远超预期。", "url": _search_url(f"{query} 龙头 业绩 超预期"), "source": "sample-bull"},
        {"title": f"{query}板块利好出台，多只个股涨停创新高", "snippet": f"日期: {d6} {query}板块受政策利好带动，多只成分股涨停，板块指数创年内新高。", "url": _search_url(f"{query} 板块 利好 涨停"), "source": "sample-bull"},
        {"title": f"北向资金大幅流入{query}板块，主力加仓信号", "snippet": f"日期: {d6} 北向资金今日净流入{query}板块超50亿，市场看多情绪浓厚。", "url": _search_url(f"北向资金 {query} 主力加仓"), "source": "sample-bull"},
        {"title": f"政策扶持{query}产业，减税降费利好板块", "snippet": f"日期: {d5} 国务院发布产业扶持政策，{query}行业迎来实质性利好。", "url": _search_url(f"政策扶持{query} 减税降费"), "source": "sample-bull"},
        {"title": f"{query}签下重大海外订单，国际业务突破", "snippet": f"日期: {d5} {query}头部企业宣布与海外客户签订十年合作协议，出海战略加速落地。", "url": _search_url(f"{query} 海外订单 国际业务"), "source": "sample-bull"},
        # ---- day-3 ~ day-2: 利空开始浮现 ----
        {"title": f"监管层关注{query}领域风险——短期利空需警惕", "snippet": f"日期: {d3} 监管部门就{query}行业发布风险提示函，涉及合规和数据安全问题。", "url": _search_url(f"监管 {query} 风险提示"), "source": "sample-bear"},
        {"title": f"国际制裁波及{query}产业链，核心零部件面临断供风险", "snippet": f"日期: {d2} 新一轮制裁名单涵盖{query}上游供应链，多家企业面临关键零部件断供危机。", "url": _search_url(f"{query} 制裁 断供"), "source": "sample-bear"},
        # ---- day-1 ~ today: 强利空爆发 ----
        {"title": f"突发：{query}龙头遭监管立案调查，股价暴跌触发熔断", "snippet": f"日期: {d1} 监管机构宣布对{query}龙头企业进行立案调查，涉嫌信息披露违规和内幕交易。", "url": _search_url(f"{query} 监管 立案调查 暴跌"), "source": "sample-strong-bear"},
        {"title": f"{query}行业裁员潮蔓延，多家头部企业宣布大规模优化", "snippet": f"日期: {d1} 多家{query}企业发布裁员公告，市场对行业景气度前景表示担忧。", "url": _search_url(f"{query} 裁员"), "source": "sample-strong-bear"},
        {"title": f"{query}行业评级遭集体下调，多家机构看空后市", "snippet": f"日期: {d0} 受监管和供应链双重压力，多家券商下调{query}板块评级至减持。", "url": _search_url(f"{query} 评级下调 看空"), "source": "sample-strong-bear"},
    ]


def fetch_news(query: str, max_results: int = 6) -> list[dict]:
    """
    获取与 query 相关的最新财经新闻。

    返回: [{"title": "...", "snippet": "...", "url": "...", "source": "..."}, ...]
    """
    # 尝试 DuckDuckGo
    results = _search_duckduckgo(query, max_results)
    if results:
        return results

    # 尝试 Google News RSS
    results = _search_google_news_rss(query, max_results)
    if results:
        return results

    # 尝试微博热搜
    results = _fetch_weibo_hot()
    if results:
        return results[:max_results]

    # 降级：使用示例数据
    return _sample_news(query)
