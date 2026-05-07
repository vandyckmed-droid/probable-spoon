"""Annual income/balance/cashflow per ticker, with on-disk pickle cache."""
import datetime as dt
import pickle
from pathlib import Path

import config
import fmp_client


def load_cache() -> dict:
    p = Path(config.FUNDAMENTALS_CACHE)
    if not p.exists():
        return {"data": {}}
    with open(p, "rb") as f:
        return pickle.load(f)


def save_cache(cache: dict) -> None:
    p = Path(config.FUNDAMENTALS_CACHE)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        pickle.dump(cache, f)


def is_stale_for(cache: dict, ticker: str) -> bool:
    """True if cache lacks ticker OR its 'fetched' is older than FUNDAMENTALS_REFRESH_DAYS."""
    entry = cache.get("data", {}).get(ticker)
    if not entry:
        return True
    fetched = entry.get("fetched")
    if not fetched:
        return True
    try:
        fetched_dt = dt.date.fromisoformat(fetched)
    except (TypeError, ValueError):
        return True
    return (dt.date.today() - fetched_dt).days >= config.FUNDAMENTALS_REFRESH_DAYS


def _as_list(payload) -> list:
    return payload if isinstance(payload, list) else []


def _fetch_one(ticker: str) -> dict | None:
    """Fetch the three statements. Return None on 403 (ETF) or other FMP failure."""
    try:
        income = fmp_client.get(
            "income-statement",
            params={"symbol": ticker, "period": "annual", "limit": 2},
        )
        balance = fmp_client.get(
            "balance-sheet-statement",
            params={"symbol": ticker, "period": "annual", "limit": 2},
        )
        cashflow = fmp_client.get(
            "cash-flow-statement",
            params={"symbol": ticker, "period": "annual", "limit": 1},
        )
    except fmp_client.FMPError:
        return None
    return {
        "fetched": dt.date.today().isoformat(),
        "income": _as_list(income),
        "balance": _as_list(balance),
        "cashflow": _as_list(cashflow),
    }


def fetch_fundamentals(
    tickers: list[str], *, force: bool = False, no_fetch: bool = False
) -> dict:
    """Per-ticker freshness. Returns cache['data']."""
    cache = load_cache()
    data = cache.setdefault("data", {})

    if no_fetch:
        return data

    candidates = list(dict.fromkeys(tickers))
    to_fetch = [t for t in candidates if force or is_stale_for(cache, t)]
    total = len(to_fetch)
    if total:
        print(f"fetching fundamentals for {total} ticker(s)...")
    changed = False
    for i, t in enumerate(to_fetch, 1):
        print(f"  [{i}/{total}] {t}")
        entry = _fetch_one(t)
        if entry is not None:
            data[t] = entry
            changed = True

    if changed:
        save_cache(cache)
    return data
