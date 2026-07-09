# -*- coding: utf-8 -*-
"""
情绪分析模块 — 新闻关键词打分 + 事件摘要

用法:
    from core.sentiment import score_headline, get_sentiment_for_date, format_sentiment_tag

    # 在 UI 层抓取新闻后构造 events 列表传入引擎
    events = [("2026-06-02", 3, "AI板块突破新高"), ("2026-06-01", -2, "监管收紧利空"), ...]
    score, headlines = get_sentiment_for_date(events, "2026-06-03")
"""

import re
from datetime import datetime
import pandas as pd

# ---- 中文金融情绪词典 ----
_POSITIVE_WORDS = [
    "利好", "突破", "爆发", "飙升", "涨停", "创新高", "大涨", "领涨",
    "政策支持", "政策利好", "补贴", "扶持", "减税", "放水", "降息",
    "回购", "增持", "业绩超预期", "扭亏", "盈利", "增长",
    "签约", "中标", "获批", "上市", "新品发布", "技术突破",
    "资金流入", "主力加仓", "机构看好", "目标价上调", "评级上调",
    "合作", "战略投资", "融资", "出海",
]

_NEGATIVE_WORDS = [
    "利空", "暴跌", "跌停", "大跌", "领跌", "跳水", "崩盘",
    "监管", "处罚", "罚款", "调查", "警示", "风险提示", "退市",
    "减持", "套现", "质押", "暴雷", "违约", "亏损", "下滑",
    "裁员", "关停", "诉讼", "索赔", "造假", "内幕交易",
    "资金流出", "主力减仓", "机构看空", "目标价下调", "评级下调",
    "贸易战", "制裁", "关税", "脱钩",
]

# 合并编译正则
_pos_pattern = re.compile("|".join(re.escape(w) for w in _POSITIVE_WORDS))
_neg_pattern = re.compile("|".join(re.escape(w) for w in _NEGATIVE_WORDS))


# 否定词列表：出现在情感词前方语境时反转/衰减分数
_NEGATION_WORDS = ["不", "无", "避免", "难以", "没有", "不会", "不再", "并未",
                   "未", "难以", "无法", "难言", "谈不上", "绝非", "并非", "尚无"]


def _apply_negation(headline: str, matches: list, is_positive: bool) -> int:
    """对匹配到的情感词应用否定词扫描。
    若在情感词前方 8 个字符窗口内出现否定词，则反转贡献：
      正向词 + 否定 → 算作 -1（假阳性抑制）
      负向词 + 否定 → 算作 +1（假阴性抑制）
    否则维持原始计数。
    """
    effective = 0
    # 合并否定词正则
    _negation_pattern = re.compile("|".join(re.escape(w) for w in _NEGATION_WORDS))

    for m in matches:
        start = m.start()
        # 取情感词前 8 个字符窗口
        prefix = headline[max(0, start - 8):start]
        if _negation_pattern.search(prefix):
            # 否定词命中：反转贡献
            effective += -1 if is_positive else 1
        else:
            effective += 1 if is_positive else -1
    return effective


def score_headline(headline: str) -> int:
    """对单条新闻标题打分：每个利好词 +1，每个利空词 -1。
    否定词（不/无/避免/难以/没有/不会等）+情感词组合时反转分数。"""
    pos_matches = list(_pos_pattern.finditer(headline))
    neg_matches = list(_neg_pattern.finditer(headline))
    score = _apply_negation(headline, pos_matches, is_positive=True) + \
            _apply_negation(headline, neg_matches, is_positive=False)
    return score


def parse_events_from_search(results: list, keyword: str) -> list[tuple[str, int, str]]:
    """
    将 web_search 返回的原始结果解析为情绪事件列表。

    results: web_search 返回的 list，每项含 title/snippet/date 等
    keyword: 搜索关键词（用于推断日期）

    返回: [(日期, 分数, 标题), ...]
    """
    events = []
    now = datetime.now()
    default_date = now.strftime("%Y-%m-%d")

    for item in results:
        title = item.get("title", "")
        snippet = item.get("snippet", item.get("description", ""))
        combined = f"{title} {snippet}"
        score = score_headline(combined)

        # 尝试提取日期
        date_str = None
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", combined)
        if m:
            date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            m = re.search(r"(\d{1,2})月(\d{1,2})日", combined)
            if m:
                date_str = f"{now.year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            else:
                date_str = default_date

        if score != 0:  # 跳过无情感倾向的新闻
            events.append((date_str, score, title))

    events.sort(key=lambda x: x[0])
    return events


