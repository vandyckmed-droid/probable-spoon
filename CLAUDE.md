# probable-spoon

Ranks US equity sectors on volatility-adjusted 9-1 momentum and ships the
result as a phone app. `SECTOR_INDICES.md` is the reference for the method,
the data flow and the phone build — read it before changing any of them.

**The phone app is the product.** The HTML report and the CSVs are by-products.
When a change would improve one at the other's expense, the phone screen wins.
Design for a phone first: dense, everything visible, minimal scroll, no
information parked behind a tap that could have been shown outright.

## Standing autonomy

Do these without asking. They are pre-authorised, and asking about them
wastes a turn.

- **Branch and repo hygiene.** Delete merged branches, keep the default branch
  sane, retarget or merge your own PRs, tidy history, fix stale references.
- **Commit and push** on the working branch, and open a draft PR for it.
- **Publish the Snack** and update the live link in `SECTOR_INDICES.md`.
- **Refresh the feed** (below) whenever asked for "today's numbers".
- **Delete build artefacts and caches** that are regenerable.
- **Fix what you find broken** in passing — stale docs, dead code, wrong
  labels — when it is smaller than the task that uncovered it.

Ask first only for: making a repo public or private, publishing to a new
external service, deleting anything unrecoverable, or spending real money.

Do not monitor for external reviews or CI comments. Nobody else touches this
repo; there will be no review to wait for.

## Talk plainly

The user is not a programmer and reads on a phone. Long replies get cut off by
the keyboard. So:

- Short answers. Lead with the result or the link, not the reasoning.
- Plain words over jargon, in chat **and on screen**: "typical swing", not
  "annualised vol"; "23 of 25 up", not "breadth 0.92".
- Offer suggestions and a recommendation, not a menu of equal options.
- Never claim something works because it should. Run it, then say so.

## Refreshing the numbers

The API key arrives as `API_KEY` in the hosted environment (`FMP_API_KEY`
also works locally); `config.py` takes either.

```bash
python3 sector_index.py --benchmark --report   # refetch, rank, write out/
python3 sector_snack.py                        # rebuild feed/sector_feed.json
```

Then publish the feed to the data-only `feed` branch — that is what the live
app reads, and it is the only step that makes a refresh visible on a phone:

```bash
git fetch origin feed
git worktree add /tmp/feed feed
cp feed/sector_feed.json /tmp/feed/sector_feed.json
git -C /tmp/feed commit -am "Refresh the feed" && git -C /tmp/feed push
git worktree remove /tmp/feed
```

Republishing the Snack is **not** part of a refresh, and doing it mints a new
link that strands the one the user has saved. Republish only when the app's
*code* changes, and update the link in `SECTOR_INDICES.md` when you do.

Markets close 16:00 New York. Prices are only complete after that.

## Verifying the phone build

Do not ship an app change on a syntax check alone. `tests/test_sector_snack.py`
covers the payload → `App.js` step; beyond that, render the bundle in a
headless React renderer against a stubbed `react-native` and drive it through
a good feed, a 404, junk JSON and a hanging request. That harness has caught
real bugs — undated numbers mid-fetch, among others.

## House style

Comments explain *why*, never *what*. Prose in commits and docs, not bullet
soup. Match the file you are editing. No emoji, no marketing adjectives, no
"comprehensive" or "robust". Never claim a test passed without running it.
