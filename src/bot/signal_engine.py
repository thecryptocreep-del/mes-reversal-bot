"""
Rolling signal scanner — wraps all three reversal patterns with a live bar deque.

Maintains a deque of the last 3 bars.

Public API:
  push_bar(bar)          — append a bar (called by runner before pattern checks)
  check_standard()       — three-bar reversal signal on bars[0..2]
  check_aggressive()     — two-bar reversal signal on bars[-2..-1]
  check_anticipation()   — hammer/shooting star signal on bars[-2..-1]
  on_bar(bar)            — push_bar + check_standard (backward compat / tests)

Logs every evaluation to a rotating daily log file (DEBUG level).
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from collections import deque
from typing import Optional

from config.risk import MIN_BAR1_BODY_POINTS, MIN_BAR2_EXTENSION_POINTS
from src.strategy.anticipation_entry import detect_signal as _detect_anticipation
from src.strategy.three_bar_reversal import Bar, Signal, detect_signal as _detect_standard
from src.strategy.two_bar_reversal import detect_signal as _detect_two_bar

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
    Maintains a rolling window of up to 3 bars and checks reversal patterns.

    Args:
        min_extension: override for MIN_BAR2_EXTENSION_POINTS
        min_bar1_body: override for MIN_BAR1_BODY_POINTS (two-bar aggressive filter)
    """

    def __init__(
        self,
        min_extension: Optional[float] = None,
        min_bar1_body: Optional[float] = None,
    ) -> None:
        self._bars: deque[Bar] = deque(maxlen=3)
        self._min_extension = (
            min_extension if min_extension is not None else MIN_BAR2_EXTENSION_POINTS
        )
        self._min_bar1_body = (
            min_bar1_body if min_bar1_body is not None else MIN_BAR1_BODY_POINTS
        )
        self._sig_logger = _get_signal_logger()

    # ------------------------------------------------------------------
    # Bar ingestion
    # ------------------------------------------------------------------

    def push_bar(self, bar: Bar) -> None:
        """Append a bar to the deque without running any pattern check."""
        self._bars.append(bar)

    # ------------------------------------------------------------------
    # Pattern checks
    # ------------------------------------------------------------------

    def check_standard(self) -> Signal:
        """Three-bar reversal: needs ≥3 bars."""
        if len(self._bars) < 3:
            return Signal.NONE
        b1, b2, b3 = self._bars[0], self._bars[1], self._bars[2]
        sig = _detect_standard(b1, b2, b3, self._min_extension)
        self._sig_logger.debug(
            "STANDARD b1=(%.2f,%.2f,%.2f,%.2f) b2=(%.2f,%.2f,%.2f,%.2f) "
            "b3=(%.2f,%.2f,%.2f,%.2f) ext=%.2f -> %s",
            b1.open, b1.high, b1.low, b1.close,
            b2.open, b2.high, b2.low, b2.close,
            b3.open, b3.high, b3.low, b3.close,
            self._min_extension, sig.name,
        )
        return sig

    def check_aggressive(self) -> Signal:
        """Two-bar reversal: needs ≥2 bars. Uses bars[-2] and bars[-1]."""
        if len(self._bars) < 2:
            return Signal.NONE
        b1, b2 = self._bars[-2], self._bars[-1]
        sig = _detect_two_bar(b1, b2, self._min_bar1_body)
        self._sig_logger.debug(
            "AGGRESSIVE b1=(%.2f,%.2f,%.2f,%.2f) b2=(%.2f,%.2f,%.2f,%.2f) "
            "min_body=%.2f -> %s",
            b1.open, b1.high, b1.low, b1.close,
            b2.open, b2.high, b2.low, b2.close,
            self._min_bar1_body, sig.name,
        )
        return sig

    def check_anticipation(self) -> Signal:
        """Hammer / shooting star: needs ≥2 bars. Uses bars[-2] and bars[-1]."""
        if len(self._bars) < 2:
            return Signal.NONE
        b1, b2 = self._bars[-2], self._bars[-1]
        sig = _detect_anticipation(b1, b2, self._min_extension)
        self._sig_logger.debug(
            "ANTICIPATION b1=(%.2f,%.2f,%.2f,%.2f) b2=(%.2f,%.2f,%.2f,%.2f) "
            "ext=%.2f -> %s",
            b1.open, b1.high, b1.low, b1.close,
            b2.open, b2.high, b2.low, b2.close,
            self._min_extension, sig.name,
        )
        return sig

    # ------------------------------------------------------------------
    # Backward-compatible single-call API (tests + legacy callers)
    # ------------------------------------------------------------------

    def on_bar(self, bar: Bar) -> Optional[Signal]:
        """
        Push bar and check the standard three-bar pattern.

        Returns Signal or None (< 3 bars seen).
        """
        self.push_bar(bar)
        if len(self._bars) < 3:
            return None
        return self.check_standard()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def bar_count(self) -> int:
        return len(self._bars)
