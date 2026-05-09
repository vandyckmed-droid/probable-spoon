"""Synthetic-only tests — no live network, no I/O."""
import numpy as np
import pandas as pd

import analytics

MARKET = "VTI"


# ---------- helpers ----------

def _returns_with_market(tickers, n, seed):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-03", periods=n, freq="B")
    cols = {MARKET: rng.normal(0.0005, 0.01, size=n)}
    for t in tickers:
        cols[t] = rng.normal(0.0, 0.01, size=n)
    return pd.DataFrame(cols, index=dates)


def _quality_funds(gp, ta, debt, cash, *, prior_gp=None, prior_ta=None):
    p_gp = gp if prior_gp is None else prior_gp
    p_ta = ta if prior_ta is None else prior_ta
    return {
        "income": [{"grossProfit": gp}, {"grossProfit": p_gp}],
        "balance": [
            {"totalAssets": ta, "totalDebt": debt, "cashAndCashEquivalents": cash},
            {"totalAssets": p_ta, "totalDebt": debt, "cashAndCashEquivalents": cash},
        ],
        "cashflow": [{"freeCashFlow": gp}],
    }


def _value_funds(ebit, fcf, shares, debt, cash, equity):
    return {
        "income": [{"weightedAverageShsOutDil": shares, "ebit": ebit}],
        "balance": [{
            "totalDebt": debt, "cashAndCashEquivalents": cash,
            "totalStockholdersEquity": equity, "totalAssets": 10_000,
        }],
        "cashflow": [{"freeCashFlow": fcf}],
    }


# ---------- log_returns ----------

def test_log_returns_drops_first_row_and_preserves_nan():
    prices = pd.DataFrame(
        {"A": [10, 11, np.nan, 12], "B": [20, 22, 21, 23]},
        index=pd.date_range("2024-01-01", periods=4, freq="B"),
    )
    r = analytics.log_returns(prices)
    assert len(r) == 3
    assert pd.isna(r.iloc[1]["A"])
    assert pd.isna(r.iloc[2]["A"])
    assert np.isclose(r.iloc[0]["B"], np.log(22 / 20))


# ---------- momentum: scale invariance ----------

def test_momentum_scale_invariant():
    n = 600
    tickers = [f"T{i}" for i in range(8)]
    rets = _returns_with_market(tickers, n, seed=1)
    rets["XLK"] = rets[MARKET] + np.random.default_rng(2).normal(0, 0.005, size=n)
    sectors = {t: "Tech" for t in tickers}
    etfs = {"Tech": "XLK"}

    z1 = analytics.residual_momentum_z(rets, MARKET, etfs, sectors)
    rets2 = rets.copy()
    rets2["T0"] = rets2["T0"] * 5.0
    z2 = analytics.residual_momentum_z(rets2, MARKET, etfs, sectors)

    assert abs(z1["T0"] - z2["T0"]) < 1e-9


# ---------- momentum: higher ranks higher ----------

def test_higher_momentum_ranks_higher():
    n = 500
    rng = np.random.default_rng(3)
    dates = pd.date_range("2022-01-03", periods=n, freq="B")
    market = rng.normal(0.0005, 0.01, size=n)
    sector_etf = market + rng.normal(0, 0.005, size=n)
    tickers = ["LOW", "HIGH"] + [f"X{i}" for i in range(8)]
    cols = {MARKET: market, "XLK": sector_etf}
    for t in tickers:
        rs = rng.normal(0.0, 0.01, size=n)
        if t == "HIGH":
            rs[-(252 + 22):-22] += 0.005
        elif t == "LOW":
            rs[-(252 + 22):-22] -= 0.005
        cols[t] = rs
    rets = pd.DataFrame(cols, index=dates)
    sectors = {t: "Tech" for t in tickers}
    etfs = {"Tech": "XLK"}

    z = analytics.residual_momentum_z(rets, MARKET, etfs, sectors)
    assert z["HIGH"] > z["LOW"]


# ---------- quality: above-cohort > below-cohort ----------

def test_quality_z_orders_correctly():
    funds = {
        "WIN": _quality_funds(gp=200, ta=1000, debt=100, cash=50),
        "MID": _quality_funds(gp=100, ta=1000, debt=100, cash=50),
        "LOW": _quality_funds(gp=50, ta=1000, debt=100, cash=50),
    }
    z = analytics.quality_z(funds)
    assert z["WIN"] > z["MID"] > z["LOW"]


