"""
Hard risk limits. No strategy or model may override these values.
Changes here require explicit user approval.
"""

MAX_POSITION_CONTRACTS = 1
DAILY_LOSS_LIMIT_USD = 150.0
MAX_TRADES_PER_DAY = 6
FLATTEN_TIME_ET = "15:55"  # flatten all positions before CME equity close

# Commission per side in USD (IB MES rate)
COMMISSION_PER_SIDE = 0.62
# Slippage per side in points (1 tick = 0.25 points = $1.25)
SLIPPAGE_POINTS_PER_SIDE = 0.25
MES_POINT_VALUE = 5.0  # $5 per point for MES

ROUND_TRIP_COST_USD = (COMMISSION_PER_SIDE + SLIPPAGE_POINTS_PER_SIDE * MES_POINT_VALUE) * 2
