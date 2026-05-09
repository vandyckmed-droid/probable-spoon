"""Cross-sectional momentum / quality / value ranking.

Pure math, no I/O, no caching, no reporting. Consumes pandas frames and
plain dicts; produces a ranked frame. Synthetic test fixtures cover
every public function.

The strict complete-data policy applies throughout: a ticker missing
any required input gets NaN for that factor, and the composite drops
any ticker that does not have all three factor z-scores. No
zero-fills, no per-stock weight renormalisation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WINSOR_LOWER = 0.05
WINSOR_UPPER = 0.95


# ---------- returns ----------

def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily log returns. Drops the first row. Preserves NaNs (no ffill)."""
    if prices.empty:
        return prices.copy()
    return np.log(prices / prices.shift(1)).iloc[1:]


# ---------- internals ----------

def _winsorize(s: pd.Series, lo: float = WINSOR_LOWER, hi: float = WINSOR_UPPER) -> pd.Series:
    return s.clip(lower=s.quantile(lo), upper=s.quantile(hi))


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def _winsor_z(s: pd.Series) -> pd.Series:
    """Winsorize then z-score, ignoring NaNs in the reference distribution."""
    finite = s.dropna()
    if finite.empty:
        return pd.Series(np.nan, index=s.index)
    z = _zscore(_winsorize(finite))
    return z.reindex(s.index)


