"""Portfolio weighting schemes for the top-N selection.

Conventions follow Maillard, Roncalli & Teiletche (2010), "On the Properties
of Equally-Weighted Risk Contributions Portfolios."

Schemes:
- equal           : w_i = 1/N
- inverse_vol     : w_i = (1/sigma_i) / sum_j(1/sigma_j)  using annualised vol
- erc             : equal risk contribution, solved via the standard sqrt
                    fixed-point iteration on the sample covariance matrix
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
    return inverse_vol_weights(returns, tickers, lookback)
