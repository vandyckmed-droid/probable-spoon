# sector feed

Data only. `sector_feed.json` is the numbers behind the sector momentum phone
app — the same object the published Expo Snack bundle carries as its offline
fallback, so a phone on the feed and a phone with no signal render the same
screen.

The app fetches it at run time. That is the whole reason this branch exists:
the Snack save API mints a new link on every publish, so keeping the numbers
out of the bundle is what lets the app's link stay put while the numbers move.

This branch carries no code and shares no history with the code branches, so
a data refresh is a one-file commit that never touches them.

Written by `sector_snack.py` in the same repository.
