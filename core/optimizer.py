# -*- coding: utf-8 -*-
"""
参数优化引擎 — 网格搜索 + Optuna 贝叶斯优化，复用 engine.run_backtest。
"""

import time
import numpy as np
import optuna
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
    # 根据参数默认值大小动态决定精度：小值需要更高精度
    if isinstance(pdef, float):
        abs_def = abs(pdef)
        if abs_def < 1e-3:
            decimals = 6
        elif abs_def < 1e-2:
            decimals = 4
        elif abs_def < 0.1:
            decimals = 3
        elif abs_def < 1:
            decimals = 2
        else:
            decimals = 1
    else:
        decimals = 0
    vals = np.round(vals, decimals)
    return vals


def grid_search(data, strategy_class, base_params,
                param1_name, param1_min, param1_max, param1_def,
                param2_name, param2_min, param2_max, param2_def,
                metric="sharpe", initial_cash=100000, commission=0.0005,
                strategy_name="", progress_callback=None, timeout=300):
    """
    对两个参数做网格搜索。

    Parameters
    ----------
    progress_callback : callable(i, total) or None
        每完成一个组合的回测时调用，用于 UI 进度条更新。
    timeout : int
        最长运行时间（秒），默认 300 秒。超时后优雅退出，返回当前已完成的结果。

    Returns
    -------
    dict with keys: matrix, p1_vals, p2_vals, param1, param2,
                    best_params, best_metric, best_metric_label,
                    strategy_name, timed_out
    """
    p1_vals = _generate_values(param1_min, param1_max, param1_def)
    p2_vals = _generate_values(param2_min, param2_max, param2_def)

    total = len(p1_vals) * len(p2_vals)
    matrix = np.full((len(p2_vals), len(p1_vals)), np.nan)
    higher_better = metric in _METRIC_HIGHER_BETTER

    best_metric = -float('inf') if higher_better else float('inf')
    best_params = None

    start_time = time.time()
    timed_out = False
    count = 0
    for i, v2 in enumerate(p2_vals):
        for j, v1 in enumerate(p1_vals):
            # 超时检查：每轮组合前判断，超时则优雅退出
            if time.time() - start_time > timeout:
                timed_out = True
                break

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

        if timed_out:
            break

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
        "timed_out": timed_out,
        "completed": count,
        "total": total,
        "method": "grid",
    }


def optuna_optimize(data, strategy_class, base_params,
                    param1_name, param1_min, param1_max, param1_def,
                    param2_name, param2_min, param2_max, param2_def,
                    metric="sharpe", initial_cash=100000, commission=0.0005,
                    strategy_name="", progress_callback=None,
                    n_trials=50, timeout=300):
    """
    使用 Optuna TPESampler 做贝叶斯参数优化。

    Parameters
    ----------
    n_trials : int
        最大尝试次数（默认 50），实际有效回测次数可能因 TrialPruned 而更少。
    其余参数与 grid_search 一致。

    Returns
    -------
    dict — 与 grid_search 相同结构，额外包含 trial_data 列表。
          其中 matrix 由 trial 结果映射到网格单元构建，未覆盖的单元为 NaN。
    """
    higher_better = metric in _METRIC_HIGHER_BETTER

    trials_results = []          # [(v1, v2, metric_val), ...]
    best_metric = -float('inf') if higher_better else float('inf')
    best_params = None
    timed_out = [False]          # 用列表包装方便闭包内修改
    start_time = time.time()

    def objective(trial):
        if time.time() - start_time > timeout:
            timed_out[0] = True
            raise optuna.TrialPruned()

        p1_is_float = isinstance(param1_def, float)
        p2_is_float = isinstance(param2_def, float)

        if p1_is_float:
            v1 = trial.suggest_float(param1_name, param1_min, param1_max)
        else:
            v1 = trial.suggest_int(param1_name, param1_min, param1_max)

        if p2_is_float:
            v2 = trial.suggest_float(param2_name, param2_min, param2_max)
        else:
            v2 = trial.suggest_int(param2_name, param2_min, param2_max)

        params = dict(base_params)
        params[param1_name] = v1
        params[param2_name] = v2

        result = run_backtest(data, strategy_class, params,
                              initial_cash=initial_cash,
                              commission=commission,
                              strategy_name=strategy_name)
        raw = result.get("raw", {})
        val = raw.get(metric)
        if val is None or np.isnan(val):
            raise optuna.TrialPruned()

        trials_results.append((v1, v2, val))

        nonlocal best_metric, best_params
        if higher_better and val > best_metric:
            best_metric = val
            best_params = dict(params)
        elif not higher_better and val < best_metric:
            best_metric = val
            best_params = dict(params)

        return val

    # 进度回调：每完成一个 trial 报告一次
    trial_count = [0]

    def _cb(study, trial):
        trial_count[0] += 1
        if progress_callback:
            progress_callback(trial_count[0], n_trials)

    study = optuna.create_study(
        direction="maximize" if higher_better else "minimize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    study.optimize(objective, n_trials=n_trials, callbacks=[_cb],
                   show_progress_bar=False)

    # ---- 从 trial 结果构造热力图矩阵 ----
    p1_vals = _generate_values(param1_min, param1_max, param1_def)
    p2_vals = _generate_values(param2_min, param2_max, param2_def)
    matrix = np.full((len(p2_vals), len(p1_vals)), np.nan)

    for v1, v2, val in trials_results:
        i = np.argmin(np.abs(p2_vals - v2))
        j = np.argmin(np.abs(p1_vals - v1))
        if np.isnan(matrix[i, j]) or (higher_better and val > matrix[i, j]) \
           or (not higher_better and val < matrix[i, j]):
            matrix[i, j] = val

    trial_data = [
        {"param1": t[0], "param2": t[1], "metric": t[2]} for t in trials_results
    ]

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
        "timed_out": timed_out[0],
        "completed": len(trials_results),
        "total": n_trials,
        "method": "optuna",
        "trial_data": trial_data,
    }
