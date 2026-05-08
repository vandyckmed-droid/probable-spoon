"""Orchestrator for the M/Q/V ranking pipeline. Cache-only by default."""
import argparse
import warnings
import webbrowser
from pathlib import Path

# Silence noisy upstream deprecation warnings (pandas/np.percentile, sharing.quick_look).
warnings.filterwarnings("ignore", message=".*interpolation.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*quick_look.*", category=DeprecationWarning)

import analytics
import report
import store
import weights as weights_mod
from config import (
    MARKET_TICKER, TOP_N, WEIGHTING_SCHEME, WEIGHT_LOOKBACK_DAYS,
    CASH_DEPLOYMENT, BETA_LOOKBACK_DAYS, VOL_TARGET, BACKTEST_DAYS,
)
from universe import load_sector_etf_map, ticker_to_sector


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
        choices=["composite", "cash", "sector", "ticker", "mktcap"],
        help="Initial sort order in the report (default composite).",
    )
    p.add_argument(
        "--limit", type=int, default=100, metavar="N",
        help="Cap the report at the top N composite-ranked stocks (default 100). "
             "Set to 0 to render the full universe.",
    )
    return p.parse_args(argv)


def main():
    args = parse_args()
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    tickers = store.universe()
    sector_etf_map = load_sector_etf_map()
    sector_etfs = list(sector_etf_map.values())
    print(f"Universe: {len(tickers)} stocks, {len(sector_etfs)} sector ETFs.")

    do_fetch = args.refresh or args.update
    if do_fetch:
        all_for_prices = list(
            dict.fromkeys([MARKET_TICKER, *sector_etfs, *tickers])
        )
        store.ensure(
            all_for_prices,
            with_fundamentals=False, with_profiles=False,
            force=args.refresh,
        )
        store.ensure(
            tickers,
            with_prices=False,
            force=args.refresh,
        )

    ts = ticker_to_sector(store.profiles())

    prices_df, _ = store.prices()
    funds = store.fundamentals()
    returns = analytics.log_returns(prices_df)
    sec_resid = analytics.compute_sector_residuals(returns, sector_etf_map)
    stock_resid, _, _ = analytics.compute_stock_residuals(returns, sec_resid, ts)
    mom_df = analytics.compute_residual_momentum(stock_resid, ts)
    qual_df, _ = analytics.compute_quality(funds, ts)
    val_df, _ = analytics.compute_value(funds, prices_df, ts)
    ranked, factors_used = analytics.build_ranked(mom_df, qual_df, val_df, ts)

    top_n = min(TOP_N, len(ranked))
    top_tickers = ranked.head(top_n).index.tolist()

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
    scale_eq = weights_mod.vol_target_scale(sigma_eq, VOL_TARGET)
    scale_ivp = weights_mod.vol_target_scale(sigma_ivp, VOL_TARGET)
    scale_hrp = weights_mod.vol_target_scale(sigma_hrp, VOL_TARGET)

    cash = args.cash if args.cash is not None else CASH_DEPLOYMENT
    factors_used["weighting_scheme"] = WEIGHTING_SCHEME
    factors_used["top_n"] = top_n
    factors_used["cash_deployment"] = float(cash)
    factors_used["hrp_lookback"] = BETA_LOOKBACK_DAYS
    factors_used["vol_target"] = VOL_TARGET
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
    factors_used["sort"] = args.sort
    factors_used["universe_total"] = len(ranked)

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
    # composite is already the default sort from build_ranked.

    names = store.company_names(display_ranked.index.tolist())
    html = report.render(display_ranked, names, factors_used)
    report_path = (out_dir / "report.html").resolve()
    report.write_report(html, str(report_path))
    # CSV always carries the full ranked frame, untruncated and unsorted-by-flag.
    report.write_csv(ranked, str((out_dir / "ranked_stocks.csv").resolve()))
    print(f"Ranked {len(display_ranked)} of {len(ranked)} tickers → {report_path}")

    if not args.no_open:
        _open_file(report_path)


if __name__ == "__main__":
    main()
