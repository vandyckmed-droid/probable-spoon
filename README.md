# probable-spoon — step 1

Cross-sectional momentum / quality / value ranking, math only.

This is the bare-bones first slice. There is no FMP client, no cache,
no HTML report, no portfolio weighting, no snapshots. Just pure
functions that turn a price frame and a fundamentals dict into a
ranked frame. Synthetic test fixtures cover every public function.

```
analytics.py             # the math
main.py                  # tiny CLI: load CSV/JSON, print top N
tests/test_analytics.py  # synthetic-only tests
```

## Run the tests

```
python -m pytest tests/ -q
```

## Run the ranker against your own data

```
python main.py \
    --prices prices.csv \
    --funds funds.json \
    --sectors sectors.json \
    --sector-etfs sector_etf_map.json \
    --market VTI \
    --top 10
```

Input shapes:
- `prices.csv` — date index, ticker columns, daily closes. Must
  include the market proxy and any sector ETF you reference.
- `funds.json` — `{ticker: {"income": [...], "balance": [...], "cashflow": [...]}}`
  with at least the latest two periods for income / balance and one
  for cashflow.
- `sectors.json` — `{ticker: sector_name}`.
- `sector_etf_map.json` — `{sector_name: etf_ticker}`.

## What's next

Step 2 will add a small FMP cache layer so the inputs come from a
real data source instead of disk. Step 3 will add a single-table
HTML report. Step 4 will add portfolio weighting.

Each step ships only when the previous one is bulletproof. Resist
adding features that don't earn space on screen.
