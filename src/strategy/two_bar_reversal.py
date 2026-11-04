"""
Two-bar reversal pattern detection.

Pattern definition:
  Long:  bar1 is a large push DOWN (bearish body). bar2 closes ABOVE bar1.open.
  Short: bar1 is a large push UP   (bullish body). bar2 closes BELOW bar1.open.

The first bar makes a momentum push; the second closes back through bar1's open,
showing rejection. Entry on bar3 open (one bar sooner than the three-bar setup).

DO NOT change min_bar1_body semantics without explicit user approval.
"""
from __future__ import annotations

from src.strategy.three_bar_reversal import Bar, Signal


def detect_signal(
    bar1: Bar,
    bar2: Bar,
    min_bar1_body: float = 0.0,
) -> Signal:
    """
    Detect a two-bar reversal from a pair of consecutive bars.

    Args:
        bar1: the momentum push bar
        bar2: the reversal bar — must close through bar1's open
        min_bar1_body: minimum bar1 body size (abs(close-open)) to filter weak setups
    """
    b1_body = abs(bar1.close - bar1.open)
    if b1_body < min_bar1_body:
        return Signal.NONE

    # Long: bar1 is bearish (pushed down), bar2 closes above bar1.open
    if bar1.close < bar1.open and bar2.close > bar1.open:
        return Signal.LONG

    # Short: bar1 is bullish (pushed up), bar2 closes below bar1.open
    if bar1.close > bar1.open and bar2.close < bar1.open:
        return Signal.SHORT

    return Signal.NONE
