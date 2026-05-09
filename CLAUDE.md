# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-process equity ranking pipeline ("M/Q/V" — Momentum, Quality, Value) that scores a US-listed universe, builds a top-N portfolio with three weighting schemes, and emits a self-contained mobile-first HTML report plus a CSV. Pure stdlib networking (urllib) so it runs on Pyto/iOS as well as desktop. Data source is Financial Modeling Prep (FMP).

## Commands

The project has no `requirements.txt`, `pyproject.toml`, or `Makefile`. It depends on `pandas` and `numpy` only (everything else is stdlib).

```bash
# Run the pipeline against the cache (default: no network)
python main.py

# Top up missing/stale caches before ranking
python main.py --update

# Force refetch of all caches before ranking
python main.py --refresh

# Useful flags
python main.py --limit 50 --sort momentum --no-open
python main.py --cash 50000 --exclude-adr --exclude-reit
python main.py --output /tmp/run1/

# Expand the universe (writes to data/universe_extra.txt and tops up caches)
python expand.py NVDA AMD              # explicit tickers
python expand.py                       # default: top 20 US stocks by mkt cap
python expand.py --top 50 --no-fetch

# Tests — synthetic data only, live FMP is auto-blocked by conftest.py
pytest                                  # full suite
pytest tests/test_pipeline.py::test_momentum_scale_invariant -v
```

`config.FMP_API_KEY` must be set (either edited into `config.py` or via the `FMP_API_KEY` env var) before any `--update` / `--refresh` / `expand.py` run. Cache-only runs (`python main.py` with no flags) do not need a key.

## Architecture

### Data flow (single pass through `main.py`)

```
universe.json + universe_extra.txt
        │
        ▼
  store.universe()  ─────►  classify_universe (hygiene + ADR/REIT/MLP labels)
        │                          │
        │                          ▼
        │                  active filters (--exclude-adr / --exclude-reit)
        │                          │
        ▼                          ▼
  store.prices()  ──►  analytics.log_returns
                              │
                              ▼
            compute_sector_residuals (sector ETF on market)
                              │
                              ▼
            compute_stock_residuals  (stock on [market, sector_residual])
                  │            │
                  ▼            ▼
       compute_residual_momentum   compute_diagnostics (63d residual chart, sigma, pullback z)
                  │
  store.fundamentals() ──► compute_quality, compute_value
                  │
                  ▼
        analytics.build_ranked  (winsorize → z → composite → rank)
                  │
                  ▼
       weights.compute_weights (equal / inverse_vol / hrp; vol-target scale)
                  │
                  ▼
       data_health.audit  +  _build_universe_pulse
                  │
                  ▼
       report.render → reports/report.html  +  reports/ranked_stocks.csv
                  │
                  ▼
       snapshots.save_snapshot → snapshots/<date>_mqv_v<ver>/
```

### Module responsibilities

- `main.py` — CLI orchestrator; the only place that wires modules together. Parses args, calls `store.ensure` if `--update`/`--refresh`, runs the analytics pipeline, builds `factors_used` (the bag passed to the renderer), writes report + CSV + snapshot.
- `config.py` — every tunable constant. Composite weights, momentum sleeve weights, fallback thresholds, cache paths, FMP endpoints, snapshot version. **Bump `MQV_VERSION` whenever any formula or weight changes** so the snapshot archive doesn't conflate strategies.
- `store.py` — the **only** module orchestrators import for data access. Wraps `prices`, `fundamentals`, `profiles`, `revisions`, `universe`. `store.ensure(...)` is the single entry point for cache top-ups.
- `analytics.py` — all math: log returns, OLS residualisation, momentum (12-1 + 6-1 sleeves), quality (gross profitability, GP change, net debt), value (EBIT/EV, FCF/EV, B/P), expectations (diagnostic only — not in composite), composite/rank.
- `weights.py` — equal / inverse-vol / ERC / HRP; portfolio-vol estimation and vol-target scaling.
- `universe.py` — `all_tickers()`, share-class dedupe, sector/industry resolution, **and** universe hygiene (preferred/warrant/right/note/unit/ETF/fund exclusion + ADR/REIT/MLP labelling). Hygiene has two layers: ticker-suffix regex (works without profiles) and profile-field checks (refines once profiles are cached).
- `prices.py` / `fundamentals.py` / `profiles.py` / `revisions.py` — per-domain FMP fetcher + pickle cache. Each owns its cache file under `cache/`.
- `fmp_client.py` — pure-stdlib HTTP client (urllib), throttle + retry + 429/5xx backoff. Tests block this module's `get()` to prevent live calls.
- `data_health.py` — post-pipeline per-ticker audit of data presence and freshness. Emits a structured dict the report renders in a Data Integrity drawer.
- `snapshots.py` — append-only daily archive (`snapshots/<date>_mqv_v<ver>/`) with metadata, frozen config, universe.csv, ranked.csv, portfolio.csv. Same-day re-runs overwrite the day's directory. Failures never raise into the pipeline.
- `report.py` — single-file HTML renderer (no JavaScript, progressive disclosure via native `<details>`) and CSV writer.
- `expand.py` — separate CLI to grow the universe; appends to `data/universe_extra.txt` and tops up only what's needed.

