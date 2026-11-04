"""
Decision engine: selects the entry mode based on time of day and signal grade.

Aggressive window (9:00–11:30 AM ET):
  A+ grade → ANTICIPATION  (enter at bar2 close — earliest, hammer/shooting star)
  B / C    → AGGRESSIVE    (enter at bar3 open  — two-bar reversal)

Outside aggressive window:
  Any grade → STANDARD     (enter at bar4 open  — three-bar reversal)

Override the aggressive window via env vars:
  AGGRESSIVE_START=09:00   AGGRESSIVE_END=11:30
"""
from __future__ import annotations

import os
from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


_AGG_START = _parse_hhmm(os.getenv("AGGRESSIVE_START", "09:00"))
_AGG_END   = _parse_hhmm(os.getenv("AGGRESSIVE_END",   "11:30"))


class EntryMode(Enum):
    STANDARD     = "standard"      # 3-bar pattern, enter on bar4 open
    AGGRESSIVE   = "aggressive"    # 2-bar pattern, enter on bar3 open
    ANTICIPATION = "anticipation"  # hammer/shooting star, enter at bar2 close


def in_aggressive_window(ts: datetime) -> bool:
    """Return True if ts falls within the aggressive trading window (ET)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_ET)
    else:
        ts = ts.astimezone(_ET)
    t = ts.time()
    return _AGG_START <= t < _AGG_END


def decide_mode(ts: datetime, is_a_plus: bool) -> EntryMode:
    """
    Choose the entry mode from timestamp and grade.

    Args:
        ts: bar close time (naive assumed ET, or tz-aware)
        is_a_plus: True if the signal is A+ grade (at a key level)
    """
    if in_aggressive_window(ts):
        return EntryMode.ANTICIPATION if is_a_plus else EntryMode.AGGRESSIVE
    return EntryMode.STANDARD
