# -*- coding: utf-8 -*-
"""
多通道新闻搜索获取器 — 用于情绪分析模块

架构参照 Agent-Reach：每个平台独立 channel，并行抓取，按序降级。
当前通道（按优先级）：雪球 → 微博热搜 → DuckDuckGo → Google News RSS → 示例数据
"""

import json
import urllib.request
import urllib.parse
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

logger = logging.getLogger(__name__)

# ---- 相关性过滤 ----
_FINANCE_KEYWORDS = [
    "股", "基金", "涨", "跌", "市", "盘", "指", "板", "块",
    "利", "资", "金", "财", "经", "投", "融", "券", "商",
    "银", "债", "汇", "率", "税", "红", "息", "盈", "亏",
    "牛", "熊", "监", "管", "策", "改", "裁", "并", "购",
    "业", "绩", "报", "发", "公", "告", "披", "露", "创",
    "IPO", "ETF", "QDII", "LOF", "A股", "港股", "美股",
    "加息", "降息", "通胀", "CPI", "PPI", "GDP",
]


def _is_finance_relevant(title: str, snippet: str = "", query: str = "") -> bool:
    """检查新闻是否与财经/投资/标的物相关。"""
    text = f"{title} {snippet}"
    # 1. 匹配 query 关键词（至少 2 字才匹配）
    if query and len(query) >= 2:
        if query.lower() in text.lower():
            return True
    # 2. 匹配财经关键词
    for kw in _FINANCE_KEYWORDS:
        if kw in text:
            return True
    return False

# ---- 通用请求工具 ----

_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

_CHANNEL_TIMEOUT = 8  # 单通道超时（秒）
_FETCH_TIMEOUT = 15   # 整体抓取超时（秒）


def _http_get(url: str, headers: dict = None, timeout: int = _CHANNEL_TIMEOUT) -> str:
    """发起 HTTP GET 请求，返回响应体文本。失败抛异常。"""
    if headers is None:
        headers = {"User-Agent": _USER_AGENT}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ===================================================================
# Channel 1: 雪球 (Xueqiu) — 零配置，财经社区热议帖
# ===================================================================

_XUEQIU_HOT_URL = "https://xueqiu.com/statuses/hot/listV2.json"
_XUEQIU_SEARCH_URL = "https://xueqiu.com/stock/search.json"
_XUEQIU_HOME_URL = "https://xueqiu.com"


def _fetch_xueqiu(query: str, max_results: int = 8) -> list[dict]:
    """
    从雪球抓取热门帖子和搜索匹配帖。

    先请求首页获取 Cookie，再请求热帖接口和搜索接口。
    """
    try:
        # 第一步：获取 Cookie
        cookie_req = urllib.request.Request(_XUEQIU_HOME_URL, headers={
            "User-Agent": _USER_AGENT,
        })
        with urllib.request.urlopen(cookie_req, timeout=6) as resp:
            headers = dict(resp.headers)
        cookies = headers.get("Set-Cookie", "")
        # 提取 xq_a_token 等核心 cookie
        import re as _re
        token_match = _re.search(r"xq_a_token=([^;]+)", cookies)
        xq_token = token_match.group(1) if token_match else ""

        results = []

        # 第二步：获取热门帖子
        hot_headers = {
            "User-Agent": _USER_AGENT,
            "Referer": _XUEQIU_HOME_URL,
        }
        if xq_token:
            hot_headers["Cookie"] = f"xq_a_token={xq_token}"

        hot_req = urllib.request.Request(_XUEQIU_HOT_URL, headers=hot_headers)
        with urllib.request.urlopen(hot_req, timeout=_CHANNEL_TIMEOUT) as resp:
            hot_data = json.loads(resp.read().decode("utf-8", errors="replace"))

        hot_items = hot_data.get("items", []) if isinstance(hot_data, dict) else []
        for item in hot_items[:max_results]:
            title = (item.get("title") or item.get("text") or item.get("description", "")).strip()
            if title and len(title) > 2:
                # 过滤纯 HTML
                title = _re.sub(r"<[^>]+>", "", title)
                item_id = item.get("id", "")
                url = f"https://xueqiu.com{item_id}" if item_id else ""
                results.append({
                    "title": title,
                    "snippet": f"雪球热议 - 回复:{item.get('reply_count', 0)} 转发:{item.get('retweet_count', 0)}",
                    "url": url,
                    "source": "xueqiu",
                })

        # 第三步：关键词搜索
        if query:
            search_params = urllib.parse.urlencode({
                "code": query,
                "size": str(max_results),
            })
            search_url = f"{_XUEQIU_SEARCH_URL}?{search_params}"
            search_headers = {
                "User-Agent": _USER_AGENT,
                "Referer": _XUEQIU_HOME_URL,
            }
            if xq_token:
                search_headers["Cookie"] = f"xq_a_token={xq_token}"
            search_req = urllib.request.Request(search_url, headers=search_headers)
            try:
                with urllib.request.urlopen(search_req, timeout=_CHANNEL_TIMEOUT) as resp:
                    search_data = json.loads(resp.read().decode("utf-8", errors="replace"))
                stocks = search_data.get("stocks", []) if isinstance(search_data, dict) else []
                for stock in stocks[:max_results]:
                    name = stock.get("name", "")
                    code = stock.get("code", "")
                    if name:
                        results.append({
                            "title": f"{name}({code}) 雪球股票",
                            "snippet": f"雪球搜索匹配: {name}",
                            "url": f"https://xueqiu.com/S/{code}" if code else "",
                            "source": "xueqiu-search",
                        })
            except Exception:
                pass  # 搜索失败不影响热帖结果

        if results:
            logger.info(f"雪球抓取成功，共 {len(results)} 条")
        return results

    except Exception as e:
        logger.warning(f"雪球抓取失败: {e}")
        return []


