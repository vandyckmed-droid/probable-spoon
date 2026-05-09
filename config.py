# =====================================================================
# PASTE YOUR FMP API KEY BETWEEN THE QUOTES BELOW.
# Get a key at https://financialmodelingprep.com/developer
# =====================================================================
FMP_API_KEY = ""
# =====================================================================

import os
if not FMP_API_KEY:
    FMP_API_KEY = os.environ.get("FMP_API_KEY", "")


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

