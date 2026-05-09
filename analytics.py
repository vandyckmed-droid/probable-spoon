"""Math module: returns, residualisation, momentum, quality, value, composite, rank."""
import numpy as np
import pandas as pd
from config import (
    MOMENTUM_MIN_OBS, MARKET_TICKER, BETA_LOOKBACK_DAYS,
    MOM_SKIP_DAYS, MOM_LONG_DAYS, MOM_SHORT_DAYS, MOM_REV_DAYS,
    MOM_W_12_1, MOM_W_6_1,
    SIGMA_DAYS, SIGMA_FLOOR, CHART_EMA_SPAN,
    WINSOR_LOWER, WINSOR_UPPER,
    Q_GP_W, Q_GP_CHANGE_W, Q_NETDEBT_W,
    V_EBIT_EV_W, V_FCF_EV_W, V_BP_W,
    W_MOMENTUM, W_QUALITY, W_VALUE,
    QUALITY_FALLBACK_THRESHOLD, VALUE_FALLBACK_THRESHOLD,
    MIN_SECTOR_SIZE,
    EXP_GROWTH_W, EXP_SURPRISE_W,
)


# ===== PART 1: returns & residualisation =====

def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily log returns. Drop the first row. Do NOT forward-fill — preserve NaNs."""
    if prices.empty:
        return prices.copy()
    rets = np.log(prices / prices.shift(1))
    return rets.iloc[1:]


def _ols_residuals(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    """OLS via np.linalg.lstsq. X already has intercept column. Return y - X @ beta."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return y - X @ beta


def compute_sector_residuals(
    returns: pd.DataFrame,
    sector_etf_map: dict[str, str],
) -> dict[str, pd.Series]:
    """Regress each sector ETF on the market over the last BETA_LOOKBACK_DAYS;
    return residual series per sector."""
    if MARKET_TICKER not in returns.columns:
        return {}
    window = returns.tail(BETA_LOOKBACK_DAYS)
    market = window[MARKET_TICKER]
    out: dict[str, pd.Series] = {}
    for sector, etf in sector_etf_map.items():
        if etf not in window.columns:
            continue
        df = pd.concat(
            [window[etf].rename("y"), market.rename("m")], axis=1
        ).dropna()
        if len(df) < MOMENTUM_MIN_OBS:
            continue
        y = df["y"].to_numpy()
        X = np.column_stack([np.ones(len(df)), df["m"].to_numpy()])
        out[sector] = pd.Series(_ols_residuals(y, X), index=df.index)
    return out


def compute_stock_residuals(
    returns: pd.DataFrame,
    sector_residuals: dict[str, pd.Series],
    ticker_sector: dict[str, str],
) -> tuple[pd.DataFrame, dict, dict]:
    """Regress each stock on [market, its sector residual] over the last
    BETA_LOOKBACK_DAYS. Drop on insufficient data."""
    if MARKET_TICKER not in returns.columns:
        return pd.DataFrame(), {}, {}
    window = returns.tail(BETA_LOOKBACK_DAYS)
    market = window[MARKET_TICKER]
    resid_cols: dict[str, pd.Series] = {}
    betas_market: dict[str, float] = {}
    betas_sector: dict[str, float] = {}
    for ticker in window.columns:
        if ticker == MARKET_TICKER:
            continue
        sector = ticker_sector.get(ticker)
        if not sector:
            continue
        sector_resid = sector_residuals.get(sector)
        if sector_resid is None:
            continue
        df = pd.concat(
            [
                window[ticker].rename("y"),
                market.rename("m"),
                sector_resid.rename("s"),
            ],
            axis=1,
        ).dropna()
        if len(df) < MOMENTUM_MIN_OBS:
            continue
        y = df["y"].to_numpy()
        X = np.column_stack(
            [np.ones(len(df)), df["m"].to_numpy(), df["s"].to_numpy()]
        )
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid_cols[ticker] = pd.Series(y - X @ beta, index=df.index)
        betas_market[ticker] = float(beta[1])
        betas_sector[ticker] = float(beta[2])
    if not resid_cols:
        return pd.DataFrame(), betas_market, betas_sector
    return pd.DataFrame(resid_cols).sort_index(), betas_market, betas_sector


# ===== PART 2: momentum =====

