"""
Main bot loop for the MES/MNQ three-bar reversal bot.

PAPER ACCOUNT ONLY unless LIVE_MODE=1 env var is explicitly set.

Usage:
    python -m src.bot.runner

Ctrl+C for graceful shutdown.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone

from config.risk import MAX_POSITION_CONTRACTS, STOP_POINTS, TARGET_POINTS, MIN_BAR2_EXTENSION_POINTS
from config.settings import LIVE_MODE, SYMBOL
from src.bot.jev_logger import JevLogger
from src.bot.risk_manager import RiskManager
from src.bot.signal_engine import SignalEngine
from src.data.live_feed import Bar, LiveFeed
from src.strategy.key_levels import DayLevels, bar2_at_level
from src.bot.notifier import send_signal_alert

# Key levels filter settings (tune via env vars)
_USE_KEY_LEVELS = os.getenv("USE_KEY_LEVELS", "1") == "1"
_LEVEL_PROXIMITY = float(os.getenv("LEVEL_PROXIMITY", "20.0"))
_MIN_EXTENSION = float(os.getenv("MIN_EXTENSION", str(MIN_BAR2_EXTENSION_POINTS)))

# Broker selection: BROKER=projectx (default) or BROKER=tradovate
_BROKER = os.getenv("BROKER", "projectx").lower()
if _BROKER == "tradovate":
    from src.broker.tradovate_client import TradovateClient as _BrokerClient  # type: ignore[assignment]
else:
    from src.broker.projectx_client import ProjectXClient as _BrokerClient  # type: ignore[assignment]
from src.strategy.three_bar_reversal import Signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

if LIVE_MODE:
    logger.warning("=" * 60)
    logger.warning("LIVE MODE ENABLED — real orders will be placed!")
    logger.warning("=" * 60)
else:
    logger.info("Paper mode — broker=%s", _BROKER)


class Bot:
    """Orchestrates the live trading loop."""

    def __init__(self) -> None:
        self._client = _BrokerClient()
        self._risk = RiskManager()
        self._signal_engine = SignalEngine(min_extension=_MIN_EXTENSION)
        self._jev = JevLogger()
        self._current_order_id: int | None = None
        self._shutdown = asyncio.Event()
        self._today_levels: DayLevels | None = None
        self._levels_date: str = ""

    # ------------------------------------------------------------------
    # Bar handler
    # ------------------------------------------------------------------

    def _on_bar(self, bar: Bar) -> None:
        """Called when each 5-min bar closes. Runs synchronously in the event loop."""
        now_et = datetime.now()
        ts_str = bar.timestamp.strftime("%Y-%m-%d %H:%M")

        # Update day levels
        self._update_levels_for_bar(bar)

        # Status line
        print(
            f"[{ts_str}] O={bar.open:.2f} H={bar.high:.2f} "
            f"L={bar.low:.2f} C={bar.close:.2f} V={bar.volume:.0f} | "
            f"trades={self._risk.trade_count}/{6} pnl=${self._risk.daily_pnl:.2f}",
            flush=True,
        )

        # Flatten check
        if self._risk.should_flatten(bar.timestamp):
            asyncio.create_task(self._flatten_position())
            return

        # Session check
        if not self._risk.in_session(bar.timestamp):
            return

        # Risk check
        if not self._risk.can_trade():
            return

        # Signal evaluation
        signal = self._signal_engine.on_bar(bar)
        if signal is None or signal == Signal.NONE:
            return

        # Have a signal — get the last 3 bars from deque
        bars_deque = self._signal_engine._bars
        if len(bars_deque) < 3:
            return
        b1, b2, b3 = bars_deque[0], bars_deque[1], bars_deque[2]

        direction = "Buy" if signal == Signal.LONG else "Sell"

        # Key levels filter
        if _USE_KEY_LEVELS:
            sig_direction = 1 if signal == Signal.LONG else -1
            if self._today_levels is None or not bar2_at_level(
                bar2_high=b2.high,
                bar2_low=b2.low,
                signal_direction=sig_direction,
                levels=self._today_levels,
                proximity_points=_LEVEL_PROXIMITY,
            ):
                logger.info("Signal %s skipped — bar2 not at a key level", signal.name)
                return
        entry_price = bar.close
        if signal == Signal.LONG:
            stop_price = entry_price - STOP_POINTS
            target_price = entry_price + TARGET_POINTS
        else:
            stop_price = entry_price + STOP_POINTS
            target_price = entry_price - TARGET_POINTS

        # Jev shadow log (never influences execution)
        self._jev.log_signal(
            timestamp=bar.timestamp,
            signal=signal,
            bar1=b1,
            bar2=b2,
            bar3=b3,
            entry_price=entry_price,
        )

        logger.info(
            "SIGNAL %s @ %.2f  stop=%.2f  tgt=%.2f",
            signal.name,
            entry_price,
            stop_price,
            target_price,
        )

        send_signal_alert(
            direction=signal.name,
            symbol=SYMBOL,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
        )

        asyncio.create_task(
            self._place_order(direction, entry_price, stop_price, target_price)
        )

    async def _place_order(
        self,
        direction: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> None:
        try:
            order_id = await self._client.place_bracket_order(
                symbol=SYMBOL,
                direction=direction,
                qty=MAX_POSITION_CONTRACTS,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
            )
            self._current_order_id = order_id
            self._risk.record_trade(0.0)  # P&L updated when position closes
        except Exception as exc:
            logger.error("Order placement failed: %s", exc)

    def _update_levels_for_bar(self, bar: Bar) -> None:
        """Refresh today's DayLevels when the date changes."""
        day_str = bar.timestamp.strftime("%Y-%m-%d")
        if day_str == self._levels_date:
            return
        self._levels_date = day_str
        # Build fresh levels — PDH/PDL/PDC require yesterday's bars which we
        # don't have in the live feed, so start with what we can compute today.
        # The opening range fills in after 9:45 ET from the first bars.
        self._today_levels = DayLevels(date=bar.timestamp.normalize())
        logger.info("New trading day %s — levels reset, waiting for opening range", day_str)

    async def _flatten_position(self) -> None:
        logger.info("Flatten time reached — closing any open position")
        try:
            pos = await self._client.get_position(SYMBOL)
            if pos["net_pos"] != 0:
                direction = "Sell" if pos["net_pos"] > 0 else "Buy"
                # Market order to flatten: use current price as both stop and target
                await self._client.place_bracket_order(
                    symbol=SYMBOL,
                    direction=direction,
                    qty=abs(pos["net_pos"]),
                    entry_price=pos["avg_price"],
                    stop_price=pos["avg_price"],
                    target_price=pos["avg_price"],
                )
        except Exception as exc:
            logger.error("Flatten error: %s", exc)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        def _sigint_handler(sig: int, frame: object) -> None:
            logger.info("Ctrl+C received — shutting down")
            self._shutdown.set()

        signal.signal(signal.SIGINT, _sigint_handler)
        signal.signal(signal.SIGTERM, _sigint_handler)

        async with self._client:
            # Use specific account if set, otherwise take first active account
            target_id = os.getenv("PROJECTX_ACCOUNT_ID")
            if target_id:
                self._client._account_id = int(target_id)
                logger.info("Using account ID %s from env", target_id)
            acct = await self._client.get_account_info()
            logger.info("Account: %s  cash=%.2f", acct.get("name"), acct.get("cash", 0))

            # Resolve contractId via REST API (needed for WS subscription)
            try:
                contract_id = await self._client.get_contract_id(SYMBOL)
                logger.info("Resolved contractId: %s", contract_id)
            except Exception as exc:
                logger.warning("Could not resolve contractId (%s) — using symbol %s", exc, SYMBOL)
                contract_id = SYMBOL

            feed = LiveFeed(
                access_token=self._client._token.access_token,  # type: ignore[union-attr]
                symbol=SYMBOL,
                on_bar=self._on_bar,
                contract_id=contract_id,
            )
            feed_task = asyncio.create_task(feed.run())
            await asyncio.wait(
                [feed_task, asyncio.create_task(self._shutdown.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            feed_task.cancel()
            logger.info("Bot stopped.")


def main() -> None:
    asyncio.run(Bot().run())


if __name__ == "__main__":
    main()