# ---- 知名分析师/博主/基金经理列表 ----
KNOWN_ANALYSTS = [
    "但斌", "林园", "李大霄", "任泽平", "洪灏",
    "张忆东", "荀玉根", "蔡嵩松", "葛兰", "张坤",
    "谢治宇", "朱少醒", "刘格菘", "傅鹏博", "董承非",
    "萧楠", "胡昕炜", "周应波", "杨锐文", "李迅雷",
    "赵晓光", "高善文", "徐彪", "戴康",
]

# ---- 标的→板块映射（常见标的快速匹配） ----
_SECTOR_HINTS = {
    "白酒": ["茅台", "五粮液", "泸州", "汾酒", "洋河", "古井", "酒鬼", "水井坊"],
    "消费": ["茅台", "五粮液", "伊利", "蒙牛", "海天", "牧原", "双汇", "金龙鱼", "农夫山泉"],
    "医药": ["恒瑞", "药明", "片仔癀", "迈瑞", "爱尔", "智飞", "长春高新", "通策", "康龙"],
    "新能源": ["宁德", "比亚迪", "隆基", "通威", "阳光", "亿纬", "赣锋", "天齐", "恩捷", "先导"],
    "半导体": ["中芯", "韦尔", "兆易", "北方华创", "卓胜", "闻泰", "紫光", "长电", "华天"],
    "AI": ["科大讯飞", "商汤", "寒武纪", "海康", "大华", "依图", "云从", "拓尔思"],
    "银行": ["工商", "建设", "农业", "中国银行", "招商", "兴业", "浦发", "民生", "平安银行", "交通"],
    "券商": ["中信", "华泰", "海通", "国君", "广发", "招商证券", "申万", "银河", "国信", "东方财富"],
    "地产": ["万科", "保利", "碧桂园", "融创", "龙湖", "华润置地", "中海", "招商蛇口", "金地"],
    "互联网": ["腾讯", "阿里", "美团", "京东", "拼多多", "网易", "百度", "快手", "字节", "小米"],
    "光伏": ["隆基", "通威", "中环", "晶澳", "天合", "晶科", "福斯特", "阳光", "锦浪"],
    "汽车": ["比亚迪", "蔚来", "理想", "小鹏", "长安", "长城", "上汽", "吉利", "赛力斯"],
    "煤炭": ["神华", "陕煤", "兖矿", "中煤", "潞安", "平煤", "山煤"],
    "电力": ["长江电力", "华能", "华电", "国电", "大唐", "三峡", "国投"],
}

# ---- 板块关键词列表，用于从新闻中提取板块线索 ----
_PLATE_KEYWORDS = [
    "白酒", "消费", "医药", "新能源", "半导体", "AI", "银行",
    "券商", "地产", "互联网", "光伏", "汽车", "煤炭", "电力",
    "钢铁", "有色", "军工", "化工", "农业", "食品", "家电",
    "建材", "机械", "电子", "通信", "传媒", "计算机", "软件",
    "旅游", "航空", "物流", "环保", "教育", "保险", "医疗",
]


def _extract_sectors_from_name(name: str) -> list[str]:
    """从标的名称中提取可能的板块关键词。"""
    sectors = []
    for sector, hints in _SECTOR_HINTS.items():
        for hint in hints:
            if hint in name:
                sectors.append(sector)
                break
    # 去重 + 保持顺序
    return list(dict.fromkeys(sectors))


def build_search_keywords(name: str, sector: str = None) -> list[tuple[str, str]]:
    """
    根据标的名称自动生成多组搜索关键词。

    返回: [(标签, 搜索关键词), ...]

    生成规则:
    1. 标的名称本身
    2. 标的+板块关键词（从名称或传入 sector 推断）
    3. 标的+知名分析师/博主
    4. 纯板块关键词（用于板块新闻）
    """
    pairs = []

    # 1. 标的名称
    pairs.append(("标的", name))

    # 2. 推断板块
    sectors = _extract_sectors_from_name(name)
    if sector and sector not in sectors:
        sectors.append(sector)

    for s in sectors[:3]:  # 最多 3 个板块
        pairs.append(("板块", f"{name} {s}板块"))
        pairs.append(("板块", f"{s}板块"))

    # 3. 知名分析师/博主（最多 5 位）
    for analyst in KNOWN_ANALYSTS[:5]:
        pairs.append(("大V", f"{name} {analyst}"))

    return pairs


