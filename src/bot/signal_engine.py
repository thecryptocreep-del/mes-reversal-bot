"""
Rolling signal scanner — wraps three_bar_reversal with live bar deque.

Maintains a deque of last 3 bars.
on_bar(bar) -> Signal | None fires on each new bar.
Logs every evaluation (including NONE) to a rotating daily log file.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from collections import deque
from datetime import datetime
from typing import Optional

from config.risk import MIN_BAR2_EXTENSION_POINTS
from src.strategy.three_bar_reversal import Bar, Signal, detect_signal

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "logs")


def _get_signal_logger() -> logging.Logger:
    os.makedirs(_LOG_DIR, exist_ok=True)
    sig_logger = logging.getLogger("signal_engine.signals")
    if not sig_logger.handlers:
        handler = logging.handlers.TimedRotatingFileHandler(
            filename=os.path.join(_LOG_DIR, "signals.log"),
            when="midnight",
            backupCount=30,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        sig_logger.addHandler(handler)
        sig_logger.setLevel(logging.DEBUG)
        sig_logger.propagate = False
    return sig_logger


class SignalEngine:
    """
    Maintains a rolling window of 3 bars and emits three-bar reversal signals.

    Args:
        min_extension: override for MIN_BAR2_EXTENSION_POINTS (tests use this)
    """

    def __init__(self, min_extension: Optional[float] = None) -> None:
        self._bars: deque[Bar] = deque(maxlen=3)
        self._min_extension = (
            min_extension if min_extension is not None else MIN_BAR2_EXTENSION_POINTS
        )
        self._sig_logger = _get_signal_logger()

    def on_bar(self, bar: Bar) -> Optional[Signal]:
        """
        Process a new bar.

        Returns Signal.LONG / Signal.SHORT when a pattern fires,
        Signal.NONE otherwise, or None if fewer than 3 bars seen yet.
        """
        self._bars.append(bar)
        if len(self._bars) < 3:
            self._sig_logger.debug(
                "bars=%d — not enough bars yet", len(self._bars)
            )
            return None

        bar1, bar2, bar3 = self._bars[0], self._bars[1], self._bars[2]
        signal = detect_signal(bar1, bar2, bar3, self._min_extension)
        self._sig_logger.debug(
            "bar1=(%.2f,%.2f,%.2f,%.2f) bar2=(%.2f,%.2f,%.2f,%.2f) "
            "bar3=(%.2f,%.2f,%.2f,%.2f) ext=%.2f -> %s",
            bar1.open, bar1.high, bar1.low, bar1.close,
            bar2.open, bar2.high, bar2.low, bar2.close,
            bar3.open, bar3.high, bar3.low, bar3.close,
            self._min_extension,
            signal.name,
        )
        return signal

    @property
    def bar_count(self) -> int:
        return len(self._bars)
