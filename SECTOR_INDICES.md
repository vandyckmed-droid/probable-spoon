# Sector "ETFs" — 25-name equal weight, ranked on vol-adjusted 9-1 momentum

Builds synthetic equal-weight indices per GICS-style sector out of that
sector's most liquid US-listed stocks, then ranks the sectors on
volatility-adjusted 9-1 log return.

## Baskets

Each sector's clean names are sorted by liquidity once and the top
`SECTOR_INDEX_SIZE` (50) become its basket. A sector slightly short of a full
basket keeps what it has down to `SECTOR_INDEX_MIN_SIZE` (40) — Communication
Services runs at 48 — because dropping a whole sector distorts the read more
than a 48-name equal weight does. The screener applies the same floor.

The machinery still supports multiple consecutive tiers (`config.SECTOR_TIERS`
is a tuple, `tier_slice` cuts any block, and the app grows a tab bar whenever
the feed carries more than one list), so splitting the fifty again later is a
config change, not a rewrite. The two-tier experiment is recoverable from
history; its headline finding — the big banks falling while the next 25
financials climbed — now shows up inside one grid instead, as a Financial
Services block that is orange on the left edge and green through the middle.

At 50 names the equal-weight baskets track the cap-weighted SPDRs more closely
than either 25-name tier did (rank correlation 0.83).

## Phone build

`sector_snack.py` renders the same payload as an Expo Snack app and publishes
it to snack.expo.dev, which Expo Go opens from a link — no desktop, no build
step, no App Store round trip.

**Live link: https://snack.expo.dev/d7HLCmRgWI7pBYs-FFCO3** — open it in Expo
Go, or scan the QR on that page. Treat it as the address of the app: it only
moves if the *code* is republished, which a data refresh no longer requires.

```bash
python3 sector_snack.py                 # write out/sector_feed.json + out/App.js
python3 sector_snack.py --push-feed     # ...and publish the numbers — this is a refresh
python3 sector_snack.py --publish       # ...and re-upload the app, minting a NEW link
python3 sector_snack.py --feed-url ''   # build a bundle that never phones home
```

`--push-feed` is the refresh: it copies the built feed into a throwaway
worktree of the `feed` branch, commits it stamped with the price date, and
pushes. It is a no-op when the numbers are unchanged, so it is safe to run
twice. `--publish` is the other thing entirely — it re-uploads the app's code
and mints a new link, stranding whatever link the user has saved, so it belongs
only to a code change.

The 11 x 25 heatmap is kept rather than inverted. Each sector is a compact
header — rank, name, score, then one line of gloss and stats — above a grid of
its 25 tickers, wrapped to as many columns as the screen affords (5 to 8, off
`useWindowDimensions`) and shaded on the same within-sector z. All 275 names
are therefore on one scroll with nothing behind a tap; tapping a cell spends a
single line to name the company and give its place in the sector.

An earlier build hid the names behind a per-sector expand, which cost roughly
925pt of scroll to read one sector's 25 names against about 84pt now. It reads
the phone's colour scheme and uses pure React Native primitives — no
dependencies for Expo Go to resolve.

### One design system

The look is brokerage-dark first and deliberately quiet: near-black ground,
charcoal sector cards, one type scale with mono reserved for numbers and
tickers, no glow, no shadows. One diverging ramp carries the within-sector z —
acid green (`#9fe519`) leading, signal orange lagging, magnitude as depth,
saturating at ±1.5σ. Light mode keeps the same vocabulary with the green
pulled down to `#4f9c00` so contrast holds on white; tints are capped in both
schemes so the theme ink is readable on every cell. The acid-green-on-black
palette is the user's standing choice; the restraint around it is the
maintainer's.

Selection dims unrelated names to 28% rather than blacking them out, so the
page still reads as a page with one family in focus; the chosen cell borders
in ink, its kin in the bright accent.

### Views, watchlist and gestures

The grid shades on one of two yardsticks, switched by a segmented control.
"By sector" uses the within-sector z; "Whole market" uses `g`, the same score
z-scored across every name on the page, computed in `build_data` so any
payload age gets it. Both feed the same `cellFill` — only the number differs —
and the legend re-labels itself so the scale on screen is never ambiguous.

Everything is a tap — a long-press variant shipped briefly and was cut as
undiscoverable. Tapping a cell selects it: the readout names the company,
the correlation family lights, and a watch toggle sits in the readout
("Add to watchlist" / "On watchlist — tap to remove"). Watched names keep an
ink ring in the grid and appear as chips in a card above it, each removable
with a tap. The list persists through
`@react-native-async-storage/async-storage` (bundled with Expo Go, declared
in the manifest); storage failures degrade to in-memory, never to a crash.

Fills are deliberately soft — dark-mode tints cap at 38% of the accent, light
at 31% — because saturation is not the signal, depth relative to neighbours
is. Cells run 4–6 to a row with real padding; a first cut at 5–8 columns
with near-full-saturation fills read as a wall of paint on a real phone.

