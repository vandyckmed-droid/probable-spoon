"""Portfolio weighting schemes for the top-N selection.

Conventions follow Maillard, Roncalli & Teiletche (2010), "On the Properties
of Equally-Weighted Risk Contributions Portfolios" — and López de Prado (2016),
"Building Diversified Portfolios that Outperform Out-of-Sample" for HRP.

Schemes:
- equal           : w_i = 1/N
- inverse_vol     : w_i = (1/sigma_i) / sum_j(1/sigma_j)  using annualised vol
- erc             : equal risk contribution, solved via the standard sqrt
                    fixed-point iteration on the sample covariance matrix
- hrp             : Hierarchical Risk Parity. Average-link agglomerative
                    clustering on the correlation-distance matrix, recursive
                    bisection on the cov matrix in cluster-leaf order, weights
                    inversely proportional to cluster variance at each split
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_TRADING_DAYS = 252


def equal_weights(tickers: list[str]) -> pd.Series:
    n = len(tickers)
    if n == 0:
        return pd.Series(dtype=float)
    return pd.Series(1.0 / n, index=tickers)


def _annualised_vol(returns: pd.DataFrame, tickers: list[str], lookback: int) -> pd.Series:
    window = returns[tickers].tail(lookback)
    return window.std(ddof=0) * np.sqrt(_TRADING_DAYS)


def inverse_vol_weights(
    returns: pd.DataFrame, tickers: list[str], lookback: int = 252,
) -> pd.Series:
    """w_i proportional to 1/sigma_i, normalised to sum to 1."""
    if not tickers:
        return pd.Series(dtype=float)
    available = [t for t in tickers if t in returns.columns]
    if not available:
        return equal_weights(tickers)
    vol = _annualised_vol(returns, available, lookback)
    inv = (1.0 / vol.replace(0, np.nan)).dropna()
    if inv.empty:
        return equal_weights(tickers)
    raw = inv / inv.sum()
    out = pd.Series(0.0, index=tickers)
    out.loc[raw.index] = raw
    s = out.sum()
    return out / s if s > 0 else equal_weights(tickers)


def erc_weights(
    returns: pd.DataFrame, tickers: list[str], lookback: int = 252,
    *, max_iter: int = 1000, tol: float = 1e-8,
) -> pd.Series:
    """Equal risk contribution: w_i × (Σw)_i = const for all i.

    Falls back to equal weights when the covariance is degenerate or the
    iteration cannot converge cleanly.
    """
    if not tickers:
        return pd.Series(dtype=float)
    available = [t for t in tickers if t in returns.columns]
    if not available:
        return equal_weights(tickers)
    if len(available) == 1:
        out = pd.Series(0.0, index=tickers)
        out.loc[available[0]] = 1.0
        return out

    window = returns[available].tail(lookback).dropna()
    if window.shape[0] < 30 or window.shape[1] < 2:
        return equal_weights(tickers)
    cov = window.cov().to_numpy()
    if not np.all(np.isfinite(cov)):
        return equal_weights(tickers)

    n = cov.shape[0]
    w = np.ones(n) / n
    for _ in range(max_iter):
        sigma_w = cov @ w
        rc = w * sigma_w
        if np.any(rc <= 0) or not np.all(np.isfinite(rc)):
            return equal_weights(tickers)
        target = rc.mean()
        w_new = w * np.sqrt(target / rc)
        w_new = np.clip(w_new, 1e-12, None)
        w_new = w_new / w_new.sum()
        if np.max(np.abs(w_new - w)) < tol:
            w = w_new
            break
        w = w_new

    out = pd.Series(0.0, index=tickers)
    out.loc[available] = w
    s = out.sum()
    return out / s if s > 0 else equal_weights(tickers)


def _cluster_variance(cov: np.ndarray, indices: list[int]) -> float:
    """Inverse-variance-weighted cluster variance (Lopez de Prado, eq. 5)."""
    sub = cov[np.ix_(indices, indices)]
    iv = 1.0 / np.diag(sub)
    iv = iv / iv.sum()
    return float(iv @ sub @ iv)


def _average_link_order(dist: np.ndarray) -> list[int]:
    """Average-link agglomerative clustering. Returns leaves in merge order.

    O(n^3) — fine for the small (~25-name) portfolios this is used for.
    """
    n = dist.shape[0]
    clusters: dict[int, list[int]] = {i: [i] for i in range(n)}
    next_id = n
    while len(clusters) > 1:
        ids = list(clusters.keys())
        best_d = float("inf")
        merge_a, merge_b = ids[0], ids[1]
        for i, ca in enumerate(ids):
            for cb in ids[i + 1:]:
                pa, pb = clusters[ca], clusters[cb]
                d = float(np.mean(dist[np.ix_(pa, pb)]))
                if d < best_d:
                    best_d = d
                    merge_a, merge_b = ca, cb
        clusters[next_id] = clusters[merge_a] + clusters[merge_b]
        del clusters[merge_a]
        del clusters[merge_b]
        next_id += 1
    return list(clusters.values())[0]


def hrp_weights(
    returns: pd.DataFrame, tickers: list[str], lookback: int = 504,
) -> pd.Series:
    """Hierarchical Risk Parity, long-only weights summing to 1.

    1. Build a 25x25 sample covariance over the lookback window.
    2. Convert to a correlation-distance matrix d_ij = sqrt(0.5 * (1 - rho_ij)).
    3. Cluster with average-link agglomerative clustering to get leaf order.
    4. Recursively bisect at the midpoint of the ordered list, allocating
       weight inversely proportional to cluster variance at each split.

    Falls back to equal weights on degenerate inputs (single name, missing
    columns, non-finite covariance, zero variance).
    """
    if not tickers:
        return pd.Series(dtype=float)
    available = [t for t in tickers if t in returns.columns]
    if not available:
        return equal_weights(tickers)
    if len(available) == 1:
        out = pd.Series(0.0, index=tickers)
        out.loc[available[0]] = 1.0
        return out

    window = returns[available].tail(lookback).dropna()
    if window.shape[0] < 30 or window.shape[1] < 2:
        return equal_weights(tickers)

    cov = window.cov().to_numpy()
    diag = np.diag(cov)
    if not np.all(np.isfinite(cov)) or np.any(diag <= 0):
        return equal_weights(tickers)

    sigma = np.sqrt(diag)
    corr = cov / np.outer(sigma, sigma)
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, None))

    leaf_order = _average_link_order(dist)
    n = len(leaf_order)
    w_pos = np.ones(n)  # weights indexed by position in leaf_order
    queue: list[list[int]] = [list(range(n))]
    while queue:
        nxt: list[list[int]] = []
        for cluster in queue:
            if len(cluster) <= 1:
                continue
            mid = len(cluster) // 2
            left_pos = cluster[:mid]
            right_pos = cluster[mid:]
            left_orig = [leaf_order[p] for p in left_pos]
            right_orig = [leaf_order[p] for p in right_pos]
            lv = _cluster_variance(cov, left_orig)
            rv = _cluster_variance(cov, right_orig)
            alpha = 1.0 - lv / (lv + rv) if (lv + rv) > 0 else 0.5
            for p in left_pos:
                w_pos[p] *= alpha
            for p in right_pos:
                w_pos[p] *= (1.0 - alpha)
            nxt.append(left_pos)
            nxt.append(right_pos)
        queue = nxt

    final = np.zeros(n)
    for pos, orig in enumerate(leaf_order):
        final[orig] = w_pos[pos]

    out = pd.Series(0.0, index=tickers)
    for i, t in enumerate(available):
        out.loc[t] = float(final[i])
    s = out.sum()
    return out / s if s > 0 else equal_weights(tickers)


_SCHEMES = {
    "equal": "equal",
    "equal_weight": "equal",
    "ew": "equal",
    "inverse_vol": "inverse_vol",
    "inv_vol": "inverse_vol",
    "ivp": "inverse_vol",
    "erc": "erc",
    "risk_parity": "erc",
    "rp": "erc",
    "hrp": "hrp",
    "hierarchical_risk_parity": "hrp",
}


def compute_weights(
    scheme: str, returns: pd.DataFrame, tickers: list[str], lookback: int = 252,
) -> pd.Series:
    """Dispatcher. Unknown scheme falls back to inverse_vol."""
    key = _SCHEMES.get((scheme or "").lower(), "inverse_vol")
    if key == "equal":
        return equal_weights(tickers)
    if key == "erc":
        return erc_weights(returns, tickers, lookback)
    if key == "hrp":
        return hrp_weights(returns, tickers, lookback)
    return inverse_vol_weights(returns, tickers, lookback)


def portfolio_volatility(
    returns: pd.DataFrame, weights_series: pd.Series, lookback: int = 252,
) -> float:
    """Annualised portfolio sigma using sample covariance over the lookback."""
    if weights_series is None or weights_series.empty:
        return 0.0
    available = [t for t in weights_series.index if t in returns.columns]
    if len(available) < 2:
        return 0.0
    window = returns[available].tail(lookback).dropna()
    if window.shape[0] < 30:
        return 0.0
    cov = window.cov().to_numpy()
    if not np.all(np.isfinite(cov)):
        return 0.0
    w = weights_series.loc[available].to_numpy()
    var = float(w @ cov @ w)
    if not np.isfinite(var) or var <= 0:
        return 0.0
    return float(np.sqrt(var) * np.sqrt(_TRADING_DAYS))


def vol_target_scale(
    realized: float, target: float | None, max_leverage: float = 1.0,
) -> float:
    """target / realized, clipped at `max_leverage`.

    When max_leverage = 1.0 the function never produces leverage — it only
    scales down a portfolio whose realised vol exceeds the target. Pass a
    larger cap (e.g. 1.25) to allow scaling UP when realised vol is below
    target, up to that ceiling.
    """
    if target is None or target <= 0 or realized <= 0:
        return 1.0
    if not np.isfinite(realized) or not np.isfinite(target):
        return 1.0
    cap = float(max(1.0, max_leverage))
    return float(min(cap, target / realized))


def backtest_portfolio(
    returns: pd.DataFrame, weights_series: pd.Series, lookback_days: int = 126,
) -> dict | None:
    """v0.1 lookback attribution: hold the current weights statically over the
    last `lookback_days` of price history. Returns total return, annualised
    Sharpe, max drawdown, and the daily cumulative simple-return path.

    Note: this is NOT a true rolling-rebalance backtest — the names and
    weights are picked from today's data and applied backwards. Useful as a
    sanity check on the resulting portfolio's recent risk/return profile,
    not as a forecast of future performance.
    """
    if weights_series is None or weights_series.empty:
        return None
    nonzero = weights_series[weights_series > 0]
    if nonzero.empty:
        return None
    available = [t for t in nonzero.index if t in returns.columns]
    if not available:
        return None
    window = returns[available].tail(lookback_days).dropna()
    if window.shape[0] < 30:
        return None
    w = nonzero.loc[available].to_numpy()
    w = w / w.sum() if w.sum() > 0 else w  # renormalise after dropping missing
    daily = window.to_numpy() @ w
    cum_log = np.cumsum(daily)
    wealth = np.exp(cum_log)
    cum_simple = wealth - 1.0
    total_return = float(cum_simple[-1])
    daily_std = float(np.std(daily, ddof=0))
    sharpe = (
        float(np.mean(daily) / daily_std * np.sqrt(_TRADING_DAYS))
        if daily_std > 0 else 0.0
    )
    running_peak = np.maximum.accumulate(wealth)
    max_dd = float((wealth / running_peak - 1.0).min())
    idx = window.index
    start_date = str(idx[0].date()) if hasattr(idx[0], "date") else str(idx[0])
    end_date = str(idx[-1].date()) if hasattr(idx[-1], "date") else str(idx[-1])
    return {
        "days": int(window.shape[0]),
        "start_date": start_date,
        "end_date": end_date,
        "total_return": total_return,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "cumulative": [float(x) for x in cum_simple],
    }


def backtest_market(
    returns: pd.DataFrame, ticker: str, lookback_days: int = 126,
) -> dict | None:
    """Same shape as backtest_portfolio but for a single benchmark ticker."""
    if ticker not in returns.columns:
        return None
    series = returns[ticker].tail(lookback_days).dropna()
    if series.shape[0] < 30:
        return None
    daily = series.to_numpy()
    cum_log = np.cumsum(daily)
    wealth = np.exp(cum_log)
    cum_simple = wealth - 1.0
    daily_std = float(np.std(daily, ddof=0))
    sharpe = (
        float(np.mean(daily) / daily_std * np.sqrt(_TRADING_DAYS))
        if daily_std > 0 else 0.0
    )
    running_peak = np.maximum.accumulate(wealth)
    max_dd = float((wealth / running_peak - 1.0).min())
    idx = series.index
    start_date = str(idx[0].date()) if hasattr(idx[0], "date") else str(idx[0])
    end_date = str(idx[-1].date()) if hasattr(idx[-1], "date") else str(idx[-1])
    return {
        "days": int(series.shape[0]),
        "start_date": start_date,
        "end_date": end_date,
        "total_return": float(cum_simple[-1]),
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "cumulative": [float(x) for x in cum_simple],
    }
