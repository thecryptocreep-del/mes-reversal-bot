"""Tests for src/bot/signal_engine.py"""
from __future__ import annotations

import pytest

from src.bot.signal_engine import SignalEngine
from src.strategy.three_bar_reversal import Bar, Signal


# Helper to build a Bar with just OHLC
def _bar(o: float, h: float, lo: float, c: float) -> Bar:
    return Bar(open=o, high=h, low=lo, close=c)


# ------------------------------------------------------------------
# test_no_signal_until_3_bars
# ------------------------------------------------------------------

def test_no_signal_until_3_bars_first():
    eng = SignalEngine(min_extension=0.0)
    result = eng.on_bar(_bar(100, 105, 95, 102))
    assert result is None


def test_no_signal_until_3_bars_second():
    eng = SignalEngine(min_extension=0.0)
    eng.on_bar(_bar(100, 105, 95, 102))
    result = eng.on_bar(_bar(102, 104, 90, 91))
    assert result is None


def test_signal_possible_on_third_bar():
    """Third bar returns a Signal (not None)."""
    eng = SignalEngine(min_extension=0.0)
    eng.on_bar(_bar(100, 105, 95, 102))
    eng.on_bar(_bar(102, 104, 90, 91))
    result = eng.on_bar(_bar(92, 110, 91, 108))
    assert result is not None  # Signal object returned


# ------------------------------------------------------------------
# test_detects_long_signal
# ------------------------------------------------------------------

def test_detects_long_signal():
    eng = SignalEngine(min_extension=0.0)
    # bar1
    eng.on_bar(_bar(100, 105, 95, 102))
    # bar2: close < bar1.low
    eng.on_bar(_bar(102, 104, 90, 91))
    # bar3: close > bar1.high
    result = eng.on_bar(_bar(92, 110, 91, 108))
    assert result == Signal.LONG


def test_detects_long_signal_sequence():
    """Multiple bars; long fires on the right triple."""
    eng = SignalEngine(min_extension=0.0)
    # Filler bars — no pattern
    eng.on_bar(_bar(200, 205, 195, 202))
    eng.on_bar(_bar(202, 204, 198, 201))
    eng.on_bar(_bar(201, 203, 199, 200))
    # Now the triple that makes a long
    eng.on_bar(_bar(100, 105, 95, 102))  # bar1
    eng.on_bar(_bar(102, 104, 90, 91))   # bar2
    result = eng.on_bar(_bar(92, 110, 91, 108))  # bar3
    assert result == Signal.LONG


# ------------------------------------------------------------------
# test_detects_short_signal
# ------------------------------------------------------------------

def test_detects_short_signal():
    eng = SignalEngine(min_extension=0.0)
    # bar1
    eng.on_bar(_bar(100, 105, 95, 103))
    # bar2: close > bar1.high
    eng.on_bar(_bar(103, 112, 102, 111))
    # bar3: close < bar1.low
    result = eng.on_bar(_bar(110, 111, 88, 90))
    assert result == Signal.SHORT


def test_no_signal_when_bar3_doesnt_reverse():
    eng = SignalEngine(min_extension=0.0)
    eng.on_bar(_bar(100, 105, 95, 103))
    eng.on_bar(_bar(103, 112, 102, 111))  # bar2 extends above bar1.high
    result = eng.on_bar(_bar(110, 111, 96, 104))  # bar3 doesn't close < bar1.low
    assert result == Signal.NONE


# ------------------------------------------------------------------
# test_min_extension_filter
# ------------------------------------------------------------------

def test_min_extension_blocks_weak_short():
    """bar2 barely pokes through bar1.high but doesn't meet min_extension."""
    # bar1.high = 105; bar2.close = 106 (only +1 above); min_extension = 5
    eng = SignalEngine(min_extension=5.0)
    eng.on_bar(_bar(100, 105, 95, 103))
    eng.on_bar(_bar(103, 107, 102, 106))   # 106 > 105 but only by 1, not 5
    result = eng.on_bar(_bar(104, 106, 88, 90))  # bar3 closes below bar1.low
    assert result == Signal.NONE


def test_min_extension_allows_strong_short():
    """bar2 extends well beyond bar1.high by more than min_extension."""
    eng = SignalEngine(min_extension=5.0)
    eng.on_bar(_bar(100, 105, 95, 103))
    eng.on_bar(_bar(103, 115, 102, 111))   # 111 > 105 + 5 → qualifies
    result = eng.on_bar(_bar(110, 111, 88, 90))  # bar3 closes < bar1.low
    assert result == Signal.SHORT


def test_min_extension_blocks_weak_long():
    """bar2 barely closes below bar1.low but doesn't meet min_extension."""
    # bar1.low = 95; bar2.close = 94 (only -1 below); min_extension = 5
    eng = SignalEngine(min_extension=5.0)
    eng.on_bar(_bar(100, 105, 95, 102))
    eng.on_bar(_bar(102, 104, 93, 94))     # 94 < 95 but only by 1, not 5
    result = eng.on_bar(_bar(92, 110, 91, 108))  # bar3 closes > bar1.high
    assert result == Signal.NONE


def test_min_extension_allows_strong_long():
    """bar2 closes well below bar1.low (more than min_extension)."""
    eng = SignalEngine(min_extension=5.0)
    eng.on_bar(_bar(100, 105, 95, 102))
    eng.on_bar(_bar(102, 104, 85, 89))     # 89 < 95 - 5 → qualifies
    result = eng.on_bar(_bar(86, 110, 85, 108))  # bar3 closes > bar1.high
    assert result == Signal.LONG


# ------------------------------------------------------------------
# bar_count property
# ------------------------------------------------------------------

def test_bar_count_grows():
    eng = SignalEngine()
    assert eng.bar_count == 0
    eng.on_bar(_bar(100, 105, 95, 102))
    assert eng.bar_count == 1
    eng.on_bar(_bar(102, 104, 90, 91))
    assert eng.bar_count == 2
    eng.on_bar(_bar(92, 110, 91, 108))
    assert eng.bar_count == 3
    # deque maxlen=3 — stays at 3
    eng.on_bar(_bar(108, 115, 105, 112))
    assert eng.bar_count == 3
