# Sector "ETFs" — 25-name equal weight, ranked on vol-adjusted 9-1 momentum

Builds one synthetic equal-weight index per GICS-style sector out of that
sector's 25 most liquid US-listed stocks, then ranks the sectors on
volatility-adjusted 9-1 log return.

```bash
export FMP_API_KEY=...          # or paste it into config.py
python3 sector_index.py                # build + rank
python3 sector_index.py --members      # also print each index's 25 names
python3 sector_index.py --benchmark    # score the SPDR sector ETFs alongside
python3 sector_index.py --no-fetch     # rerun off the cache, no network
python3 sector_index.py --force        # refetch every price series
```

Writes to `out/`: `sector_etf_ranking.json` (full payload incl. constituents),
`sector_etf_ranking.csv` (the ranking table), `sector_etf_constituents.csv`
(members and their 4% weights). Prices cache to `cache/sector_prices.pkl` and
refresh daily.

## Universe

1. FMP `company-screener` over NYSE / NASDAQ / AMEX, US-domiciled, actively
   trading, not an ETF or fund, market cap > $2bn, > 300k shares/day.
2. Secondary share classes dropped, so one line per company.
3. Top 45 per sector on screener dollar volume become candidates.
4. Candidates need a complete price history across the scoring window; the 25
   survivors with the highest median 63-day dollar volume become the index.

Sectors with fewer than 25 clean liquid names are skipped rather than padded.

## Index

Daily-rebalanced equal weight — each day the index return is the mean of its
25 constituents' simple returns, chained into a level series based at 100.
Prices are FMP adjusted closes, so splits and dividends are already handled.

Membership is *today's* most liquid names applied to past prices. That is fine
for ranking sectors as they stand now, but it is not a tradable backtest: the
history inherits whatever survivorship the current membership implies.

## Score

9-1 momentum measures the 9 months ending one month ago — the most recent
month is skipped, the standard short-term-reversal guard. In trading days that
is t-189d to t-21d, a 168-day window.

```
obs         = 168                                  # daily returns in the window
numerator   = ln(L[t-21d] / L[t-189d]) * 252 / obs # annualised 9-1 log return
denominator = stdev(daily log returns, ddof=1) * sqrt(252)
score       = numerator / denominator
```

Both legs are annualised and both are measured on that same 168-day window, so
nothing about the skipped month or the last 9 months' tail leaks into one leg
but not the other. The ratio is unitless and scale-invariant in index level.

Tunable in `config.py`: `SECTOR_INDEX_SIZE`, `MOM_9_1_LONG_DAYS`,
`MOM_9_1_SKIP_DAYS`, `LIQUIDITY_WINDOW_DAYS`, `SCREEN_MIN_MARKET_CAP`,
`SCREEN_MIN_VOLUME`.

## Sanity check

`--benchmark` scores the cap-weighted SPDR sector ETF for each sector on the
identical window. The two disagree by construction — equal weight over 25
liquid names is a higher-beta, more concentrated read on a sector than a
cap-weighted basket of everything in it — but the rankings should broadly
agree, and a collapse in rank correlation is a signal that something upstream
broke.
