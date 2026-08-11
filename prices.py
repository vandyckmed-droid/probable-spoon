"""Adjusted daily prices and volumes, with on-disk pickle cache."""
import datetime as dt
import pickle
from pathlib import Path

import pandas as pd

import config
import fmp_client


def load_cache() -> dict:
    p = Path(config.PRICES_CACHE)
    if not p.exists():
        return {"as_of": None, "prices": pd.DataFrame(), "volumes": pd.DataFrame()}
    with open(p, "rb") as f:
        return pickle.load(f)


def save_cache(cache: dict) -> None:
    p = Path(config.PRICES_CACHE)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            pickle.dump(cache, f)
    except (OSError, PermissionError) as e:
        print(f"WARNING: could not save prices cache to {p}: {e}")


def is_stale(cache: dict) -> bool:
    """True if cache empty or older than PRICES_REFRESH_DAYS."""
    as_of = cache.get("as_of")
    if not as_of:
        return True
    try:
        as_of_dt = dt.date.fromisoformat(as_of)
    except (TypeError, ValueError):
        return True
    return (dt.date.today() - as_of_dt).days >= config.PRICES_REFRESH_DAYS


def _parse_rows(rows: list) -> tuple[pd.Series, pd.Series]:
    dates, closes, vols = [], [], []
    for r in rows or []:
        d = r.get("date")
        if not d:
            continue
        c = r.get("adjClose")
        if c is None:
            c = r.get("close")
        if c is None:
            continue
        dates.append(pd.Timestamp(d))
        closes.append(float(c))
        vols.append(float(r.get("volume") or 0))
    if not dates:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    idx = pd.DatetimeIndex(dates)
    return (
        pd.Series(closes, index=idx).sort_index(),
        pd.Series(vols, index=idx).sort_index(),
    )


def fetch_one(ticker: str, from_date: str) -> tuple[pd.Series, pd.Series]:
    """Adjusted close + volume for one ticker from `from_date`. Empty on failure."""
    try:
        data = fmp_client.get(
            "historical-price-eod/full",
            params={"symbol": ticker, "from": from_date},
        )
        if isinstance(data, dict):
            rows = data.get("historical") or []
        else:
            rows = data or []
        p, v = _parse_rows(rows)
        if not p.empty:
            return p, v
    except fmp_client.FMPError:
        pass

    try:
        data = fmp_client.get(
            f"historical-price-full/{ticker}",
            base=config.FMP_LEGACY_BASE,
        )
        rows = data.get("historical") if isinstance(data, dict) else []
        return _parse_rows(rows or [])
    except fmp_client.FMPError:
        return pd.Series(dtype=float), pd.Series(dtype=float)


def fetch_prices(
    tickers: list[str], *, force: bool = False, no_fetch: bool = False
) -> dict:
    """Refresh price cache so it contains ONLY `tickers`. Returns cache dict."""
    tickers = list(dict.fromkeys(tickers))
    cache = load_cache()

    if no_fetch:
        return cache

    stale = is_stale(cache)
    cached_p = cache["prices"]
    cached_v = cache["volumes"]
    have = set(cached_p.columns) if not cached_p.empty else set()

    if force or stale:
        to_fetch = list(tickers)
    else:
        to_fetch = [t for t in tickers if t not in have]

    from_date = (
        dt.date.today()
        - dt.timedelta(days=int(config.HISTORY_TRADING_DAYS * 1.5))
    ).isoformat()

    new_p: dict[str, pd.Series] = {}
    new_v: dict[str, pd.Series] = {}
    total = len(to_fetch)
    if total:
        print(f"fetching prices for {total} ticker(s)...")
    for i, t in enumerate(to_fetch, 1):
        print(f"  [{i}/{total}] {t}")
        p, v = fetch_one(t, from_date)
        if not p.empty:
            new_p[t] = p
        if not v.empty:
            new_v[t] = v

    keep = [t for t in tickers if t not in to_fetch and t in have]
    parts_p, parts_v = [], []
    if keep:
        parts_p.append(cached_p[keep])
        keep_v = [t for t in keep if t in cached_v.columns]
        if keep_v:
            parts_v.append(cached_v[keep_v])
    if new_p:
        parts_p.append(pd.DataFrame(new_p))
    if new_v:
        parts_v.append(pd.DataFrame(new_v))

    prices_df = (
        pd.concat(parts_p, axis=1).sort_index() if parts_p else pd.DataFrame()
    )
    volumes_df = (
        pd.concat(parts_v, axis=1).sort_index() if parts_v else pd.DataFrame()
    )

    if not prices_df.empty:
        prices_df = prices_df[[c for c in tickers if c in prices_df.columns]]
    if not volumes_df.empty:
        volumes_df = volumes_df[[c for c in tickers if c in volumes_df.columns]]

    cache = {
        "as_of": dt.date.today().isoformat(),
        "prices": prices_df,
        "volumes": volumes_df,
    }
    save_cache(cache)
    return cache
