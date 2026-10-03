"""Tests for risk configuration values."""
from config.risk import (
    COMMISSION_PER_SIDE,
    DAILY_LOSS_LIMIT_USD,
    FLATTEN_TIME_ET,
    MAX_POSITION_CONTRACTS,
    MAX_TRADES_PER_DAY,
    MES_POINT_VALUE,
    ROUND_TRIP_COST_USD,
    SLIPPAGE_POINTS_PER_SIDE,
)


def test_risk_limits_are_positive():
    assert MAX_POSITION_CONTRACTS > 0
    assert DAILY_LOSS_LIMIT_USD > 0
    assert MAX_TRADES_PER_DAY > 0


def test_round_trip_cost_calculation():
    expected = (COMMISSION_PER_SIDE + SLIPPAGE_POINTS_PER_SIDE * MES_POINT_VALUE) * 2
    assert abs(ROUND_TRIP_COST_USD - expected) < 0.01


def test_flatten_time_format():
    parts = FLATTEN_TIME_ET.split(":")
    assert len(parts) == 2
    hour, minute = int(parts[0]), int(parts[1])
    assert 0 <= hour <= 23
    assert 0 <= minute <= 59


def test_mes_point_value():
    # MES is $5 per point
    assert MES_POINT_VALUE == 5.0


def test_commission_per_side():
    # IB MES rate should be under $1
    assert 0 < COMMISSION_PER_SIDE < 1.0
