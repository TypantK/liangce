# -*- coding: utf-8 -*-
"""
多通道新闻搜索获取器 — 用于情绪分析模块

设计原则（解决「情绪事件与板块无关 / 交易被锁死」两类 bug）：
  1. 来源质量优先：akshare 东方财富个股新闻（国内直连、按股票代码强相关）放最前；
     全站热帖/热搜榜与具体板块无关，已不再作为板块相关性来源。
  2. 外网通道（DuckDuckGo / Google News）需代理，作为降级；全部失败再兜底示例数据。
  3. 相关性过滤：必须命中 query 或多财经关键词组合，避免「股/盘」单字噪声污染。
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
    """检查新闻是否与财经/投资/标的物相关。

    规则（避免「有情绪事件就乱关联板块」的错配）：
      1) 若提供了 query（标的/板块名），文本需直接包含 query 关键词；
      2) 否则需至少命中 2 个财经关键词（排除仅含「股/盘」等泛字的噪声）。
    """
    text = f"{title} {snippet}"
    low = text.lower()

    if query and len(query) >= 2:
        if query.lower() in low:
            return True

    hit = 0
    for kw in _FINANCE_KEYWORDS:
        if kw in low:
            hit += 1
            if hit >= 2:
                return True
    return False

# ---- 通用请求工具 ----

_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

_CHANNEL_TIMEOUT = 8
_FETCH_TIMEOUT = 15


def _http_get(url: str, headers: dict = None, timeout: int = _CHANNEL_TIMEOUT) -> str:
    if headers is None:
        headers = {"User-Agent": _USER_AGENT}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ===================================================================
# Channel 0: akshare 东方财富个股/板块新闻（国内直连，强相关，优先）
# ===================================================================

def _fetch_akshare_news(symbol: str, max_results: int = 8) -> list:
    """使用 akshare 东方财富接口抓取与具体标的强相关的新闻。
    - 个股 (.SZ/.SH/纯数字代码)：stock_news_em(code) 返回该股票专属新闻，强相关。
    - 板块/美股/加密货币：东方财富无对应接口，降级用百度宏观财经新闻做弱补充。
    """
    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare 未安装，跳过 akshare 新闻通道")
        return []

    results = []
    try:
        code = None
        if symbol.endswith(".SZ") or symbol.endswith(".SH"):
            # 只去掉交易所后缀，保留纯数字代码（'600519.SH' -> '600519'）
            code = symbol.split(".", 1)[0]
        elif symbol.isdigit():
            code = symbol
        if code:
            # 个股：东方财富个股新闻（强相关）。失败时重试一次（akshare 首次偶发空）。
            df = ak.stock_news_em(symbol=code)
            if df is None or len(df) == 0:
                try:
                    df = ak.stock_news_em(symbol=code)
                except Exception:
                    df = None
            if df is not None:
                for _, row in df.iterrows():
                    title = str(row.get("新闻标题", "") or "").strip()
                    content = str(row.get("新闻内容", "") or "").strip()
                    pub = str(row.get("发布时间", "") or "").strip()
                    src = str(row.get("文章来源", "") or "东方财富").strip()
                    url = str(row.get("新闻链接", "") or "").strip()
                    if not title:
                        continue
                    results.append({
                        "title": title,
                        "snippet": content[:200] if content else title,
                        "url": url,
                        "source": f"eastmoney/{src}",
                        "date": pub[:10] if len(pub) >= 10 else "",
                    })
            if results:
                logger.info(f"akshare 个股新闻抓取成功 {symbol}，共 {len(results)} 条")
                return results[:max_results]
            # 个股无新闻：直接返回空，交由雪球搜索/web 通道或示例数据，
            # 不再坠入「百度宏观」(包含其它股票新闻，与标的无关，会造成错配)。
            logger.info(f"akshare 个股新闻为空 {symbol}，交后续通道")
            return []
    except Exception as e:
        logger.warning(f"akshare 个股新闻失败({symbol}): {e}")

    # 板块/美股/加密货币：东方财富无对应接口，用百度宏观财经新闻做弱补充。
    try:
        df = ak.news_economic_baidu()
        for _, row in df.iterrows():
            title = str(row.get("新闻标题", "") or "").strip()
            content = str(row.get("新闻内容", "") or "").strip()
            if not title:
                continue
            results.append({
                "title": title,
                "snippet": content[:200] if content else title,
                "url": str(row.get("新闻链接", "") or "").strip(),
                "source": "baidu_econ",
                "date": "",
            })
        if results:
            logger.info(f"akshare 宏观新闻补充 {symbol}，共 {len(results)} 条")
            return results[:max_results]
    except Exception as e:
        logger.warning(f"akshare 宏观新闻失败({symbol}): {e}")

    return []


# ===================================================================
# Channel 1: 雪球（仅按代码搜索个股，不再返回全站热帖）
# ===================================================================

_XUEQIU_SEARCH_URL = "https://xueqiu.com/stock/search.json"
_XUEQIU_HOME_URL = "https://xueqiu.com"


def _fetch_xueqiu_search_only(query: str, max_results: int = 8) -> list:
    """仅用雪球「按代码搜索个股」接口，返回与 query 相关的个股结果。
    不再返回全站热门帖子（全站热帖与具体板块/标的无关，会造成情绪事件错配）。"""
    try:
        import re as _re
        cookie_req = urllib.request.Request(_XUEQIU_HOME_URL, headers={
            "User-Agent": _USER_AGENT,
        })
        with urllib.request.urlopen(cookie_req, timeout=6) as resp:
            headers = dict(resp.headers)
        cookies = headers.get("Set-Cookie", "")
        token_match = _re.search(r"xq_a_token=([^;]+)", cookies)
        xq_token = token_match.group(1) if token_match else ""

        results = []
        if not query:
            return results

        search_params = urllib.parse.urlencode({"code": query, "size": str(max_results)})
        search_url = f"{_XUEQIU_SEARCH_URL}?{search_params}"
        search_headers = {"User-Agent": _USER_AGENT, "Referer": _XUEQIU_HOME_URL}
        if xq_token:
            search_headers["Cookie"] = f"xq_a_token={xq_token}"
        search_req = urllib.request.Request(search_url, headers=search_headers)
        with urllib.request.urlopen(search_req, timeout=_CHANNEL_TIMEOUT) as resp:
            search_data = json.loads(resp.read().decode("utf-8", errors="replace"))
        stocks = search_data.get("stocks", []) if isinstance(search_data, dict) else []
        for stock in stocks[:max_results]:
            name = stock.get("name", "")
            code = stock.get("code", "")
            if name:
                results.append({
                    "title": f"{name}({code}) 雪球个股",
                    "snippet": f"雪球搜索匹配: {name}",
                    "url": f"https://xueqiu.com/S/{code}" if code else "",
                    "source": "xueqiu-search",
                })
        if results:
            logger.info(f"雪球搜索成功 {query}，共 {len(results)} 条")
        return results
    except Exception as e:
        logger.warning(f"雪球搜索失败({query}): {e}")
        return []


# ===================================================================
# Channel 2: DuckDuckGo HTML 搜索（需代理，外网降级）
# ===================================================================

def _search_duckduckgo(query: str, max_results: int = 8) -> list:
    import re
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query + " 财经 新闻"})
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
# Channel 3: Google News RSS（需代理，外网降级）
# ===================================================================

def _search_google_news_rss(query: str, max_results: int = 8) -> list:
    encoded_query = urllib.parse.quote(query + " 财经")
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"

    try:
        import feedparser
        feed = feedparser.parse(rss_url)
        if feed.entries:
            results = []
            for entry in feed.entries[:max_results]:
                results.append({"title": entry.get("title", ""), "snippet": entry.get("summary", ""), "url": entry.get("link", ""), "source": "news"})
            if results:
                return results
    except ImportError:
        pass
    except Exception:
        pass

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
                results.append({"title": title, "snippet": description or "", "url": link or "", "source": "news"})
        return results
    except Exception:
        return []


# ===================================================================
# Channel 4: 示例数据（最终降级，仅离线演示用）
# ===================================================================

def _sample_news(query: str) -> list:
    now = datetime.now()
    d7 = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    d6 = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    d5 = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    d3 = (now - timedelta(days=3)).strftime("%Y-%m-%d")
    d2 = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    d1 = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    d0 = now.strftime("%Y-%m-%d")

    return [
        {"title": f"机构看好{query}赛道：行业景气度持续提升", "snippet": f"日期: {d7} 多家券商发布{query}行业研报，评级上调至增持。", "url": "", "source": "sample-bull"},
        {"title": f"{query}龙头业绩超预期，盈利大幅增长", "snippet": f"日期: {d7} {query}龙头公布季报，净利润同比增长45%，远超预期。", "url": "", "source": "sample-bull"},
        {"title": f"{query}板块利好出台，多只个股涨停创新高", "snippet": f"日期: {d6} {query}板块受政策利好带动，多只成分股涨停，板块指数创年内新高。", "url": "", "source": "sample-bull"},
        {"title": f"北向资金大幅流入{query}板块，主力加仓信号", "snippet": f"日期: {d6} 北向资金今日净流入{query}板块超50亿，市场看多情绪浓厚。", "url": "", "source": "sample-bull"},
        {"title": f"政策扶持{query}产业，减税降费利好板块", "snippet": f"日期: {d5} 国务院发布产业扶持政策，{query}行业迎来实质性利好。", "url": "", "source": "sample-bull"},
        {"title": f"{query}签下重大海外订单，国际业务突破", "snippet": f"日期: {d5} {query}头部企业宣布与海外客户签订十年合作协议，出海战略加速落地。", "url": "", "source": "sample-bull"},
        {"title": f"监管层关注{query}领域风险——短期利空需警惕", "snippet": f"日期: {d3} 监管部门就{query}行业发布风险提示函，涉及合规和数据安全问题。", "url": "", "source": "sample-bear"},
        {"title": f"国际制裁波及{query}产业链，核心零部件面临断供风险", "snippet": f"日期: {d2} 新一轮制裁名单涵盖{query}上游供应链，多家企业面临关键零部件断供危机。", "url": "", "source": "sample-bear"},
        {"title": f"突发：{query}龙头遭监管立案调查，股价暴跌触发熔断", "snippet": f"日期: {d1} 监管机构宣布对{query}龙头企业进行立案调查，涉嫌信息披露违规和内幕交易。", "url": "", "source": "sample-strong-bear"},
        {"title": f"{query}行业裁员潮蔓延，多家头部企业宣布大规模优化", "snippet": f"日期: {d1} 多家{query}企业发布裁员公告，市场对行业景气度前景表示担忧。", "url": "", "source": "sample-strong-bear"},
        {"title": f"{query}行业评级遭集体下调，多家机构看空后市", "snippet": f"日期: {d0} 受监管和供应链双重压力，多家券商下调{query}板块评级至减持。", "url": "", "source": "sample-strong-bear"},
    ]


# ===================================================================
# 主入口: 多通道抓取（akshare 优先，web 通道降级）
# ===================================================================

def fetch_news(query: str, max_results: int = 6) -> list:
    """抓取与 query（标的代码/板块名/个股名）相关的财经新闻。

    通道优先级（国内网络最稳的放最前）:
        1. akshare 东方财富个股新闻（强相关）/ 百度宏观新闻（弱补充）
        2. 雪球按代码搜索（个股相关，不走全站热帖）
        3. DuckDuckGo / Google News（外网，需代理）
        4. 示例数据（兜底，仅离线演示用）

    返回: [{"title","snippet","url","source","date", ...}, ...]
    """
    try:
        ak_res = _fetch_akshare_news(query, max_results)
        if ak_res:
            return ak_res[:max_results]
    except Exception as e:
        logger.warning(f"akshare 通道异常: {e}")

    try:
        xq = _fetch_xueqiu_search_only(query, max_results)
        if xq:
            return xq[:max_results]
    except Exception as e:
        logger.warning(f"雪球搜索通道异常: {e}")

    web_channels = [
        ("duckduckgo", lambda: _search_duckduckgo(query, max_results)),
        ("google_news", lambda: _search_google_news_rss(query, max_results)),
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_map = {executor.submit(fn): name for name, fn in web_channels}
        for future in as_completed(future_map, timeout=_FETCH_TIMEOUT):
            name = future_map[future]
            try:
                results = future.result(timeout=_CHANNEL_TIMEOUT)
                if results:
                    logger.info(f"web 通道 {name} 返回 {len(results)} 条")
                    return results[:max_results]
            except Exception as e:
                logger.warning(f"web 通道 {name} 失败: {e}")

    logger.warning("所有通道均失败，降级到示例数据")
    results = _sample_news(query)
    if query:
        results = [r for r in results if _is_finance_relevant(r.get("title", ""), r.get("snippet", ""), query)]
    return results[:max_results]


# ===================================================================
# 通道诊断
# ===================================================================

def diagnose_channels() -> dict:
    import time
    results = {}
    try:
        import akshare as ak
        results["akshare"] = "ok (installed)"
    except Exception as e:
        results["akshare"] = f"unavailable: {e}"

    try:
        start = time.time()
        req = urllib.request.Request(_XUEQIU_SEARCH_URL + "?" + urllib.parse.urlencode({"code": "600519", "size": "1"}), headers={"User-Agent": _USER_AGENT, "Referer": _XUEQIU_HOME_URL})
        with urllib.request.urlopen(req, timeout=4) as resp:
            resp.read()
        results["xueqiu"] = f"ok ({(time.time()-start)*1000:.0f}ms)"
    except Exception as e:
        results["xueqiu"] = f"error: {e}"

    try:
        start = time.time()
        _http_get("https://html.duckduckgo.com/html/", timeout=4)
        results["duckduckgo"] = f"ok ({(time.time()-start)*1000:.0f}ms)"
    except Exception as e:
        results["duckduckgo"] = f"error: {e}"

    try:
        start = time.time()
        _http_get("https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans", timeout=4)
        results["google_news"] = f"ok ({(time.time()-start)*1000:.0f}ms)"
    except Exception as e:
        results["google_news"] = f"error: {e}"

    results["sample"] = "ok (always available)"
    return results
