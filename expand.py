"""CLI to expand the universe with extra tickers."""
import argparse

import store


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Add tickers to the universe extras file."
    )
    p.add_argument("tickers", nargs="+", help="Tickers to add (case-insensitive).")
    p.add_argument(
        "--no-fetch", action="store_true",
        help="Skip data fetch after adding.",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    cleaned: list[str] = []
    seen: set[str] = set()
    for t in args.tickers:
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


if __name__ == "__main__":
    main()
