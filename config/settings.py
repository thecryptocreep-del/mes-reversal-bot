"""
IB connection settings and instrument configuration.
Never put account numbers or API keys here — use environment variables.
"""
import os

# IB Gateway connection
IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
IB_PAPER_PORT = int(os.getenv("IB_PAPER_PORT", "4002"))
IB_LIVE_PORT = int(os.getenv("IB_LIVE_PORT", "4001"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))

LIVE_MODE = os.getenv("LIVE_MODE", "0") == "1"
IB_PORT = IB_LIVE_PORT if LIVE_MODE else IB_PAPER_PORT

# Active instrument — switch via INSTRUMENT env var (MES or MNQ)
INSTRUMENT = os.getenv("INSTRUMENT", "MNQ").upper()

INSTRUMENT_CONFIG = {
    "MES": {
        "symbol": "MES",
        "yahoo_ticker": "MES=F",
        "exchange": "CME",
        "point_value": 5.0,       # $5 per point
        "tick_size": 0.25,
        "commission_per_side": 0.62,
    },
    "MNQ": {
        "symbol": "MNQ",
        "yahoo_ticker": "NQ=F",   # Yahoo doesn't carry MNQ=F; NQ=F has same price, different multiplier
        "exchange": "CME",
        "point_value": 2.0,       # $2 per point for Micro NQ
        "tick_size": 0.25,
        "commission_per_side": 0.62,
    },
}

if INSTRUMENT not in INSTRUMENT_CONFIG:
    raise ValueError(f"Unknown INSTRUMENT={INSTRUMENT!r}. Choose MES or MNQ.")

_cfg = INSTRUMENT_CONFIG[INSTRUMENT]
SYMBOL          = _cfg["symbol"]
YAHOO_TICKER    = _cfg["yahoo_ticker"]
EXCHANGE        = "CME"
CURRENCY        = "USD"
SEC_TYPE        = "FUT"
BAR_SIZE        = "5 mins"
POINT_VALUE     = _cfg["point_value"]
TICK_SIZE       = _cfg["tick_size"]
COMMISSION_PER_SIDE = _cfg["commission_per_side"]

# Contract roll: roll this many business days before last trade date
ROLL_DAYS_BEFORE_EXPIRY = 4

# Quarterly expiry months
EXPIRY_MONTHS = {"H": 3, "M": 6, "U": 9, "Z": 12}

# Data paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
CONTINUOUS_CSV = os.path.join(RAW_DIR, f"{SYMBOL}_5min_continuous.csv")
