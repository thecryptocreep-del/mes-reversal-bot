"""
Anticipation entry (Option 3) pattern detection.

Pattern definition:
  Long:  bar2 wicks ≥min_extension below bar1.low (extension into support),
         AND bar2.close ≥ bar1.low (closes back above — hammer candle body).
  Short: bar2 wicks ≥min_extension above bar1.high (extension into resistance),
         AND bar2.close ≤ bar1.high (closes back below — shooting star body).

Enters at bar2's close — one bar sooner than the two-bar setup.
Requires A+ grade (key level confluence) to trade; bot enforces this in runner.py.

DO NOT change the wick extension or close-reversal conditions without explicit
user approval (CLAUDE.md: ask before changing pattern definitions).
"""
from __future__ import annotations

from src.strategy.three_bar_reversal import Bar, Signal


def detect_signal(
    bar1: Bar,
    bar2: Bar,
    min_extension: float = 0.0,
) -> Signal:
    """
    Detect an anticipation (hammer / shooting star) entry pattern.

    Args:
        bar1: the reference bar
        bar2: must wick past bar1's extreme by min_extension AND close back inside
        min_extension: minimum points bar2's wick must extend beyond bar1's extreme
    """
    # Long: hammer — wick extends below bar1.low, body closes at or above bar1.low
    if bar2.low < bar1.low - min_extension and bar2.close >= bar1.low:
        return Signal.LONG

    # Short: shooting star — wick extends above bar1.high, body closes at or below bar1.high
    if bar2.high > bar1.high + min_extension and bar2.close <= bar1.high:
        return Signal.SHORT

    return Signal.NONE
