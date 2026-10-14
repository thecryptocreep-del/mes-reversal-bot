"""
Tradovate REST + WebSocket client.

Uses TRADOVATE_USERNAME and TRADOVATE_PASSWORD env vars for auth.
Paper = demo.tradovateapi.com, Live = live.tradovateapi.com (check LIVE_MODE).
PAPER ACCOUNT ONLY unless LIVE_MODE=1 env var is set.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

LIVE_MODE = os.getenv("LIVE_MODE", "0") == "1"

_BASE_REST = (
    "https://live.tradovateapi.com/v1"
    if LIVE_MODE
    else "https://demo.tradovateapi.com/v1"
)
_BASE_WS = (
    "wss://live.tradovateapi.com/v1/websocket"
    if LIVE_MODE
    else "wss://demo.tradovateapi.com/v1/websocket"
)
_MD_WS = "wss://md.tradovateapi.com/v1/websocket"

TOKEN_TTL_SECONDS = 23 * 3600  # refresh before 24 h expiry


@dataclass
class _Token:
    access_token: str
    issued_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return (time.time() - self.issued_at) >= TOKEN_TTL_SECONDS


class TradovateClient:
    """Async Tradovate REST client with token management."""

    def __init__(self) -> None:
        self._username: str = os.environ["TRADOVATE_USERNAME"]
        self._password: str = os.environ["TRADOVATE_PASSWORD"]
        self._token: Optional[_Token] = None
        self._session: Optional[aiohttp.ClientSession] = None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "TradovateClient":
        self._session = aiohttp.ClientSession()
        await self._ensure_token()
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _ensure_token(self) -> None:
        if self._token is None or self._token.is_expired():
            await self._authenticate()

    async def _authenticate(self) -> None:
        assert self._session is not None
        payload = {
            "name": self._username,
            "password": self._password,
            "appId": "mes-reversal-bot",
            "appVersion": "1.0",
            "cid": 0,
            "sec": "",
        }
        async with self._session.post(
            f"{_BASE_REST}/auth/accesstokenrequest", json=payload
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if "accessToken" not in data:
            raise RuntimeError(f"Auth failed: {data}")
        self._token = _Token(access_token=data["accessToken"])
        logger.info("Tradovate token acquired (paper=%s)", not LIVE_MODE)

    def _headers(self) -> dict[str, str]:
        assert self._token is not None
        return {"Authorization": f"Bearer {self._token.access_token}"}

    async def _get(self, path: str, **params: Any) -> Any:
        await self._ensure_token()
        assert self._session is not None
        async with self._session.get(
            f"{_BASE_REST}{path}", headers=self._headers(), params=params
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        await self._ensure_token()
        assert self._session is not None
        async with self._session.post(
            f"{_BASE_REST}{path}", headers=self._headers(), json=body
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    async def get_account_info(self) -> dict[str, Any]:
        """Return dict with cash and daily P&L."""
        accounts = await self._get("/account/list")
        if not accounts:
            raise RuntimeError("No accounts found")
        acct = accounts[0]
        summary = await self._get(f"/accountRiskStatus/item", id=acct["id"])
        return {
            "account_id": acct["id"],
            "name": acct.get("name"),
            "cash": acct.get("cashBalance", 0.0),
            "daily_pnl": summary.get("openPnl", 0.0),
        }

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def place_bracket_order(
        self,
        symbol: str,
        direction: str,
        qty: int,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> int:
        """
        Place a bracket order (entry + stop + target).

        Args:
            symbol: e.g. "MNQZ4"
            direction: "Buy" or "Sell"
            qty: number of contracts
            entry_price: limit entry price
            stop_price: stop-loss price
            target_price: take-profit price

        Returns:
            order_id of the entry leg
        """
        if LIVE_MODE:
            logger.warning("LIVE_MODE is active — placing real order!")
        else:
            logger.info(
                "Paper bracket: %s %s %d @ %.2f stop=%.2f tgt=%.2f",
                direction, symbol, qty, entry_price, stop_price, target_price,
            )

        # Resolve contract id
        contract = await self._get("/contract/find", name=symbol)
        contract_id = contract["id"]

        body = {
            "accountSpec": self._username,
            "contractId": contract_id,
            "action": direction,
            "orderQty": qty,
            "orderType": "Limit",
            "price": entry_price,
            "bracket1": {
                "action": "Sell" if direction == "Buy" else "Buy",
                "orderType": "Stop",
                "stopPrice": stop_price,
                "orderQty": qty,
            },
            "bracket2": {
                "action": "Sell" if direction == "Buy" else "Buy",
                "orderType": "Limit",
                "price": target_price,
                "orderQty": qty,
            },
            "isAutomated": True,
        }
        result = await self._post("/order/placebracketorder", body)
        order_id: int = result["orderId"]
        logger.info("Bracket order placed: id=%d", order_id)
        return order_id

    async def cancel_order(self, order_id: int) -> None:
        """Cancel an open order by id."""
        await self._post("/order/cancelorder", {"orderId": order_id})
        logger.info("Order %d cancelled", order_id)

    async def get_position(self, symbol: str) -> dict[str, Any]:
        """
        Return current position for symbol.
        Returns dict with netPos (signed contracts) and avgPrice.
        """
        positions = await self._get("/position/list")
        for pos in positions:
            if pos.get("contractId") and symbol.upper() in str(pos.get("contractId", "")):
                return {
                    "symbol": symbol,
                    "net_pos": pos.get("netPos", 0),
                    "avg_price": pos.get("prevPrice", 0.0),
                    "open_pnl": pos.get("openPnl", 0.0),
                }
        return {"symbol": symbol, "net_pos": 0, "avg_price": 0.0, "open_pnl": 0.0}
