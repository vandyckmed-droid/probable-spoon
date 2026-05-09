"""Analyst estimates + earnings surprises per ticker, with on-disk pickle cache.

Step 1 of the Expectations factor — diagnostic only, not in composite.
Mirrors the fundamentals.py pattern (per-ticker freshness, additive cache,
graceful save failure).
"""
import datetime as dt
import pickle
from pathlib import Path

import config
import fmp_client


def load_cache() -> dict:
    p = Path(config.REVISIONS_CACHE)
    if not p.exists():
        return {"data": {}}
    with open(p, "rb") as f:
        return pickle.load(f)


def save_cache(cache: dict) -> None:
    p = Path(config.REVISIONS_CACHE)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            pickle.dump(cache, f)
    except (OSError, PermissionError) as e:
        print(f"WARNING: could not save revisions cache to {p}: {e}")


def is_stale_for(cache: dict, ticker: str) -> bool:
    """True if cache lacks ticker OR its 'fetched' is older than REVISIONS_REFRESH_DAYS."""
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
    return (dt.date.today() - fetched_dt).days >= config.REVISIONS_REFRESH_DAYS


def _as_list(payload) -> list:
    return payload if isinstance(payload, list) else []


def _fetch_one(ticker: str) -> dict | None:
    """Fetch annual estimates and recent earnings surprises.

    Surprises are optional — if FMP returns 403 (e.g. tier restriction) we
    keep the estimates and continue with surprises = []. If estimates
    themselves fail, the ticker is skipped (returns None).
    """
    try:
        estimates = fmp_client.get(
            "analyst-estimates",
            params={"symbol": ticker, "period": "annual", "limit": 2},
        )
    except fmp_client.FMPError:
        return None
    try:
        surprises = fmp_client.get(
            "earnings-surprises",
            params={"symbol": ticker, "limit": 4},
        )
    except fmp_client.FMPError:
        surprises = []
    return {
        "fetched": dt.date.today().isoformat(),
        "estimates": _as_list(estimates),
        "surprises": _as_list(surprises),
    }


def fetch_revisions(
    tickers: list[str], *, force: bool = False, no_fetch: bool = False,
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
        print(f"fetching expectations for {total} ticker(s)...")
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
