"""
Hard risk limits. No strategy or model may override these values.
Changes here require explicit user approval.
"""
from config.settings import COMMISSION_PER_SIDE, POINT_VALUE, TICK_SIZE

MAX_POSITION_CONTRACTS        = 1  # B / C grade
MAX_POSITION_CONTRACTS_APLUS  = 2  # A+ grade (at key level)
DAILY_LOSS_LIMIT_USD   = 150.0
MAX_TRADES_PER_DAY     = 6
FLATTEN_TIME_ET        = "15:55"

# Session window (ET) — override via SESSION_START / SESSION_END env vars (HH:MM)
import os as _os
def _parse_hhmm(val: str) -> tuple:
    h, m = val.split(":")
    return (int(h), int(m))

SESSION_START_ET = _parse_hhmm(_os.getenv("SESSION_START", "09:00"))
SESSION_END_ET   = _parse_hhmm(_os.getenv("SESSION_END",   "11:50"))

# Stop and target in points — derived from 55-day MNQ market structure analysis
# Stop  = 1 ATR (40pts covers 90th pct MAE at 1 bar)
# Target = 1.5× stop (60pts sits between median 4-bar and 8-bar MFE)
STOP_POINTS   = 40.0
TARGET_POINTS = 60.0

# Minimum bar2 extension beyond bar1 extreme — filters noise setups
MIN_BAR2_EXTENSION_POINTS = 5.0

MES_POINT_VALUE        = POINT_VALUE  # backwards compat alias
SLIPPAGE_POINTS_PER_SIDE = TICK_SIZE  # 1 tick slippage per side

ROUND_TRIP_COST_USD = (COMMISSION_PER_SIDE + SLIPPAGE_POINTS_PER_SIDE * POINT_VALUE) * 2
