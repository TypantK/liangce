# -*- coding: utf-8 -*-
"""
参数网格搜索引擎 — 对两个参数做全组合遍历，复用 engine.run_backtest。
"""

import numpy as np
from core.engine import run_backtest

METRIC_LABELS = {
    "sharpe":            "夏普比率",
    "annualized_return": "年化收益率",
    "win_rate":          "胜率",
}

_METRIC_HIGHER_BETTER = {"sharpe", "annualized_return", "win_rate"}


def _generate_values(pmin, pmax, pdef):
    """与 backtest_page 一致的 step 逻辑，但限制最多 30 个点。"""
    step = 0.1 if isinstance(pdef, float) else 1
    vals = np.arange(pmin, pmax + step / 2, step)
    if len(vals) > 30:
        vals = np.linspace(pmin, pmax, 30)
    # 四舍五入到 step 精度
    decimals = 1 if isinstance(pdef, float) else 0
    vals = np.round(vals, decimals)
    return vals


def grid_search(data, strategy_class, base_params,
                param1_name, param1_min, param1_max, param1_def,
                param2_name, param2_min, param2_max, param2_def,
                metric="sharpe", initial_cash=100000, commission=0.0005,
                strategy_name="", progress_callback=None):
    """
    对两个参数做网格搜索。

    Parameters
    ----------
    progress_callback : callable(i, total) or None
        每完成一个组合的回测时调用，用于 UI 进度条更新。

    Returns
    -------
    dict with keys: matrix, p1_vals, p2_vals, param1, param2,
                    best_params, best_metric, best_metric_label,
                    strategy_name
    """
    p1_vals = _generate_values(param1_min, param1_max, param1_def)
    p2_vals = _generate_values(param2_min, param2_max, param2_def)

    total = len(p1_vals) * len(p2_vals)
    matrix = np.full((len(p2_vals), len(p1_vals)), np.nan)
    higher_better = metric in _METRIC_HIGHER_BETTER

    best_metric = -float('inf') if higher_better else float('inf')
    best_params = None

    count = 0
    for i, v2 in enumerate(p2_vals):
        for j, v1 in enumerate(p1_vals):
            params = dict(base_params)
            params[param1_name] = float(v1) if isinstance(param1_def, float) else int(v1)
            params[param2_name] = float(v2) if isinstance(param2_def, float) else int(v2)

            result = run_backtest(data, strategy_class, params,
                                  initial_cash=initial_cash,
                                  commission=commission,
                                  strategy_name=strategy_name)
            raw = result.get("raw", {})
            val = raw.get(metric)
            if val is None:
                val = float('nan')
            matrix[i, j] = val

            if not np.isnan(val):
                if higher_better and val > best_metric:
                    best_metric = val
                    best_params = dict(params)
                elif not higher_better and val < best_metric:
                    best_metric = val
                    best_params = dict(params)

            count += 1
            if progress_callback:
                progress_callback(count, total)

    return {
        "matrix": matrix.tolist(),
        "p1_vals": p1_vals.tolist(),
        "p2_vals": p2_vals.tolist(),
        "param1": param1_name,
        "param2": param2_name,
        "best_params": best_params,
        "best_metric": best_metric,
        "best_metric_label": METRIC_LABELS.get(metric, metric),
        "strategy_name": strategy_name,
    }