def _winsorize(s: pd.Series, lower: float = WINSOR_LOWER, upper: float = WINSOR_UPPER) -> pd.Series:
    """Clip non-null values to [quantile(lower), quantile(upper)]. Preserve index and NaNs."""
    return s.clip(lower=s.quantile(lower), upper=s.quantile(upper))


def _zscore(s: pd.Series) -> pd.Series:
    """(s - mean) / std (ddof=0). Zeros aligned to s.index when std is 0 or NaN."""
    mean = s.mean()
    std = s.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=s.index)
    return (s - mean) / std


def compute_residual_momentum(
    stock_residuals: pd.DataFrame,
    ticker_sector: dict[str, str],
) -> pd.DataFrame:
    """Risk-adjusted residual momentum sleeves, cross-sectional z, 50/50 composite.

    For each ticker:
      sigma_d       = std(resid[-SIGMA_DAYS:], ddof=0), floored at SIGMA_FLOOR.
      m12_raw       = sum(resid[-MOM_LONG_DAYS:-MOM_SKIP_DAYS])
                       / (sigma_d * sqrt(MOM_LONG_DAYS - MOM_SKIP_DAYS))
      m6_raw        = sum(resid[-MOM_SHORT_DAYS:-MOM_SKIP_DAYS])
                       / (sigma_d * sqrt(MOM_SHORT_DAYS - MOM_SKIP_DAYS))
      m1_raw        = sum(resid[-MOM_REV_DAYS:])
                       / (sigma_d * sqrt(MOM_REV_DAYS))   # diagnostic only

    Each cumulative window is divided by its own iid-implied standard error
    (sigma_d * sqrt(K)), so the raw values read as proper σ on the cumulative
    move. The cross-sectional z below is invariant to a constant scaling, so
    rankings/composites are mathematically unchanged versus the previous
    sigma_d-only divisor.

    Each sleeve is then winsorized + z-scored across the universe, combined
    50/50, and z-scored once more.
    """
    rows: dict[str, dict] = {}
    long_window = MOM_LONG_DAYS - MOM_SKIP_DAYS
    short_window = MOM_SHORT_DAYS - MOM_SKIP_DAYS
    rev_window = MOM_REV_DAYS
    sqrt_long = float(np.sqrt(long_window))
    sqrt_short = float(np.sqrt(short_window))
    sqrt_rev = float(np.sqrt(rev_window))
    for ticker in stock_residuals.columns:
        s = stock_residuals[ticker].dropna()
        n = len(s)
        arr = s.to_numpy()
        if n < SIGMA_DAYS:
            rows[ticker] = {
                "sector": ticker_sector.get(ticker, "Unknown"),
                "m12_raw": float("nan"), "m6_raw": float("nan"), "m1_raw": float("nan"),
            }
            continue
        sigma = max(float(np.std(arr[-SIGMA_DAYS:], ddof=0)), SIGMA_FLOOR)
        m12 = (
            float(np.sum(arr[-MOM_LONG_DAYS:-MOM_SKIP_DAYS])) / (sigma * sqrt_long)
            if n >= MOM_LONG_DAYS else float("nan")
        )
        m6 = (
            float(np.sum(arr[-MOM_SHORT_DAYS:-MOM_SKIP_DAYS])) / (sigma * sqrt_short)
            if n >= MOM_SHORT_DAYS else float("nan")
        )
        m1 = (
            float(np.sum(arr[-MOM_REV_DAYS:])) / (sigma * sqrt_rev)
            if n >= MOM_REV_DAYS else float("nan")
        )
        rows[ticker] = {
            "sector": ticker_sector.get(ticker, "Unknown"),
            "m12_raw": m12, "m6_raw": m6, "m1_raw": m1,
        }
    df = pd.DataFrame.from_dict(rows, orient="index")
    if df.empty:
        return df
    df["m12_z"] = _zscore(_winsorize(df["m12_raw"]))
    df["m6_z"] = _zscore(_winsorize(df["m6_raw"]))
    df["m1_z"] = _zscore(_winsorize(df["m1_raw"]))
    combined = MOM_W_12_1 * df["m12_z"] + MOM_W_6_1 * df["m6_z"]
    df["residual_momentum_z"] = _zscore(_winsorize(combined))
    return df[
        ["sector", "m12_raw", "m6_raw", "m1_raw",
         "m12_z", "m6_z", "m1_z", "residual_momentum_z"]
    ]