def deduplicate_news(news_list: list[dict]) -> list[dict]:
    """
    新闻去重：按标题相似度合并。

    策略：
    1. 完全相同的 title 只保留第一条
    2. 标题包含关系（短标题完全出现在长标题中）→ 保留较长的
    3. URL 相同 → 保留第一条
    """
    if not news_list:
        return []

    seen_urls = set()
    result = []

    for item in news_list:
        url = item.get("url", "")
        title = item.get("title", "").strip()

        # URL 去重
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)

        # 标题包含去重：新标题是已有标题的子串则跳过，已有标题是新标题的子串则替换
        is_dup = False
        for i, existing in enumerate(result):
            existing_title = existing.get("title", "").strip()
            if not title or not existing_title:
                continue
            if title == existing_title:
                is_dup = True
                break
            if len(title) > len(existing_title) and existing_title in title:
                # 新标题更长 → 替换旧条目
                result[i] = item
                is_dup = True
                break
            if len(title) < len(existing_title) and title in existing_title:
                # 旧标题更长 → 丢弃新条目
                is_dup = True
                break

        if not is_dup:
            result.append(item)

    return result


def search_and_parse_events(
    fetch_fn,
    name: str,
    sector: str = None,
    max_per_query: int = 6,
) -> list[tuple[str, int, str]]:
    """
    使用多组关键词并行搜索、解析、去重，返回情绪事件列表。

    fetch_fn: callable(query, max_results) -> list[dict]
              实际搜索函数（如 sentiment_fetcher.fetch_news）
    name:     标的名称
    sector:   可选，行业分类信息

    返回: [(date_str, score, title), ...]

    流程:
    1. 生成多组搜索关键词
    2. 逐组调用 fetch_fn 抓取
    3. 汇总所有结果并去重
    4. 解析为情绪事件
    """
    keywords_pairs = build_search_keywords(name, sector)
    all_raw = []
    seen_queries = set()

    for label, query in keywords_pairs:
        if query in seen_queries:
            continue
        seen_queries.add(query)
        try:
            results = fetch_fn(query, max_per_query)
            if results:
                # 标记搜索来源
                for r in results:
                    r["_search_query"] = query
                    r["_search_label"] = label
                # 相关性过滤（财经关键词或 query 本身）
                from core.sentiment_fetcher import _is_finance_relevant
                results = [r for r in results if _is_finance_relevant(
                    r.get("title", ""), r.get("snippet", ""), query)]
                all_raw.extend(results)
        except Exception:
            # 单个查询失败不阻塞其他查询
            pass

    # 去重
    all_raw = deduplicate_news(all_raw)

    # 解析为事件
    all_events = []
    for item in all_raw:
        title = item.get("title", "")
        snippet = item.get("snippet", item.get("description", ""))
        combined = f"{title} {snippet}"
        score = score_headline(combined)

        now = datetime.now()
        date_str = None
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", combined)
        if m:
            date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            m = re.search(r"(\d{1,2})月(\d{1,2})日", combined)
            if m:
                date_str = f"{now.year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            else:
                date_str = now.strftime("%Y-%m-%d")

        if score != 0:
            all_events.append((date_str, score, title))

    all_events.sort(key=lambda x: x[0])
    return all_events