# ===================================================================
# Channel 2: 微博热搜 (Weibo)
# ===================================================================

def _fetch_weibo_hot() -> list[dict]:
    """从微博热搜 API 抓取实时热门话题。"""
    try:
        req = urllib.request.Request(
            "https://weibo.com/ajax/side/hotSearch",
            headers={
                "User-Agent": _USER_AGENT,
                "Referer": "https://weibo.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=_CHANNEL_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        results = []
        realtime = data.get("data", {}).get("realtime", [])
        for item in realtime[:25]:
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


# ===================================================================
# Channel 3: DuckDuckGo HTML 搜索
# ===================================================================

def _search_duckduckgo(query: str, max_results: int = 8) -> list[dict]:
    """使用 DuckDuckGo HTML 搜索获取结果。"""
    import re
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({
        "q": query + " 财经 新闻",
    })
    try:
        html = _http_get(url)
    except Exception as e:
        logger.warning(f"DuckDuckGo 搜索请求失败: {e}")
        return []

    results = []
    items = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL | re.IGNORECASE
    )
    if not items:
        logger.warning(f"DuckDuckGo HTML 解析未匹配到结果项(query={query})")
    for url_match, title, snippet in items[:max_results]:
        title_clean = re.sub(r'<[^>]+>', '', title).strip()
        snippet_clean = re.sub(r'<[^>]+>', '', snippet).strip()
        if title_clean:
            results.append({"title": title_clean, "snippet": snippet_clean, "url": url_match, "source": "web"})
    return results


# ===================================================================
# Channel 4: Google News RSS
# ===================================================================

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

    # 降级：手动解析 RSS XML
    try:
        import xml.etree.ElementTree as ET
        xml_data = _http_get(rss_url, timeout=10)
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


# ===================================================================
# Channel 5: 示例数据（最终降级）
# ===================================================================

def _sample_news(query: str) -> list[dict]:
    """示例新闻数据（当所有真实通道不可用时降级使用）。

    使用相对于当前日期的动态偏移，分散在 7 天内确保 3 日窗口不会互相污染：
      day-7 ~ day-5: 利好密集，策略正常买入
      day-3 ~ day-2: 利空初现，买入暂停
      day-1 ~ today: 强利空爆发(sentiment < -3)，触发极端利空强制平仓
    """
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
        {"title": f"机构看好{query}赛道：行业景气度持续提升", "snippet": f"日期: {d7} 多家券商发布{query}行业研报，评级上调至增持。", "url": "", "source": "sample-bull"},
        {"title": f"{query}龙头业绩超预期，盈利大幅增长", "snippet": f"日期: {d7} {query}龙头公布季报，净利润同比增长45%，远超预期。", "url": "", "source": "sample-bull"},
        {"title": f"{query}板块利好出台，多只个股涨停创新高", "snippet": f"日期: {d6} {query}板块受政策利好带动，多只成分股涨停，板块指数创年内新高。", "url": "", "source": "sample-bull"},
        {"title": f"北向资金大幅流入{query}板块，主力加仓信号", "snippet": f"日期: {d6} 北向资金今日净流入{query}板块超50亿，市场看多情绪浓厚。", "url": "", "source": "sample-bull"},
        {"title": f"政策扶持{query}产业，减税降费利好板块", "snippet": f"日期: {d5} 国务院发布产业扶持政策，{query}行业迎来实质性利好。", "url": "", "source": "sample-bull"},
        {"title": f"{query}签下重大海外订单，国际业务突破", "snippet": f"日期: {d5} {query}头部企业宣布与海外客户签订十年合作协议，出海战略加速落地。", "url": "", "source": "sample-bull"},
        # ---- day-3 ~ day-2: 利空开始浮现 ----
        {"title": f"监管层关注{query}领域风险——短期利空需警惕", "snippet": f"日期: {d3} 监管部门就{query}行业发布风险提示函，涉及合规和数据安全问题。", "url": "", "source": "sample-bear"},
        {"title": f"国际制裁波及{query}产业链，核心零部件面临断供风险", "snippet": f"日期: {d2} 新一轮制裁名单涵盖{query}上游供应链，多家企业面临关键零部件断供危机。", "url": "", "source": "sample-bear"},
        # ---- day-1 ~ today: 强利空爆发 ----
        {"title": f"突发：{query}龙头遭监管立案调查，股价暴跌触发熔断", "snippet": f"日期: {d1} 监管机构宣布对{query}龙头企业进行立案调查，涉嫌信息披露违规和内幕交易。", "url": "", "source": "sample-strong-bear"},
        {"title": f"{query}行业裁员潮蔓延，多家头部企业宣布大规模优化", "snippet": f"日期: {d1} 多家{query}企业发布裁员公告，市场对行业景气度前景表示担忧。", "url": "", "source": "sample-strong-bear"},
        {"title": f"{query}行业评级遭集体下调，多家机构看空后市", "snippet": f"日期: {d0} 受监管和供应链双重压力，多家券商下调{query}板块评级至减持。", "url": "", "source": "sample-strong-bear"},
    ]


