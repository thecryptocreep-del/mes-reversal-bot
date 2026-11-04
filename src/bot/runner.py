"""
Main bot loop for the MES/MNQ reversal bot.

PAPER ACCOUNT ONLY unless LIVE_MODE=1 env var is explicitly set.

Three entry modes selected by decision engine:
  STANDARD     (11:30 AM – close)  — 3-bar reversal, enter bar4 open
  AGGRESSIVE   (9–11:30 AM, B/C)  — 2-bar reversal, enter bar3 open
  ANTICIPATION (9–11:30 AM, A+ )  — hammer pattern, enter at bar2 close

Usage:
    python main.py

Ctrl+C for graceful shutdown.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Optional

from config.risk import (
    MAX_POSITION_CONTRACTS,
    MAX_POSITION_CONTRACTS_APLUS,
    MAX_TRADES_PER_DAY,
    STOP_POINTS,
    TARGET_POINTS,
    MIN_BAR2_EXTENSION_POINTS,
    MIN_BAR1_BODY_POINTS,
)
from config.settings import LIVE_MODE, SYMBOL
from src.bot.decision_engine import EntryMode, in_aggressive_window
from src.bot.jev_logger import JevLogger
from src.bot.risk_manager import RiskManager
from src.bot.signal_engine import SignalEngine
from src.data.live_feed import Bar, LiveFeed
from src.strategy.key_levels import DayLevels, SignalGrade, grade_signal
from src.data.prior_day import fetch_prior_day
from src.bot.notifier import send_signal_alert
from src.strategy.three_bar_reversal import Signal

# Key levels filter settings (tune via env vars)
_USE_KEY_LEVELS  = os.getenv("USE_KEY_LEVELS", "1") == "1"
_LEVEL_PROXIMITY = float(os.getenv("LEVEL_PROXIMITY", "20.0"))
_MIN_EXTENSION   = float(os.getenv("MIN_EXTENSION", str(MIN_BAR2_EXTENSION_POINTS)))
_MIN_BAR1_BODY   = float(os.getenv("MIN_BAR1_BODY", str(MIN_BAR1_BODY_POINTS)))

# Broker selection: BROKER=projectx (default) or BROKER=tradovate
_BROKER = os.getenv("BROKER", "projectx").lower()
if _BROKER == "tradovate":
    from src.broker.tradovate_client import TradovateClient as _BrokerClient  # type: ignore[assignment]
else:
    from src.broker.projectx_client import ProjectXClient as _BrokerClient  # type: ignore[assignment]

import pathlib as _pathlib
_log_dir = _pathlib.Path("logs")
_log_dir.mkdir(exist_ok=True)
_log_file = _log_dir / f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_log_file, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

if LIVE_MODE:
    logger.warning("=" * 60)
    logger.warning("LIVE MODE ENABLED — real orders will be placed!")
    logger.warning("=" * 60)
else:
    logger.info("Paper mode — broker=%s", _BROKER)


class Bot:
    """Orchestrates the live trading loop with multi-mode decision engine."""

    def __init__(self) -> None:
        self._client = _BrokerClient()
        self._risk = RiskManager()
        self._signal_engine = SignalEngine(
            min_extension=_MIN_EXTENSION,
            min_bar1_body=_MIN_BAR1_BODY,
        )
        self._jev = JevLogger()
        self._current_order_id: Optional[int] = None
        self._open_exit_ids: list[int] = []
        self._trade_direction: Optional[str] = None
        self._trade_target: Optional[float] = None
        self._trade_qty: int = 0
        self._shutdown = asyncio.Event()
        self._today_levels: Optional[DayLevels] = None
        self._levels_date: str = ""
        self._flattened_today: bool = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _grade_bar(self, bar, sig_direction: int) -> SignalGrade:
        """Grade a signal by checking bar's extreme against today's key levels."""
        if _USE_KEY_LEVELS and self._today_levels is not None:
            return grade_signal(
                bar2_high=bar.high,
                bar2_low=bar.low,
                signal_direction=sig_direction,
                levels=self._today_levels,
                proximity_points=_LEVEL_PROXIMITY,
            )
        return SignalGrade.C

    # ------------------------------------------------------------------
    # Bar handler
    # ------------------------------------------------------------------

    def _on_bar(self, bar: Bar) -> None:
        """Called when each 5-min bar closes. Runs synchronously in the event loop."""
        ts_str = bar.timestamp.strftime("%Y-%m-%d %H:%M")
        self._update_levels_for_bar(bar)

        bar_line = (
            f"[{ts_str}] O={bar.open:.2f} H={bar.high:.2f} "
            f"L={bar.low:.2f} C={bar.close:.2f} V={bar.volume:.0f} | "
            f"trades={self._risk.trade_count}/{'∞' if MAX_TRADES_PER_DAY == 0 else MAX_TRADES_PER_DAY} pnl=${self._risk.daily_pnl:.2f}"
        )
        print(bar_line, flush=True)
        logger.info(bar_line)

        # Software TP check — fire at bar close if price crossed target
        if self._trade_target is not None and self._trade_direction is not None:
            tp_hit = (
                (self._trade_direction == "Buy"  and bar.high >= self._trade_target) or
                (self._trade_direction == "Sell" and bar.low  <= self._trade_target)
            )
            if tp_hit:
                logger.info(
                    "TP hit: target=%.2f bar H=%.2f L=%.2f — closing position",
                    self._trade_target, bar.high, bar.low,
                )
                asyncio.create_task(self._close_position_at_tp())
                return

        # Flatten check — only once per day
        if self._risk.should_flatten(bar.timestamp):
            if not self._flattened_today:
                self._flattened_today = True
                asyncio.create_task(self._flatten_position())
            return

        # Session check
        if not self._risk.in_session(bar.timestamp):
            return

        # Risk check
        if not self._risk.can_trade():
            return

        # Already in a position — do not layer trades
        if self._trade_target is not None:
            return

        # Push bar to deque
        self._signal_engine.push_bar(bar)
        if self._signal_engine.bar_count < 2:
            return

        # --- DECISION ENGINE ---
        in_agg = in_aggressive_window(bar.timestamp)
        signal = Signal.NONE
        mode = EntryMode.STANDARD
        b1 = b2 = b3 = None
        grade = SignalGrade.C

        if in_agg:
            bars = self._signal_engine._bars

            # Priority 1: Anticipation — requires A+ grade
            ant_sig = self._signal_engine.check_anticipation()
            if ant_sig != Signal.NONE:
                _b1, _b2 = bars[-2], bars[-1]
                sig_dir = 1 if ant_sig == Signal.LONG else -1
                g = self._grade_bar(_b2, sig_dir)
                if g == SignalGrade.A_PLUS:
                    signal, mode, grade = ant_sig, EntryMode.ANTICIPATION, g
                    b1, b2 = _b1, _b2

            # Priority 2: Aggressive two-bar — any grade
            if signal == Signal.NONE:
                agg_sig = self._signal_engine.check_aggressive()
                if agg_sig != Signal.NONE:
                    _b1, _b2 = bars[-2], bars[-1]
                    sig_dir = 1 if agg_sig == Signal.LONG else -1
                    # Extension bar is bar1 (the big push) — grade by its extreme
                    g = self._grade_bar(_b1, sig_dir)
                    signal, mode, grade = agg_sig, EntryMode.AGGRESSIVE, g
                    b1, b2 = _b1, _b2

        else:
            # Standard three-bar — outside aggressive window
            if self._signal_engine.bar_count < 3:
                return
            std_sig = self._signal_engine.check_standard()
            if std_sig is not None and std_sig != Signal.NONE:
                bars = self._signal_engine._bars
                _b1, _b2, _b3 = bars[0], bars[1], bars[2]
                sig_dir = 1 if std_sig == Signal.LONG else -1
                g = self._grade_bar(_b2, sig_dir)
                signal, mode, grade = std_sig, EntryMode.STANDARD, g
                b1, b2, b3 = _b1, _b2, _b3

        if signal == Signal.NONE or b1 is None:
            return

        # --- SIGNAL CONFIRMED ---
        direction = "Buy" if signal == Signal.LONG else "Sell"
        sig_direction = 1 if signal == Signal.LONG else -1

        qty = MAX_POSITION_CONTRACTS_APLUS if grade == SignalGrade.A_PLUS else MAX_POSITION_CONTRACTS
        logger.info(
            "Signal: %s  mode=%s  grade=%s  qty=%d",
            signal.name, mode.value, grade.value, qty,
        )

        entry_price = bar.close
        if signal == Signal.LONG:
            stop_price   = entry_price - STOP_POINTS
            target_price = entry_price + TARGET_POINTS
        else:
            stop_price   = entry_price + STOP_POINTS
            target_price = entry_price - TARGET_POINTS

        # Jev shadow log (never influences execution)
        self._jev.log_signal(
            timestamp=bar.timestamp,
            signal=signal,
            bar1=b1,
            bar2=b2,
            bar3=b3,
            entry_price=entry_price,
            mode=mode.value,
        )

        logger.info(
            "SIGNAL %s @ %.2f  stop=%.2f  tgt=%.2f  mode=%s",
            signal.name, entry_price, stop_price, target_price, mode.value,
        )

        send_signal_alert(
            direction=signal.name,
            symbol=SYMBOL,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
        )

        asyncio.create_task(
            self._place_order(direction, entry_price, stop_price, target_price, qty)
        )

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    async def _place_order(
        self,
        direction: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
        qty: int = MAX_POSITION_CONTRACTS,
    ) -> None:
        try:
            ids = await self._client.place_bracket_order(
                symbol=SYMBOL,
                direction=direction,
                qty=qty,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
            )
            self._current_order_id = ids["entry_id"]
            self._open_exit_ids = [i for i in [ids.get("stop_id")] if i]
            self._trade_direction = direction
            self._trade_target = target_price
            self._trade_qty = qty
        except Exception as exc:
            logger.error("Order placement failed: %s", exc)

    async def _close_position_at_tp(self) -> None:
        """Software take-profit: cancel the stop order and close position at market."""
        target    = self._trade_target
        direction = self._trade_direction
        qty       = self._trade_qty
        stop_ids  = list(self._open_exit_ids)

        # Clear state immediately to prevent re-entry
        self._trade_target    = None
        self._trade_direction = None
        self._trade_qty       = 0
        self._open_exit_ids   = []

        try:
            stop_cancel_ok = True
            if stop_ids:
                logger.info("TP: cancelling stop order(s) %s", stop_ids)
                cancel_results = await self._client.cancel_orders(stop_ids)
                # errorCode 5 = order not found / already executed (stop may have hit)
                if any(r.get("errorCode", 0) != 0 for r in cancel_results):
                    stop_cancel_ok = False
                    logger.warning(
                        "Stop cancel returned error — verifying position before TP close: %s",
                        cancel_results,
                    )

            if not stop_cancel_ok:
                # Stop may have already filled — check actual net position
                try:
                    pos = await self._client.get_position(SYMBOL)
                    if pos.get("net_pos", 0) == 0:
                        logger.warning(
                            "Position already flat — stop executed before TP detection; "
                            "recording as stop-loss (pnl=%.2f)",
                            -STOP_POINTS * qty * 2.0,
                        )
                        self._risk.record_trade(-STOP_POINTS * qty * 2.0)
                        return
                except Exception as exc:
                    logger.error("Could not verify position after cancel error: %s", exc)

            close_direction = "Sell" if direction == "Buy" else "Buy"
            from src.broker.projectx_client import ORDER_TYPE_MARKET, SIDE_BUY, SIDE_SELL
            exit_side = SIDE_SELL if close_direction == "Sell" else SIDE_BUY
            contract_id = await self._client.get_contract_id(SYMBOL)
            body = {
                "accountId": self._client._account_id,
                "contractId": contract_id,
                "type": ORDER_TYPE_MARKET,
                "side": exit_side,
                "size": qty,
            }
            result = await self._client._post("/Order/place", body)
            logger.info("TP close order: %s → %s", close_direction, result)
            pnl = TARGET_POINTS * qty * 2.0  # approximate MNQ point value
            self._risk.record_trade(pnl)
        except Exception as exc:
            logger.error("TP close failed: %s", exc)

    # ------------------------------------------------------------------
    # Level updates
    # ------------------------------------------------------------------

    def _update_levels_for_bar(self, bar: Bar) -> None:
        day_str = bar.timestamp.strftime("%Y-%m-%d")
        if day_str == self._levels_date:
            return
        self._levels_date = day_str
        import pandas as _pd
        self._today_levels = DayLevels(date=_pd.Timestamp(bar.timestamp).normalize())
        self._flattened_today = False
        logger.info("New trading day %s — levels reset", day_str)

    # ------------------------------------------------------------------
    # Flatten
    # ------------------------------------------------------------------

    async def _flatten_position(self) -> None:
        logger.info("Flatten time reached — closing any open position")
        if self._open_exit_ids:
            await self._client.cancel_orders(self._open_exit_ids)
            self._open_exit_ids = []
        try:
            pos = await self._client.get_position(SYMBOL)
            if pos["net_pos"] != 0:
                direction = "Sell" if pos["net_pos"] > 0 else "Buy"
                await self._client.place_market_close(
                    symbol=SYMBOL,
                    direction=direction,
                    qty=abs(pos["net_pos"]),
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

        signal.signal(signal.SIGINT,  _sigint_handler)
        signal.signal(signal.SIGTERM, _sigint_handler)

        async with self._client:
            target_id = os.getenv("PROJECTX_ACCOUNT_ID")
            if target_id:
                self._client._account_id = int(target_id)
                logger.info("Using account ID %s from env", target_id)
            acct = await self._client.get_account_info()
            logger.info("Account: %s  cash=%.2f", acct.get("name"), acct.get("cash", 0))

            pd_levels = fetch_prior_day(SYMBOL)
            import pandas as _pd2
            self._today_levels = DayLevels(
                date=_pd2.Timestamp.now().normalize(),
                pdh=pd_levels["pdh"],
                pdl=pd_levels["pdl"],
                pdc=pd_levels["pdc"],
            )
            self._levels_date = datetime.now().strftime("%Y-%m-%d")

            try:
                contract_id = await self._client.get_contract_id(SYMBOL)
                logger.info("Resolved contractId: %s", contract_id)
            except Exception as exc:
                logger.warning(
                    "Could not resolve contractId (%s) — using symbol %s", exc, SYMBOL
                )
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
