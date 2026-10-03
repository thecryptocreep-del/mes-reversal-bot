"""Tests for three-bar reversal pattern detection."""
import pandas as pd
import pytest

from src.strategy.three_bar_reversal import Bar, Signal, detect_signal, scan_signals


def test_long_signal():
    bar1 = Bar(open=100, high=105, low=95, close=102)
    bar2 = Bar(open=102, high=104, low=90, close=91)   # close < bar1.low
    bar3 = Bar(open=92, high=110, low=91, close=108)   # close > bar1.high
    assert detect_signal(bar1, bar2, bar3) == Signal.LONG


def test_short_signal():
    bar1 = Bar(open=100, high=105, low=95, close=103)
    bar2 = Bar(open=103, high=112, low=102, close=111)  # close > bar1.high
    bar3 = Bar(open=110, high=111, low=88, close=90)    # close < bar1.low
    assert detect_signal(bar1, bar2, bar3) == Signal.SHORT


def test_no_signal_partial():
    bar1 = Bar(open=100, high=105, low=95, close=102)
    bar2 = Bar(open=102, high=104, low=90, close=91)   # close < bar1.low
    bar3 = Bar(open=92, high=104, low=91, close=100)   # close NOT > bar1.high
    assert detect_signal(bar1, bar2, bar3) == Signal.NONE


def test_no_signal_neutral():
    bar1 = Bar(open=100, high=105, low=95, close=102)
    bar2 = Bar(open=102, high=104, low=96, close=100)  # stays inside bar1
    bar3 = Bar(open=100, high=106, low=94, close=101)
    assert detect_signal(bar1, bar2, bar3) == Signal.NONE


def test_scan_signals_length():
    df = pd.DataFrame({
        "open":  [100, 101, 102, 103, 104],
        "high":  [106, 107, 108, 109, 110],
        "low":   [ 94,  95,  80,  85,  90],
        "close": [102, 103,  85, 107, 101],
    })
    signals = scan_signals(df)
    assert len(signals) == len(df)
    assert signals.iloc[0] == Signal.NONE
    assert signals.iloc[1] == Signal.NONE


def test_scan_signals_detects_long():
    # bar0=bar1, bar1=bar2, bar2=bar3 in pattern terms
    df = pd.DataFrame({
        "open":  [100, 102,  92],
        "high":  [105, 104, 110],
        "low":   [ 95,  90,  91],
        "close": [102,  91, 108],
    })
    signals = scan_signals(df)
    assert signals.iloc[2] == Signal.LONG


def test_scan_signals_detects_short():
    df = pd.DataFrame({
        "open":  [100, 103, 110],
        "high":  [105, 112, 111],
        "low":   [ 95, 102,  88],
        "close": [103, 111,  90],
    })
    signals = scan_signals(df)
    assert signals.iloc[2] == Signal.SHORT