def compute_diagnostics(
    stock_residuals: pd.DataFrame,
    tickers: list[str],
    chart_lookback: int = 252,
) -> dict:
    """Per-ticker residual diagnostics for the expanded card.

    The chart series is the rolling 6-1 residual-momentum sleeve used in the
    momentum composite, evaluated at every date over the lookback. At each
    date `e` the value is

        sum(resid[e - MOM_SHORT_DAYS + 1 : e - MOM_SKIP_DAYS + 1])
            / (max(std(resid[e - SIGMA_DAYS + 1 : e + 1], ddof=0), SIGMA_FLOOR)
               * sqrt(MOM_SHORT_DAYS - MOM_SKIP_DAYS))

    so the endpoint matches `m6_raw` in `compute_residual_momentum` exactly.
    Values are in proper σ units (cumulative-move standard errors).

    Returns a dict keyed by ticker with:
        chart_m6:    [floats], the rolling sigma-scaled 6-1 series
                      (last `chart_lookback` trading days).
        current_m6:  float, the most recent value of chart_m6 — i.e. the
                      m6_raw used in the momentum composite, in σ units.
        pullback_z:  float, last 21d cumulative residual / (sigma_daily *
                      sqrt(21)) — raw short-term timing aid.
        ema_span:    int, EMA span applied to the chart series (1 = none).
    """
    out: dict = {}
    if stock_residuals is None or stock_residuals.empty:
        return out
    ema_span = max(1, int(CHART_EMA_SPAN))
    sum_window = MOM_SHORT_DAYS - MOM_SKIP_DAYS
    sqrt_window = float(np.sqrt(sum_window))
    for t in tickers:
        if t not in stock_residuals.columns:
            continue
        s = stock_residuals[t].dropna()
        if len(s) < MOM_SHORT_DAYS:
            continue
        # Rolling 6-1 numerator: sum of the 105-day window that ends 21 days
        # before each date. Shifting by MOM_SKIP_DAYS first, then summing the
        # next (MOM_SHORT_DAYS - MOM_SKIP_DAYS) days, gives exactly the slice
        # arr[-MOM_SHORT_DAYS:-MOM_SKIP_DAYS] when evaluated at the endpoint.
        rolling_sum = s.shift(MOM_SKIP_DAYS).rolling(sum_window).sum()
        rolling_sigma = (
            s.rolling(SIGMA_DAYS).std(ddof=0).clip(lower=SIGMA_FLOOR)
        )
        m6_series = (rolling_sum / (rolling_sigma * sqrt_window)).dropna()
        if m6_series.empty:
            continue
        # Very gentle EMA on the chart so day-to-day noise does not zigzag a
        # chart that is meant to read as longer-horizon strength. The endpoint
        # then no longer exactly equals m6_raw, so we report the raw last
        # value as current_m6 to keep the headline tied to the composite.
        if ema_span > 1:
            chart_full = m6_series.ewm(span=ema_span, adjust=False).mean()
        else:
            chart_full = m6_series
        chart = chart_full.tail(chart_lookback)
        current_m6 = float(m6_series.iloc[-1])
        sigma_daily = max(float(s.tail(SIGMA_DAYS).std(ddof=0)), SIGMA_FLOOR)
        pullback_z = float("nan")
        if len(s) >= MOM_REV_DAYS:
            recent_21 = float(s.tail(MOM_REV_DAYS).sum())
            pullback_z = recent_21 / (sigma_daily * float(np.sqrt(MOM_REV_DAYS)))
        out[t] = {
            "chart_m6": [float(x) for x in chart.tolist()],
            "current_m6": current_m6,
            "pullback_z": float(pullback_z) if np.isfinite(pullback_z) else 0.0,
            "ema_span": ema_span,
        }
    return out


# ===== PART 3: quality & value =====

