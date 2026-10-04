"""
Three-bar reversal pattern detection.

Pattern definition (DO NOT CHANGE without explicit user approval):
  Long:  bar2.close < bar1.low  AND bar3.close > bar1.high
  Short: bar2.close > bar1.high AND bar3.close < bar1.low

Returns signal for bar3 based on the preceding two bars.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

import pandas as pd


class Signal(Enum):
    NONE = 0
    LONG = 1
    SHORT = -1


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float


def detect_signal(bar1: Bar, bar2: Bar, bar3: Bar, min_extension: float = 0.0) -> Signal:
    """
    Detect a three-bar reversal signal given three consecutive bars.

    Args:
        min_extension: minimum points bar2 must close beyond bar1's extreme.
                       Filters out weak setups where bar2 barely pokes through.
    """
    if bar2.close < bar1.low - min_extension and bar3.close > bar1.high:
        return Signal.LONG
    if bar2.close > bar1.high + min_extension and bar3.close < bar1.low:
        return Signal.SHORT
    return Signal.NONE


def scan_signals(df: pd.DataFrame, min_extension: float = 0.0) -> pd.Series:
    """
    Scan a OHLC DataFrame for three-bar reversal signals.

    Args:
        df: DataFrame with columns [open, high, low, close], datetime index
        min_extension: minimum points bar2 must extend beyond bar1's extreme

    Returns:
        Series of Signal values aligned to df.index (signal fires on bar3's close)
    """
    signals = pd.Series(Signal.NONE, index=df.index, dtype=object)

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values

    for i in range(2, len(df)):
        bar1 = Bar(opens[i - 2], highs[i - 2], lows[i - 2], closes[i - 2])
        bar2 = Bar(opens[i - 1], highs[i - 1], lows[i - 1], closes[i - 1])
        bar3 = Bar(opens[i], highs[i], lows[i], closes[i])
        signals.iloc[i] = detect_signal(bar1, bar2, bar3, min_extension)

    return signals
