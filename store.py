"""Unified data-layer facade. Orchestrators import only this module."""
import pandas as pd

import fundamentals as fundamentals_mod
import prices as prices_mod
import profiles as profiles_mod
import universe as universe_mod


def universe() -> list[str]:
    """De-duplicated, share-class-corrected universe."""
    return universe_mod.all_tickers()


def ensure(
    tickers: list[str],
    *,
    with_prices: bool = True,
    with_fundamentals: bool = True,
    with_profiles: bool = True,
    force: bool = False,
    no_fetch: bool = False,
) -> None:
    """Top up caches.

    CRITICAL re prices: fetch_prices REWRITES its cache to only the tickers passed
    in. Always pass the full union (market + sector ETFs + stocks) when with_prices.
    """
    if with_prices:
        prices_mod.fetch_prices(tickers, force=force, no_fetch=no_fetch)
    if with_fundamentals:
        fundamentals_mod.fetch_fundamentals(tickers, force=force, no_fetch=no_fetch)
    if with_profiles:
        profiles_mod.fetch_profiles(tickers, force=force, no_fetch=no_fetch)


def prices() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (prices_df, volumes_df) from cache; empty DataFrames if absent."""
    cache = prices_mod.load_cache()
    p = cache.get("prices")
    v = cache.get("volumes")
    if not isinstance(p, pd.DataFrame):
        p = pd.DataFrame()
    if not isinstance(v, pd.DataFrame):
        v = pd.DataFrame()
    return p, v


def fundamentals() -> dict:
    """{ticker: {income, balance, cashflow, fetched}}."""
    return fundamentals_mod.load_cache().get("data", {})


def profiles() -> dict:
    """{ticker: {company_name, sector, industry, country, exchange, currency, fetched}}."""
    return profiles_mod.load_cache().get("data", {})


def company_names(tickers: list[str]) -> dict[str, str]:
    """{ticker: company_name}, falling back to the ticker itself."""
    data = profiles()
    out: dict[str, str] = {}
    for t in tickers:
        prof = data.get(t) or {}
        name = prof.get("company_name") or ""
        out[t] = name if name else t
    return out


def add_to_universe(tickers: list[str], *, fetch: bool = True) -> list[str]:
    """Append to extras file. If fetch=True, top up fundamentals/profiles for new ones.

    Skips prices on purpose: fetch_prices rewrites its cache, and this module
    does not see market/sector ETFs. The main pipeline owns the full-union
    prices refresh.
    """
    new = universe_mod.add_to_universe_extras(tickers)
    if new and fetch:
        ensure(new, with_prices=False)
    return new
