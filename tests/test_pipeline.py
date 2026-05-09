"""Pytest suite — no live network, all data synthetic."""
import numpy as np
import pandas as pd

import analytics
import store
from config import MOMENTUM_MIN_OBS, MARKET_TICKER, W_MOMENTUM, W_QUALITY, W_VALUE


# ---------- helpers ----------

def _resid_frame(tickers, n, seed):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(
        {t: rng.normal(0.0, 0.01, size=n) for t in tickers},
        index=dates,
    )


def _quality_funds(gp, ta, debt, cash, *, prior_gp=None, prior_ta=None):
    """Two-period funds dict for the strict-policy quality test.

    Defaults to a flat prior year so gp_change is computable — the
    strict complete-data policy excludes any ticker without a usable
    prior period rather than back-filling NaN components.
    """
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


# ---------- 6. strict policy excludes names missing a factor ----------

def test_strict_policy_excludes_when_quality_missing():
    """Names without a quality_z are dropped from the ranking and
    surfaced in composite_excluded; the surviving names rank with full
    M+Q+V weights — no renormalisation, no zero-fill."""
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
    ranked, factors_used = analytics.build_ranked(mom_df, qual_df, val_df, ts)

    weights = factors_used["weights"]
    # Configured weights apply unchanged — no renormalisation.
    assert weights == {"momentum": W_MOMENTUM, "quality": W_QUALITY, "value": W_VALUE}

    # Only names with all three z's finite are in the ranked frame.
    assert set(ranked.index) == {"T0", "T1"}

    excluded = factors_used["composite_excluded"]
    assert set(excluded.keys()) == {f"T{i}" for i in range(2, 10)}
    for t in excluded:
        assert any("quality" in r.lower() for r in excluded[t])


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


# ---------- 10. strict policy excludes incomplete quality / value ----------

def test_strict_quality_excludes_missing_components():
    """A ticker missing any required Quality input gets no quality_z and
    is recorded in meta['excluded'] with a human-readable reason."""
    funds = {
        "FULL":   _quality_funds(gp=200, ta=1000, debt=100, cash=50),
        "FULL2":  _quality_funds(gp=180, ta=1000, debt=100, cash=50),
        # Missing prior period → no YoY change.
        "NO_PRIOR": {
            "income": [{"grossProfit": 100}],
            "balance": [{"totalAssets": 1000, "totalDebt": 50, "cashAndCashEquivalents": 25}],
            "cashflow": [],
        },
        # Missing gross profit entirely.
        "NO_GP": {
            "income": [{}, {"grossProfit": 90}],
            "balance": [
                {"totalAssets": 1000, "totalDebt": 50, "cashAndCashEquivalents": 25},
                {"totalAssets": 950, "totalDebt": 50, "cashAndCashEquivalents": 25},
            ],
            "cashflow": [],
        },
    }
    ts = {t: "Tech" for t in funds}
    df, meta = analytics.compute_quality(funds, ts)
    eligible = set(df.index)
    assert "FULL" in eligible and "FULL2" in eligible
    assert "NO_PRIOR" not in eligible
    assert "NO_GP" not in eligible

    excluded = meta["excluded"]
    assert "NO_PRIOR" in excluded
    assert any("YoY" in r for r in excluded["NO_PRIOR"])
    assert "NO_GP" in excluded
    assert any("gross profit" in r for r in excluded["NO_GP"])
    # Coverage uses the active universe (ts) as the denominator.
    assert meta["n_active"] == 4
    assert meta["n_eligible"] == 2
    assert meta["n_excluded"] == 2


def test_strict_value_excludes_missing_components():
    """A ticker missing any required Value input gets no value_z and
    is recorded in meta['excluded'] with a human-readable reason."""
    funds = {
        "FULL":  _value_funds(ebit=300, fcf=200, shares=100, debt=100, cash=50, equity=500),
        "FULL2": _value_funds(ebit=200, fcf=150, shares=100, debt=100, cash=50, equity=500),
        # Missing FCF entirely.
        "NO_FCF": {
            "income": [{"weightedAverageShsOutDil": 100, "ebit": 100}],
            "balance": [{
                "totalDebt": 100, "cashAndCashEquivalents": 50,
                "totalStockholdersEquity": 500, "totalAssets": 10_000,
            }],
            "cashflow": [{}],
        },
        # Missing equity → no book/market.
        "NO_EQUITY": {
            "income": [{"weightedAverageShsOutDil": 100, "ebit": 100}],
            "balance": [{
                "totalDebt": 100, "cashAndCashEquivalents": 50,
                "totalAssets": 10_000,
            }],
            "cashflow": [{"freeCashFlow": 100}],
        },
    }
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    prices = pd.DataFrame({t: [10.0] * 10 for t in funds}, index=dates)
    ts = {t: "Tech" for t in funds}
    df, meta = analytics.compute_value(funds, prices, ts)
    eligible = set(df.index)
    assert "FULL" in eligible and "FULL2" in eligible
    assert "NO_FCF" not in eligible
    assert "NO_EQUITY" not in eligible

    excluded = meta["excluded"]
    assert any("free cash flow" in r for r in excluded["NO_FCF"])
    assert any("equity" in r for r in excluded["NO_EQUITY"])
    assert meta["n_active"] == 4
    assert meta["n_eligible"] == 2


# ---------- 11. preferred-share regex doesn't overmatch ordinary tickers ----------

def test_preferred_regex_does_not_overmatch():
    """The preferred-share suffix pattern should require a series letter
    after .P / -P (e.g. BAC.PA, BAC-PA) so plain tickers ending in P,
    or the bare suffixes .P / -P, don't get swept into 'preferred'."""
    from universe import _classify_one
    # Ordinary common stocks that previously could have been at risk.
    for t in ["MMM", "PEP", "AAPL", "BRK.A", "BRK.B"]:
        status, info = _classify_one(t, {})
        assert status == "eligible", f"{t} should remain eligible: got {info}"
    # Real preferred-share suffixes still get caught.
    for t in ["BAC.PA", "BAC-PA", "BAC.PRA", "BAC-PRA"]:
        status, info = _classify_one(t, {})
        assert status == "excluded" and info == "preferred", f"{t} should be preferred"
