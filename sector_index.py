"""25-name equal-weight sector "ETFs", ranked on volatility-adjusted 9-1 momentum.

Build
-----
1. Screen every liquid US common stock (screener.py) and shortlist candidates
   per sector on screener dollar volume.
2. Pull ~500 calendar days of adjusted closes, then pick the 25 most liquid
   survivors per sector on median 63-day dollar volume, requiring complete
   price history across the scoring window.
3. Chain each sector's constituents into a daily-rebalanced equal-weight index.

Score
-----
9-1 momentum: the log return from t-9 months to t-1 month, i.e. the last month
is skipped. Numerator and denominator use that same window and both are
annualised, so the score is a Sharpe-like ratio of excess-of-nothing return
to risk:

    numerator   = ln(L[t-1m] / L[t-9m]) * 252 / obs
    denominator = stdev(daily log returns over the window, ddof=1) * sqrt(252)
    score       = numerator / denominator

Constituents are the *current* most-liquid names, so the index history is
backward-looking on today's membership — fine for cross-sector ranking, but it
is not a tradable backtest.
"""
import argparse
import csv
import datetime as dt
import json
import math
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

import analytics
import config
import prices as prices_mod
import screener

TRADING_DAYS = config.TRADING_DAYS_PER_YEAR

# Cap-weighted reference for --benchmark. Not used in the build itself.
SPDR_SECTOR_ETFS = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
    "Communication Services": "XLC",
}


# ---------------------------------------------------------------- prices ----

def _load_price_cache() -> dict:
    p = Path(config.SECTOR_PRICES_CACHE)
    if not p.exists():
        return {"as_of": None, "prices": {}, "volumes": {}}
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except (OSError, pickle.UnpicklingError, EOFError):
        return {"as_of": None, "prices": {}, "volumes": {}}


def _save_price_cache(cache: dict) -> None:
    p = Path(config.SECTOR_PRICES_CACHE)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            pickle.dump(cache, f)
    except (OSError, PermissionError) as e:
        print(f"WARNING: could not save price cache to {p}: {e}")


def _cache_is_stale(cache: dict) -> bool:
    as_of = cache.get("as_of")
    if not as_of:
        return True
    try:
        as_of_dt = dt.date.fromisoformat(as_of)
    except (TypeError, ValueError):
        return True
    return (dt.date.today() - as_of_dt).days >= config.SECTOR_PRICES_REFRESH_DAYS