# ===================================================================
# 通道诊断: 检测各通道可用性
# ===================================================================

def diagnose_channels() -> dict[str, str]:
    """
    检测各通道当前状态，返回 {通道名: 状态} 字典。
    状态值: "ok" / "timeout" / "error:xxx" / "unavailable"
    参照 agent-reach doctor 命令。
    """
    import time

    results = {}

    # 测试雪球 (快速 ping)
    try:
        start = time.time()
        req = urllib.request.Request(_XUEQIU_HOME_URL, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=4) as resp:
            resp.read()
        elapsed = (time.time() - start) * 1000
        results["xueqiu"] = f"ok ({elapsed:.0f}ms)"
    except Exception as e:
        results["xueqiu"] = f"error: {e}"

    # 测试微博
    try:
        start = time.time()
        req = urllib.request.Request(
            "https://weibo.com/ajax/side/hotSearch",
            headers={"User-Agent": _USER_AGENT, "Referer": "https://weibo.com/"},
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            json.loads(resp.read().decode("utf-8", errors="replace"))
        elapsed = (time.time() - start) * 1000
        results["weibo"] = f"ok ({elapsed:.0f}ms)"
    except Exception as e:
        results["weibo"] = f"error: {e}"

    # 测试 DuckDuckGo
    try:
        start = time.time()
        _http_get("https://html.duckduckgo.com/html/", timeout=4)
        elapsed = (time.time() - start) * 1000
        results["duckduckgo"] = f"ok ({elapsed:.0f}ms)"
    except Exception as e:
        results["duckduckgo"] = f"error: {e}"

    # 测试 Google News RSS
    try:
        start = time.time()
        _http_get("https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans", timeout=4)
        elapsed = (time.time() - start) * 1000
        results["google_news"] = f"ok ({elapsed:.0f}ms)"
    except Exception as e:
        results["google_news"] = f"error: {e}"

    results["sample"] = "ok (always available)"

    return results


# ===================================================================
# 主入口: 并行多通道抓取
# ===================================================================

def fetch_news(query: str, max_results: int = 6) -> list[dict]:
    """
    并行从多通道抓取与 query 相关的财经新闻。

    通道优先级: 雪球 > 微博热搜 > DuckDuckGo > Google News RSS > 示例数据
    并行执行前 4 个通道，首个有结果即返回；全部失败则降级到示例数据。

    返回: [{"title": "...", "snippet": "...", "url": "...", "source": "..."}, ...]
    """
    # 定义通道及其执行函数
    channels = [
        ("xueqiu",       lambda: _fetch_xueqiu(query, max_results)),
        ("weibo",        _fetch_weibo_hot),
        ("duckduckgo",   lambda: _search_duckduckgo(query, max_results)),
        ("google_news",  lambda: _search_google_news_rss(query, max_results)),
    ]

    # 并行执行所有通道
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {
            executor.submit(fn): name
            for name, fn in channels
        }

        # 收集结果：通道级超时约束
        for future in as_completed(future_map, timeout=_FETCH_TIMEOUT):
            name = future_map[future]
            try:
                results = future.result(timeout=_CHANNEL_TIMEOUT)
                if results:
                    logger.info(f"多通道抓取: {name} 返回 {len(results)} 条结果")
                    return results[:max_results]
                else:
                    logger.info(f"多通道抓取: {name} 无结果")
            except TimeoutError:
                logger.warning(f"多通道抓取: {name} 超时")
            except Exception as e:
                logger.warning(f"多通道抓取: {name} 失败: {e}")

    # 全部失败 → 降级到示例数据
    logger.warning("所有通道均失败，降级到示例数据")
    results = _sample_news(query)
    # 相关性过滤：只保留财经相关的新闻
    if query:
        results = [r for r in results if _is_finance_relevant(
            r.get("title", ""), r.get("snippet", ""), query)]
    return results[:max_results]
