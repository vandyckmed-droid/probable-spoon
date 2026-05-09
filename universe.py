"""Universe loading, share-class dedupe, ticker→sector resolution, hygiene."""
import json
import re
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

    # Restrict to the deduped universe so dropped share classes
    # (e.g. PBR-A when PBR is also present) don't reappear downstream.
    valid = set(all_tickers())
    return {t: s for t, s in out.items() if t in valid}


def ticker_to_industry(profiles_data: dict) -> dict[str, str]:
    """Map each cached profile to its FMP industry string, defaulted to
    'Unknown' when the profile is missing or the field is empty. Intended
    for industry-level z-scoring; the caller filters to the active set."""
    out: dict[str, str] = {}
    for ticker, prof in (profiles_data or {}).items():
        ind = (prof.get("industry") or "").strip()
        out[ticker] = ind or "Unknown"
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


# ---------------------------------------------------------------------------
# Universe hygiene
#
# Keep: common stocks, ADRs, foreign ordinary shares.
# Exclude: preferreds, baby bonds/notes, warrants, rights, ETFs/funds,
#          SPAC units. Duplicate share classes are already handled above.
# Label: ADRs, REITs, MLPs.
#
# Detection has two layers. Ticker-suffix patterns catch cases where the
# profile data is missing or wrong (warrants, preferreds, rights, notes,
# units). Profile fields (isEtf / isFund / isAdr / industry / country)
# refine the rest. Both are conservative — when in doubt, the ticker is
# kept eligible rather than silently excluded.
# ---------------------------------------------------------------------------

_TICKER_EXCLUSIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(\.WS|\.W|-WS|-W)$", re.IGNORECASE),                  "warrant"),
    # Preferred shares: require a series letter after .P / -P / .PR / -PR
    # so plain symbols ending in "P" (and the bare suffixes ".P" / "-P"
    # without a series letter) don't get swept in. US vendors emit
    # preferreds as e.g. BAC.PA, BAC-PA, BAC.PRA, BAC-PRA — the pattern
    # below matches each form but stops short of overmatching.
    (re.compile(r"(\.PR[A-Z]|-PR[A-Z]|\.P[A-Z]|-P[A-Z])$", re.I),       "preferred"),
    (re.compile(r"(\.RT|-RT|\.R)$", re.IGNORECASE),                     "right"),
    (re.compile(r"(-NT|\.NT)$", re.IGNORECASE),                         "note"),
    (re.compile(r"(\.U|-U|=U)$", re.IGNORECASE),                        "unit"),
]

_EXCLUSION_LABELS = {
    "warrant":   "Warrants",
    "preferred": "Preferred shares",
    "right":     "Rights",
    "note":      "Baby bonds / notes",
    "unit":      "SPAC units",
    "etf":       "ETFs",
    "fund":      "Mutual / closed-end funds",
}


def _classify_one(ticker: str, profile: dict) -> tuple[str, object]:
    """Return ('excluded', reason) or ('eligible', list_of_labels)."""
    for rx, kind in _TICKER_EXCLUSIONS:
        if rx.search(ticker):
            return ("excluded", kind)

    if profile:
        if profile.get("is_etf") is True:
            return ("excluded", "etf")
        if profile.get("is_fund") is True:
            return ("excluded", "fund")

    labels: list[str] = []
    if profile:
        industry = (profile.get("industry") or "").lower()
        name = (profile.get("company_name") or "").lower()
        country = (profile.get("country") or "").upper()
        is_adr_flag = profile.get("is_adr") is True

        if (
            is_adr_flag
            or "adr" in name
            or "depositary" in name
            or (country and country not in ("US", "USA"))
        ):
            labels.append("ADR")
        if "reit" in industry or "real estate investment" in industry:
            labels.append("REIT")
        if (
            " lp" in (" " + name)
            or "limited partnership" in name
            or "master limited" in industry
        ):
            labels.append("MLP")

    return ("eligible", labels)


def classify_universe(
    tickers: list[str], profiles_data: dict,
) -> tuple[list[str], dict[str, str], dict[str, list[str]]]:
    """Apply hygiene rules to a raw ticker list.

    Returns:
        eligible: tickers that pass all rules, in input order
        excluded: {ticker: reason_key} where reason_key is one of
                  warrant, preferred, right, note, unit, etf, fund
        labels:   {ticker: [labels]} where labels is some combination of
                  ADR, REIT, MLP — empty entries are omitted
    """
    eligible: list[str] = []
    excluded: dict[str, str] = {}
    labels: dict[str, list[str]] = {}
    for t in tickers:
        prof = profiles_data.get(t) or {}
        status, info = _classify_one(t, prof)
        if status == "excluded":
            excluded[t] = info  # type: ignore[assignment]
        else:
            eligible.append(t)
            if info:
                labels[t] = info  # type: ignore[assignment]
    return eligible, excluded, labels


def exclusion_reason_label(key: str) -> str:
    """Human-readable label for an exclusion reason key."""
    return _EXCLUSION_LABELS.get(key, key.title())
