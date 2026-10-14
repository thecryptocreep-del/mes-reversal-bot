"""
WebSocket 5-minute bar builder for Tradovate market data.

Subscribes to MNQ (or configured instrument) via:
  wss://md.tradovateapi.com/v1/websocket

Accumulates tick/quote data into 5-min OHLCV bars.
Fires on_bar callback when each 5-minute bar closes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)

_MD_WS = "wss://md.tradovateapi.com/v1/websocket"
_BAR_SECONDS = 300  # 5-minute bars


@dataclass
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: datetime  # bar-close UTC timestamp


@dataclass
class _BarAccumulator:
    bar_open_ts: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = float("inf")
    close: float = 0.0
    volume: float = 0.0

    def update(self, price: float, size: float = 0.0) -> None:
        if self.bar_open_ts == 0.0:
            self.open = price
            self.high = price
            self.low = price
        else:
            self.high = max(self.high, price)
            self.low = min(self.low, price)
        self.close = price
        self.volume += size

    def to_bar(self, ts: float) -> Bar:
        return Bar(
            open=self.open,
            high=self.high,
            low=self.low if self.low != float("inf") else self.open,
            close=self.close,
            volume=self.volume,
            timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
        )


class LiveFeed:
    """
    Connects to Tradovate market-data WebSocket and builds 5-min bars.

    Usage::

        feed = LiveFeed(access_token, symbol="MNQ", on_bar=my_callback)
        await feed.run()
    """

    def __init__(
        self,
        access_token: str,
        symbol: str,
        on_bar: Callable[[Bar], None],
        bar_seconds: int = _BAR_SECONDS,
    ) -> None:
        self._token = access_token
        self._symbol = symbol
        self._on_bar = on_bar
        self._bar_seconds = bar_seconds
        self._acc = _BarAccumulator()
        self._current_slot: int = 0  # unix epoch // bar_seconds
        self._running = False

    def _slot(self, ts: float) -> int:
        return int(ts // self._bar_seconds)

    def _handle_price(self, price: float, size: float, ts: float) -> Optional[Bar]:
        """Feed a tick. Returns a closed Bar if the 5-min slot just ended."""
        slot = self._slot(ts)
        if self._current_slot == 0:
            self._current_slot = slot
            self._acc.bar_open_ts = slot * self._bar_seconds

        if slot != self._current_slot:
            # Bar closed — emit it
            closed_bar = self._acc.to_bar(self._current_slot * self._bar_seconds + self._bar_seconds)
            # Start new bar
            self._current_slot = slot
            self._acc = _BarAccumulator()
            self._acc.bar_open_ts = slot * self._bar_seconds
            self._acc.update(price, size)
            return closed_bar

        self._acc.update(price, size)
        return None

    async def run(self) -> None:
        """Connect and stream until cancelled."""
        self._running = True
        session = aiohttp.ClientSession()
        try:
            async with session.ws_connect(
                _MD_WS,
                headers={"Authorization": f"Bearer {self._token}"},
            ) as ws:
                logger.info("LiveFeed connected to %s", _MD_WS)
                # Subscribe to quotes
                sub_msg = json.dumps(
                    {"op": "md/subscribeQuote", "args": [self._symbol]}
                )
                await ws.send_str(sub_msg)

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        self._process_message(msg.data, time.time())
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        logger.warning("WebSocket closed/error: %s", msg.type)
                        break
        finally:
            await session.close()
            self._running = False

    def _process_message(self, raw: str, now: float) -> None:
        try:
            # Tradovate frames: "a[...]" array or "h" heartbeat
            if raw.startswith("a"):
                events = json.loads(raw[1:])
                for evt in events:
                    self._dispatch(evt, now)
        except Exception as exc:
            logger.debug("LiveFeed parse error: %s", exc)

    def _dispatch(self, evt: dict, ts: float) -> None:
        if evt.get("e") == "md" and "d" in evt:
            data = evt["d"]
            quotes = data.get("quotes", [])
            for q in quotes:
                price = q.get("bidPrice") or q.get("askPrice")
                if price:
                    bar = self._handle_price(float(price), 0.0, ts)
                    if bar is not None:
                        try:
                            self._on_bar(bar)
                        except Exception as exc:
                            logger.error("on_bar callback error: %s", exc)
