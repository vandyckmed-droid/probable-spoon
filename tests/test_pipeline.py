"""Pytest suite — no live network, all data synthetic."""
import numpy as np
import pandas as pd

import analytics
import store
from config import MOMENTUM_MIN_OBS, MARKET_TICKER


# ---------- helpers ----------

def _resid_frame(tickers, n, seed):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(
        {t: rng.normal(0.0, 0.01, size=n) for t in tickers},
        index=dates,
    )


def _quality_funds(gp, ta, debt, cash):
    return {
        "income": [{"grossProfit": gp}, {}],
        "balance": [
            {"totalAssets": ta, "totalDebt": debt, "cashAndCashEquivalents": cash},
            {},
        ],
        "cashflow": [],
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


# ---------- 1. momentum scale invariance ----------

def test_momentum_scale_invariant():
    tickers = ["A", "B", "C", "D"]
    resid = _resid_frame(tickers, n=500, seed=1)
    ts = {t: "Tech" for t in tickers}

    out1 = analytics.compute_residual_momentum(resid, ts)

    resid2 = resid.copy()
    resid2["A"] = resid2["A"] * 5.0
    out2 = analytics.compute_residual_momentum(resid2, ts)

    assert abs(out1.loc["A", "residual_momentum_z"]
               - out2.loc["A", "residual_momentum_z"]) < 1e-9


# ---------- 2. higher momentum ranks higher ----------

def test_higher_momentum_ranks_higher():
    n = MOMENTUM_MIN_OBS + 100
    rng = np.random.default_rng(2)
    dates = pd.date_range("2022-01-03", periods=n, freq="B")
    tickers = ["LOW", "HIGH"] + [f"X{i}" for i in range(8)]
    data = {}
    for t in tickers:
        rs = rng.normal(0.0, 0.01, size=n)
        if t == "HIGH":
            rs[-(252 + 22):-22] += 0.005
        elif t == "LOW":
            rs[-(252 + 22):-22] -= 0.005
        data[t] = rs
    resid = pd.DataFrame(data, index=dates)

    ts = {t: "Tech" for t in tickers}
    out = analytics.compute_residual_momentum(resid, ts)

    assert out.loc["HIGH", "residual_momentum_z"] > out.loc["LOW", "residual_momentum_z"]


# ---------- 3. quality gp_z above sector ----------

def test_quality_gp_z_positive_when_above_sector():
    funds = {
        "WIN": _quality_funds(gp=200, ta=1000, debt=100, cash=50),  # 0.20
        "MID": _quality_funds(gp=100, ta=1000, debt=100, cash=50),  # 0.10
        "LOW": _quality_funds(gp=50, ta=1000, debt=100, cash=50),   # 0.05
    }
    ts = {t: "Tech" for t in funds}
    df, _ = analytics.compute_quality(funds, ts)
    assert df.loc["WIN", "gp_z"] > 0
    assert df.loc["LOW", "gp_z"] < 0


# ---------- 4. value ebit_ev_z above sector ----------

def test_value_ebit_ev_z_positive_when_above_sector():
    funds = {
        "WIN": _value_funds(ebit=300, fcf=200, shares=100, debt=100, cash=50, equity=500),
        "MID": _value_funds(ebit=150, fcf=100, shares=100, debt=100, cash=50, equity=500),
        "LOW": _value_funds(ebit=50, fcf=30, shares=100, debt=100, cash=50, equity=500),
    }
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    prices = pd.DataFrame({t: [10.0] * 10 for t in funds}, index=dates)
    ts = {t: "Tech" for t in funds}
    df, _ = analytics.compute_value(funds, prices, ts)
    assert df.loc["WIN", "ebit_ev_z"] > 0
    assert df.loc["LOW", "ebit_ev_z"] < 0


# ---------- 5. residuals drop short history ----------

def test_residuals_drop_short_history():
    n = MOMENTUM_MIN_OBS + 50
    rng = np.random.default_rng(3)
    dates = pd.date_range("2022-01-03", periods=n, freq="B")
    market = rng.normal(0.0005, 0.01, size=n)
    sector = market + rng.normal(0.0, 0.005, size=n)
    long_stock = market + rng.normal(0.0, 0.01, size=n)
    short_stock = pd.Series(market + rng.normal(0.0, 0.01, size=n), index=dates)
    short_stock.iloc[:-(MOMENTUM_MIN_OBS - 10)] = np.nan  # leaves <MOMENTUM_MIN_OBS valid

    returns = pd.DataFrame(
        {
            MARKET_TICKER: market,
            "XLK": sector,
            "LONG": long_stock,
            "SHORT": short_stock.to_numpy(),
        },
        index=dates,
    )

    sec_resid = analytics.compute_sector_residuals(returns, {"Tech": "XLK"})
    ts = {"LONG": "Tech", "SHORT": "Tech"}
    stock_resid, _, _ = analytics.compute_stock_residuals(returns, sec_resid, ts)

    assert "LONG" in stock_resid.columns
    assert "SHORT" not in stock_resid.columns


# ---------- 6. composite renormalises when quality drops ----------

def test_composite_renormalises_when_quality_drops():
    tickers = [f"T{i}" for i in range(10)]
    mom_df = pd.DataFrame(
        {
            "sector": ["Tech"] * 10,
            "m12_raw": 0.0, "m6_raw": 0.0, "m1_raw": 0.0,
            "m12_z": 0.0, "m6_z": 0.0, "m1_z": 0.0,
            "residual_momentum_z": np.linspace(-1, 1, 10),
        },
        index=tickers,
    )
    qual_df = pd.DataFrame(
        {
            "sector": ["Tech", "Tech"],
            "gross_profitability": 0.0, "gp_change": 0.0, "balance_sheet_quality": 0.0,
            "gp_z": 0.0, "gp_change_z": 0.0, "nd_z": 0.0,
            "quality_raw": 0.0,
            "quality_z": [0.5, -0.5],
        },
        index=["T0", "T1"],
    )
    val_df = pd.DataFrame(
        {
            "sector": ["Tech"] * 10,
            "market_cap": 1000.0,
            "ebit_ev": 0.0, "fcf_ev": 0.0, "book_mc": 0.0,
            "ebit_ev_z": 0.0, "fcf_ev_z": 0.0, "book_mc_z": 0.0,
            "value_raw": 0.0,
            "value_z": np.linspace(-0.5, 0.5, 10),
        },
        index=tickers,
    )
    ts = {t: "Tech" for t in tickers}
    _, factors_used = analytics.build_ranked(mom_df, qual_df, val_df, ts)

    weights = factors_used["weights"]
    assert "quality" not in weights
    assert "momentum" in weights and "value" in weights
    assert abs(sum(weights.values()) - 1.0) < 1e-9


# ---------- 7. add_to_universe idempotent ----------

def test_add_to_universe_idempotent(tmp_root):
    new1 = store.add_to_universe(["NVDA", "AMD"], fetch=False)
    assert sorted(new1) == ["AMD", "NVDA"]

    extras_path = tmp_root / "data" / "universe_extra.txt"
    after_first = extras_path.read_text()

    new2 = store.add_to_universe(["NVDA", "AMD"], fetch=False)
    assert new2 == []
    assert extras_path.read_text() == after_first


# ---------- 8. add_to_universe uppercases ----------

def test_add_to_universe_uppercases(tmp_root):
    new = store.add_to_universe(["nvda"], fetch=False)
    assert "NVDA" in new

    extras_path = tmp_root / "data" / "universe_extra.txt"
    assert "NVDA" in extras_path.read_text()


# ---------- 9. company_names falls back to ticker ----------

def test_company_names_falls_back_to_ticker(tmp_root):
    assert store.company_names(["XXXXX"]) == {"XXXXX": "XXXXX"}
