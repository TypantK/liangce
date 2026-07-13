# -*- coding: utf-8 -*-
"""
东方财富统一访问层 (em_client)
============================================================
设计目标（借鉴 simonlin1212/a-stock-data 的 em_get 思路，代码自研）：
  1. 统一限流：东财对高频无节制请求会风控/封 IP，这里用进程级最小请求间隔
     (QPS 限流) 平滑请求，避免「扫描发现页时并发打爆被封」。
  2. 自动重试：网络抖动/偶发 5xx 时按退避重试，减少单次失败。
  3. 完整请求头：带真实 UA + Referer + Accept，规避「无 UA / 无 Referer 被拒」。
  4. 多域名备胎：东财行情 push2his 有多个镜像域名（push2his / 61.push2his /
     push2 等），主域名被限流时自动切换到备胎域名，提升健壮性。

对外主接口：
    em_get(path, params, base=None, timeout=15) -> dict   # 返回解析后的 JSON
    em_kline(secid, klt, fqt, beg, end) -> list[str]      # 通用 K 线原始行

本模块只做「访问 + 限流 + 降级」，不做业务解析，业务层（data_fetcher /
discover_page）拿到 JSON / klines 后自行组织成 DataFrame。
"""

from __future__ import annotations

import time
import random
import threading
import requests
from typing import Optional, List, Dict, Any


# ---------------------------------------------------------------------------
#  配置
# ---------------------------------------------------------------------------

# 东方财富行情历史 K 线的候选域名（主 → 备胎）。
# 同一路径在不同域名上都可用，主域名被限流/超时会自动切换。
_EM_HIS_HOSTS = [
    "https://push2his.eastmoney.com",
    "https://61.push2his.eastmoney.com",
    "https://push2his.eastmoney.com",  # 主域名再试一次（不同时刻风控面不同）
]

# 东方财富实时行情 / 列表接口候选域名。
_EM_PUSH_HOSTS = [
    "https://push2.eastmoney.com",
    "https://push2delay.eastmoney.com",
]

# 东财行情接口通用 ut 令牌（公开、行情页均使用此值）。
EM_UT = "fa5fd1943c7b386f172d6893dbfba10b"

# 完整请求头：真实浏览器 UA + Referer + Accept，规避无头请求被拒。
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# ---- 限流参数 ----
# 进程级最小请求间隔（秒）。东财对同 IP 高频请求敏感，设 0.35s ≈ 最高 ~3 QPS，
# 兼顾「发现页批量扫描不太慢」与「不易触发风控」。
_MIN_INTERVAL = 0.35
# 单个请求的重试次数与退避基数。
_MAX_RETRY = 3
_BACKOFF_BASE = 0.8


# ---------------------------------------------------------------------------
#  进程级限流器（线程安全）
# ---------------------------------------------------------------------------

class _RateLimiter:
    """最简单有效的令牌间隔限流：保证任意两次实际发出请求间隔 >= min_interval。

    线程安全，供发现页多标的（可能并发）扫描时平滑东财请求，避免瞬时并发打爆。
    """

    def __init__(self, min_interval: float):
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last_ts = 0.0

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_ts)
            if wait > 0:
                time.sleep(wait)
            self._last_ts = time.monotonic()

    def set_interval(self, interval: float):
        with self._lock:
            self._min_interval = max(0.0, interval)


_limiter = _RateLimiter(_MIN_INTERVAL)


def set_rate_limit(qps: float):
    """按目标 QPS 动态调整限流（qps<=0 表示不限流）。"""
    if qps <= 0:
        _limiter.set_interval(0.0)
    else:
        _limiter.set_interval(1.0 / qps)


# ---------------------------------------------------------------------------
#  核心：带限流 + 重试 + 多域名备胎的 GET
# ---------------------------------------------------------------------------

# 复用连接，减少握手开销。
_session = requests.Session()
_session.headers.update(_HEADERS)


def em_get(path: str, params: Dict[str, Any],
           hosts: Optional[List[str]] = None,
           timeout: int = 15) -> Dict[str, Any]:
    """向东方财富发起受限流保护的 GET，返回解析后的 JSON dict。

    Args:
        path:    接口路径，形如 "/api/qt/stock/kline/get"（以 / 开头）。
        params:  查询参数（不含 ut，会自动补 ut）。
        hosts:   候选域名列表；默认用历史 K 线域名组 _EM_HIS_HOSTS。
        timeout: 单次请求超时秒数。

    Returns:
        解析后的 JSON dict。

    Raises:
        RuntimeError: 所有域名 × 重试均失败时抛出（附最后一次错误）。
    """
    if hosts is None:
        hosts = _EM_HIS_HOSTS
    # 自动补 ut 令牌（若调用方未显式提供）
    q = dict(params)
    q.setdefault("ut", EM_UT)

    last_err: Optional[Exception] = None
    for host in hosts:
        url = host + path
        for attempt in range(_MAX_RETRY):
            _limiter.acquire()  # 全局限流：无论哪个域名都遵守最小间隔
            try:
                resp = _session.get(url, params=q, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                # 东财风控/无数据时常返回 data=None，视为可重试/可切域名的软失败
                if isinstance(data, dict) and data.get("data") is None \
                        and "klines" not in str(data):
                    last_err = RuntimeError(f"东财返回空 data（{host}{path}）")
                    # 空 data 多为该域名当前风控，直接跳到下个域名
                    break
                return data
            except Exception as e:  # noqa: BLE001 —— 网络层异常统一按可重试处理
                last_err = e
                # 指数退避 + 抖动，缓解瞬时限流
                sleep_s = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.3)
                time.sleep(sleep_s)
        # 换下一个备胎域名
    raise RuntimeError(f"东方财富请求失败（已试 {len(hosts)} 域名）: {last_err}")


def em_kline(secid: str, klt: str = "101", fqt: str = "0",
             beg: str = "0", end: str = "20500101",
             timeout: int = 15) -> List[str]:
    """通用东财 K 线拉取，返回 klines 原始字符串行列表。

    Args:
        secid: 东财证券标识，如 "90.BK1036"（板块）/ "1.600519"（沪市个股）/
               "0.000001"（深市个股）/ "1.000300"（沪深300指数）。
        klt:   K 线类型：101=日，102=周，103=月。
        fqt:   复权：0=不复权，1=前复权，2=后复权。
        beg:   起始日 YYYYMMDD（"0" 表示尽可能早）。
        end:   结束日 YYYYMMDD。

    Returns:
        klines 列表，每项形如 "2024-01-02,开,收,高,低,量,额,..."；无数据返回 []。
    """
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": klt,
        "fqt": fqt,
        "beg": beg,
        "end": end,
    }
    data = em_get("/api/qt/stock/kline/get", params, hosts=_EM_HIS_HOSTS, timeout=timeout)
    return (data.get("data") or {}).get("klines", []) or []
