# -*- coding: utf-8 -*-
"""补丁：直接用 Python 重写 search_and_parse_events，确保落盘。"""
import io

path = r"x:\Personal\Project\liangce\core\sentiment.py"
with io.open(path, "r", encoding="utf-8") as f:
    src = f.read()

# 用最稳健的方式：定位函数定义起始，按逻辑块替换签名+docstring+开头
marker = "def search_and_parse_events("
idx = src.find(marker)
assert idx != -1, "function not found"

# 找到该函数体结束：下一个顶层 def（缩进为0的def）之前
rest = src[idx:]
next_def = rest.find("\ndef ", len("def search_and_parse_events("))
if next_def == -1:
    func_block = rest
else:
    func_block = rest[:next_def]

# 旧签名块（真实磁盘，无 code 参数）
old_head = '''def search_and_parse_events(
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
    keywords_pairs = build_search_keywords(name, sector)'''

assert old_head in func_block, "old_head not found in disk content"

new_head = '''def search_and_parse_events(
    fetch_fn,
    name: str,
    sector: str = None,
    max_per_query: int = 6,
    code: str = None,
) -> list[tuple[str, int, str]]:
    """
    使用多组关键词并行搜索、解析、去重，返回情绪事件列表。

    fetch_fn: callable(query, max_results) -> list[dict]
              实际搜索函数（如 sentiment_fetcher.fetch_news）
    name:     标的名称
    sector:   可选，行业分类信息
    code:     可选，标的代码（如 '600519.SH'）。若提供，优先用代码走 akshare
              个股新闻通道（强相关），其余维度用名称/板块词走的 web 通道。

    返回: [(date_str, score, title), ...]

    流程:
    1. 生成多组「总结性」搜索关键词（标的 / 板块 / 概念题材 / 行业视角 / 大V）
    2. 逐组调用 fetch_fn 抓取（代码维度优先 akshare 个股路径）
    3. 汇总所有结果并去重
    4. 解析为情绪事件
    """
    keywords_pairs = build_search_keywords(name, sector, code)
    all_raw = []
    seen_queries = set()

    # 代码维度：优先用代码抓取 akshare 个股新闻（强相关、与标的直接对应）
    if code:
        try:
            code_res = fetch_fn(code, max_per_query)
            if code_res:
                for r in code_res:
                    r["_search_query"] = code
                    r["_search_label"] = "代码"
                all_raw.extend(code_res)
                seen_queries.add(code)
        except Exception:
            pass

    for label, query in keywords_pairs:'''

new_func_block = func_block.replace(old_head, new_head)
src = src[:idx] + new_func_block + src[idx + len(func_block):]

with io.open(path, "w", encoding="utf-8") as f:
    f.write(src)

print("OK: 已写入 code 优先逻辑")