def _winsor_zscore_within_sector(s: pd.Series, sectors: pd.Series) -> pd.Series:
    """Within-sector winsorize+z when the sector has at least MIN_SECTOR_SIZE
    finite members; otherwise fall back to a universe-wide z for those tickers.
    Preserves NaN where the input itself is NaN.
    """
    out = pd.Series(np.nan, index=s.index, dtype=float)
    sec = sectors.reindex(s.index)
    fallback_idx: list = []
    for _, idx in sec.groupby(sec).groups.items():
        group = s.loc[idx]
        if group.dropna().shape[0] >= MIN_SECTOR_SIZE:
            out.loc[idx] = _zscore(_winsorize(group))
        else:
            fallback_idx.extend(idx)
    if fallback_idx:
        universe_z = _zscore(_winsorize(s))
        out.loc[fallback_idx] = universe_z.loc[fallback_idx]
    return out


def compute_quality(
    funds: dict,
    ticker_sector: dict[str, str],
) -> tuple[pd.DataFrame, dict]:
    """Sector-relative z on quality components, then a universe-wide z on
    the weighted composite so quality_z is comparable to momentum_z."""
    rows: dict[str, dict] = {}
    for ticker, data in funds.items():
        if ticker not in ticker_sector:
            continue
        income = data.get("income") or []
        balance = data.get("balance") or []
        if not income or not balance:
            continue
        inc_t = income[0]
        bal_t = balance[0]
        ta_t = bal_t.get("totalAssets")
        if not ta_t or ta_t <= 0:
            continue
        gp_t = inc_t.get("grossProfit")
        debt_t = bal_t.get("totalDebt")
        cash_t = bal_t.get("cashAndCashEquivalents")
        if cash_t is None:
            cash_t = bal_t.get("cashAndShortTermInvestments")
        gp_ratio = (gp_t / ta_t) if gp_t is not None else float("nan")
        gp_change = float("nan")
        if len(income) > 1 and len(balance) > 1:
            gp_t1 = income[1].get("grossProfit")
            ta_t1 = balance[1].get("totalAssets")
            if gp_t is not None and gp_t1 is not None and ta_t1 and ta_t1 > 0:
                gp_change = (gp_t / ta_t) - (gp_t1 / ta_t1)
        if debt_t is not None and cash_t is not None:
            bsq = -(debt_t - cash_t) / ta_t
        else:
            bsq = float("nan")
        if pd.isna(gp_ratio) and pd.isna(bsq):
            continue
        rows[ticker] = {
            "sector": ticker_sector.get(ticker, "Unknown"),
            "gross_profitability": gp_ratio,
            "gp_change": gp_change,
            "balance_sheet_quality": bsq,
        }
    if not rows:
        return pd.DataFrame(), {"coverage": 0.0}
    df = pd.DataFrame.from_dict(rows, orient="index")
    sectors = df["sector"]
    df["gp_z"] = _winsor_zscore_within_sector(df["gross_profitability"], sectors)
    df["gp_change_z"] = _winsor_zscore_within_sector(df["gp_change"], sectors)
    df["nd_z"] = _winsor_zscore_within_sector(df["balance_sheet_quality"], sectors)
    df["quality_raw"] = (
        Q_GP_W * df["gp_z"].fillna(0)
        + Q_GP_CHANGE_W * df["gp_change_z"].fillna(0)
        + Q_NETDEBT_W * df["nd_z"].fillna(0)
    )
    df["quality_z"] = _zscore(_winsorize(df["quality_raw"]))
    coverage = df["quality_z"].notna().sum() / len(funds) if funds else 0.0
    cols = ["sector", "gross_profitability", "gp_change", "balance_sheet_quality",
            "gp_z", "gp_change_z", "nd_z", "quality_raw", "quality_z"]
    return df[cols], {"coverage": float(coverage)}


