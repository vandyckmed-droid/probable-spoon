"""Universe loading, share-class dedupe, ticker→sector resolution."""
import json
from pathlib import Path

UNIVERSE_JSON = Path("data/universe.json")
UNIVERSE_EXTRA = Path("data/universe_extra.txt")
SECTOR_ETF_MAP = Path("data/sector_etf_map.json")

# When both share classes appear, keep the voting class and drop the other.
# GOOGL (voting) > GOOG, FOXA (voting) > FOX, BRK.A (voting) > BRK.B,
# PBR (Brazilian ON, voting) > PBR-A (PN preferred, non-voting).
# Both dotted and hyphenated ticker conventions are covered for share classes
# where US data vendors disagree on the format (BRK, PBR).
_SHARE_CLASS_DROPS = {
    "GOOG": "GOOGL",
    "FOX": "FOXA",
    "BRK.B": "BRK.A",
    "BRK-B": "BRK-A",
    "PBR-A": "PBR",
    "PBR.A": "PBR",
}


def load_universe_json() -> dict[str, list[str]]:
    if not UNIVERSE_JSON.exists():
        return {}
    try:
        with open(UNIVERSE_JSON, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): [str(t).upper() for t in v]
        for k, v in data.items()
        if isinstance(v, list)
    }


def load_universe_extras() -> list[str]:
    if not UNIVERSE_EXTRA.exists():
        return []
    out: list[str] = []
    seen: set[str] = set()
    with open(UNIVERSE_EXTRA, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            t = line.upper()
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out


def load_sector_etf_map() -> dict[str, str]:
    if not SECTOR_ETF_MAP.exists():
        return {}
    try:
        with open(SECTOR_ETF_MAP, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def all_tickers() -> list[str]:
    """Union of universe.json values and extras, share-class filter, sorted."""
    s: set[str] = set()
    for tickers in load_universe_json().values():
        s.update(t.upper() for t in tickers)
    s.update(load_universe_extras())
    for drop, keep in _SHARE_CLASS_DROPS.items():
        if drop in s and keep in s:
            s.discard(drop)
    return sorted(s)


def ticker_to_sector(profiles_data: dict) -> dict[str, str]:
    """Map each universe ticker to its sector, applying research overrides last."""
    out: dict[str, str] = {}
    for sector, tickers in load_universe_json().items():
        for t in tickers:
            out[t.upper()] = sector
    for t in load_universe_extras():
        if t in out:
            continue
        prof = profiles_data.get(t) or {}
        out[t] = prof.get("sector") or "Unknown"

    for t in list(out.keys()):
        prof = profiles_data.get(t) or {}
        industry = (prof.get("industry") or "").lower()
        if not industry:
            continue
        if "semiconductor" in industry:
            out[t] = "Semiconductors"
        elif "aerospace" in industry or "defense" in industry:
            out[t] = "Aerospace & Defense"
    return out


def add_to_universe_extras(tickers: list[str]) -> list[str]:
    """Append novel tickers to the extras file. Idempotent. Returns newly added."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for t in tickers:
        u = t.strip().upper()
        if u and u not in seen:
            seen.add(u)
            cleaned.append(u)

    existing = set(load_universe_extras())
    new = [t for t in cleaned if t not in existing]
    if not new:
        return []

    UNIVERSE_EXTRA.parent.mkdir(parents=True, exist_ok=True)
    content = (
        UNIVERSE_EXTRA.read_text(encoding="utf-8")
        if UNIVERSE_EXTRA.exists() else ""
    )
    if content and not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new) + "\n"
    UNIVERSE_EXTRA.write_text(content, encoding="utf-8")
    return new
