"""Orchestrator for the M/Q/V ranking pipeline. Cache-only by default."""
import argparse
import warnings
import webbrowser
from pathlib import Path

# Silence noisy upstream deprecation warnings (pandas/np.percentile, sharing.quick_look).
warnings.filterwarnings("ignore", message=".*interpolation.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*quick_look.*", category=DeprecationWarning)

import pandas as pd

import analytics
import report
import snapshots
import store
import weights as weights_mod
from config import (
    MARKET_TICKER, TOP_N, WEIGHTING_SCHEME, WEIGHT_LOOKBACK_DAYS,
    CASH_DEPLOYMENT, BETA_LOOKBACK_DAYS, VOL_TARGET, VOL_TARGET_MAX_LEVERAGE,
    BACKTEST_DAYS, EXPECTATIONS_ENABLED,
)
from universe import (
    classify_universe, exclusion_reason_label,
    load_sector_etf_map, ticker_to_industry, ticker_to_sector,
)


def _open_file(path: Path) -> None:
    """Best-effort open across Pyto and desktop."""
    path_str = str(path)
    # Pyto: prefer file_system module if it exposes a preview/quick_look.
    try:
        import file_system  # type: ignore[import-not-found]
        for name in ("quick_look", "quick_look_url", "preview", "open"):
            fn = getattr(file_system, name, None)
            if callable(fn):
                fn(path_str)
                return
    except ImportError:
        pass
    except Exception:
        pass
    # Pyto legacy path (works but deprecated; warning is suppressed above).
    try:
        from sharing import quick_look  # type: ignore[import-not-found]
        quick_look(path_str)
        return
    except ImportError:
        pass
    except Exception:
        pass
    # Desktop / generic fallback.
    try:
        webbrowser.open(path.as_uri())
    except Exception as e:
        print(f"(could not auto-open: {e})")


_MKT_CAP_BUCKETS: list[tuple[str, float, float]] = [
    ("Mega (≥$200B)",        200e9, float("inf")),
    ("Large ($10B–$200B)",    10e9,  200e9),
    ("Mid ($2B–$10B)",         2e9,   10e9),
    ("Small ($300M–$2B)",    300e6,    2e9),
    ("Micro (<$300M)",                0.0, 300e6),
]