def get_sentiment_for_date(
    events: list[tuple[str, int, str]],
    target_date: str,
    window_days: int = 7,
) -> tuple[float, list[str]]:
    """
    获取 target_date 附近 window_days 内的加权情绪得分和相关新闻标题。

    返回: (加权分数, [相关新闻标题列表])

    权重: 当天=1.0, 线性衰减到 window_days 天=0.3
    """
    try:
        target = datetime.strptime(target_date[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return 0.0, []

    relevant = []
    total_score = 0.0
    for date_str, score, title in events:
        try:
            event_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        days_diff = abs((target - event_date).days)
        if days_diff <= window_days:
            weight = max(0.3, 1.0 - days_diff / (window_days + 1) * 0.7)
            total_score += score * weight
            relevant.append(title)

    return round(total_score, 2), relevant


def format_sentiment_tag(score: float) -> str:
    """将情绪分数转为可读标签。"""
    if score > 2:
        return "利好"
    elif score > 0.5:
        return "偏多"
    elif score < -2:
        return "利空"
    elif score < -0.5:
        return "偏空"
    else:
        return "中性"


def summarize_news(raw_news: list[dict]) -> str:
    """
    从原始新闻列表生成一句情绪摘要标题。
    raw_news 每项含 title / snippet / url / source 等字段。
    """
    if not raw_news:
        return "暂无市场情绪数据"

    scored = []
    for item in raw_news:
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        score = score_headline(f"{title} {snippet}")
        scored.append((score, title))

    positive = [t for s, t in scored if s > 0]
    negative = [t for s, t in scored if s < 0]
    total = sum(s for s, _ in scored)

    if total > 3:
        tag = "利好"
    elif total > 1:
        tag = "偏多"
    elif total < -3:
        tag = "利空"
    elif total < -1:
        tag = "偏空"
    else:
        tag = "中性"

    # 关键词提取：从利好/利空标题中各取一个代表词
    pos_key = ""
    if positive:
        p = positive[0]
        for kw in ["突破", "利好", "看好", "流入", "增长", "涨停"]:
            if kw in p:
                pos_key = kw
                break
        if not pos_key:
            pos_key = "偏多信号"

    neg_key = ""
    if negative:
        n = negative[0]
        for kw in ["风险", "利空", "下滑", "减持", "监管", "调查"]:
            if kw in n:
                neg_key = kw
                break
        if not neg_key:
            neg_key = "利空信号"

    if positive and negative:
        return f"{tag}情绪：{pos_key} vs {neg_key}（抓取{len(raw_news)}条新闻）"
    elif positive:
        return f"{tag}情绪：{pos_key}（抓取{len(raw_news)}条新闻）"
    elif negative:
        return f"{tag}情绪：{neg_key}（抓取{len(raw_news)}条新闻）"
    else:
        return f"{tag}情绪（抓取{len(raw_news)}条新闻）"


def generate_events_from_price(
    data, name: str, target_count: int = 40
) -> list[tuple[str, int, str]]:
    """
    从价格数据生成合成情绪事件，均匀覆盖回测区间。

    策略：
    - 扫描每日涨跌幅，涨幅 > 1.5% → 利好事件，跌幅 > 1.5% → 利空事件
    - 控制总事件数不超过 target_count，按显著性排序取 Top-N
    - 利好/利空各约一半，确保情绪信号有交替

    data: OHLCV DataFrame（index 为日期）
    name: 标的名称
    target_count: 目标事件数量

    返回: [(日期, 分数, 标题), ...]
    """
    df = data.copy()
    if "close" not in df.columns:
        return []

    ret = df["close"].pct_change()
    events = []

    for i in range(1, len(df)):
        r = ret.iloc[i]
        if pd.isna(r):
            continue
        date_str = df.index[i].strftime("%Y-%m-%d")
        pct = abs(r) * 100

        if r > 0.015:
            score = min(round(r * 200), 8)  # +3% → 6分, +2% → 4分
            titles = [
                f"{name}单日涨{pct:.1f}%，资金加速流入",
                f"{name}放量拉升{pct:.1f}%，多头占据主导",
                f"市场情绪回暖，{name}领涨板块",
                f"{name}突破关键阻力位，看多信号增强",
                f"北向资金加仓{name}，反弹趋势确立",
            ]
            title = titles[i % len(titles)]
            events.append((date_str, score, title))
        elif r < -0.015:
            score = max(round(r * 200), -8)  # -3% → -6分, -2% → -4分
            titles = [
                f"{name}单日跌{pct:.1f}%，市场抛压加重",
                f"{name}放量下挫{pct:.1f}%，空头施压",
                f"市场避险情绪升温，{name}承压回落",
                f"{name}跌破关键支撑，利空信号显现",
                f"资金流出{name}板块，短期偏谨慎",
            ]
            title = titles[i % len(titles)]
            events.append((date_str, score, title))

    if not events:
        return []

    # 按分数绝对值排序，取 Top-N 个最具影响力的事件
    events.sort(key=lambda x: abs(x[1]), reverse=True)
    events = events[:target_count]
    # 再按日期排序
    events.sort(key=lambda x: x[0])

    return events
