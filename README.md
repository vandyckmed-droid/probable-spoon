# probable-spoon

Which corners of the US stock market are climbing, and which companies inside
them are doing the climbing.

**The app: https://snack.expo.dev/lo8fxonAKzb7T0SVCN_La**

Open that on a phone with [Expo Go](https://expo.dev/go) installed, or scan the
QR code on the page. There is nothing to install and no account to make.

It shows eleven sectors ranked best to worst, each with its 50 biggest,
most-traded companies laid out as a grid — about 550 names on one scroll.
Green squares are leading, orange squares are lagging, and the deeper the
colour the stronger the signal. A toggle switches the yardstick: shade each
company against its own sector, or against the whole page at once.

Tap any square to name the company, light up everything anywhere on the page
that moves with it, and add it to a watchlist that survives restarts.

Tap any square and it lights up everything across the whole screen that moves
with it, dimming the rest — the airlines light the cruise lines, the chipmakers
light the power companies feeding the data centres. Those groupings are
measured, not assigned: they come from how the share prices actually moved
together, so they cut across the sector lines wherever the real relationships
do.

Every screen carries the date the prices were taken, and says plainly when it
is showing saved numbers, or numbers nobody has refreshed lately.

## What the score means

A climb-per-bump number: how far a sector rose over nine months, divided by
how roughly it got there. A sector that ground steadily upward beats one that
ended in the same place after wild swings. Above about 1.0 is a solid climb,
near zero is going nowhere, below zero is falling.

The nine months end a month ago — the most recent few weeks are deliberately
left out, because fresh moves tend to snap back and counting them flatters
whatever just bounced.

Sectors here are not real funds. Each is a made-up basket of that sector's 25
most-traded US companies held in equal amounts, so that one giant company
cannot speak for a whole sector. The real SPDR sector fund is scored alongside
each one as a sanity check.

**This is information, not advice.** The baskets use today's most-traded
companies applied to past prices, which flatters the history — the names that
stumbled badly are not in the list any more. It ranks sectors as they stand
today; it is not a trading record.

## The code

| | |
|---|---|
| `sector_index.py` | builds the baskets and ranks them |
| `sector_snack.py` | turns the ranking into the phone app, and publishes both |
| `main.py` and friends | an older single-stock ranking pipeline, separate from the above |

`SECTOR_INDICES.md` is the full reference: the method, the maths, the data
flow, and how the phone build works. `CLAUDE.md` covers how this repo is
maintained.

Prices come from [FMP](https://financialmodelingprep.com/) and are adjusted for
splits and dividends. A key is needed to rebuild the numbers; reading the app
needs nothing.

```bash
export API_KEY=...
python3 sector_index.py --benchmark    # rebuild and rank
python3 sector_snack.py --push-feed    # publish the numbers to the app
python3 -m pytest -q                   # 59 tests, no network
```

The app reads its numbers from the [`feed`](../../tree/feed) branch at run
time, so refreshing them never changes the link above.
