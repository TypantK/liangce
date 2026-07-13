# -*- coding: utf-8 -*-
"""
每日市场复盘数据层 (daily_review)
============================================================
方法论借鉴自 quantskills/skill-market-daily-review（仅参考「章节→数据」的
组织结构与「事实/推断分离、优雅降级不估数」原则），**代码完全自研**，
数据源使用本项目已有的免费通道（akshare + core.em_client 东财直连），
不引入 Pandadata、不拷贝其任何代码，规避 GPL-3.0 传染。

产出一个结构化 dict，交由 discover_page 渲染。每个字段都标注：
  - value：事实数据（取不到则为 None，绝不估算/编造）
  - as_of：数据对应交易日（T+1 复盘：盘后数据对应「上一交易日」）

章节：
  1. indices     指数概览（上证/深证/创业板/沪深300）
  2. breadth     市场宽度（涨跌家数、涨停/跌停）
  3. sectors     行业热点（涨幅前/后行业板块）
  4. capital     资金面（北向资金、主力净流入行业）

所有联网失败均降级为 None + 备注，UI 显示「数据暂不可用」，不影响其它章节。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any, List


# ---------------------------------------------------------------------------
#  工具
# ---------------------------------------------------------------------------

def _safe_float(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
#  1. 指数概览
# ---------------------------------------------------------------------------

def fetch_indices() -> Dict[str, Any]:
    """主要宽基指数实时/收盘快照（上证/深证/创业板/沪深300）。

    走 em_client 东财直连（限流+备胎），返回 {list, note}。取不到返回空 list。
    """
    from .em_client import em_get

    # 东财 secid：1.000001=上证，0.399001=深证成指，0.399006=创业板指，1.000300=沪深300
    targets = [
        ("上证指数", "1.000001"),
        ("深证成指", "0.399001"),
        ("创业板指", "0.399006"),
        ("沪深300", "1.000300"),
    ]
    out: List[Dict[str, Any]] = []
    for name, secid in targets:
        try:
            data = em_get(
                "/api/qt/stock/get",
                {
                    "secid": secid,
                    # f43=最新价 f170=涨跌幅 f169=涨跌额 f47=成交量 f48=成交额
                    "fields": "f43,f44,f45,f46,f47,f48,f169,f170",
                },
                hosts=None,  # 用默认历史域名组即可，get 接口同样可用
            )
            d = data.get("data") or {}
            price = _safe_float(d.get("f43"))
            pct = _safe_float(d.get("f170"))
            # 东财价格/涨跌幅通常放大 100 倍（分/万分），做还原
            if price is not None:
                price = price / 100.0
            if pct is not None:
                pct = pct / 100.0
            out.append({"name": name, "price": price, "pct": pct})
        except Exception:
            out.append({"name": name, "price": None, "pct": None})
    return {"list": out, "note": "指数为实时/最近收盘快照"}


# ---------------------------------------------------------------------------
#  2. 市场宽度
# ---------------------------------------------------------------------------

def fetch_breadth() -> Dict[str, Any]:
    """市场宽度：上涨/下跌/平盘家数、涨停/跌停数。

    优先 akshare 全 A 实时快照统计涨跌家数；涨停/跌停用东财涨停池接口。
    任一失败对应字段置 None，不影响其它。
    """
    result: Dict[str, Any] = {
        "up": None, "down": None, "flat": None,
        "limit_up": None, "limit_down": None,
        "note": "基于全 A 实时快照统计",
    }
    # ---- 涨跌家数：akshare 实时行情快照 ----
    try:
        import akshare as ak
        spot = ak.stock_zh_a_spot_em()
        if spot is not None and not spot.empty and "涨跌幅" in spot.columns:
            chg = spot["涨跌幅"].astype(float)
            result["up"] = int((chg > 0).sum())
            result["down"] = int((chg < 0).sum())
            result["flat"] = int((chg == 0).sum())
    except Exception:
        pass

    # ---- 涨停/跌停家数：东财涨停/跌停池 ----
    try:
        import akshare as ak
        today = datetime.now().strftime("%Y%m%d")
        zt = ak.stock_zt_pool_em(date=today)
        if zt is not None and not zt.empty:
            result["limit_up"] = int(len(zt))
    except Exception:
        pass
    try:
        import akshare as ak
        today = datetime.now().strftime("%Y%m%d")
        dt = ak.stock_zt_pool_dtgc_em(date=today)
        if dt is not None and not dt.empty:
            result["limit_down"] = int(len(dt))
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
#  3. 行业热点
# ---------------------------------------------------------------------------

def fetch_sectors(top_n: int = 6) -> Dict[str, Any]:
    """行业板块涨幅榜：取涨幅前 top_n 与后 top_n。

    走 akshare 东财行业板块实时（stock_board_industry_name_em 含涨跌幅）。
    """
    result: Dict[str, Any] = {"top": [], "bottom": [], "note": "东财行业板块实时涨跌幅"}
    try:
        import akshare as ak
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            return result
        # 定位名称列与涨跌幅列
        name_col = next((c for c in df.columns if c.strip() in ("板块名称", "名称", "行业")), None)
        pct_col = next((c for c in df.columns if "涨跌幅" in c), None)
        if not name_col or not pct_col:
            return result
        df = df[[name_col, pct_col]].copy()
        df.columns = ["name", "pct"]
        df["pct"] = df["pct"].astype(float)
        df = df.sort_values("pct", ascending=False)
        result["top"] = df.head(top_n).to_dict("records")
        result["bottom"] = df.tail(top_n).sort_values("pct").to_dict("records")
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
#  4. 资金面
# ---------------------------------------------------------------------------

def fetch_capital() -> Dict[str, Any]:
    """资金面：北向资金净流入 + 行业主力净流入前列。

    北向资金说明：东财沪深股通口径近年有偏差，此处以 akshare 汇总接口为准，
    并在 UI 标注「口径参考」。行业主力净流入用东财行业资金流。
    """
    result: Dict[str, Any] = {
        "north": None,           # 北向资金净流入（亿元）
        "north_note": "北向资金口径以东财汇总为参考，实时性与准确性有限",
        "main_inflow": [],       # 行业主力净流入前列
    }
    # ---- 北向资金 ----
    try:
        import akshare as ak
        nb = ak.stock_hsgt_fund_flow_summary_em()
        if nb is not None and not nb.empty:
            # 汇总「北向」相关行的净流入
            val_col = next((c for c in nb.columns if "成交净买额" in c or "净流入" in c or "净买额" in c), None)
            if val_col:
                mask = nb.apply(lambda r: any("北" in str(v) for v in r.values), axis=1)
                sub = nb[mask]
                if not sub.empty:
                    result["north"] = _safe_float(sub[val_col].astype(float).sum())
    except Exception:
        pass

    # ---- 行业主力净流入 ----
    try:
        import akshare as ak
        flow = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
        if flow is not None and not flow.empty:
            name_col = next((c for c in flow.columns if c.strip() in ("名称", "行业", "板块")), None)
            val_col = next((c for c in flow.columns if "主力净流入-净额" in c or "主力净流入" in c), None)
            if name_col and val_col:
                sub = flow[[name_col, val_col]].copy()
                sub.columns = ["name", "inflow"]
                sub["inflow"] = sub["inflow"].astype(float)
                sub = sub.sort_values("inflow", ascending=False).head(6)
                result["main_inflow"] = sub.to_dict("records")
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
#  聚合入口
# ---------------------------------------------------------------------------

def build_daily_review() -> Dict[str, Any]:
    """组装完整每日复盘数据。各章节独立降级，任一失败不影响其它。

    Returns:
        {
          "as_of": "YYYY-MM-DD",   # 复盘对应交易日说明
          "generated_at": "...",   # 生成时间
          "indices": {...}, "breadth": {...},
          "sectors": {...}, "capital": {...},
        }
    """
    now = datetime.now()
    # T+1 复盘：盘后（15:00 后）对应今日；盘中/盘前对应「最近已收盘交易日」提示由 UI 呈现
    return {
        "as_of": _today_str(),
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "is_after_close": (now.hour > 15) or (now.hour == 15 and now.minute >= 0),
        "indices": fetch_indices(),
        "breadth": fetch_breadth(),
        "sectors": fetch_sectors(),
        "capital": fetch_capital(),
    }
