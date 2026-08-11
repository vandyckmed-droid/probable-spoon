"""Sector-index tests — synthetic data only, no network."""
import math

import numpy as np
import pandas as pd
import pytest

import config
import sector_index


def _wiggle(n):
    """Zero-net alternating noise: adds volatility without moving endpoints."""
    return np.tile([1.0, -1.0], (n + 1) // 2)[:n]


def _levels(n, drift, wiggle=0.002):
    rets = drift + wiggle * _wiggle(n)
    return pd.Series(
        100.0 * np.exp(np.cumsum(rets)),
        index=pd.date_range("2023-01-02", periods=n, freq="B"),
    )


def _panel(tickers, n, seed=0, drift=0.0004, vol=0.01):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    data = {}
    for i, t in enumerate(tickers):
        rets = rng.normal(drift, vol, size=n)
        data[t] = 100.0 * np.exp(np.cumsum(rets))
    return pd.DataFrame(data, index=dates)


# ---------- window geometry ----------

def test_window_is_nine_minus_one():
    n = 300
    start, end = sector_index.window_bounds(n)
    assert n - 1 - end == config.MOM_9_1_SKIP_DAYS      # skips the last month
    assert n - 1 - start == config.MOM_9_1_LONG_DAYS    # opens 9 months back
    assert end - start == config.MOM_9_1_LONG_DAYS - config.MOM_9_1_SKIP_DAYS


def test_score_ignores_the_skipped_month():
    levels = _levels(260, 0.0005)
    base = sector_index.vol_adjusted_9_1(levels)

    shocked = levels.copy()
    shocked.iloc[-config.MOM_9_1_SKIP_DAYS:] *= 1.5   # last month only
    after = sector_index.vol_adjusted_9_1(shocked)

    assert base["ann_log_return"] == after["ann_log_return"]
    assert base["ann_vol"] == after["ann_vol"]


# ---------- annualisation ----------

def test_both_legs_annualised_on_the_same_window():
    n = 260
    daily = 0.0006
    levels = _levels(n, daily)
    stats = sector_index.vol_adjusted_9_1(levels)
    obs = config.MOM_9_1_LONG_DAYS - config.MOM_9_1_SKIP_DAYS

    assert stats["window_obs"] == obs
    assert math.isclose(stats["log_return_9_1"], daily * obs, rel_tol=1e-9)
    # numerator annualises the same window it measures
    assert math.isclose(
        stats["ann_log_return"],
        stats["log_return_9_1"] * config.TRADING_DAYS_PER_YEAR / obs,
        rel_tol=1e-12,
    )


def test_vol_leg_annualises_by_sqrt_time():
    rng = np.random.default_rng(7)
    n = 260
    sigma_d = 0.012
    rets = rng.normal(0.0, sigma_d, size=n)
    levels = pd.Series(
        100.0 * np.exp(np.cumsum(rets)),
        index=pd.date_range("2023-01-02", periods=n, freq="B"),
    )
    stats = sector_index.vol_adjusted_9_1(levels)
    start, end = sector_index.window_bounds(n)
    window_sigma = np.std(np.diff(np.log(levels.iloc[start:end + 1])), ddof=1)

    assert math.isclose(
        stats["ann_vol"],
        window_sigma * math.sqrt(config.TRADING_DAYS_PER_YEAR),
        rel_tol=1e-12,
    )


def test_score_is_scale_invariant_in_index_level():
    levels = pd.Series(
        100.0 * np.exp(np.cumsum(np.random.default_rng(3).normal(3e-4, 0.01, 260))),
        index=pd.date_range("2023-01-02", periods=260, freq="B"),
    )
    a = sector_index.vol_adjusted_9_1(levels)
    b = sector_index.vol_adjusted_9_1(levels * 7.5)
    assert math.isclose(a["score"], b["score"], rel_tol=1e-9)


def test_higher_vol_same_return_scores_lower():
    n = 260
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    calm = _levels(n, 5e-4, wiggle=0.004)
    wild = _levels(n, 5e-4, wiggle=0.020)
    assert calm.index.equals(idx) and wild.index.equals(idx)

    calm_stats = sector_index.vol_adjusted_9_1(calm)
    wild_stats = sector_index.vol_adjusted_9_1(wild)
    assert math.isclose(
        calm_stats["ann_log_return"], wild_stats["ann_log_return"], rel_tol=1e-9
    )
    assert wild_stats["ann_vol"] > 4.5 * calm_stats["ann_vol"]
    assert calm_stats["score"] > wild_stats["score"]


# ---------- index construction ----------

def test_equal_weight_index_averages_constituents():
    px = _panel(["A", "B", "C"], 60, seed=5)
    levels = sector_index.equal_weight_index(px)
    expected = px.pct_change().mean(axis=1).iloc[1:]
    got = levels.pct_change()
    assert math.isclose(got.iloc[1], expected.iloc[1], rel_tol=1e-12)
    assert len(levels) == len(px) - 1


def test_equal_weight_index_is_weight_not_price_weighted():
    """A 10x share price on one name must not change the index path."""
    px = _panel(["A", "B"], 60, seed=9)
    base = sector_index.equal_weight_index(px)
    scaled = px.copy()
    scaled["A"] = scaled["A"] * 10.0
    assert np.allclose(base.to_numpy(), sector_index.equal_weight_index(scaled).to_numpy())


# ---------- selection ----------

def _candidates(tickers):
    return [
        {"ticker": t, "name": t, "sector": "Tech", "industry": "x",
         "market_cap": 1e10, "screen_dollar_volume": 1e8}
        for t in tickers
    ]


def test_selection_takes_most_liquid_and_drops_short_history():
    n = 260
    tickers = [f"T{i:02d}" for i in range(config.SECTOR_INDEX_SIZE + 5)]
    closes = _panel(tickers, n, seed=2)
    # T00 is the most liquid name but only started trading recently.
    closes.loc[closes.index[:n - 30], "T00"] = np.nan
    volumes = pd.DataFrame(
        {t: np.full(n, 1e6 * (len(tickers) - i)) for i, t in enumerate(tickers)},
        index=closes.index,
    )

    chosen, rejected = sector_index.select_constituents(
        _candidates(tickers), closes, volumes
    )
    picked = [c["ticker"] for c in chosen]

    assert len(picked) == config.SECTOR_INDEX_SIZE
    assert "T00" not in picked
    assert any(r["ticker"] == "T00" and "window" in r["reason"] for r in rejected)
    advs = [c["median_dollar_volume"] for c in chosen]
    assert advs == sorted(advs, reverse=True)


def test_trading_calendar_drops_phantom_dates():
    px = _panel(["A", "B", "C", "D", "E"], 40, seed=4)
    phantom = pd.Timestamp("2023-01-14")   # a Saturday only one ticker "traded"
    px.loc[phantom] = [np.nan] * 5
    px.loc[phantom, "A"] = 101.0
    px = px.sort_index()

    kept = sector_index.trading_calendar(px)
    assert phantom not in kept.index
    assert len(kept) == 40


# ---------- per-name scoring ----------

def _members(tickers):
    return [{"ticker": t, "name": t, "industry": "x", "market_cap": 1e10,
             "median_dollar_volume": 1e8} for t in tickers]


def test_members_are_scored_and_ranked_within_sector():
    n = 260
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    # Deliberately ordered drifts: C is the strongest, A the weakest.
    px = pd.DataFrame({
        t: _levels(n, drift).to_numpy()
        for t, drift in (("A", 1e-4), ("B", 4e-4), ("C", 9e-4))
    }, index=idx)

    scored = sector_index.score_constituents(px, _members(["A", "B", "C"]))

    assert [r["ticker"] for r in scored] == ["C", "B", "A"]   # sorted best first
    assert [r["sector_rank"] for r in scored] == [1, 2, 3]
    assert scored[0]["score"] > scored[-1]["score"]
    assert scored[0]["sector_z"] > 0 > scored[-1]["sector_z"]
    assert abs(sum(r["sector_z"] for r in scored)) < 1e-9   # z is peer-relative


def test_member_scores_match_the_index_treatment():
    """A one-name sector's member score is exactly its index score."""
    n = 260
    px = pd.DataFrame({"A": _levels(n, 5e-4)})
    scored = sector_index.score_constituents(px, _members(["A"]))
    index_stats = sector_index.vol_adjusted_9_1(sector_index.equal_weight_index(px))

    # The index drops the first row, so allow the one-day framing difference.
    assert scored[0]["score"] == pytest.approx(index_stats["score"], rel=0.02)


def test_scoring_survives_a_degenerate_member():
    n = 260
    px = pd.DataFrame({
        "A": _levels(n, 5e-4).to_numpy(),
        "FLAT": np.full(n, 50.0),          # zero variance -> unscorable
    }, index=pd.date_range("2023-01-02", periods=n, freq="B"))

    scored = sector_index.score_constituents(px, _members(["A", "FLAT"]))
    by_ticker = {r["ticker"]: r for r in scored}

    assert by_ticker["FLAT"]["score"] is None
    assert by_ticker["FLAT"]["sector_rank"] is None
    assert by_ticker["A"]["sector_rank"] == 1
    assert scored[-1]["ticker"] == "FLAT"   # unscorable names sort last