### Family highlighting and haptics

Tapping a cell selects it and its family: `payload["peers"]`, the
`PEER_COUNT` names whose daily log returns correlate highest with it over the
scoring window, above `PEER_MIN_CORRELATION`. The peer search deliberately
spans every sector and both tiers — DAL surfaces UAL and AAL, then the cruise
lines and the consumer lenders; NVDA surfaces the semis, then Vertiv out of
Industrials and MPWR and IBKR down on the second list. A name whose closest
relatives are three sectors away is the signal, not noise to be filtered out.
Some names correlate with nothing above the floor and simply report that.

Haptics are a selection tick on tap, an impact on pull-to-refresh and a
success notification when new numbers land. Every call goes through `buzz()`,
which swallows anything thrown: a simulator or a phone with the feature off
must lose the buzz, not the screen. `expo-haptics` ships inside Expo Go, so it
is declared in the Snack manifest and needs no build step — it is the only
dependency, and a test asserts that every import is either built in or
declared.

### Why the numbers are fetched, not baked

The Snack save API mints a fresh `hashId` on every call; there is no way to
update an anonymous Snack in place (verified — passing the existing `id` or
`hashId` back just creates another Snack). So a bundle carrying its own numbers
means a new link on every refresh, and a phone pointed at yesterday's link
quietly going stale.

The bundle therefore carries two things: `BAKED`, the snapshot as of publish,
and `FEED`, a URL to look for something newer (`config.SECTOR_FEED_URL`, empty
to disable). On mount — and on pull-to-refresh — it races the fetch against
`SECTOR_FEED_TIMEOUT_MS` and only swaps in the result if it passes a shape
check. A 404, a timeout, junk JSON or no signal all land on the same fallback:
the baked snapshot, with the reason and the as-of date on screen. The date
renders in *every* state, including mid-fetch; a screen of undated numbers is
worse than a visibly stale one.

"Up to date" only ever means *agrees with the feed*, which says nothing about
whether the feed is still being refreshed. So the app also ages the price date
itself and, past `SECTOR_STALE_AFTER_DAYS`, says how many days old the numbers
are in the warning colour. The threshold is 5 days: long enough to stay silent
across a holiday weekend, short enough that an abandoned feed is obvious.

`out/sector_feed.json` is that feed, byte-identical to what gets baked in, so
a phone on the feed and a phone offline render the same screen. It is a build
artefact and deliberately untracked here: the published copy on the `feed`
branch is the single source of truth, and keeping a second tracked copy beside
the code only created two things to keep in step. That branch's commit history
— one commit per refresh, stamped with the price date — is what a "what moved
this week" view would read.

It is published on the **`feed` branch** — an orphan branch carrying only
`sector_feed.json` and a README, no code and no shared history with the code
branches, so a data refresh is a one-file commit that cannot touch them and
cannot be stranded by a merge or a branch deletion. `raw.githubusercontent.com`
serves it with `access-control-allow-origin: *` and a 5-minute cache, so the
Snack web preview can read it too.

Nothing needs republishing after a refresh — phones pick it up on next open or on
pull-to-refresh. If the feed ever 404s the app falls back to the snapshot baked
in at publish time and says so on screen.

The screen is written for a reader who does not know the vocabulary. Sectors
carry a plain gloss ("chips, software, hardware"), and the stat line reads
*46%/yr · swing 24% · 23/25 up* rather than annualised return, annualised vol
and breadth. The maths — what the score is, which window, why the last month
is skipped, the survivorship caveat — sits in a collapsed "How this works"
panel rather than on the first screen, with the exact window, observation
count and as-of date under it as a mono stamp.

`tests/test_sector_snack.py` covers the payload → `App.js` step: every sector
and name survives, unscorable names stay as nulls, the basket size is
data-driven rather than a hardcoded 25, feed and baked snapshot are the same
object, and the bundle imports nothing beyond `react` and `react-native`.

The rendered bundle is also driven through a headless React renderer against
four feeds — good, 404, junk JSON, and one that never responds — asserting all
275 cells render up front, that tapping one names the company and tapping it
again closes it, that a good feed goes live, and that the other three fall
back with the as-of date still on screen.

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

## Name-level scores

Every constituent is scored with the identical 9-1 treatment applied to its own
adjusted-close series, then ranked and z-scored *within its own sector* — the
peer group is the other 24 names, so the z reads as dispersion inside the
sector rather than a market-wide level. The z is deliberately not winsorised:
the repo's 5/95 clip is built for a 500-name cross-section and inside a
25-name bucket it collapses the top two names onto one value. Consumers clamp
the display scale instead — the heatmap saturates at ±1.5σ.

Each sector also reports `breadth`, the share of its 25 names with a positive
score on their own. It separates a sector carried by a few names (Technology,
72%) from one that moved together (Industrials and Energy, 92%).

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
