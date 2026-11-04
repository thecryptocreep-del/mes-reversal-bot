"""Tests for two-bar reversal pattern detection."""
import pytest
from src.strategy.three_bar_reversal import Bar
from src.strategy.two_bar_reversal import detect_signal
from src.strategy.three_bar_reversal import Signal


def test_long_bar1_red_bar2_above_open():
    bar1 = Bar(open=100, high=105, low=85, close=88)   # bearish push down
    bar2 = Bar(open=89, high=108, low=87, close=103)   # close > bar1.open (100)
    assert detect_signal(bar1, bar2) == Signal.LONG


def test_short_bar1_green_bar2_below_open():
    bar1 = Bar(open=100, high=118, low=98, close=115)  # bullish push up
    bar2 = Bar(open=114, high=116, low=92, close=96)   # close < bar1.open (100)
    assert detect_signal(bar1, bar2) == Signal.SHORT


def test_no_signal_bar2_does_not_cross_open():
    bar1 = Bar(open=100, high=105, low=85, close=88)
    bar2 = Bar(open=89, high=99, low=87, close=97)     # close < bar1.open — no reversal
    assert detect_signal(bar1, bar2) == Signal.NONE


def test_min_bar1_body_filters_small_bar():
    bar1 = Bar(open=100, high=104, low=96, close=98)   # body = 2pts
    bar2 = Bar(open=98, high=108, low=96, close=105)   # would signal long
    assert detect_signal(bar1, bar2, min_bar1_body=5.0) == Signal.NONE


def test_min_bar1_body_allows_large_bar():
    bar1 = Bar(open=100, high=108, low=82, close=84)   # body = 16pts
    bar2 = Bar(open=85, high=110, low=83, close=104)   # close > bar1.open
    assert detect_signal(bar1, bar2, min_bar1_body=10.0) == Signal.LONG


def test_doji_bar1_no_signal():
    bar1 = Bar(open=100, high=104, low=96, close=100)  # doji — body = 0
    bar2 = Bar(open=100, high=108, low=99, close=106)
    assert detect_signal(bar1, bar2, min_bar1_body=5.0) == Signal.NONE


def test_bar2_exactly_at_open_no_long():
    bar1 = Bar(open=100, high=105, low=85, close=88)
    bar2 = Bar(open=89, high=103, low=87, close=100)   # close == bar1.open (not >)
    assert detect_signal(bar1, bar2) == Signal.NONE


def test_bar2_exactly_at_open_no_short():
    bar1 = Bar(open=100, high=118, low=98, close=115)
    bar2 = Bar(open=114, high=116, low=98, close=100)  # close == bar1.open (not <)
    assert detect_signal(bar1, bar2) == Signal.NONE
