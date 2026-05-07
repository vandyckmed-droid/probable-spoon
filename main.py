"""Orchestrator for the M/Q/V ranking pipeline. Cache-only by default."""
import argparse
import warnings
import webbrowser
from pathlib import Path

# Silence pandas's deprecated np.percentile(interpolation=...) call.
warnings.filterwarnings("ignore", message=".*interpolation.*", category=DeprecationWarning)

import analytics
import report
import store
from config import MARKET_TICKER
from universe import load_sector_etf_map, ticker_to_sector


def _open_file(path: Path) -> None:
    """Best-effort open: Pyto's quick_look first, then webbrowser."""
    try:
        from sharing import quick_look  # type: ignore[import-not-found]
        quick_look(str(path))
        return
    except ImportError:
        pass
    except Exception as e:
        print(f"(quick_look failed: {e})")
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
