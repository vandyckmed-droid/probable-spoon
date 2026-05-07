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
V_FCF_EV_W  = 0.60
V_BP_W      = 0.00   # deprecated, kept for diagnostics

# Coverage fallbacks
QUALITY_FALLBACK_THRESHOLD = 0.40
VALUE_FALLBACK_THRESHOLD   = 0.40
MIN_SECTOR_SIZE            = 5    # below this, fall back to universe-wide z

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

