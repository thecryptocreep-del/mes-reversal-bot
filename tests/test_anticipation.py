"""Tests for anticipation entry (hammer / shooting star) pattern."""
import pytest
from src.strategy.three_bar_reversal import Bar, Signal
from src.strategy.anticipation_entry import detect_signal


def test_long_hammer_basic():
    # bar2 wicks below bar1.low (extension) and closes above bar1.low
    bar1 = Bar(open=100, high=105, low=90, close=102)
    bar2 = Bar(open=92, high=94, low=82, close=91)  # low=82 < bar1.low-5=85, close=91 >= bar1.low=90
    assert detect_signal(bar1, bar2, min_extension=5.0) == Signal.LONG


def test_short_shooting_star_basic():
    # bar2 wicks above bar1.high (extension) and closes below bar1.high
    bar1 = Bar(open=100, high=110, low=95, close=102)
    bar2 = Bar(open=108, high=118, low=106, close=109)  # high=118 > bar1.high+5=115, close=109 <= bar1.high=110
    assert detect_signal(bar1, bar2, min_extension=5.0) == Signal.SHORT


def test_no_signal_bar2_does_not_close_back():
    # bar2 wicks below bar1.low but closes BELOW bar1.low — full extension, not a hammer
    bar1 = Bar(open=100, high=105, low=90, close=102)
    bar2 = Bar(open=92, high=93, low=82, close=85)  # close=85 < bar1.low=90
    assert detect_signal(bar1, bar2, min_extension=5.0) == Signal.NONE


def test_no_signal_wick_not_enough_extension():
    # bar2 wick extends only 3pts below bar1.low, min_extension=5
    bar1 = Bar(open=100, high=105, low=90, close=102)
    bar2 = Bar(open=91, high=93, low=87, close=91)  # low=87 → extension=3pts, need 5
    assert detect_signal(bar1, bar2, min_extension=5.0) == Signal.NONE


def test_long_no_extension_at_all():
    # bar2 stays inside bar1's range
    bar1 = Bar(open=100, high=105, low=90, close=102)
    bar2 = Bar(open=102, high=104, low=91, close=101)
    assert detect_signal(bar1, bar2, min_extension=5.0) == Signal.NONE


def test_long_zero_min_extension():
    # With no minimum, any wick below bar1.low + close above qualifies
    bar1 = Bar(open=100, high=105, low=90, close=102)
    bar2 = Bar(open=91, high=92, low=89, close=90)  # low=89 just below bar1.low=90, close=90 == bar1.low
    assert detect_signal(bar1, bar2, min_extension=0.0) == Signal.LONG


def test_short_close_exactly_at_bar1_high():
    bar1 = Bar(open=100, high=110, low=95, close=102)
    bar2 = Bar(open=108, high=120, low=107, close=110)  # close=110 == bar1.high
    assert detect_signal(bar1, bar2, min_extension=5.0) == Signal.SHORT


def test_long_close_exactly_at_bar1_low():
    bar1 = Bar(open=100, high=105, low=90, close=102)
    bar2 = Bar(open=92, high=93, low=82, close=90)  # close=90 == bar1.low
    assert detect_signal(bar1, bar2, min_extension=5.0) == Signal.LONG