### Key invariants

1. **`fetch_prices` rewrites its cache to ONLY the tickers it was passed.** When calling `store.ensure(..., with_prices=True)`, always pass the union of `[MARKET_TICKER, *sector_etfs, *stocks]` or you'll wipe the market/ETF columns. `store.add_to_universe` handles this correctly; mimic it if you add a new entry point.
2. **No look-ahead.** Residualisation and momentum windows are right-anchored on the cache's last date. Don't introduce future-dated joins.
3. **Cross-sectional z-scores recompute over the active set.** User filters (`--exclude-adr`, `--exclude-reit`) run *after* hygiene and *before* analytics, so composites and weights reflect what was actually scored.
4. **Composite weights renormalise when a factor is unavailable.** If `quality_z` is mostly NaN (below `QUALITY_FALLBACK_THRESHOLD`), the composite drops quality and re-normalises momentum + value to sum to 1. Tests assert this.
5. **Hierarchical normalisation for quality/value:** industry-level z when industry bucket ≥ `INDUSTRY_MIN_SIZE` (25), else sector-level when sector bucket ≥ `MIN_SECTOR_SIZE` (5), else universe-wide. The `*_scope` columns record which tier each ticker used.
6. **Snapshots are version-tagged.** Set `MQV_STABLE = True` only when the model is frozen; otherwise `MQV_VERSION` (e.g. `0.4-dev`) is in the directory name to keep dev runs out of the stable timeline.
7. **Expectations is diagnostic-only** today — it attaches `expectations_z` and `expectations_scope` to `ranked` but is NOT in the composite. Toggle via `EXPECTATIONS_ENABLED` in config.
8. **Pyto compatibility:** `fmp_client` uses urllib (no `requests`), and `main._open_file` tries Pyto's `file_system` / `sharing.quick_look` before falling back to `webbrowser`. Don't introduce non-stdlib HTTP or OS-specific path APIs.

### Caches and gitignored artefacts

`.gitignore` excludes `cache/`, `reports/`, `snapshots/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`. Pickle caches under `cache/`:
- `prices.pkl` — refresh after `PRICES_REFRESH_DAYS` (5)
- `fundamentals.pkl` — per-ticker freshness, `FUNDAMENTALS_REFRESH_DAYS` (30)
- `profiles.pkl` — per-ticker freshness, `PROFILES_REFRESH_DAYS` (30)
- `revisions.pkl` — `REVISIONS_REFRESH_DAYS` (7), only used when `EXPECTATIONS_ENABLED`

### Tests

`tests/conftest.py` autouses `block_fmp` to fail any test that triggers a live FMP call — keep that fixture active. The `tmp_root` fixture chdirs to a tmp dir with empty `data/` and `cache/`; use it whenever a test writes to those relative paths (e.g. `add_to_universe` tests). All test data is synthetic; do not check in real fundamentals or price snapshots into the test suite.
