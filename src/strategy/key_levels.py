"""
Key level detection for the three-bar reversal strategy.

Levels calculated fresh each day from the DataFrame:
  - Prior Day High (PDH) / Prior Day Low (PDL)
  - Prior Day Close (PDC)
  - Opening Range High (ORH) / Opening Range Low (ORL)  — first 15 min of RTH
  - Weekly Open (first bar of the week)

A signal is "at a level" when bar2's extreme (the overextension leg) reaches
within `proximity_points` of any key level.

  Long setup  → bar2.low must be within proximity of a level (selling into support)
  Short setup → bar2.high must be within proximity of a level (buying into resistance)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd
import numpy as np


class SignalGrade(Enum):
    A_PLUS = "A+"   # bar2 within proximity of a key level  → double size
    B      = "B"    # bar2 within 2× proximity              → normal size
    C      = "C"    # no key level nearby                   → minimum size


# Opening range window: 9:30 – 9:45 ET (first 15 min of RTH)
_OR_START = (9, 30)
_OR_END   = (9, 45)


@dataclass
class DayLevels:
    date: pd.Timestamp
    pdh: Optional[float] = None   # prior day high
    pdl: Optional[float] = None   # prior day low
    pdc: Optional[float] = None   # prior day close
    orh: Optional[float] = None   # opening range high
    orl: Optional[float] = None   # opening range low
    weekly_open: Optional[float] = None

    def all_levels(self) -> list[float]:
        return [v for v in [self.pdh, self.pdl, self.pdc, self.orh, self.orl, self.weekly_open]
                if v is not None]


def build_level_map(df: pd.DataFrame) -> dict[str, DayLevels]:
    """
    Build a dict mapping date-string → DayLevels for every trading day in df.

    df must have a DatetimeIndex and columns [open, high, low, close].
    Times are assumed to be in ET (or naive ET-equivalent).
    """
    # Group by calendar date
    df = df.copy()
    df["_date"] = df.index.normalize()

    dates = sorted(df["_date"].unique())
    level_map: dict[str, DayLevels] = {}

    for i, date in enumerate(dates):
        day_str = str(date.date())
        levels = DayLevels(date=date)

        # Prior day stats
        if i > 0:
            prev_date = dates[i - 1]
            prev_bars = df[df["_date"] == prev_date]
            if len(prev_bars):
                levels.pdh = float(prev_bars["high"].max())
                levels.pdl = float(prev_bars["low"].min())
                levels.pdc = float(prev_bars["close"].iloc[-1])

        # Opening range (9:30–9:45 ET)
        day_bars = df[df["_date"] == date]
        or_bars = day_bars[
            day_bars.index.map(lambda t: _OR_START <= (t.hour, t.minute) < _OR_END)
        ]
        if len(or_bars):
            levels.orh = float(or_bars["high"].max())
            levels.orl = float(or_bars["low"].min())

        # Weekly open — first bar of each Mon (or first trading day of week)
        day_of_week = date.dayofweek  # 0=Mon
        if day_of_week == 0 or (i == 0):
            if len(day_bars):
                levels.weekly_open = float(day_bars["open"].iloc[0])
        else:
            # Carry forward from most recent Monday
            prev_levels = level_map.get(str(dates[i - 1].date()))
            if prev_levels:
                levels.weekly_open = prev_levels.weekly_open

        level_map[day_str] = levels

    return level_map


def bar2_at_level(
    bar2_high: float,
    bar2_low: float,
    signal_direction: int,      # 1=long, -1=short
    levels: DayLevels,
    proximity_points: float = 10.0,
) -> bool:
    """
    Return True if bar2's overextension leg is within proximity_points of any key level.

    Long setup  → bar2 pushed DOWN, so check bar2.low vs all levels
    Short setup → bar2 pushed UP,   so check bar2.high vs all levels
    """
    key_levels = levels.all_levels()
    if not key_levels:
        return False

    extreme = bar2_low if signal_direction == 1 else bar2_high
    return any(abs(extreme - lvl) <= proximity_points for lvl in key_levels)


def grade_signal(
    bar2_high: float,
    bar2_low: float,
    signal_direction: int,
    levels: DayLevels,
    proximity_points: float = 10.0,
) -> SignalGrade:
    """
    Grade a signal by how close bar2's extreme is to a key level.

      A+ — within proximity_points   (strong confluence)
      B  — within 2× proximity_points (moderate confluence)
      C  — no key level nearby        (pattern only, minimum size)
    """
    if bar2_at_level(bar2_high, bar2_low, signal_direction, levels, proximity_points):
        return SignalGrade.A_PLUS
    if bar2_at_level(bar2_high, bar2_low, signal_direction, levels, proximity_points * 2):
        return SignalGrade.B
    return SignalGrade.C
