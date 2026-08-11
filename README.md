# probable-spoon

Which corners of the US stock market are climbing, and which companies inside
them are doing the climbing.

**The app: https://snack.expo.dev/XPWcdurzg01b7HhgmGa_b**

Open that on a phone with [Expo Go](https://expo.dev/go) installed, or scan the
QR code on the page. There is nothing to install and no account to make.

It shows eleven sectors ranked best to worst, each with its 25 biggest,
most-traded companies laid out as a grid. Every sector has its own colour, and
the brighter a square burns, the stronger that company is against the others in
its own sector.

There are two lists behind the tabs at the top. **Top 25** is those biggest
names. **Next 25** is the 25 directly below them in each sector — same rules,
one rung down the size ladder — and it is scored and ranked entirely on its
own, so it answers a separate question: are the smaller companies going the
same way as the giants? Often they are not. Right now the big banks are the
worst sector on the first list and the smaller financials are the fourth best
on the second.

The two lists look deliberately different: the first is lit and glowing, the
second is drawn in outline. Same sector colours in both, so you can still tell
Energy from Technology at a glance.

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