def _build_universe_pulse(
    tickers: list, profiles_data: dict, labels: dict, ranked,
) -> dict:
    """Descriptive stats for the Universe Pulse section.

    Operates on the post-filter active set so the numbers describe what is
    actually scoring. Sectors and industries come from cached profiles;
    market-cap stats come from `ranked` (which has it computed once per run).
    """
    n = len(tickers)
    if n == 0:
        return {"n": 0}

    adr_n = sum(1 for t in tickers if "ADR" in (labels.get(t) or []))
    reit_n = sum(1 for t in tickers if "REIT" in (labels.get(t) or []))
    mlp_n = sum(1 for t in tickers if "MLP" in (labels.get(t) or []))
    classified = sum(1 for t in tickers if profiles_data.get(t))
    unknown = n - classified
    common = max(0, n - adr_n - mlp_n)
    composition = [
        ("Common stock", common),
        ("ADR", adr_n),
        ("REIT", reit_n),
        ("MLP", mlp_n),
        ("Unclassified", unknown),
    ]

    sectors: dict[str, int] = {}
    industries: dict[str, int] = {}
    # Track tickers that are missing classification — either because we have
    # no profile at all (unclassified) or because the profile sector is empty
    # (unknown sector). The user wants to be able to audit this list.
    unclassified_rows: list[tuple[str, str]] = []
    for t in tickers:
        prof = profiles_data.get(t) or {}
        sec_raw = (prof.get("sector") or "").strip()
        sec = sec_raw or "Unknown"
        ind = (prof.get("industry") or "Unknown").strip() or "Unknown"
        sectors[sec] = sectors.get(sec, 0) + 1
        industries[ind] = industries.get(ind, 0) + 1
        if not prof or not sec_raw:
            name = (prof.get("company_name") or "").strip()
            unclassified_rows.append((t, name))

    sector_rows = sorted(sectors.items(), key=lambda kv: (-kv[1], kv[0]))
    industry_rows = sorted(industries.items(), key=lambda kv: (-kv[1], kv[0]))

    mkt_caps: list[float] = []
    if ranked is not None and not ranked.empty and "market_cap" in ranked.columns:
        for t in tickers:
            if t in ranked.index:
                mc = ranked.loc[t, "market_cap"]
                if pd.notna(mc) and mc > 0:
                    mkt_caps.append(float(mc))
    mkt_caps_sorted = sorted(mkt_caps)
    if mkt_caps_sorted:
        median = mkt_caps_sorted[len(mkt_caps_sorted) // 2]
        mc_stats = {
            "median": median,
            "min": mkt_caps_sorted[0],
            "max": mkt_caps_sorted[-1],
            "n_with_data": len(mkt_caps_sorted),
        }
    else:
        mc_stats = {}

    bucket_counts = []
    for label, lo, hi in _MKT_CAP_BUCKETS:
        c = sum(1 for mc in mkt_caps_sorted if mc >= lo and mc < hi)
        bucket_counts.append((label, c))

    return {
        "n": n,
        "composition": composition,
        "sectors": sector_rows,
        "industries": industry_rows,
        "market_cap": mc_stats,
        "buckets": bucket_counts,
        "unclassified": sorted(unclassified_rows),
    }


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Rank the universe from cached data. Default: no network."
    )
    p.add_argument(
        "--refresh", action="store_true",
        help="Force refetch of all caches before ranking.",
    )
    p.add_argument(
        "--update", action="store_true",
        help="Top up missing/stale data before ranking.",
    )
    p.add_argument(
        "--output", default="reports/",
        help="Output directory (default: reports/).",
    )
    p.add_argument(
        "--no-open", action="store_true",
        help="Do not auto-open the report after writing.",
    )
    p.add_argument(
        "--cash", type=float, default=None, metavar="DOLLARS",
        help=f"Cash to allocate across the top N (default {CASH_DEPLOYMENT}). "
             "Per-stock cash = weight × cash, rounded.",
    )
    p.add_argument(
        "--sort", default="composite",
        choices=[
            "composite", "cash", "sector", "ticker", "mktcap",
            "momentum", "quality", "value",
        ],
        help="Initial sort order in the report (default composite).",
    )
    p.add_argument(
        "--limit", type=int, default=100, metavar="N",
        help="Cap the report at the top N composite-ranked stocks (default 100). "
             "Set to 0 to render the full universe.",
    )
    p.add_argument(
        "--exclude-adr", action="store_true",
        help="Drop ADR-labeled tickers before z-scoring/ranking (Universe filter).",
    )
    p.add_argument(
        "--exclude-reit", action="store_true",
        help="Drop REIT-labeled tickers before z-scoring/ranking (Universe filter).",
    )
    return p.parse_args(argv)


