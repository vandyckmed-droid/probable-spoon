"""CLI to expand the universe. Default action: add top 20 US stocks by market cap."""
import argparse

import config
import fmp_client
import store


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Add tickers to the universe. With no arguments, adds top 20 by market cap."
    )
    p.add_argument(
        "tickers", nargs="*",
        help="Tickers to add. Omit to use --top instead.",
    )
    p.add_argument(
        "--top", type=int, default=20, metavar="N",
        help="When no tickers are given, add top N US stocks by market cap (default 20).",
    )
    p.add_argument(
        "--no-fetch", action="store_true",
        help="Skip data fetch after adding.",
    )
    return p.parse_args(argv)


def fetch_top_by_market_cap(
    n: int, *, exclude: set[str] | None = None,
) -> list[str]:
    """Top N US-listed stocks by market cap, skipping any in `exclude`."""
    if n <= 0:
        return []
    exclude_upper = {t.upper() for t in (exclude or set())}
    params = {
        "marketCapMoreThan": 1_000_000_000,
        "isEtf": "false",
        "isFund": "false",
        "isActivelyTrading": "true",
        "exchange": "NYSE,NASDAQ",
        "limit": max(n * 5 + len(exclude_upper) + 200, 500),
    }
    try:
        rows = fmp_client.get("company-screener", params=params)
    except fmp_client.FMPError:
        try:
            rows = fmp_client.get(
                "stock-screener", params=params, base=config.FMP_LEGACY_BASE,
            )
        except fmp_client.FMPError:
            return []
    if not isinstance(rows, list):
        return []
    rows.sort(
        key=lambda r: (r.get("marketCap") or 0) if isinstance(r, dict) else 0,
        reverse=True,
    )
    out: list[str] = []
    seen: set[str] = set()
    for r in rows:
        s = r.get("symbol") if isinstance(r, dict) else None
        if not s:
            continue
        u = s.upper()
        if u in seen or u in exclude_upper:
            continue
        seen.add(u)
        out.append(s)
        if len(out) >= n:
            break
    return out


def main(argv=None):
    args = parse_args(argv)
    raw = list(args.tickers)
    if not raw:
        existing = {t.upper() for t in store.universe()}
        print(
            f"Fetching next {args.top} by market cap "
            f"(skipping {len(existing)} already in universe)..."
        )
        raw = fetch_top_by_market_cap(args.top, exclude=existing)
        if not raw:
            print("Could not fetch. Check FMP_API_KEY at the top of config.py.")
            return

    cleaned: list[str] = []
    seen: set[str] = set()
    for t in raw:
        u = t.strip().upper()
        if u and u not in seen:
            seen.add(u)
            cleaned.append(u)

    existing = set(store.universe())
    already = [t for t in cleaned if t in existing]
    new = store.add_to_universe(cleaned, fetch=not args.no_fetch)

    if new:
        print(f"Added: {', '.join(new)}")
    if already:
        print(f"Already present: {', '.join(already)}")
    if new and not args.no_fetch:
        print(f"Fetched data for: {', '.join(new)}")
    print(f"Universe now contains {len(store.universe())} tickers.")


if __name__ == "__main__":
    main()
