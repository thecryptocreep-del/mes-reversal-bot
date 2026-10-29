"""
WebSocket 5-minute bar builder for live market data.

Broker selection via BROKER env var (default: projectx):

  projectx  — wss://gateway.projectx.com/hubs/market  (SignalR)
  tradovate — wss://md.tradovateapi.com/v1/websocket

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

_BROKER = os.getenv("BROKER", "projectx").lower()
_MD_WS_TRADOVATE = "wss://md.tradovateapi.com/v1/websocket"
_MD_WS_PROJECTX = "wss://api.topstepx.com/hubs/market"
_MD_WS = _MD_WS_PROJECTX if _BROKER == "projectx" else _MD_WS_TRADOVATE
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
            if _BROKER == "projectx":
                await self._run_projectx(session)
            else:
                await self._run_tradovate(session)
        except Exception as exc:
            logger.error("LiveFeed run error: %s", exc, exc_info=True)
        finally:
            await session.close()
            self._running = False

    # ------------------------------------------------------------------
    # ProjectX (SignalR) feed
    # ------------------------------------------------------------------

    async def _run_projectx(self, session: aiohttp.ClientSession) -> None:
        """ProjectX SignalR WebSocket feed."""
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        logger.info("LiveFeed connecting to %s", _MD_WS)
        try:
            async with session.ws_connect(_MD_WS, headers=headers) as ws:
                logger.info("LiveFeed connected to ProjectX %s", _MD_WS)
                # SignalR handshake
                handshake = json.dumps({"protocol": "json", "version": 1}) + "\x1e"
                await ws.send_str(handshake)
                # Subscribe to market quotes
                sub = json.dumps({"type": 1, "target": "SubscribeQuotes", "arguments": [self._symbol]}) + "\x1e"
                await ws.send_str(sub)
                logger.info("LiveFeed subscribed to %s quotes — waiting for bars", self._symbol)

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        self._process_message_projectx(msg.data, time.time())
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        logger.warning("ProjectX WebSocket closed/error: %s", msg.data)
                        break
        except aiohttp.WSServerHandshakeError as exc:
            logger.error("WebSocket handshake failed (HTTP %s) — check bearer token: %s", exc.status, exc)
        except Exception as exc:
            logger.error("ProjectX WebSocket error: %s", exc, exc_info=True)

    def _process_message_projectx(self, raw: str, now: float) -> None:
        """Parse SignalR frames (record-separator 0x1e delimited JSON)."""
        try:
            for frame in raw.split("\x1e"):
                frame = frame.strip()
                if not frame:
                    continue
                data = json.loads(frame)
                # type 1 = Invocation; look for quote updates
                if data.get("type") == 1:
                    args = data.get("arguments", [])
                    for arg in args:
                        if isinstance(arg, dict):
                            self._dispatch_projectx(arg, now)
                        elif isinstance(arg, list):
                            for item in arg:
                                if isinstance(item, dict):
                                    self._dispatch_projectx(item, now)
        except Exception as exc:
            logger.debug("ProjectX LiveFeed parse error: %s", exc)

    def _dispatch_projectx(self, evt: dict, ts: float) -> None:
        """Handle a single quote/trade event from ProjectX."""
        # Accept lastPrice, tradePrice, bidPrice, askPrice
        price = (
            evt.get("lastPrice")
            or evt.get("tradePrice")
            or evt.get("bidPrice")
            or evt.get("askPrice")
        )
        if price:
            size = float(evt.get("volume", evt.get("tradeSize", 0.0)))
            bar = self._handle_price(float(price), size, ts)
            if bar is not None:
                try:
                    self._on_bar(bar)
                except Exception as exc:
                    logger.error("on_bar callback error: %s", exc)

    # ------------------------------------------------------------------
    # Tradovate feed (legacy)
    # ------------------------------------------------------------------

    async def _run_tradovate(self, session: aiohttp.ClientSession) -> None:
        """Tradovate market-data WebSocket feed."""
        async with session.ws_connect(
            _MD_WS_TRADOVATE,
            headers={"Authorization": f"Bearer {self._token}"},
        ) as ws:
            logger.info("LiveFeed connected to Tradovate %s", _MD_WS_TRADOVATE)
            sub_msg = json.dumps(
                {"op": "md/subscribeQuote", "args": [self._symbol]}
            )
            await ws.send_str(sub_msg)

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._process_message_tradovate(msg.data, time.time())
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    logger.warning("Tradovate WebSocket closed/error: %s", msg.type)
                    break

    def _process_message_tradovate(self, raw: str, now: float) -> None:
        try:
            # Tradovate frames: "a[...]" array or "h" heartbeat
            if raw.startswith("a"):
                events = json.loads(raw[1:])
                for evt in events:
                    self._dispatch_tradovate(evt, now)
        except Exception as exc:
            logger.debug("Tradovate LiveFeed parse error: %s", exc)

    def _dispatch_tradovate(self, evt: dict, ts: float) -> None:
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

    # Keep old entry point name for backward compat
    def _process_message(self, raw: str, now: float) -> None:
        if _BROKER == "projectx":
            self._process_message_projectx(raw, now)
        else:
            self._process_message_tradovate(raw, now)