def main():
    args = parse_args()
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_tickers = store.universe()
    sector_etf_map = load_sector_etf_map()
    sector_etfs = list(sector_etf_map.values())
    print(f"Universe: {len(raw_tickers)} stocks raw, {len(sector_etfs)} sector ETFs.")

    do_fetch = args.refresh or args.update
    if do_fetch:
        all_for_prices = list(
            dict.fromkeys([MARKET_TICKER, *sector_etfs, *raw_tickers])
        )
        store.ensure(
            all_for_prices,
            with_fundamentals=False, with_profiles=False,
            force=args.refresh,
        )
        store.ensure(
            raw_tickers,
            with_prices=False,
            with_revisions=EXPECTATIONS_ENABLED,
            force=args.refresh,
        )

    # Universe hygiene: drop preferreds, baby bonds/notes, warrants, rights,
    # SPAC units, ETFs, and funds; surface ADR/REIT/MLP labels for everything
    # else. Bootstrap behaviour: on the very first run the profile cache may
    # be empty and only ticker-suffix patterns will fire — once profiles are
    # cached, the next run filters cleanly.
    profiles_data = store.profiles()
    eligible_tickers, excluded, labels = classify_universe(raw_tickers, profiles_data)
    print(
        f"Eligible: {len(eligible_tickers)} (excluded {len(excluded)}: "
        + ", ".join(sorted({exclusion_reason_label(r) for r in excluded.values()}))
        + ")"
        if excluded else f"Eligible: {len(eligible_tickers)}"
    )

    # Apply user-controlled active filters AFTER hygiene but BEFORE the
    # pipeline runs, so cross-sectional z-scores, composite, ranks, and
    # weights all recompute over the active set.
    active_filters: dict = {
        "exclude_adr": bool(args.exclude_adr),
        "exclude_reit": bool(args.exclude_reit),
        "removed_by_filter": [],
        "removed_count": 0,
    }
    tickers = list(eligible_tickers)
    if args.exclude_adr or args.exclude_reit:
        kept: list[str] = []
        removed: list[tuple[str, str]] = []
        for t in tickers:
            tags = labels.get(t) or []
            if args.exclude_adr and "ADR" in tags:
                removed.append((t, "ADR"))
                continue
            if args.exclude_reit and "REIT" in tags:
                removed.append((t, "REIT"))
                continue
            kept.append(t)
        tickers = kept
        active_filters["removed_by_filter"] = removed
        active_filters["removed_count"] = len(removed)
        active_summary = ", ".join(
            x for x in (
                "exclude ADRs" if args.exclude_adr else "",
                "exclude REITs" if args.exclude_reit else "",
            ) if x
        )
        print(
            f"Active filters ({active_summary}): "
            f"{len(eligible_tickers)} → {len(tickers)} "
            f"({len(removed)} removed)"
        )

    ts = ticker_to_sector(profiles_data)
    ti = ticker_to_industry(profiles_data)
    # Restrict both maps to eligible tickers so the pipeline never
    # processes anything we just filtered out.
    active_set = set(tickers)
    ts = {t: s for t, s in ts.items() if t in active_set}
    ti = {t: i for t, i in ti.items() if t in active_set}

    prices_df, _ = store.prices()
    funds = store.fundamentals()
    returns = analytics.log_returns(prices_df)
    sec_resid = analytics.compute_sector_residuals(returns, sector_etf_map)
    stock_resid, betas_market, betas_sector = analytics.compute_stock_residuals(
        returns, sec_resid, ts,
    )
    mom_df = analytics.compute_residual_momentum(stock_resid, ts)
    qual_df, _ = analytics.compute_quality(funds, ts, ti)
    val_df, _ = analytics.compute_value(funds, prices_df, ts, ti)
    ranked, factors_used = analytics.build_ranked(mom_df, qual_df, val_df, ts, ti)

    # Diagnostic Expectations factor (step 1) — NOT in composite. Attaches as
    # a separate column the report surfaces in each card's expanded panel.
    if EXPECTATIONS_ENABLED:
        revisions_data = store.revisions()
        exp_df, exp_meta = analytics.compute_expectations(revisions_data, ts, ti)
        if not exp_df.empty and "expectations_scope" in exp_df.columns:
            ranked["expectations_scope"] = ranked.index.map(exp_df["expectations_scope"])
        if not exp_df.empty:
            ranked["expectations_z"] = ranked.index.map(exp_df["expectations_z"])
        else:
            ranked["expectations_z"] = float("nan")
        eligible_n = len(tickers) or 1
        coverage = float(exp_df["expectations_z"].notna().sum()) / eligible_n if not exp_df.empty else 0.0
        factors_used["expectations_enabled"] = True
        factors_used["expectations_coverage"] = coverage
        factors_used["expectations_count"] = int(
            exp_df["expectations_z"].notna().sum() if not exp_df.empty else 0
        )
        print(
            f"Expectations (diagnostic): "
            f"{factors_used['expectations_count']} of {eligible_n} eligible "
            f"({coverage*100:.1f}% coverage)"
        )
    else:
        factors_used["expectations_enabled"] = False

    top_n = min(TOP_N, len(ranked))
    top_tickers = ranked.head(top_n).index.tolist()

    # Surface the per-ticker betas (already estimated by compute_stock_residuals)
    # so they ride along in ranked.csv and into the snapshot archive for later
    # diagnostic / forward-test use.
    if betas_market:
        ranked["beta_market"] = ranked.index.map(betas_market)
    if betas_sector:
        ranked["beta_sector"] = ranked.index.map(betas_sector)

    # Diagnostic series for each visible card: rolling 63-day residual return
    # chart, current 63d value, sigma reading, and 21d pullback z. Replaces
    # the older 21-day price sparkline.
    diagnostic_tickers = list(ranked.index[:200])
    diagnostics = analytics.compute_diagnostics(stock_resid, diagnostic_tickers)

    # Three weighting schemes for the toggle. HRP runs on residual returns
    # (market- and sector-orthogonalised); equal and inverse_vol run on raw
    # daily log returns over the standard 252-day window.
    equal_w = weights_mod.compute_weights("equal", returns, top_tickers)
    ivp_w = weights_mod.compute_weights(
        "inverse_vol", returns, top_tickers, WEIGHT_LOOKBACK_DAYS,
    )
    hrp_input = stock_resid if not stock_resid.empty else returns
    hrp_w = weights_mod.compute_weights(
        "hrp", hrp_input, top_tickers, BETA_LOOKBACK_DAYS,
    )
    ranked["equal_weight"] = ranked.index.map(equal_w).fillna(0.0)
    ranked["ivp_weight"] = ranked.index.map(ivp_w).fillna(0.0)
    ranked["hrp_weight"] = ranked.index.map(hrp_w).fillna(0.0)

    # Realised portfolio vol per scheme + vol-targeting scale.
    sigma_eq = weights_mod.portfolio_volatility(returns, equal_w, WEIGHT_LOOKBACK_DAYS)
    sigma_ivp = weights_mod.portfolio_volatility(returns, ivp_w, WEIGHT_LOOKBACK_DAYS)
    sigma_hrp = weights_mod.portfolio_volatility(returns, hrp_w, WEIGHT_LOOKBACK_DAYS)
    scale_eq = weights_mod.vol_target_scale(
        sigma_eq, VOL_TARGET, VOL_TARGET_MAX_LEVERAGE,
    )
    scale_ivp = weights_mod.vol_target_scale(
        sigma_ivp, VOL_TARGET, VOL_TARGET_MAX_LEVERAGE,
    )
    scale_hrp = weights_mod.vol_target_scale(
        sigma_hrp, VOL_TARGET, VOL_TARGET_MAX_LEVERAGE,
    )

    cash = args.cash if args.cash is not None else CASH_DEPLOYMENT
    factors_used["weighting_scheme"] = WEIGHTING_SCHEME
    factors_used["top_n"] = top_n
    factors_used["cash_deployment"] = float(cash)
    factors_used["hrp_lookback"] = BETA_LOOKBACK_DAYS
    factors_used["vol_target"] = VOL_TARGET
    factors_used["vol_target_max_leverage"] = VOL_TARGET_MAX_LEVERAGE
    factors_used["scheme_vols"] = {
        "equal": sigma_eq, "ivp": sigma_ivp, "hrp": sigma_hrp,
    }
    factors_used["scheme_scales"] = {
        "equal": scale_eq, "ivp": scale_ivp, "hrp": scale_hrp,
    }

    # Lookback attribution (v0.1 backtest): apply current weights to the last
    # BACKTEST_DAYS of returns and report total return, Sharpe, max drawdown.
    factors_used["backtest"] = {
        "lookback_days": BACKTEST_DAYS,
        "equal": weights_mod.backtest_portfolio(returns, equal_w, BACKTEST_DAYS),
        "ivp":   weights_mod.backtest_portfolio(returns, ivp_w, BACKTEST_DAYS),
        "hrp":   weights_mod.backtest_portfolio(returns, hrp_w, BACKTEST_DAYS),
        "market": weights_mod.backtest_market(returns, MARKET_TICKER, BACKTEST_DAYS),
    }
    # Per-ticker residualisation labels. v1 exposes the structure; today every
    # active ticker is sector-residualised against an ETF proxy. v3 will fan
    # this out to industry-ETF / internal-LOO / sector-ETF / none as the
    # pipeline gains industry residuals.
    if "industry" in ranked.columns:
        residual_scope = pd.Series("none", index=ranked.index, dtype=object)
        proxy_source = pd.Series("none", index=ranked.index, dtype=object)
        # If compute_stock_residuals produced a column for the ticker, it ran
        # against [market, sector_etf_residual]. Otherwise residualisation
        # was skipped (insufficient data, missing sector ETF, etc.).
        residualised = set(stock_resid.columns) if not stock_resid.empty else set()
        sector_for_t = ts
        for t in ranked.index:
            if t in residualised:
                residual_scope.loc[t] = "sector"
                proxy_source.loc[t] = (
                    "sector_etf" if sector_for_t.get(t) in sector_etf_map else "none"
                )
        ranked["residual_scope"] = residual_scope
        ranked["proxy_source"] = proxy_source

    # Bucket-count audit for the methodology / universe drawer. Counts only
    # use the active set so the numbers match what was actually scored.
    if "industry" in ranked.columns:
        ind_counts = ranked["industry"].value_counts()
        sec_counts = ranked["sector"].value_counts()
        ind_eligible = int((ind_counts >= 25).sum())
        ind_total = int((ind_counts.index != "Unknown").sum())
        sec_eligible = int((sec_counts >= 5).sum())
        sec_total = int((sec_counts.index != "Unknown").sum())
        scope_counts: dict[str, dict] = {"quality": {}, "value": {}, "expectations": {}}
        for col, key in (
            ("quality_scope", "quality"),
            ("value_scope", "value"),
            ("expectations_scope", "expectations"),
        ):
            if col in ranked.columns:
                vc = ranked[col].fillna("none").value_counts()
                scope_counts[key] = {str(k): int(v) for k, v in vc.items()}
        factors_used["normalization"] = {
            "industry_min": 25,
            "sector_min": 5,
            "industry_buckets_total": ind_total,
            "industry_buckets_eligible": ind_eligible,
            "sector_buckets_total": sec_total,
            "sector_buckets_eligible": sec_eligible,
            "scope_counts": scope_counts,
            "industry_top": [
                (str(k), int(v)) for k, v in ind_counts.head(15).items()
            ],
        }

    factors_used["sort"] = args.sort
    factors_used["universe_total"] = len(ranked)
    factors_used["universe_raw_count"] = len(raw_tickers)
    factors_used["universe_eligible_count"] = len(eligible_tickers)
    factors_used["universe_active_count"] = len(tickers)
    factors_used["universe_excluded"] = excluded
    factors_used["universe_labels"] = labels
    factors_used["universe_active_filters"] = active_filters
    factors_used["universe_pulse"] = _build_universe_pulse(
        tickers, profiles_data, labels, ranked,
    )
    excluded_by_reason: dict[str, list[str]] = {}
    excluded_named_by_reason: dict[str, list[tuple[str, str]]] = {}
    for _t, _reason in excluded.items():
        _label = exclusion_reason_label(_reason)
        excluded_by_reason.setdefault(_label, []).append(_t)
        _name = ((profiles_data.get(_t) or {}).get("company_name") or "").strip()
        excluded_named_by_reason.setdefault(_label, []).append((_t, _name))
    for _label in excluded_by_reason:
        excluded_by_reason[_label].sort()
    for _label in excluded_named_by_reason:
        excluded_named_by_reason[_label].sort(key=lambda p: p[0])
    factors_used["universe_excluded_by_reason"] = excluded_by_reason
    factors_used["universe_excluded_named_by_reason"] = excluded_named_by_reason

    # Surface the latest price date so stale data is visible in the report
    # header. Uses the last index of the cached prices frame as the canonical
    # report-level "as of" date.
    if not prices_df.empty:
        last_idx = prices_df.index[-1]
        factors_used["prices_as_of"] = (
            str(last_idx.date()) if hasattr(last_idx, "date") else str(last_idx)
        )

    if args.limit and args.limit > 0 and len(ranked) > args.limit:
        display_ranked = ranked.head(args.limit).copy()
        factors_used["display_limit"] = args.limit
    else:
        display_ranked = ranked
        factors_used["display_limit"] = None

    if args.sort == "cash":
        display_ranked = display_ranked.sort_values(
            "hrp_weight", ascending=False, kind="mergesort"
        )
    elif args.sort == "sector":
        display_ranked = display_ranked.sort_values(
            ["sector", "composite"], ascending=[True, False], kind="mergesort"
        )
    elif args.sort == "ticker":
        display_ranked = display_ranked.sort_index(ascending=True, kind="mergesort")
    elif args.sort == "mktcap":
        display_ranked = display_ranked.sort_values(
            "market_cap", ascending=False, kind="mergesort", na_position="last"
        )
    elif args.sort == "momentum":
        display_ranked = display_ranked.sort_values(
            "residual_momentum_z", ascending=False, kind="mergesort", na_position="last"
        )
    elif args.sort == "quality":
        display_ranked = display_ranked.sort_values(
            "quality_z", ascending=False, kind="mergesort", na_position="last"
        )
    elif args.sort == "value":
        display_ranked = display_ranked.sort_values(
            "value_z", ascending=False, kind="mergesort", na_position="last"
        )
    # composite is already the default sort from build_ranked.

    names = store.company_names(display_ranked.index.tolist())
    html = report.render(
        display_ranked, names, factors_used,
        diagnostics=diagnostics,
    )
    report_path = (out_dir / "report.html").resolve()
    report.write_report(html, str(report_path))
    # CSV always carries the full ranked frame, untruncated and unsorted-by-flag.
    report.write_csv(ranked, str((out_dir / "ranked_stocks.csv").resolve()))
    print(f"Ranked {len(display_ranked)} of {len(ranked)} tickers → {report_path}")

    # Append-only snapshot archive — quiet background record. Failures here
    # never block the report; save_snapshot returns None and prints a warning.
    snap_path = snapshots.save_snapshot(
        ranked=ranked,
        top_n=top_n,
        factors_used=factors_used,
        raw_tickers=raw_tickers,
        active_tickers=tickers,
        excluded=excluded,
        profiles_data=profiles_data,
        labels=labels,
        prices_as_of=factors_used.get("prices_as_of"),
    )
    if snap_path is not None:
        print(f"Snapshot saved → {snap_path}")

    if not args.no_open:
        _open_file(report_path)


if __name__ == "__main__":
    main()
