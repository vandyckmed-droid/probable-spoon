# probable-spoon

Mobile-first M/Q/V (momentum / quality / value) ranking pipeline backed
by Financial Modeling Prep. Designed to run from Pyto on iOS or any
desktop Python; reports render as a single self-contained HTML file.

## First-run setup

Two files are user-specific and never committed — set them once and a
`git pull` or branch switch will leave them alone.

### 1. FMP API key

```
cp secrets/fmp_key.example secrets/fmp_key
# edit secrets/fmp_key — single line, key only
```

The repo's `.gitignore` keeps `secrets/` out of git. `config.py` loads
the key from this file, or from the `FMP_API_KEY` env var if set.

### 2. Universe

```
cp data/universe_extra.txt.example data/universe_extra.txt
# edit, or run expand.py to grow it from FMP's screener
```

`data/universe_extra.txt` is gitignored for the same reason —
preserves your local list across branch switches.

`data/sector_etf_map.json` IS tracked because it's shared config.

## Run

```
python main.py            # cache-only, fast
python main.py --update   # top up missing / stale data first
python main.py --refresh  # force refetch everything
```

Output lands in `reports/report.html` plus a per-day archive under
`snapshots/`.

## Tests

```
python -m pytest tests/ -q
```

No live network — synthetic data only.
