#!/usr/bin/env python3
"""
测试情绪事件触发强制平仓的参数配置。
"""
import sys
sys.path.insert(0, '.')

from core.sentiment import score_headline, parse_events_from_search

# 构造强利空新闻
strong_bear_news = [
    {
        "title": "监管层对AI板块展开全面调查，多家公司涉嫌违规",
        "snippet": "日期: 2026-06-05 监管机构宣布对AI行业进行大规模合规调查，涉及数据安全、算法透明度等多个方面，市场预期将引发行业洗牌。",
        "date": "2026-06-05"
    },
    {
        "title": "AI龙头公司业绩暴雷，股价暴跌触发熔断",
        "snippet": "日期: 2026-06-05 某AI龙头公司发布财报，净利润同比下滑85%，远低于市场预期，股价开盘即跌停。",
        "date": "2026-06-05"
    },
    {
        "title": "国际制裁波及AI芯片供应链，多家企业面临断供风险",
        "snippet": "日期: 2026-06-04 新一轮国际制裁名单包含多家AI芯片供应商，国内AI企业面临核心零部件断供危机。",
        "date": "2026-06-04"
    },
    {
        "title": "AI行业裁员潮蔓延，头部企业宣布大规模优化",
        "snippet": "日期: 2026-06-04 多家AI企业宣布裁员计划，涉及研发、市场等多个部门，行业景气度急剧下滑。",
        "date": "2026-06-04"
    }
]

print("=== 强利空新闻标题及分数 ===")
for item in strong_bear_news:
    combined = f"{item['title']} {item['snippet']}"
    score = score_headline(combined)
    print(f"分数: {score:2d} | {item['title']}")
    print(f"      {item['snippet'][:80]}...")

# 解析为事件
events = parse_events_from_search(strong_bear_news, "AI")
print(f"\n=== 解析后事件列表 ===")
for date_str, score, title in events:
    print(f"{date_str} | {score:2d} | {title}")

# 计算2026-06-05的情绪分数
from core.sentiment import get_sentiment_for_date
score, headlines = get_sentiment_for_date(events, "2026-06-05", window_days=7)
print(f"\n=== 2026-06-05 情绪分析 ===")
print(f"加权分数: {score}")
print(f"相关新闻: {headlines}")

# 检查是否触发强制平仓
if score < -3:
    print(f"\n✅ 分数 {score} < -3，将触发情绪极端利空强制平仓")
    print("卖出原因示例：情绪极端利空强制平仓 (1)监管层对AI板块展开全面调查...; (2)AI龙头公司业绩暴雷...")
else:
    print(f"\n❌ 分数 {score} 未达到 -3 阈值，不会触发强制平仓")