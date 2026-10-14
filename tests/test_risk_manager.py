"""Tests for src/bot/risk_manager.py"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.bot.risk_manager import RiskManager

_ET = ZoneInfo("America/New_York")


def _et(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_ET)


# ------------------------------------------------------------------
# can_trade — trade limit
# ------------------------------------------------------------------

def test_trade_limit_enforced():
    rm = RiskManager()
    now = _et(2024, 1, 10, 10, 0)
    for _ in range(6):
        assert rm.can_trade(now)
        rm.record_trade(0.0, now)
    # 7th trade must be blocked
    assert not rm.can_trade(now)


def test_trade_limit_exactly_at_max():
    """Exactly MAX_TRADES_PER_DAY trades recorded → can_trade returns False."""
    from config.risk import MAX_TRADES_PER_DAY
    rm = RiskManager()
    now = _et(2024, 1, 10, 10, 0)
    for _ in range(MAX_TRADES_PER_DAY):
        rm.record_trade(0.0, now)
    assert not rm.can_trade(now)


# ------------------------------------------------------------------
# can_trade — daily loss limit
# ------------------------------------------------------------------

def test_daily_loss_limit_enforced():
    from config.risk import DAILY_LOSS_LIMIT_USD
    rm = RiskManager()
    now = _et(2024, 1, 10, 10, 0)
    # Record a single large loss that exceeds the limit
    rm.record_trade(-DAILY_LOSS_LIMIT_USD - 1, now)
    assert not rm.can_trade(now)


def test_daily_loss_limit_exactly_at_boundary():
    """Loss equal to limit blocks trading."""
    from config.risk import DAILY_LOSS_LIMIT_USD
    rm = RiskManager()
    now = _et(2024, 1, 10, 10, 0)
    rm.record_trade(-DAILY_LOSS_LIMIT_USD, now)
    assert not rm.can_trade(now)


def test_partial_loss_allows_trading():
    from config.risk import DAILY_LOSS_LIMIT_USD
    rm = RiskManager()
    now = _et(2024, 1, 10, 10, 0)
    rm.record_trade(-(DAILY_LOSS_LIMIT_USD / 2), now)
    assert rm.can_trade(now)


# ------------------------------------------------------------------
# should_flatten
# ------------------------------------------------------------------

def test_flatten_time_before():
    rm = RiskManager()
    before_flatten = _et(2024, 1, 10, 15, 54)
    assert not rm.should_flatten(before_flatten)


def test_flatten_time_at_exact_time():
    rm = RiskManager()
    at_flatten = _et(2024, 1, 10, 15, 55)
    assert rm.should_flatten(at_flatten)


def test_flatten_time_after():
    rm = RiskManager()
    after_flatten = _et(2024, 1, 10, 16, 0)
    assert rm.should_flatten(after_flatten)


# ------------------------------------------------------------------
# in_session
# ------------------------------------------------------------------

def test_session_window_inside():
    rm = RiskManager()
    inside = _et(2024, 1, 10, 10, 30)
    assert rm.in_session(inside)


def test_session_window_before_open():
    rm = RiskManager()
    before = _et(2024, 1, 10, 8, 59)
    assert not rm.in_session(before)


def test_session_window_after_close():
    rm = RiskManager()
    after = _et(2024, 1, 10, 12, 0)
    assert not rm.in_session(after)


def test_session_window_at_start():
    rm = RiskManager()
    at_start = _et(2024, 1, 10, 9, 0)
    assert rm.in_session(at_start)


def test_session_window_at_end():
    rm = RiskManager()
    at_end = _et(2024, 1, 10, 11, 50)
    assert rm.in_session(at_end)


# ------------------------------------------------------------------
# resets at midnight
# ------------------------------------------------------------------

def test_resets_at_midnight():
    rm = RiskManager()
    day1 = _et(2024, 1, 10, 10, 0)
    # Fill up trades on day 1
    for _ in range(6):
        rm.record_trade(0.0, day1)
    assert not rm.can_trade(day1)

    # New day — counters should reset
    day2 = _et(2024, 1, 11, 9, 30)
    assert rm.can_trade(day2)


def test_resets_daily_pnl_at_midnight():
    from config.risk import DAILY_LOSS_LIMIT_USD
    rm = RiskManager()
    day1 = _et(2024, 1, 10, 10, 0)
    rm.record_trade(-DAILY_LOSS_LIMIT_USD - 50, day1)
    assert not rm.can_trade(day1)

    day2 = _et(2024, 1, 11, 9, 30)
    assert rm.can_trade(day2)
    assert rm.daily_pnl == 0.0
    assert rm.trade_count == 0