def compute_value(
    funds: dict,
    prices: pd.DataFrame,
    ticker_sector: dict[str, str],
) -> tuple[pd.DataFrame, dict]:
    """Sector-relative z on value components, then a universe-wide z on
    the weighted composite so value_z is comparable to momentum_z."""
    rows: dict[str, dict] = {}
    for ticker, data in funds.items():
        if ticker not in ticker_sector:
            continue
        income = data.get("income") or []
        balance = data.get("balance") or []
        cashflow = data.get("cashflow") or []
        if not income or not balance:
            continue
        if ticker not in prices.columns:
            continue
        price_series = prices[ticker].dropna()
        if price_series.empty:
            continue
        latest_close = float(price_series.iloc[-1])
        inc_t = income[0]
        bal_t = balance[0]
        cf_t = cashflow[0] if cashflow else {}
        shares = inc_t.get("weightedAverageShsOutDil")
        if not shares or shares <= 0 or latest_close <= 0:
            continue
        market_cap = latest_close * shares
        debt = bal_t.get("totalDebt") or 0
        cash = bal_t.get("cashAndCashEquivalents") or 0
        ev = market_cap + debt - cash
        if ev <= 0:
            continue
        ebit = inc_t.get("ebit")
        if ebit is None:
            ebit = inc_t.get("operatingIncome")
        fcf = cf_t.get("freeCashFlow")
        equity = bal_t.get("totalStockholdersEquity")
        ebit_ev = (ebit / ev) if ebit is not None else float("nan")
        fcf_ev = (fcf / ev) if fcf is not None else float("nan")
        book_mc = (equity / market_cap) if equity is not None else float("nan")
        rows[ticker] = {
            "sector": ticker_sector.get(ticker, "Unknown"),
            "market_cap": market_cap,
            "ebit_ev": ebit_ev, "fcf_ev": fcf_ev, "book_mc": book_mc,
        }
    if not rows:
        return pd.DataFrame(), {"coverage": 0.0}
    df = pd.DataFrame.from_dict(rows, orient="index")
    sectors = df["sector"]
    df["ebit_ev_z"] = _winsor_zscore_within_sector(df["ebit_ev"], sectors)
    df["fcf_ev_z"] = _winsor_zscore_within_sector(df["fcf_ev"], sectors)
    df["book_mc_z"] = _winsor_zscore_within_sector(df["book_mc"], sectors)
    df["value_raw"] = (
        V_EBIT_EV_W * df["ebit_ev_z"].fillna(0)
        + V_FCF_EV_W * df["fcf_ev_z"].fillna(0)
        + V_BP_W * df["book_mc_z"].fillna(0)
    )
    df["value_z"] = _zscore(_winsorize(df["value_raw"]))
    coverage = df["value_z"].notna().sum() / len(funds) if funds else 0.0
    cols = ["sector", "market_cap", "ebit_ev", "fcf_ev", "book_mc",
            "ebit_ev_z", "fcf_ev_z", "book_mc_z", "value_raw", "value_z"]
    return df[cols], {"coverage": float(coverage)}


def compute_expectations(
    revisions_data: dict,
    ticker_sector: dict[str, str],
) -> tuple[pd.DataFrame, dict]:
    """Diagnostic Expectations score from analyst estimates + earnings surprises.

    Components:
      growth   = next-year EPS consensus / current-year EPS consensus − 1
                 (only when current consensus > 0)
      surprise = (actual_eps − estimated_eps) / |estimated_eps|
                 (most recent reported quarter)

    Each component is winsorised + z-scored within sector (small-sector
    fallback to a universe-wide z below MIN_SECTOR_SIZE), blended
    EXP_GROWTH_W / EXP_SURPRISE_W, then a universe-wide winsor + z-score
    on the composite produces expectations_z.

    Returns (df, meta). df is indexed by ticker with columns:
        sector, growth, surprise, growth_z, surprise_z,
        expectations_raw, expectations_z
    meta = {"coverage": fraction_of_input_tickers_with_finite_z}.
    """
    rows: dict[str, dict] = {}
    for ticker, data in revisions_data.items():
        if ticker not in ticker_sector:
            continue
        estimates = data.get("estimates") or []
        surprises = data.get("surprises") or []

        # Forward EPS growth from the two nearest annual consensus snapshots.
        growth = float("nan")
        valid_est = [e for e in estimates if isinstance(e, dict) and e.get("date")]
        if len(valid_est) >= 2:
            sorted_est = sorted(valid_est, key=lambda e: e.get("date") or "")
            curr = sorted_est[0].get("epsAvg")
            nxt = sorted_est[1].get("epsAvg")
            if (
                isinstance(curr, (int, float)) and isinstance(nxt, (int, float))
                and curr > 0
            ):
                growth = float(nxt) / float(curr) - 1.0

        # Most recent earnings surprise, scaled by |estimate|.
        surprise = float("nan")
        if surprises and isinstance(surprises[0], dict):
            recent = surprises[0]
            actual = recent.get("actualEarningResult")
            estimate = recent.get("estimatedEarning")
            if (
                isinstance(actual, (int, float))
                and isinstance(estimate, (int, float))
                and estimate != 0
            ):
                surprise = (float(actual) - float(estimate)) / abs(float(estimate))

        if pd.isna(growth) and pd.isna(surprise):
            continue
        rows[ticker] = {
            "sector": ticker_sector.get(ticker, "Unknown"),
            "growth": growth,
            "surprise": surprise,
        }

    if not rows:
        return pd.DataFrame(), {"coverage": 0.0}
    df = pd.DataFrame.from_dict(rows, orient="index")
    sectors = df["sector"]
    df["growth_z"] = _winsor_zscore_within_sector(df["growth"], sectors)
    df["surprise_z"] = _winsor_zscore_within_sector(df["surprise"], sectors)
    df["expectations_raw"] = (
        EXP_GROWTH_W * df["growth_z"].fillna(0)
        + EXP_SURPRISE_W * df["surprise_z"].fillna(0)
    )
    df["expectations_z"] = _zscore(_winsorize(df["expectations_raw"]))
    coverage = (
        df["expectations_z"].notna().sum() / len(revisions_data)
        if revisions_data else 0.0
    )
    cols = ["sector", "growth", "surprise", "growth_z", "surprise_z",
            "expectations_raw", "expectations_z"]
    return df[cols], {"coverage": float(coverage)}


