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
    CASH_DEPLOYMENT,
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
             "The Weight column renders as a rounded dollar amount.",
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
    w = weights_mod.compute_weights(
        WEIGHTING_SCHEME, returns, top_tickers, WEIGHT_LOOKBACK_DAYS,
    )
    ranked["weight"] = ranked.index.map(w).fillna(0.0)
    cash = args.cash if args.cash is not None else CASH_DEPLOYMENT
    factors_used["weighting_scheme"] = WEIGHTING_SCHEME
    factors_used["top_n"] = top_n
    factors_used["cash_deployment"] = float(cash)

    names = store.company_names(ranked.index.tolist())
    html = report.render(ranked, names, factors_used)
    report_path = (out_dir / "report.html").resolve()
    report.write_report(html, str(report_path))
    report.write_csv(ranked, str((out_dir / "ranked_stocks.csv").resolve()))
    print(f"Ranked {len(ranked)} tickers → {report_path}")

    if not args.no_open:
        _open_file(report_path)


if __name__ == "__main__":
    main()
