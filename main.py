"""Orchestrator for the M/Q/V ranking pipeline."""
import argparse
from pathlib import Path

import analytics
import report
import store
from config import MARKET_TICKER
from universe import load_sector_etf_map, ticker_to_sector


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Run the M/Q/V ranking pipeline.")
    p.add_argument(
        "--refresh", action="store_true",
        help="Force refetch of all caches.",
    )
    p.add_argument(
        "--no-fetch", action="store_true",
        help="Use caches only; never hit the network.",
    )
    p.add_argument(
        "--output", default="reports/",
        help="Output directory (default: reports/).",
    )
    return p.parse_args(argv)


def main():
    args = parse_args()
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    tickers = store.universe()
    sector_etf_map = load_sector_etf_map()
    sector_etfs = list(sector_etf_map.values())

    all_for_prices = list(dict.fromkeys([MARKET_TICKER, *sector_etfs, *tickers]))
    store.ensure(
        all_for_prices,
        with_fundamentals=False,
        with_profiles=False,
        force=args.refresh,
        no_fetch=args.no_fetch,
    )
    store.ensure(
        tickers,
        with_prices=False,
        force=args.refresh,
        no_fetch=args.no_fetch,
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
    report.write_report(html, str(out_dir / "report.html"))
    report.write_csv(ranked, str(out_dir / "ranked_stocks.csv"))
    print(f"Ranked {len(ranked)} tickers → {out_dir}/report.html")


if __name__ == "__main__":
    main()