# ===== PART 4: composite & ranking =====

_FACTOR_COL = {
    "momentum": "residual_momentum_z",
    "quality": "quality_z",
    "value": "value_z",
}

_FINAL_COLS = [
    "sector", "market_cap",
    "m12_raw", "m6_raw", "m1_raw", "m12_z", "m6_z", "m1_z", "residual_momentum_z",
    "gross_profitability", "gp_change", "balance_sheet_quality",
    "gp_z", "gp_change_z", "nd_z", "quality_raw", "quality_z",
    "ebit_ev", "fcf_ev", "book_mc", "ebit_ev_z", "fcf_ev_z", "book_mc_z",
    "value_raw", "value_z",
    "composite", "rank", "sector_rank",
]


def build_ranked(
    mom_df: pd.DataFrame,
    qual_df: pd.DataFrame,
    val_df: pd.DataFrame,
    ticker_sector: dict[str, str],
) -> tuple[pd.DataFrame, dict]:
    """Outer-join factor frames, apply coverage fallback, compute composite/rank."""
    parts = []
    for d in (mom_df, qual_df, val_df):
        if d is not None and not d.empty:
            parts.append(d.drop(columns=["sector"], errors="ignore"))
    df = pd.concat(parts, axis=1, join="outer") if parts else pd.DataFrame()
    if df.empty:
        return df, {"weights": {}, "quality": False, "value": False}

    df["sector"] = pd.Series(
        {t: ticker_sector.get(t, "Unknown") for t in df.index}
    )

    n = len(df)
    qual_z = df["quality_z"] if "quality_z" in df.columns else pd.Series(dtype=float)
    val_z = df["value_z"] if "value_z" in df.columns else pd.Series(dtype=float)
    qual_coverage = qual_z.notna().sum() / n if n else 0.0
    val_coverage = val_z.notna().sum() / n if n else 0.0
    use_quality = qual_coverage >= QUALITY_FALLBACK_THRESHOLD
    use_value = val_coverage >= VALUE_FALLBACK_THRESHOLD

    raw = {
        "momentum": W_MOMENTUM,
        "quality": W_QUALITY if use_quality else 0.0,
        "value": W_VALUE if use_value else 0.0,
    }
    total = sum(raw.values())
    weights = (
        {k: v / total for k, v in raw.items() if v > 0} if total > 0 else {}
    )

    composite = pd.Series(0.0, index=df.index)
    for k, w in weights.items():
        col = _FACTOR_COL[k]
        series = df[col] if col in df.columns else pd.Series(0.0, index=df.index)
        composite = composite + w * series.fillna(0)
    df["composite"] = composite
    df["rank"] = df["composite"].rank(ascending=False, method="min").astype(int)
    df["sector_rank"] = (
        df.groupby("sector")["composite"]
        .rank(ascending=False, method="min")
        .astype(int)
    )

    for c in _FINAL_COLS:
        if c not in df.columns:
            df[c] = float("nan")
    df = df[_FINAL_COLS].sort_values("rank")
    factors_used = {"weights": weights, "quality": use_quality, "value": use_value}
    return df, factors_used
