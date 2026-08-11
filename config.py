# =====================================================================
# PASTE YOUR FMP API KEY BETWEEN THE QUOTES BELOW.
# Get a key at https://financialmodelingprep.com/developer
# =====================================================================
FMP_API_KEY = ""
# =====================================================================

import os
if not FMP_API_KEY:
    # API_KEY is what the hosted environment injects; FMP_API_KEY is the name a
    # local shell is likely to use. Take either, preferring the explicit one.
    FMP_API_KEY = os.environ.get("FMP_API_KEY") or os.environ.get("API_KEY", "")


# Pipeline
HISTORY_TRADING_DAYS = 756       # ~3 years
MOMENTUM_MIN_OBS     = 252
BETA_LOOKBACK_DAYS   = 504       # ~2 years for beta estimation
MOM_SKIP_DAYS        = 21
MOM_LONG_DAYS        = 252       # 12-1
MOM_SHORT_DAYS       = 126       # 6-1
MOM_REV_DAYS         = 21        # 1m reversal (diagnostic)
SIGMA_DAYS           = 63        # current residual-sigma window
SIGMA_FLOOR          = 1e-6      # volatility floor
CHART_EMA_SPAN       = 5         # gentle EMA smoothing for the 63d residual chart; 1 disables
TRADING_DAYS_PER_YEAR= 252

# Winsorisation
WINSOR_LOWER = 0.05
WINSOR_UPPER = 0.95

# Composite weights (sum to 1)
W_MOMENTUM = 0.50
W_QUALITY  = 0.30
W_VALUE    = 0.20

# Momentum sleeves (sum to 1 within momentum)
MOM_W_12_1 = 0.50
MOM_W_6_1  = 0.50

# Quality sub-components (sum to 1 within quality)
Q_GP_W        = 0.50
Q_GP_CHANGE_W = 0.20
Q_NETDEBT_W   = 0.30

# Value sub-components (sum to 1 within value)
V_EBIT_EV_W = 0.40
V_FCF_EV_W  = 0.40
V_BP_W      = 0.20

# Coverage fallbacks / bucket sizing
QUALITY_FALLBACK_THRESHOLD = 0.40
VALUE_FALLBACK_THRESHOLD   = 0.40
INDUSTRY_MIN_SIZE          = 25   # min industry bucket for industry-level z
MIN_SECTOR_SIZE            = 5    # below this, fall back to universe-wide z

# Portfolio weighting (applied to the top N composite-ranked names)
TOP_N                = 25
WEIGHTING_SCHEME     = "hrp"           # default for the Weighted Top 25 toggle
WEIGHT_LOOKBACK_DAYS = 252
CASH_DEPLOYMENT      = 30000           # default $; overridden by `main.py --cash`
VOL_TARGET                = 0.15            # annualised target portfolio vol; None disables
VOL_TARGET_MAX_LEVERAGE   = 1.25            # scale cap when realised vol < target
BACKTEST_DAYS        = 126             # ~6 months of look-back attribution

# Expectations factor — diagnostic only in step 1, NOT in composite yet.
# Flip to False to disable the fetch + render entirely.
EXPECTATIONS_ENABLED      = True
REVISIONS_CACHE           = "cache/revisions.pkl"
REVISIONS_REFRESH_DAYS    = 7
EXP_GROWTH_W              = 0.50  # forward EPS growth weight
EXP_SURPRISE_W            = 0.50  # latest earnings surprise weight

# Snapshot archive — quiet background log of each model run. Version-aware
# so dev tweaks don't masquerade as a stable strategy history.
MQV_STRATEGY_NAME = "mqv"
MQV_VERSION       = "0.4-dev"   # bump on any formula / weight change
MQV_STABLE        = False       # set True only when the model is frozen
SNAPSHOTS_DIR     = "snapshots"
SNAPSHOTS_INDEX_LIMIT = 20      # how many recent snapshots the report lists

# Sector "ETFs": 25-name equal-weight sector indices, ranked on
# volatility-adjusted 9-1 momentum (see sector_index.py).
SECTOR_INDEX_SIZE           = 25        # constituents per synthetic sector ETF
SECTOR_CANDIDATES_PER_SECTOR= 95        # screener shortlist before data-quality cuts

# Two rungs of the same ladder. Each sector's clean names are sorted by
# liquidity and cut into consecutive blocks of SECTOR_INDEX_SIZE, so tier 2 is
# the next 25 down rather than a different kind of company. Each tier is its
# own equal-weight index, scored and ranked entirely within itself.
SECTOR_TIERS = (
    {
        "key": "top",
        "label": "Top 25",
        "note": "the 25 most-traded companies in each sector",
    },
    {
        "key": "next",
        "label": "Next 25",
        "note": "the 25 directly below those — same rules, one rung down",
    },
)
SCREEN_MIN_MARKET_CAP       = 2_000_000_000
SCREEN_MIN_VOLUME           = 300_000   # shares/day on the screener snapshot
SCREEN_LIMIT                = 5000      # per-exchange screener page size
LIQUIDITY_WINDOW_DAYS       = 63        # median dollar volume window (~3 months)
MOM_9_1_LONG_DAYS           = 189       # 9 months of trading days (9 x 21)
MOM_9_1_SKIP_DAYS           = 21        # skip the most recent month
SECTOR_HISTORY_DAYS         = 500       # calendar days of price history to pull
SECTOR_PRICES_CACHE         = "cache/sector_prices.pkl"
SECTOR_PRICES_REFRESH_DAYS  = 1
SECTOR_OUTPUT_DIR           = "out"

# Phone build (sector_snack.py). The Snack save API mints a fresh link on every
# publish, so a link that survives a data refresh needs the numbers to live at a
# URL the app fetches at run time rather than baked into the bundle. Point this
# at the published sector_feed.json; leave it empty and the app simply runs on
# the snapshot baked in at build time.
SECTOR_FEED_URL             = (
    "https://raw.githubusercontent.com/"
    "vandyckmed-droid/probable-spoon/feed/sector_feed.json"
)
SECTOR_FEED_BRANCH          = "feed"     # data-only orphan branch; no code, no shared history
SECTOR_FEED_TIMEOUT_MS      = 6000       # then fall back to the baked snapshot
SECTOR_FEED_FILE            = "out/sector_feed.json"    # build output; the published copy
SECTOR_FEED_BRANCH_FILE     = "sector_feed.json"        # ...lives on the feed branch alone
SECTOR_STALE_AFTER_DAYS     = 5         # beyond this the app says how old the numbers are
PEER_COUNT                  = 8         # "moves like this" names kept per ticker
PEER_MIN_CORRELATION        = 0.35      # below this they are not really related

# Universe / market
MARKET_TICKER = "VTI"

# FMP
FMP_BASE        = "https://financialmodelingprep.com/stable"
FMP_LEGACY_BASE = "https://financialmodelingprep.com/api/v3"
FMP_TIMEOUT_S   = 20
FMP_MAX_RETRIES = 3
FMP_REQUEST_PAUSE_S = 0.12

# Cache
CACHE_DIR          = "cache"
PRICES_CACHE       = "cache/prices.pkl"
FUNDAMENTALS_CACHE = "cache/fundamentals.pkl"
PROFILES_CACHE     = "cache/profiles.pkl"
PRICES_REFRESH_DAYS       = 5
FUNDAMENTALS_REFRESH_DAYS = 30
PROFILES_REFRESH_DAYS     = 30