def fetch_history(
    tickers: list[str], *, force: bool = False, no_fetch: bool = False
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(closes, volumes) for `tickers`, topping up the on-disk cache."""
    tickers = list(dict.fromkeys(tickers))
    cache = _load_price_cache()
    px: dict[str, pd.Series] = dict(cache.get("prices") or {})
    vol: dict[str, pd.Series] = dict(cache.get("volumes") or {})

    if no_fetch:
        to_fetch: list[str] = []
    elif force or _cache_is_stale(cache):
        to_fetch = list(tickers)
    else:
        to_fetch = [t for t in tickers if t not in px]

    from_date = (
        dt.date.today() - dt.timedelta(days=config.SECTOR_HISTORY_DAYS)
    ).isoformat()

    if to_fetch:
        print(f"fetching {len(to_fetch)} price history(ies)...")
    for i, ticker in enumerate(to_fetch, 1):
        if i % 25 == 0 or i == len(to_fetch):
            print(f"  [{i}/{len(to_fetch)}]")
        p, v = prices_mod.fetch_one(ticker, from_date)
        if not p.empty:
            px[ticker] = p
            vol[ticker] = v

    if to_fetch:
        _save_price_cache(
            {"as_of": dt.date.today().isoformat(), "prices": px, "volumes": vol}
        )

    have = [t for t in tickers if t in px]
    closes = pd.DataFrame({t: px[t] for t in have}).sort_index()
    volumes = pd.DataFrame(
        {t: vol[t] for t in have if t in vol and not vol[t].empty}
    ).sort_index()
    return closes, volumes


# ------------------------------------------------------------ selection ----

def window_bounds(n_obs: int) -> tuple[int, int]:
    """(start, end) positional indices of the 9-1 window in a length-n series."""
    end = n_obs - 1 - config.MOM_9_1_SKIP_DAYS
    start = n_obs - 1 - config.MOM_9_1_LONG_DAYS
    return start, end


def median_dollar_volume(
    closes: pd.DataFrame, volumes: pd.DataFrame, ticker: str
) -> float:
    """Median dollar volume over the trailing liquidity window."""
    if ticker not in closes.columns or ticker not in volumes.columns:
        return 0.0
    dv = (closes[ticker] * volumes[ticker]).dropna()
    if dv.empty:
        return 0.0
    return float(dv.tail(config.LIQUIDITY_WINDOW_DAYS).median())


def _has_full_window(series: pd.Series, n_obs: int) -> bool:
    """True when the ticker prices through the whole scoring window.

    The index level series is one row shorter than the price panel (the first
    day has no return), so the constituent needs one extra day of history
    before the window opens.
    """
    start, _ = window_bounds(n_obs)
    start -= 1
    if start < 0:
        return False
    return not bool(series.iloc[start:].isna().any())


def trading_calendar(closes: pd.DataFrame, min_coverage: float = 0.8) -> pd.DataFrame:
    """Drop panel dates where fewer than `min_coverage` of tickers priced.

    The panel index is a union across tickers, so a single vendor artefact can
    introduce a date almost nobody traded on; keeping it would flag otherwise
    clean names as having gaps.
    """
    if closes.empty:
        return closes
    coverage = closes.notna().mean(axis=1)
    return closes.loc[coverage >= min_coverage]


def select_constituents(
    candidates: list[dict], closes: pd.DataFrame, volumes: pd.DataFrame
) -> tuple[list[dict], list[dict]]:
    """(chosen, rejected) — the most liquid `SECTOR_INDEX_SIZE` clean names."""
    n_obs = len(closes.index)
    chosen: list[dict] = []
    rejected: list[dict] = []
    for rec in candidates:
        ticker = rec["ticker"]
        if ticker not in closes.columns:
            rejected.append({**rec, "reason": "no price history"})
            continue
        if not _has_full_window(closes[ticker], n_obs):
            rejected.append({**rec, "reason": "incomplete 9-1 window"})
            continue
        adv = median_dollar_volume(closes, volumes, ticker)
        if adv <= 0:
            rejected.append({**rec, "reason": "no volume data"})
            continue
        chosen.append({**rec, "median_dollar_volume": adv})

    chosen.sort(key=lambda r: -r["median_dollar_volume"])
    keep = chosen[: config.SECTOR_INDEX_SIZE]
    rejected += [
        {**r, "reason": "below liquidity cut"}
        for r in chosen[config.SECTOR_INDEX_SIZE :]
    ]
    return keep, rejected


# ------------------------------------------------------------ index math ----

def equal_weight_index(closes: pd.DataFrame) -> pd.Series:
    """Daily-rebalanced equal-weight index level, base 100."""
    if closes.empty:
        return pd.Series(dtype=float)
    rets = closes.pct_change()
    port = rets.mean(axis=1, skipna=True).iloc[1:].fillna(0.0)
    return 100.0 * (1.0 + port).cumprod()


def vol_adjusted_9_1(levels: pd.Series) -> dict | None:
    """Annualised 9-1 log return, annualised vol over the same window, ratio."""
    n_obs = len(levels)
    start, end = window_bounds(n_obs)
    if start < 0 or end <= start:
        return None

    window = levels.iloc[start : end + 1]
    log_levels = np.log(window.to_numpy(dtype=float))
    daily = np.diff(log_levels)
    obs = daily.size
    if obs < 2:
        return None

    total_log_return = float(log_levels[-1] - log_levels[0])
    ann_return = total_log_return * TRADING_DAYS / obs
    sigma = float(np.std(daily, ddof=1))
    ann_vol = sigma * math.sqrt(TRADING_DAYS)
    if ann_vol <= config.SIGMA_FLOOR:
        return None

    return {
        "window_start": str(window.index[0].date()),
        "window_end": str(window.index[-1].date()),
        "window_obs": int(obs),
        "log_return_9_1": total_log_return,
        "ann_log_return": ann_return,
        "ann_vol": ann_vol,
        "score": ann_return / ann_vol,
    }


def score_constituents(closes: pd.DataFrame, members: list[dict]) -> list[dict]:
    """Score each member on its own price series, then rank it inside its sector.

    A single stock's adjusted-close series is a level series, so the members
    take the identical 9-1 treatment the index gets. The z-score is
    sector-relative by construction — the peer group is the other 24 names —
    so it reads as dispersion within the sector, not market-wide level.

    Deliberately not winsorised: the repo's 5/95 clip protects cross-sectional
    fits over a 500-name universe, but inside a 25-name bucket it collapses the
    best two names onto one value and the worst two onto another. Consumers
    that need outlier protection should clamp the display scale instead.
    """
    keep = ("score", "ann_log_return", "ann_vol", "log_return_9_1")
    scored: list[dict] = []
    for rec in members:
        stats = vol_adjusted_9_1(closes[rec["ticker"]].dropna()) or {}
        scored.append({**rec, **{k: stats.get(k) for k in keep}})

    raw = pd.Series(
        {r["ticker"]: r["score"] for r in scored if r["score"] is not None},
        dtype=float,
    )
    if not raw.empty:
        z = analytics.zscore(raw)
        order = raw.rank(ascending=False, method="min").astype(int)
        for rec in scored:
            t = rec["ticker"]
            rec["sector_z"] = float(z[t]) if t in z.index else None
            rec["sector_rank"] = int(order[t]) if t in order.index else None

    scored.sort(key=lambda r: (r["sector_rank"] is None, r["sector_rank"] or 0))
    return scored


# --------------------------------------------------------------- pipeline ----

def build(*, force: bool = False, no_fetch: bool = False) -> dict:
    """Run the whole build and return the ranked result payload."""
    print("screening liquid universe...")
    buckets = screener.candidates_by_sector()
    if not buckets:
        raise SystemExit("screener returned no usable sectors")
    print(f"  {len(buckets)} sector(s), "
          f"{sum(len(v) for v in buckets.values())} candidate(s)")

    tickers = [rec["ticker"] for recs in buckets.values() for rec in recs]
    closes, volumes = fetch_history(tickers, force=force, no_fetch=no_fetch)
    if closes.empty:
        raise SystemExit("no price history available")
    closes = trading_calendar(closes)
    volumes = volumes.reindex(closes.index)
    print(f"  price panel: {closes.shape[1]} ticker(s) x {closes.shape[0]} day(s)")

    sectors: list[dict] = []
    for sector, candidates in buckets.items():
        chosen, _rejected = select_constituents(candidates, closes, volumes)
        if len(chosen) < config.SECTOR_INDEX_SIZE:
            print(
                f"  skipping {sector}: only {len(chosen)} clean name(s) "
                f"of {len(candidates)} candidate(s)"
            )
            continue
        chosen = score_constituents(closes, chosen)
        members = [r["ticker"] for r in chosen]
        levels = equal_weight_index(closes[members])
        stats = vol_adjusted_9_1(levels)
        if stats is None:
            print(f"  skipping {sector}: scoring window unavailable")
            continue
        sectors.append({
            "sector": sector,
            "n_constituents": len(members),
            **stats,
            "median_dollar_volume": float(
                np.median([r["median_dollar_volume"] for r in chosen])
            ),
            "breadth": sum(
                1 for r in chosen if (r.get("score") or 0.0) > 0
            ) / len(chosen),
            "constituents": [
                {
                    "ticker": r["ticker"],
                    "name": r["name"],
                    "industry": r["industry"],
                    "market_cap": r["market_cap"],
                    "median_dollar_volume": r["median_dollar_volume"],
                    "score": r.get("score"),
                    "sector_z": r.get("sector_z"),
                    "sector_rank": r.get("sector_rank"),
                    "ann_log_return": r.get("ann_log_return"),
                    "ann_vol": r.get("ann_vol"),
                }
                for r in chosen
            ],
        })

    sectors.sort(key=lambda s: -s["score"])
    for i, s in enumerate(sectors, 1):
        s["rank"] = i

    return {
        "as_of": str(closes.index[-1].date()),
        "generated": dt.date.today().isoformat(),
        "method": {
            "index": f"{config.SECTOR_INDEX_SIZE}-name equal weight, daily rebalanced",
            "selection": (
                f"most liquid by median {config.LIQUIDITY_WINDOW_DAYS}d dollar volume, "
                f"market cap > ${config.SCREEN_MIN_MARKET_CAP/1e9:.0f}bn"
            ),
            "signal": (
                f"annualised 9-1 log return / annualised vol, both over the same "
                f"{config.MOM_9_1_LONG_DAYS - config.MOM_9_1_SKIP_DAYS}-day window "
                f"(t-{config.MOM_9_1_LONG_DAYS}d to t-{config.MOM_9_1_SKIP_DAYS}d)"
            ),
        },
        "sectors": sectors,
    }


# ----------------------------------------------------------------- output ----

def print_table(payload: dict) -> None:
    sectors = payload["sectors"]
    if not sectors:
        print("no sectors ranked")
        return
    first = sectors[0]
    print()
    print(
        f"Volatility-adjusted 9-1 momentum — equal-weight sector indices "
        f"({config.SECTOR_INDEX_SIZE} names each)"
    )
    print(
        f"window {first['window_start']} -> {first['window_end']} "
        f"({first['window_obs']} obs), prices through {payload['as_of']}"
    )
    print()
    print(f"{'#':>2}  {'sector':<24}{'score':>8}{'ann ret':>10}{'ann vol':>9}"
          f"{'9-1 log':>9}{'med $vol':>11}")
    print("-" * 73)
    for s in sectors:
        print(
            f"{s['rank']:>2}  {s['sector']:<24}"
            f"{s['score']:>8.2f}"
            f"{s['ann_log_return']*100:>9.1f}%"
            f"{s['ann_vol']*100:>8.1f}%"
            f"{s['log_return_9_1']*100:>8.1f}%"
            f"{s['median_dollar_volume']/1e6:>10.0f}m"
        )
    print()


def benchmark(payload: dict) -> dict:
    """Score the listed SPDR sector ETF on the same window, as a sanity check.

    The synthetic indices are equal weight over the 25 most liquid names, the
    SPDRs are cap weighted over the full sector, so the levels legitimately
    differ; the ranking should still broadly agree.
    """
    from_date = (
        dt.date.today() - dt.timedelta(days=config.SECTOR_HISTORY_DAYS)
    ).isoformat()
    print(f"{'sector':<24}{'ours':>7}{'etf':>7}{'  etf':<6}{'ret gap':>9}{'vol gap':>9}")
    print("-" * 62)
    ours, theirs = [], []
    out: dict[str, dict] = {}
    for s in payload["sectors"]:
        etf = SPDR_SECTOR_ETFS.get(s["sector"])
        if not etf:
            continue
        px, _ = prices_mod.fetch_one(etf, from_date)
        stats = vol_adjusted_9_1(px.dropna()) if not px.empty else None
        if stats is None:
            print(f"{s['sector']:<24}{s['score']:>7.2f}{'  n/a':>7}  {etf}")
            continue
        ours.append(s["score"])
        theirs.append(stats["score"])
        out[s["sector"]] = {"etf": etf, **stats}
        print(
            f"{s['sector']:<24}{s['score']:>7.2f}{stats['score']:>7.2f}  {etf:<4}"
            f"{(s['ann_log_return'] - stats['ann_log_return'])*100:>8.1f}%"
            f"{(s['ann_vol'] - stats['ann_vol'])*100:>8.1f}%"
        )
    result = {"etfs": out, "rank_correlation": None}
    if len(ours) > 2:
        rank = lambda v: np.argsort(np.argsort(v))  # noqa: E731
        result["rank_correlation"] = float(np.corrcoef(rank(ours), rank(theirs))[0, 1])
        print(f"\nrank correlation with the SPDR sector ETFs: "
              f"{result['rank_correlation']:.2f}")
    payload["benchmark"] = result
    return result


def write_outputs(payload: dict) -> list[Path]:
    out_dir = Path(config.SECTOR_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    json_path = out_dir / "sector_etf_ranking.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    written.append(json_path)

    csv_path = out_dir / "sector_etf_ranking.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "rank", "sector", "score", "ann_log_return", "ann_vol",
            "log_return_9_1", "n_constituents", "median_dollar_volume",
            "window_start", "window_end",
        ])
        for s in payload["sectors"]:
            w.writerow([
                s["rank"], s["sector"], f"{s['score']:.4f}",
                f"{s['ann_log_return']:.6f}", f"{s['ann_vol']:.6f}",
                f"{s['log_return_9_1']:.6f}", s["n_constituents"],
                f"{s['median_dollar_volume']:.0f}",
                s["window_start"], s["window_end"],
            ])
    written.append(csv_path)

    members_path = out_dir / "sector_etf_constituents.csv"
    with open(members_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "sector", "sector_rank", "ticker", "name", "industry",
            "score", "sector_z", "ann_log_return", "ann_vol",
            "market_cap", "median_dollar_volume", "weight",
        ])
        for s in payload["sectors"]:
            weight = 1.0 / s["n_constituents"]
            for c in s["constituents"]:
                w.writerow([
                    s["sector"], c["sector_rank"], c["ticker"], c["name"],
                    c["industry"],
                    "" if c["score"] is None else f"{c['score']:.4f}",
                    "" if c["sector_z"] is None else f"{c['sector_z']:.4f}",
                    "" if c["ann_log_return"] is None else f"{c['ann_log_return']:.6f}",
                    "" if c["ann_vol"] is None else f"{c['ann_vol']:.6f}",
                    f"{c['market_cap']:.0f}", f"{c['median_dollar_volume']:.0f}",
                    f"{weight:.4f}",
                ])
    written.append(members_path)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="refetch all prices")
    ap.add_argument("--no-fetch", action="store_true", help="cache only, no network")
    ap.add_argument("--members", action="store_true", help="print constituents")
    ap.add_argument(
        "--benchmark", action="store_true",
        help="score the SPDR sector ETFs on the same window as a cross-check",
    )
    args = ap.parse_args()

    if not config.FMP_API_KEY and not args.no_fetch:
        raise SystemExit("set FMP_API_KEY in the environment or config.py")

    payload = build(force=args.force, no_fetch=args.no_fetch)
    print_table(payload)
    if args.members:
        for s in payload["sectors"]:
            names = ", ".join(c["ticker"] for c in s["constituents"])
            print(f"{s['sector']}: {names}\n")
    if args.benchmark:
        benchmark(payload)
        print()
    written = write_outputs(payload)
    for path in written:
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
