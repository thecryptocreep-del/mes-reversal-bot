"""
Live risk enforcement for the MES/MNQ reversal bot.

All hard limits are read from config/risk.py and cannot be overridden here.
Resets daily trackers at midnight ET.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from config.risk import (
    DAILY_LOSS_LIMIT_USD,
    FLATTEN_TIME_ET,
    MAX_TRADES_PER_DAY,
    SESSION_END_ET,
    SESSION_START_ET,
)

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def _et_now() -> datetime:
    return datetime.now(tz=_ET)


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


_FLATTEN_TIME = _parse_hhmm(FLATTEN_TIME_ET)
_SESSION_START = time(*SESSION_START_ET)
_SESSION_END = time(*SESSION_END_ET)


class RiskManager:
    """
    Tracks daily trade count and P&L, enforces hard risk limits.

    All thresholds come from config/risk.py.
    """

    def __init__(self) -> None:
        self._trade_date: Optional[str] = None  # "YYYY-MM-DD"
        self._trade_count: int = 0
        self._daily_pnl: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reset_if_new_day(self, now_et: Optional[datetime] = None) -> None:
        """Reset daily counters when the calendar date changes in ET."""
        if now_et is None:
            now_et = _et_now()
        today = now_et.strftime("%Y-%m-%d")
        if self._trade_date != today:
            if self._trade_date is not None:
                logger.info(
                    "New trading day %s — resetting risk counters "
                    "(prev trades=%d pnl=%.2f)",
                    today,
                    self._trade_count,
                    self._daily_pnl,
                )
            self._trade_date = today
            self._trade_count = 0
            self._daily_pnl = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def can_trade(self, now_et: Optional[datetime] = None) -> bool:
        """
        Return True if another trade is allowed under hard risk limits.

        Checks:
        - MAX_TRADES_PER_DAY
        - DAILY_LOSS_LIMIT_USD
        """
        if now_et is None:
            now_et = _et_now()
        self._reset_if_new_day(now_et)

        if self._trade_count >= MAX_TRADES_PER_DAY:
            logger.info(
                "can_trade=False: trade count %d >= %d",
                self._trade_count,
                MAX_TRADES_PER_DAY,
            )
            return False

        if self._daily_pnl <= -abs(DAILY_LOSS_LIMIT_USD):
            logger.info(
                "can_trade=False: daily P&L %.2f <= -%.2f",
                self._daily_pnl,
                DAILY_LOSS_LIMIT_USD,
            )
            return False

        return True

    def should_flatten(self, ts: Optional[datetime] = None) -> bool:
        """
        Return True if all positions should be closed (flatten time reached).
        ts can be naive (assumed ET) or tz-aware.
        """
        if ts is None:
            ts = _et_now()
        elif ts.tzinfo is None:
            ts = ts.replace(tzinfo=_ET)
        else:
            ts = ts.astimezone(_ET)
        return ts.time() >= _FLATTEN_TIME

    def in_session(self, ts: Optional[datetime] = None) -> bool:
        """
        Return True if ts falls within the configured trading session window.
        SESSION_START_ET <= ts.time() <= SESSION_END_ET
        """
        if ts is None:
            ts = _et_now()
        elif ts.tzinfo is None:
            ts = ts.replace(tzinfo=_ET)
        else:
            ts = ts.astimezone(_ET)
        t = ts.time()
        return _SESSION_START <= t <= _SESSION_END

    def record_trade(self, pnl: float, now_et: Optional[datetime] = None) -> None:
        """Update daily trackers after a trade closes."""
        if now_et is None:
            now_et = _et_now()
        self._reset_if_new_day(now_et)
        self._trade_count += 1
        self._daily_pnl += pnl
        logger.info(
            "Trade recorded: pnl=%.2f | daily trades=%d pnl=%.2f",
            pnl,
            self._trade_count,
            self._daily_pnl,
        )

    # ------------------------------------------------------------------
    # Accessors (for display)
    # ------------------------------------------------------------------

    @property
    def trade_count(self) -> int:
        self._reset_if_new_day()
        return self._trade_count

    @property
    def daily_pnl(self) -> float:
        self._reset_if_new_day()
        return self._daily_pnl
