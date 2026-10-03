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

# MES contract
SYMBOL = "MES"
EXCHANGE = "CME"
CURRENCY = "USD"
SEC_TYPE = "FUT"
BAR_SIZE = "5 mins"

# Contract roll: roll this many business days before last trade date
ROLL_DAYS_BEFORE_EXPIRY = 4

# Quarterly expiry months
EXPIRY_MONTHS = {"H": 3, "M": 6, "U": 9, "Z": 12}

# Data paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
CONTINUOUS_CSV = os.path.join(RAW_DIR, "MES_5min_continuous.csv")
