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


def score_headline(headline: str) -> int:
    """对单条新闻标题打分：每个利好词 +1，每个利空词 -1。返回整数分数。"""
    pos_count = len(_pos_pattern.findall(headline))
    neg_count = len(_neg_pattern.findall(headline))
    return pos_count - neg_count


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

        events.append((date_str, score, title))

    events.sort(key=lambda x: x[0])
    return events


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
