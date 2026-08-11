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

**Live link: https://snack.expo.dev/Nn44oLRTEfVMjdcpEU6pQ** — open it in Expo
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

There is no chart. Three builds tried to visualise 550 names on a phone — a
tinted heatmap, a dot strip, then a scrubbable dot strip — and all three failed
the same way for the same reason: they were dashboards, asking the reader to
decode a legend and work a gesture before learning anything. The user's verdict
after the third ("I want a totally 100% new front end") retired the idea, not
the details.

What replaced it is an ordinary drill-down app. Five screens, a real back
stack, and every target a full-width row:

- **Sectors** — eleven rows: rank, name, the score *in plain words*
  ("climbing hard", "drifting up", "going nowhere", "falling"), how many of its
  companies rose, the number, and a hairline for size. The row reads correctly
  with the number and the bar ignored entirely.
- **One sector** — a paragraph of plain English (what it holds, what it did,
  the real SPDR fund's score for comparison), then every company as a ranked
  list. Deliberately boring: fifty rows scroll in a second.
- **One company** — its score, its standing stated as a sentence ("1st of 50 in
  Technology, and 2nd of 548 across every sector"), a watch button, and its
  correlation family as rows that navigate onward.
- **Watchlist** and **How this works** hang off the first screen.

`verdict_for()` in the build does the translation, in five coarse buckets a
person can hold in their head rather than a continuous scale nobody can read.
The by-sector/whole-market toggle is gone with the chart: a company screen just
states both ranks in a sentence, so there is no mode to get lost in.

The palette rule survives from the chart era, because it was the one part that
was right: **the accent colours appear only at full strength** on type and on
3pt hairlines, never blended into a surface as an area fill. `cellFill`/`mix`
stay deleted and a test enforces their absence.

Navigation is a `stack` array of screen descriptors — push, pop, and Android's
hardware back button pops it rather than leaving the app. The scroller is keyed
by screen so a push lands at the top of the new screen instead of halfway down
the last one, and fresh numbers arriving from the feed reset the stack, because
the open screens described the old ones.

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

The rendered bundle is also bundled (esbuild, react-native aliased to a
~40-line RN-to-CSS stub) and driven in a real Chromium against four feeds —
good, 404, junk JSON, and one that never responds — asserting a good feed goes
live, the other three fall back with the as-of date still on screen, and that
a mouse-driven scrub across a strip walks through distinct names live, the
settle lights the family and offers the watch toggle, a zero-length press
still selects, and the view switch relabels the page. The stub maps the RN
responder system onto mouse events so the scrub is exercised as a real drag. The same stub renders both colour schemes for
screenshots before any publish.

## Universe

1. FMP `company-screener` over NYSE / NASDAQ / AMEX, US-domiciled, actively
   trading, not an ETF or fund, market cap > $2bn, > 300k shares/day.
2. Secondary share classes dropped, so one line per company.
3. Top 95 per sector on screener dollar volume become candidates.
4. Candidates need a complete price history across the scoring window; the 50
   survivors with the highest median 63-day dollar volume become the index
   (short baskets keep what they have down to 40 — see Baskets above).

## Index

Daily-rebalanced equal weight — each day the index return is the mean of its
constituents' simple returns, chained into a level series based at 100.
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
peer group is its ~49 sector peers, so the z reads as dispersion inside the
sector rather than a market-wide level. The z is deliberately not winsorised:
the repo's 5/95 clip is built for a 500-name cross-section and inside a
50-name bucket it collapses the best few names onto one value. Consumers clamp
the display scale instead — the app clamps dot positions at ±2.5σ.

Each sector also reports `breadth`, the share of its names with a positive
score on their own. It separates a sector carried by a few names (Technology,
35 of 50 up) from one that moved together (Energy, 44 of 50 up).

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