# ---------- quality: strict policy excludes missing inputs ----------

def test_quality_excludes_missing_components():
    funds = {
        "FULL_A": _quality_funds(gp=200, ta=1000, debt=100, cash=50),
        "FULL_B": _quality_funds(gp=180, ta=1000, debt=100, cash=50),
        "FULL_C": _quality_funds(gp=150, ta=1000, debt=100, cash=50),
        # No prior period — gp_change uncomputable.
        "NO_PRIOR": {
            "income": [{"grossProfit": 100}],
            "balance": [{"totalAssets": 1000, "totalDebt": 50, "cashAndCashEquivalents": 25}],
            "cashflow": [],
        },
        # Missing total debt entirely.
        "NO_DEBT": {
            "income": [{"grossProfit": 100}, {"grossProfit": 90}],
            "balance": [
                {"totalAssets": 1000, "cashAndCashEquivalents": 25},
                {"totalAssets": 950, "cashAndCashEquivalents": 25},
            ],
            "cashflow": [],
        },
    }
    z = analytics.quality_z(funds)
    assert set(z.dropna().index) == {"FULL_A", "FULL_B", "FULL_C"}
    assert "NO_PRIOR" not in z.index
    assert "NO_DEBT" not in z.index


# ---------- value: above-cohort > below-cohort ----------

def test_value_z_orders_correctly():
    funds = {
        "WIN": _value_funds(ebit=300, fcf=200, shares=100, debt=100, cash=50, equity=500),
        "MID": _value_funds(ebit=150, fcf=100, shares=100, debt=100, cash=50, equity=500),
        "LOW": _value_funds(ebit=50, fcf=30, shares=100, debt=100, cash=50, equity=500),
    }
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    prices = pd.DataFrame({t: [10.0] * 10 for t in funds}, index=dates)

    z = analytics.value_z(funds, prices)
    assert z["WIN"] > z["MID"] > z["LOW"]


# ---------- value: strict policy excludes missing inputs ----------

def test_value_excludes_missing_components():
    funds = {
        "FULL_A": _value_funds(ebit=300, fcf=200, shares=100, debt=100, cash=50, equity=500),
        "FULL_B": _value_funds(ebit=200, fcf=150, shares=100, debt=100, cash=50, equity=500),
        "FULL_C": _value_funds(ebit=100, fcf=80, shares=100, debt=100, cash=50, equity=500),
        # No FCF.
        "NO_FCF": {
            "income": [{"weightedAverageShsOutDil": 100, "ebit": 100}],
            "balance": [{
                "totalDebt": 100, "cashAndCashEquivalents": 50,
                "totalStockholdersEquity": 500, "totalAssets": 10_000,
            }],
            "cashflow": [{}],
        },
    }
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    prices = pd.DataFrame({t: [10.0] * 10 for t in funds}, index=dates)

    z = analytics.value_z(funds, prices)
    assert set(z.dropna().index) == {"FULL_A", "FULL_B", "FULL_C"}
    assert "NO_FCF" not in z.index


# ---------- composite: strict eligibility ----------

def test_composite_excludes_when_any_factor_missing():
    mom = pd.Series({"A": 1.0, "B": 0.5, "C": -0.5, "D": -1.0})
    qual = pd.Series({"A": 0.5, "B": float("nan"), "C": 0.0, "D": 1.0})
    val = pd.Series({"A": 0.0, "B": 0.5, "C": 0.5, "D": 1.0})

    ranked = analytics.composite_rank(mom, qual, val)
    assert set(ranked.index) == {"A", "C", "D"}
    assert "B" not in ranked.index


# ---------- composite: weights apply unchanged, no renormalisation ----------

def test_composite_weights_apply_directly():
    # Three tickers, identical quality and value, momentum varies.
    mom = pd.Series({"A": 1.0, "B": 0.0, "C": -1.0})
    qual = pd.Series({"A": 0.0, "B": 0.0, "C": 0.0})
    val = pd.Series({"A": 0.0, "B": 0.0, "C": 0.0})

    ranked = analytics.composite_rank(mom, qual, val, weights=(0.5, 0.3, 0.2))
    # composite = 0.5 * mom + 0 + 0
    assert np.isclose(ranked.loc["A", "composite"], 0.5)
    assert np.isclose(ranked.loc["B", "composite"], 0.0)
    assert np.isclose(ranked.loc["C", "composite"], -0.5)
    assert ranked.loc["A", "rank"] == 1
    assert ranked.loc["C", "rank"] == 3
