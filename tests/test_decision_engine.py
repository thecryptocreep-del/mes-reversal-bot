"""Tests for the decision engine — mode selection from time + grade."""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from src.bot.decision_engine import EntryMode, in_aggressive_window, decide_mode

_ET = ZoneInfo("America/New_York")


def _et(hour: int, minute: int) -> datetime:
    return datetime(2024, 11, 4, hour, minute, 0, tzinfo=_ET)


# ---------------------------------------------------------------------------
# in_aggressive_window
# ---------------------------------------------------------------------------

def test_in_window_9am():
    assert in_aggressive_window(_et(9, 0)) is True


def test_in_window_10am():
    assert in_aggressive_window(_et(10, 0)) is True


def test_in_window_11_29():
    assert in_aggressive_window(_et(11, 29)) is True


def test_not_in_window_at_11_30():
    # End is exclusive: 11:30 is NOT in window
    assert in_aggressive_window(_et(11, 30)) is False


def test_not_in_window_afternoon():
    assert in_aggressive_window(_et(13, 0)) is False


def test_not_in_window_before_9am():
    assert in_aggressive_window(_et(8, 59)) is False


def test_naive_timestamp_treated_as_et():
    # Naive datetime — assumed ET
    ts = datetime(2024, 11, 4, 10, 0, 0)
    assert in_aggressive_window(ts) is True


# ---------------------------------------------------------------------------
# decide_mode
# ---------------------------------------------------------------------------

def test_decide_anticipation_aplus_in_window():
    assert decide_mode(_et(10, 0), is_a_plus=True) == EntryMode.ANTICIPATION


def test_decide_aggressive_bc_in_window():
    assert decide_mode(_et(10, 0), is_a_plus=False) == EntryMode.AGGRESSIVE


def test_decide_standard_aplus_outside_window():
    assert decide_mode(_et(13, 0), is_a_plus=True) == EntryMode.STANDARD


def test_decide_standard_bc_outside_window():
    assert decide_mode(_et(13, 0), is_a_plus=False) == EntryMode.STANDARD


def test_decide_standard_exactly_at_1130():
    # 11:30 is outside the aggressive window
    assert decide_mode(_et(11, 30), is_a_plus=True) == EntryMode.STANDARD
