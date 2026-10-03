"""
Hard risk limits. No strategy or model may override these values.
Changes here require explicit user approval.
"""
from config.settings import COMMISSION_PER_SIDE, POINT_VALUE, TICK_SIZE

MAX_POSITION_CONTRACTS = 1
DAILY_LOSS_LIMIT_USD = 150.0
MAX_TRADES_PER_DAY = 6
FLATTEN_TIME_ET = "15:55"

MES_POINT_VALUE = POINT_VALUE  # kept for backwards compat
SLIPPAGE_POINTS_PER_SIDE = TICK_SIZE  # 1 tick slippage per side

ROUND_TRIP_COST_USD = (COMMISSION_PER_SIDE + SLIPPAGE_POINTS_PER_SIDE * POINT_VALUE) * 2
