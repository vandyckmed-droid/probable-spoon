"""Liquid US-listed common-stock universe via the FMP screener.

Stage 1 of the sector-index build: a broad exchange sweep filtered on market
cap and share volume, then a per-sector shortlist ranked on screener dollar
volume. The shortlist is deliberately wider than the final index size so that
stage 2 (real price history) can drop names on data quality and still fill
every sector.
"""
import config
import fmp_client

EXCHANGES = ("NYSE", "NASDAQ", "AMEX")

# Sectors that are not tradable equity sleeves for this purpose.
_EXCLUDED_SECTORS = {"", "None", "Unknown"}


def _screen_exchange(exchange: str) -> list[dict]:
    try:
        rows = fmp_client.get(
            "company-screener",
            params={
                "exchange": exchange,
                "country": "US",
                "marketCapMoreThan": int(config.SCREEN_MIN_MARKET_CAP),
                "volumeMoreThan": int(config.SCREEN_MIN_VOLUME),
                "isEtf": "false",
                "isFund": "false",
                "isActivelyTrading": "true",
                "limit": config.SCREEN_LIMIT,
            },
        )
    except fmp_client.FMPError as e:
        print(f"WARNING: screener failed for {exchange}: {e}")
        return []
    return rows if isinstance(rows, list) else []


def _clean(row: dict) -> dict | None:
    symbol = (row.get("symbol") or "").upper()
    sector = (row.get("sector") or "").strip()
    if not symbol or sector in _EXCLUDED_SECTORS:
        return None
    try:
        price = float(row.get("price") or 0.0)
        volume = float(row.get("volume") or 0.0)
        market_cap = float(row.get("marketCap") or 0.0)
    except (TypeError, ValueError):
        return None
    if price <= 0 or volume <= 0 or market_cap <= 0:
        return None
    return {
        "ticker": symbol,
        "name": row.get("companyName") or symbol,
        "sector": sector,
        "industry": (row.get("industry") or "").strip(),
        "price": price,
        "volume": volume,
        "market_cap": market_cap,
        "screen_dollar_volume": price * volume,
        "exchange": row.get("exchangeShortName") or row.get("exchange") or "",
    }


def _drop_secondary_share_classes(by_ticker: dict[str, dict]) -> dict[str, dict]:
    """Keep one line per company: the known voting class, else the root symbol.

    Two conventions show up in FMP data — separator-suffixed classes (BRK.B,
    PBR-A) whose root is also listed, and separator-free pairs (GOOG/GOOGL)
    which the repo's curated map resolves.
    """
    from universe import _SHARE_CLASS_DROPS

    out = dict(by_ticker)
    for drop, keep in _SHARE_CLASS_DROPS.items():
        if drop in out and keep in out:
            del out[drop]
    for symbol in list(out):
        for sep in (".", "-"):
            root = symbol.split(sep, 1)[0]
            if root != symbol and root in out:
                del out[symbol]
                break
    return out


def liquid_universe() -> list[dict]:
    """Every liquid US common stock the screener returns, de-duplicated."""
    by_ticker: dict[str, dict] = {}
    for exchange in EXCHANGES:
        rows = _screen_exchange(exchange)
        print(f"  screener {exchange}: {len(rows)} row(s)")
        for row in rows:
            rec = _clean(row)
            if rec is None:
                continue
            prev = by_ticker.get(rec["ticker"])
            if prev is None or rec["screen_dollar_volume"] > prev["screen_dollar_volume"]:
                by_ticker[rec["ticker"]] = rec
    by_ticker = _drop_secondary_share_classes(by_ticker)
    return sorted(by_ticker.values(), key=lambda r: -r["screen_dollar_volume"])


def candidates_by_sector(rows: list[dict] | None = None) -> dict[str, list[dict]]:
    """{sector: [candidate, ...]} — top N per sector on screener dollar volume."""
    rows = liquid_universe() if rows is None else rows
    buckets: dict[str, list[dict]] = {}
    for rec in rows:
        buckets.setdefault(rec["sector"], []).append(rec)

    out: dict[str, list[dict]] = {}
    for sector, recs in buckets.items():
        if len(recs) < config.SECTOR_INDEX_SIZE:
            print(
                f"  skipping {sector}: only {len(recs)} liquid name(s), "
                f"need {config.SECTOR_INDEX_SIZE}"
            )
            continue
        recs.sort(key=lambda r: -r["screen_dollar_volume"])
        out[sector] = recs[: config.SECTOR_CANDIDATES_PER_SECTOR]
    return dict(sorted(out.items()))
