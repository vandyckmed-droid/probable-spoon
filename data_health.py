"""Per-ticker audit of data presence and freshness across the pipeline.

Run after the pipeline finishes. Inputs are the active ticker set and the
cached / computed data structures. Output is a structured dict the report
renderer surfaces in a Data Integrity drawer:

    {
        "n_active":      int,
        "n_with_issues": int,
        "by_category":   {category_label: count, ...},
        "by_ticker":     {ticker: [issue, ...], ...},
        "categories":    [(category_id, label, severity), ...],  # ordered
    }

Each issue dict has: category, detail, calc, source, action, last_refresh.
Categories are stable strings so the renderer can group + sort consistently.

Severity ordering (worst first): block (calculation can't run) → fallback
(used a less-precise tier) → stale (data old) → info (cosmetic).
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from config import BETA_LOOKBACK_DAYS


# Required price history for residualisation (matches BETA_LOOKBACK_DAYS).
REQUIRED_HISTORY_DAYS = BETA_LOOKBACK_DAYS

# Days a price series can lag the cache's latest date before it's "stale".
STALE_PRICE_GAP_DAYS = 5

# Categories: (id, human label, severity). Severity ranks a category for
# sort/display: 0=block, 1=fallback-used, 2=stale, 3=info.
CATEGORIES: list[tuple[str, str, int]] = [
    ("missing_profile",        "Missing profile",                 0),
    ("missing_sector",         "Missing sector",                  1),
    ("missing_industry",       "Missing industry",                1),
    ("missing_prices",         "Missing price history",           0),
    ("insufficient_history",   "Insufficient price history",      1),
    ("stale_prices",           "Stale price series",              2),
    ("missing_fundamentals",   "Missing fundamentals",            0),
    ("missing_income",         "Missing income statement",        1),
    ("missing_balance",        "Missing balance sheet",           1),
    ("missing_cashflow",       "Missing cash flow statement",     1),
    ("residual_skipped",       "Residualisation skipped",         0),
    ("momentum_missing",       "Momentum factor unavailable",     1),
    ("quality_missing",        "Quality factor unavailable",      1),
    ("value_missing",          "Value factor unavailable",        1),
    ("normalisation_fallback", "Normalisation fell back to universe", 3),
]
_CAT_INDEX = {cat: (label, sev) for cat, label, sev in CATEGORIES}


def _make(category: str, *, detail: str = "", calc: str = "",
          source: str = "", action: str = "",
          last_refresh: str | None = None) -> dict:
    return {
        "category": category,
        "detail": detail,
        "calc": calc,
        "source": source,
        "action": action,
        "last_refresh": last_refresh,
    }


def audit(
    active_tickers: list[str],
    profiles_data: dict,
    funds_data: dict,
    prices_df: pd.DataFrame,
    stock_resid_columns: set,
    ranked: pd.DataFrame,
    sector_etf_map: dict,
) -> dict:
    """Walk every active ticker and emit a list of data issues for it.

    The audit is deliberately conservative: it does not assert that an
    issue is fatal, only that data is missing or substituted. The report
    surfaces the issues so the user can decide whether to refresh, accept
    the fallback, or exclude the ticker.
    """
    by_ticker: dict[str, list[dict]] = {}

    cache_last_date = None
    if not prices_df.empty:
        last_idx = prices_df.index[-1]
        cache_last_date = (
            last_idx.date() if hasattr(last_idx, "date") else None
        )

    for t in active_tickers:
        issues: list[dict] = []

        prof = profiles_data.get(t) or {}
        if not prof:
            issues.append(_make(
                "missing_profile",
                detail="No FMP profile cached",
                calc="profile, sector/industry normalisation",
                source="no_cache_entry",
                action="re-run with --update to refetch profile",
            ))
        else:
            last_refresh = prof.get("fetched") or None
            sec = (prof.get("sector") or "").strip()
            ind = (prof.get("industry") or "").strip()
            if not sec:
                issues.append(_make(
                    "missing_sector",
                    detail="Profile fetched but sector field empty",
                    calc="sector residualisation, sector-relative z",
                    source="api_returned_empty_field"
                           if last_refresh else "never_fetched",
                    action="fallback to universe-wide z; "
                           "re-run with --update if FMP has since populated",
                    last_refresh=last_refresh,
                ))
            if not ind:
                issues.append(_make(
                    "missing_industry",
                    detail="Profile fetched but industry field empty",
                    calc="industry-relative z",
                    source="api_returned_empty_field"
                           if last_refresh else "never_fetched",
                    action="fallback to sector or universe",
                    last_refresh=last_refresh,
                ))

        n_days = 0
        last_t_date = None
        if (
            isinstance(prices_df, pd.DataFrame) and not prices_df.empty
            and t in prices_df.columns
        ):
            series = prices_df[t].dropna()
            n_days = len(series)
            if n_days:
                last_t = series.index[-1]
                last_t_date = (
                    last_t.date() if hasattr(last_t, "date") else None
                )
        if n_days == 0:
            issues.append(_make(
                "missing_prices",
                detail="No price series cached",
                calc="momentum, residualisation, weighting",
                source="no_price_column",
                action="re-run with --update to fetch prices",
            ))
        elif n_days < REQUIRED_HISTORY_DAYS:
            issues.append(_make(
                "insufficient_history",
                detail=f"{n_days} days cached / "
                       f"{REQUIRED_HISTORY_DAYS} needed for residualisation",
                calc="residualisation, beta estimation",
                source="short_history",
                action="wait for more history; momentum still computed "
                       "if length >= MOMENTUM_MIN_OBS",
                last_refresh=str(last_t_date) if last_t_date else None,
            ))
        elif (
            cache_last_date and last_t_date
            and (cache_last_date - last_t_date).days > STALE_PRICE_GAP_DAYS
        ):
            gap = (cache_last_date - last_t_date).days
            issues.append(_make(
                "stale_prices",
                detail=f"Last price {last_t_date} ({gap}d behind universe)",
                calc="momentum endpoint, residual chart",
                source="possible_delisting_or_halt",
                action="verify ticker still trades; re-run with --update",
                last_refresh=str(last_t_date),
            ))

        funds = funds_data.get(t) or {}
        if not funds:
            issues.append(_make(
                "missing_fundamentals",
                detail="No cached income / balance / cash flow",
                calc="quality, value",
                source="no_cache_entry",
                action="re-run with --update",
            ))
        else:
            f_refresh = funds.get("fetched") or None
            if not (funds.get("income") or []):
                issues.append(_make(
                    "missing_income",
                    detail="Income statements empty",
                    calc="quality (gross profit), value (EBIT/EV)",
                    source="empty_response",
                    action="verify FMP coverage for this ticker",
                    last_refresh=f_refresh,
                ))
            if not (funds.get("balance") or []):
                issues.append(_make(
                    "missing_balance",
                    detail="Balance sheets empty",
                    calc="quality (assets/debt), value (book/MC, EV)",
                    source="empty_response",
                    action="verify FMP coverage",
                    last_refresh=f_refresh,
                ))
            if not (funds.get("cashflow") or []):
                issues.append(_make(
                    "missing_cashflow",
                    detail="Cash flow statements empty",
                    calc="value (FCF/EV)",
                    source="empty_response",
                    action="verify FMP coverage; FCF/EV uses sector "
                           "fallback if missing",
                    last_refresh=f_refresh,
                ))

        if t not in stock_resid_columns:
            sec = (prof.get("sector") or "").strip() if prof else ""
            sec_etf = sector_etf_map.get(sec) if sec else None
            if not sec:
                source = "missing_sector_for_residual"
            elif not sec_etf:
                source = f"no_etf_proxy_for_sector_{sec}"
            else:
                source = "insufficient_history_or_data"
            issues.append(_make(
                "residual_skipped",
                detail="Stock has no residual return series",
                calc="momentum, HRP weighting",
                source=source,
                action=(
                    "wait for history or use --update; momentum will fall "
                    "back to NaN" if "history" in source
                    else "ensure sector/ETF mapping is configured"
                ),
            ))

        if t in ranked.index:
            row = ranked.loc[t]
            if pd.isna(row.get("residual_momentum_z")):
                issues.append(_make(
                    "momentum_missing",
                    detail="residual_momentum_z is NaN",
                    calc="momentum sleeve",
                    source="upstream_residual_or_history_gap",
                    action="see residual / history issues above",
                ))
            if pd.isna(row.get("quality_z")):
                issues.append(_make(
                    "quality_missing",
                    detail="quality_z is NaN",
                    calc="quality sleeve",
                    source="missing_inputs_or_zero_assets",
                    action="see fundamentals issues above",
                ))
            if pd.isna(row.get("value_z")):
                issues.append(_make(
                    "value_missing",
                    detail="value_z is NaN",
                    calc="value sleeve",
                    source="missing_inputs_or_negative_ev",
                    action="see fundamentals issues above",
                ))
            for col, key in (
                ("quality_scope", "quality"),
                ("value_scope", "value"),
            ):
                if col in ranked.columns and row.get(col) == "universe":
                    issues.append(_make(
                        "normalisation_fallback",
                        detail=f"{key} normalised universe-wide "
                               f"(industry+sector buckets too small)",
                        calc=f"{key} sleeve",
                        source="bucket_below_threshold",
                        action="cosmetic; ranking still valid",
                    ))

        if issues:
            by_ticker[t] = issues

    by_category: dict[str, int] = {}
    for issues in by_ticker.values():
        for iss in issues:
            cat = iss["category"]
            by_category[cat] = by_category.get(cat, 0) + 1

    return {
        "n_active": len(active_tickers),
        "n_with_issues": len(by_ticker),
        "by_category": by_category,
        "by_ticker": by_ticker,
        "categories": [
            (cat, label, sev)
            for cat, label, sev in CATEGORIES
            if by_category.get(cat, 0) > 0
        ],
    }


def category_label(cat: str) -> str:
    """Human label for a category id; falls back to the id itself."""
    info = _CAT_INDEX.get(cat)
    return info[0] if info else cat


def category_severity(cat: str) -> int:
    """Severity rank (lower = worse). Defaults to 3 (info) for unknowns."""
    info = _CAT_INDEX.get(cat)
    return info[1] if info else 3
