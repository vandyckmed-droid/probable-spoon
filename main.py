"""Step-1 orchestrator: load disk inputs, compute ranking, print top-N.

No FMP, no caching, no HTML. Reads pandas-friendly CSV / JSON from disk,
calls analytics.*, writes the ranked frame to stdout.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import analytics


def _load_funds(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_sectors(path: str) -> dict[str, str]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    p = argparse.ArgumentParser(description="MQV ranking, step 1.")
    p.add_argument("--prices", required=True,
                   help="CSV: date index, ticker columns, daily closes.")
    p.add_argument("--funds", required=True,
                   help="JSON: {ticker: {income: [...], balance: [...], cashflow: [...]}}.")
    p.add_argument("--sectors", required=True,
                   help="JSON: {ticker: sector_name}.")
    p.add_argument("--sector-etfs", required=True,
                   help="JSON: {sector_name: etf_ticker}.")
    p.add_argument("--market", default="VTI",
                   help="Market proxy ticker (default VTI).")
    p.add_argument("--top", type=int, default=10,
                   help="Print this many ranked rows (default 10).")
    args = p.parse_args()

    prices = pd.read_csv(args.prices, index_col=0, parse_dates=True)
    funds = _load_funds(args.funds)
    sectors = _load_sectors(args.sectors)
    sector_etfs = _load_sectors(args.sector_etfs)

    returns = analytics.log_returns(prices)
    mom = analytics.residual_momentum_z(returns, args.market, sector_etfs, sectors)
    qual = analytics.quality_z(funds)
    val = analytics.value_z(funds, prices)
    ranked = analytics.composite_rank(mom, qual, val)

    n_universe = sum(1 for t in prices.columns if t != args.market)
    print(
        f"universe={n_universe}  "
        f"momentum_eligible={int(mom.notna().sum())}  "
        f"quality_eligible={int(qual.notna().sum())}  "
        f"value_eligible={int(val.notna().sum())}  "
        f"composite_eligible={len(ranked)}"
    )
    if ranked.empty:
        print("(no ranked tickers)")
        return
    print(ranked.head(args.top).round(3).to_string())


if __name__ == "__main__":
    main()
