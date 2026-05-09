"""Snapshot archive — append-only point-in-time record of each successful run.

Designed as background data collection that becomes useful later for forward
testing, rank-decay analysis, turnover tracking, and realised-return work
once the model stabilises. Snapshots are version-tagged so dev tweaks do
not silently merge into a "stable strategy" timeline.

Layout:
    snapshots/
        2026-05-08T14-32-15_mqv_v0.4-dev/
            metadata.json     run-level info, weights, vol targets, counts
            config.json       formula constants frozen at this run
            universe.csv      every raw ticker + status (active / excluded)
            ranked.csv        full ranked frame (everything that scored)
            portfolio.csv     top-N selection with weights & cash per scheme

The directory is gitignored — runtime artifact like cache/ and reports/.
Failures (disk full, sandbox restrictions) are reported as warnings, never
crash the pipeline.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

import config


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_", ".") else "-" for c in s)


def _today_stamp() -> str:
    """Date-only stamp used in snapshot directory names. One snapshot per day:
    same-day re-runs overwrite the day's directory in place, preserving the
    archive as a once-a-day point-in-time series rather than a per-run log."""
    return dt.date.today().strftime("%Y-%m-%d")


# Files we manage inside a snapshot directory. Removed before each write so
# a stale artefact from a previous run does not survive when the new run
# does not produce that file (e.g., empty ranked → no portfolio.csv).
_SNAPSHOT_FILES = (
    "metadata.json", "config.json",
    "universe.csv", "ranked.csv", "portfolio.csv",
)


def _config_snapshot() -> dict:
    """Freeze the relevant config constants for this run."""
    keys = [
        "W_MOMENTUM", "W_QUALITY", "W_VALUE",
        "MOM_W_12_1", "MOM_W_6_1",
        "Q_GP_W", "Q_GP_CHANGE_W", "Q_NETDEBT_W",
        "V_EBIT_EV_W", "V_FCF_EV_W", "V_BP_W",
        "HISTORY_TRADING_DAYS", "MOMENTUM_MIN_OBS", "BETA_LOOKBACK_DAYS",
        "MOM_LONG_DAYS", "MOM_SHORT_DAYS", "MOM_SKIP_DAYS", "MOM_REV_DAYS",
        "SIGMA_DAYS", "SIGMA_FLOOR",
        "WEIGHT_LOOKBACK_DAYS", "BACKTEST_DAYS",
        "WINSOR_LOWER", "WINSOR_UPPER",
        "MIN_SECTOR_SIZE",
        "QUALITY_FALLBACK_THRESHOLD", "VALUE_FALLBACK_THRESHOLD",
        "TOP_N", "WEIGHTING_SCHEME", "CASH_DEPLOYMENT", "VOL_TARGET",
        "EXPECTATIONS_ENABLED", "EXP_GROWTH_W", "EXP_SURPRISE_W",
        "MARKET_TICKER",
    ]
    out: dict = {}
    for k in keys:
        if hasattr(config, k):
            v = getattr(config, k)
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[k] = v
            else:
                out[k] = str(v)
    return out


def _build_metadata(
    factors_used: dict, top_n: int, prices_as_of: str | None,
    warnings_list: list[str] | None = None,
) -> dict:
    """Run-level metadata. Strips bulky nested dicts that already live in CSVs."""
    fu = factors_used or {}
    universe_excluded = fu.get("universe_excluded") or {}
    excluded_summary: dict[str, int] = {}
    for _t, reason in universe_excluded.items():
        excluded_summary[reason] = excluded_summary.get(reason, 0) + 1
    return {
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "strategy": getattr(config, "MQV_STRATEGY_NAME", "mqv"),
        "version": getattr(config, "MQV_VERSION", "unknown"),
        "stable": bool(getattr(config, "MQV_STABLE", False)),
        "prices_as_of": prices_as_of,
        "weights_renormalised": fu.get("weights"),
        "weighting_scheme": fu.get("weighting_scheme"),
        "top_n": int(top_n),
        "cash_deployment": fu.get("cash_deployment"),
        "vol_target": fu.get("vol_target"),
        "scheme_vols": fu.get("scheme_vols"),
        "scheme_scales": fu.get("scheme_scales"),
        "universe_counts": {
            "raw": fu.get("universe_raw_count"),
            "eligible": fu.get("universe_eligible_count"),
            "active": fu.get("universe_active_count"),
            "excluded_total": sum(excluded_summary.values()),
            "excluded_by_reason": excluded_summary,
        },
        "active_filters": fu.get("universe_active_filters"),
        "expectations_enabled": fu.get("expectations_enabled"),
        "expectations_coverage": fu.get("expectations_coverage"),
        "expectations_count": fu.get("expectations_count"),
        "display_limit": fu.get("display_limit"),
        "warnings": warnings_list or [],
    }


def _universe_csv(
    raw_tickers: list, active_tickers: list, excluded: dict,
    profiles_data: dict, labels: dict, ranked: pd.DataFrame,
) -> pd.DataFrame:
    """One row per raw ticker; status column tells you what happened to it."""
    active_set = set(active_tickers)
    rows = []
    seen: set = set()
    for t in raw_tickers:
        if t in seen:
            continue
        seen.add(t)
        prof = profiles_data.get(t) or {}
        if t in excluded:
            status = f"excluded_{excluded[t]}"
        elif t in active_set:
            status = "active"
        else:
            status = "filtered_out"
        mc = float("nan")
        if ranked is not None and not ranked.empty and t in ranked.index:
            v = ranked.loc[t, "market_cap"] if "market_cap" in ranked.columns else float("nan")
            if pd.notna(v):
                mc = float(v)
        rows.append({
            "ticker": t,
            "status": status,
            "sector": prof.get("sector") or "",
            "industry": prof.get("industry") or "",
            "country": prof.get("country") or "",
            "market_cap": mc,
            "labels": "|".join(labels.get(t) or []),
        })
    return pd.DataFrame(rows)


def _portfolio_csv(
    ranked: pd.DataFrame, top_n: int, cash: float | None,
    scheme_scales: dict | None,
) -> pd.DataFrame:
    """Top-N selection with weights and cash from each weighting scheme."""
    if ranked is None or ranked.empty:
        return pd.DataFrame()
    top = ranked.head(top_n).copy()
    keep = [c for c in ("sector", "composite", "rank") if c in top.columns]
    for c in ("equal_weight", "ivp_weight", "hrp_weight", "expectations_z"):
        if c in top.columns:
            keep.append(c)
    out = top[keep].copy()
    cash = float(cash or 0)
    scales = scheme_scales or {}
    if cash > 0:
        for col, key in (("equal_weight", "equal"),
                         ("ivp_weight", "ivp"),
                         ("hrp_weight", "hrp")):
            if col in out.columns:
                eff = cash * float(scales.get(key, 1.0) or 1.0)
                out[f"{col.split('_')[0]}_cash"] = (out[col] * eff).round(2)
    return out


def save_snapshot(
    *,
    ranked: pd.DataFrame,
    top_n: int,
    factors_used: dict,
    raw_tickers: list,
    active_tickers: list,
    excluded: dict,
    profiles_data: dict,
    labels: dict,
    prices_as_of: str | None,
    warnings_list: list[str] | None = None,
) -> Path | None:
    """Persist a full snapshot. Returns the snapshot dir on success, None on
    failure (e.g. read-only filesystem). Never raises into the caller."""
    try:
        version = _slug(getattr(config, "MQV_VERSION", "unknown"))
        strategy = _slug(getattr(config, "MQV_STRATEGY_NAME", "mqv"))
        ts = _today_stamp()
        root = Path(getattr(config, "SNAPSHOTS_DIR", "snapshots"))
        snap_dir = root / f"{ts}_{strategy}_v{version}"
        snap_dir.mkdir(parents=True, exist_ok=True)
        # Same-day re-run: clear our managed files so a previous run's
        # artefact does not survive when the new run does not regenerate
        # it. We only touch the known snapshot files — anything else the
        # user might drop in the directory is left alone.
        for fname in _SNAPSHOT_FILES:
            fp = snap_dir / fname
            if fp.exists():
                try:
                    fp.unlink()
                except OSError:
                    pass

        meta = _build_metadata(factors_used, top_n, prices_as_of, warnings_list)
        cfg = _config_snapshot()

        (snap_dir / "metadata.json").write_text(
            json.dumps(meta, indent=2, default=str), encoding="utf-8",
        )
        (snap_dir / "config.json").write_text(
            json.dumps(cfg, indent=2, default=str), encoding="utf-8",
        )

        uni = _universe_csv(
            raw_tickers, active_tickers, excluded, profiles_data, labels, ranked,
        )
        if not uni.empty:
            uni.to_csv(snap_dir / "universe.csv", index=False)

        if ranked is not None and not ranked.empty:
            ranked.to_csv(snap_dir / "ranked.csv", index=True)

        port = _portfolio_csv(
            ranked, top_n,
            factors_used.get("cash_deployment") if factors_used else None,
            factors_used.get("scheme_scales") if factors_used else None,
        )
        if not port.empty:
            port.to_csv(snap_dir / "portfolio.csv", index=True)

        return snap_dir
    except (OSError, PermissionError, ValueError, TypeError) as e:
        print(f"WARNING: could not save snapshot: {e}")
        return None


def list_snapshots(limit: int | None = None) -> list[dict]:
    """Summary records for recent snapshots, newest first. Reads only the
    per-snapshot metadata.json so it's cheap to call from the report."""
    root = Path(getattr(config, "SNAPSHOTS_DIR", "snapshots"))
    if not root.exists():
        return []
    entries: list[dict] = []
    for child in sorted(root.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        meta_path = child / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        counts = meta.get("universe_counts") or {}
        entries.append({
            "dir": child.name,
            "timestamp": meta.get("timestamp"),
            "version": meta.get("version"),
            "stable": bool(meta.get("stable")),
            "active": counts.get("active"),
            "top_n": meta.get("top_n"),
        })
        if limit is not None and len(entries) >= limit:
            break
    return entries
