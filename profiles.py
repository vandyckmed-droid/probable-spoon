"""Company /profile per ticker, with on-disk pickle cache."""
import datetime as dt
import pickle
from pathlib import Path

import config
import fmp_client


_FIELD_MAP = {
    "company_name": "companyName",
    "sector": "sector",
    "industry": "industry",
    "country": "country",
    "exchange": "exchangeShortName",
    "currency": "currency",
}


def load_cache() -> dict:
    p = Path(config.PROFILES_CACHE)
    if not p.exists():
        return {"data": {}}
    with open(p, "rb") as f:
        return pickle.load(f)


def save_cache(cache: dict) -> None:
    p = Path(config.PROFILES_CACHE)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        pickle.dump(cache, f)


def is_stale_for(cache: dict, ticker: str) -> bool:
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
    return (dt.date.today() - fetched_dt).days >= config.PROFILES_REFRESH_DAYS


def _fetch_one(ticker: str) -> dict | None:
    """Try stable then legacy. Return None on FMPError (incl. 403 ETFs)."""
    try:
        data = fmp_client.get("profile", params={"symbol": ticker})
    except fmp_client.FMPError:
        try:
            data = fmp_client.get(f"profile/{ticker}", base=config.FMP_LEGACY_BASE)
        except fmp_client.FMPError:
            return None

    rows = data if isinstance(data, list) else []
    if not rows:
        return None
    row = rows[0] if isinstance(rows[0], dict) else {}

    entry: dict = {"fetched": dt.date.today().isoformat()}
    for out_key, src_key in _FIELD_MAP.items():
        val = row.get(src_key)
        entry[out_key] = val if isinstance(val, str) else ("" if val is None else str(val))
    return entry


def fetch_profiles(
    tickers: list[str], *, force: bool = False, no_fetch: bool = False
) -> dict:
    """Per-ticker freshness. Returns cache['data']."""
    cache = load_cache()
    data = cache.setdefault("data", {})

    if no_fetch:
        return data

    changed = False
    for t in dict.fromkeys(tickers):
        if not force and not is_stale_for(cache, t):
            continue
        entry = _fetch_one(t)
        if entry is not None:
            data[t] = entry
            changed = True

    if changed:
        save_cache(cache)
    return data