def _ols_residuals(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return y - X @ beta, beta


# ---------- momentum ----------

def residual_momentum_z(
    returns: pd.DataFrame,
    market_ticker: str,
    sector_etfs: dict[str, str],
    ticker_sector: dict[str, str],
    *,
    long_days: int = 252,
    short_days: int = 126,
    skip_days: int = 22,
    sigma_days: int = 63,
    lookback_days: int = 504,
    min_obs: int = 252,
    sigma_floor: float = 1e-6,
) -> pd.Series:
    """Sector-residualised momentum, sigma-scaled, blended 12-1 / 6-1.

    Each sector ETF is regressed on the market across the lookback to
    extract a market-orthogonal sector residual. Each stock is then
    regressed on [market, sector_residual]. The 12-1 and 6-1 cumulative
    residuals are scaled by the iid-implied standard error
    (sigma_d * sqrt(window)), winsorised + z-scored cross-sectionally,
    blended 50/50, then winsorised + z-scored once more.

    Returns a Series indexed by ticker. NaN for tickers without enough
    history or without a sector ETF mapping.
    """
    if market_ticker not in returns.columns:
        return pd.Series(dtype=float)
    window = returns.tail(lookback_days)
    market = window[market_ticker]

    # Sector residuals first.
    sec_resid: dict[str, pd.Series] = {}
    for sector, etf in sector_etfs.items():
        if etf not in window.columns:
            continue
        df = pd.concat([window[etf].rename("y"), market.rename("m")], axis=1).dropna()
        if len(df) < min_obs:
            continue
        X = np.column_stack([np.ones(len(df)), df["m"].to_numpy()])
        resid, _ = _ols_residuals(df["y"].to_numpy(), X)
        sec_resid[sector] = pd.Series(resid, index=df.index)

    # Per-stock residuals on [market, sector_resid].
    long_w = long_days - skip_days
    short_w = short_days - skip_days
    sqrt_long = float(np.sqrt(long_w))
    sqrt_short = float(np.sqrt(short_w))
    raws: dict[str, tuple[float, float]] = {}
    for ticker in window.columns:
        if ticker == market_ticker:
            continue
        sector = ticker_sector.get(ticker)
        if not sector or sector not in sec_resid:
            continue
        df = pd.concat(
            [window[ticker].rename("y"), market.rename("m"), sec_resid[sector].rename("s")],
            axis=1,
        ).dropna()
        if len(df) < min_obs:
            continue
        X = np.column_stack(
            [np.ones(len(df)), df["m"].to_numpy(), df["s"].to_numpy()]
        )
        stock_resid, _ = _ols_residuals(df["y"].to_numpy(), X)
        n = len(stock_resid)
        if n < long_days:
            continue
        sigma = max(float(np.std(stock_resid[-sigma_days:], ddof=0)), sigma_floor)
        m12 = float(np.sum(stock_resid[-long_days:-skip_days])) / (sigma * sqrt_long)
        m6 = float(np.sum(stock_resid[-short_days:-skip_days])) / (sigma * sqrt_short)
        raws[ticker] = (m12, m6)

    if not raws:
        return pd.Series(dtype=float)

    df = pd.DataFrame.from_dict(raws, orient="index", columns=["m12", "m6"])
    z12 = _winsor_z(df["m12"])
    z6 = _winsor_z(df["m6"])
    blend = 0.5 * z12 + 0.5 * z6
    return _winsor_z(blend).rename("momentum_z")


# ---------- quality ----------

def quality_z(
    funds: dict[str, dict],
    *,
    weights: tuple[float, float, float] = (0.5, 0.2, 0.3),
) -> pd.Series:
    """Strict-policy quality composite.

    Components (all required, no zero-fill, no fallback):
      gross_profitability   = grossProfit_t / totalAssets_t
      gp_change             = gross_profitability_t - gross_profitability_{t-1}
      net_debt_quality      = -(totalDebt - cash) / totalAssets

    Each component is winsorised + z-scored across the universe of
    eligible tickers, blended with `weights`, then winsorised + z-scored
    once more. Tickers missing any input get NaN.
    """
    rows: dict[str, dict] = {}
    for ticker, data in (funds or {}).items():
        income = data.get("income") or []
        balance = data.get("balance") or []
        if not income or not balance or len(income) < 2 or len(balance) < 2:
            continue
        i0, b0 = income[0], balance[0]
        i1, b1 = income[1], balance[1]
        ta = b0.get("totalAssets")
        ta_p = b1.get("totalAssets")
        gp = i0.get("grossProfit")
        gp_p = i1.get("grossProfit")
        debt = b0.get("totalDebt")
        cash = b0.get("cashAndCashEquivalents")
        if cash is None:
            cash = b0.get("cashAndShortTermInvestments")
        if None in (ta, ta_p, gp, gp_p, debt, cash):
            continue
        if ta <= 0 or ta_p <= 0:
            continue
        rows[ticker] = {
            "gp": gp / ta,
            "gp_chg": (gp / ta) - (gp_p / ta_p),
            "nd": -(debt - cash) / ta,
        }
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame.from_dict(rows, orient="index")
    w_gp, w_chg, w_nd = weights
    blend = (
        w_gp * _winsor_z(df["gp"])
        + w_chg * _winsor_z(df["gp_chg"])
        + w_nd * _winsor_z(df["nd"])
    )
    return _winsor_z(blend).rename("quality_z")


# ---------- value ----------

def value_z(
    funds: dict[str, dict],
    prices: pd.DataFrame,
    *,
    weights: tuple[float, float, float] = (0.4, 0.4, 0.2),
) -> pd.Series:
    """Strict-policy value composite.

    Components (all required):
      ebit_ev = EBIT / EnterpriseValue
      fcf_ev  = FreeCashFlow / EnterpriseValue
      book_mc = StockholdersEquity / MarketCap
    where EnterpriseValue = MarketCap + TotalDebt - Cash.

    Tickers missing any input — or with non-positive EV / market cap —
    get NaN.
    """
    rows: dict[str, dict] = {}
    for ticker, data in (funds or {}).items():
        income = data.get("income") or []
        balance = data.get("balance") or []
        cashflow = data.get("cashflow") or []
        if not income or not balance or not cashflow:
            continue
        if ticker not in prices.columns:
            continue
        series = prices[ticker].dropna()
        if series.empty:
            continue
        last = float(series.iloc[-1])
        if last <= 0:
            continue
        i0, b0 = income[0], balance[0]
        c0 = cashflow[0]
        shares = i0.get("weightedAverageShsOutDil")
        ebit = i0.get("ebit") or i0.get("operatingIncome")
        fcf = c0.get("freeCashFlow")
        equity = b0.get("totalStockholdersEquity")
        debt = b0.get("totalDebt")
        cash = b0.get("cashAndCashEquivalents")
        if cash is None:
            cash = b0.get("cashAndShortTermInvestments")
        if None in (shares, ebit, fcf, equity, debt, cash):
            continue
        if shares <= 0:
            continue
        mc = last * shares
        ev = mc + debt - cash
        if mc <= 0 or ev <= 0:
            continue
        rows[ticker] = {
            "ebit_ev": ebit / ev,
            "fcf_ev": fcf / ev,
            "book_mc": equity / mc,
        }
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame.from_dict(rows, orient="index")
    w_ee, w_fe, w_bm = weights
    blend = (
        w_ee * _winsor_z(df["ebit_ev"])
        + w_fe * _winsor_z(df["fcf_ev"])
        + w_bm * _winsor_z(df["book_mc"])
    )
    return _winsor_z(blend).rename("value_z")


# ---------- composite + rank ----------

def composite_rank(
    momentum: pd.Series,
    quality: pd.Series,
    value: pd.Series,
    *,
    weights: tuple[float, float, float] = (0.5, 0.3, 0.2),
) -> pd.DataFrame:
    """Strict-policy composite. Only tickers with all three finite
    z-scores enter the ranking; weights are applied as-is, no
    renormalisation.

    Returns a DataFrame indexed by ticker with columns:
        momentum_z, quality_z, value_z, composite, rank
    sorted by rank ascending (best first).
    """
    df = pd.concat(
        {"momentum_z": momentum, "quality_z": quality, "value_z": value},
        axis=1,
    )
    eligible = df.dropna()
    if eligible.empty:
        return pd.DataFrame(
            columns=["momentum_z", "quality_z", "value_z", "composite", "rank"]
        )
    w_m, w_q, w_v = weights
    eligible = eligible.copy()
    eligible["composite"] = (
        w_m * eligible["momentum_z"]
        + w_q * eligible["quality_z"]
        + w_v * eligible["value_z"]
    )
    eligible["rank"] = (
        eligible["composite"].rank(ascending=False, method="min").astype(int)
    )
    return eligible.sort_values("rank")
