"""
ProjectX REST client (used by Topstep and other prop firms).

Auth:
  Primary:  PROJECTX_API_KEY env var  (API-key header)
  Fallback: PROJECTX_USERNAME + PROJECTX_PASSWORD (token-based)

ProjectX handles paper/eval vs. live account separation server-side
via account IDs, so the base URL is the same regardless of mode.
Set LIVE_MODE=1 only if you intend real execution (see config/risk.py).

PAPER ACCOUNT ONLY unless LIVE_MODE=1 env var is explicitly set.
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

_BASE_REST = "https://api.topstepx.com/api"
_WS_MARKET = "wss://api.topstepx.com/hubs/market"

TOKEN_TTL_SECONDS = 23 * 3600  # refresh before 24 h expiry


@dataclass
class _Token:
    access_token: str
    issued_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return (time.time() - self.issued_at) >= TOKEN_TTL_SECONDS


class ProjectXClient:
    """Async ProjectX REST client with API-key or token-based auth."""

    def __init__(self) -> None:
        self._api_key: Optional[str] = os.getenv("PROJECTX_API_KEY")
        self._username: Optional[str] = os.getenv("PROJECTX_USERNAME")
        if not self._api_key or not self._username:
            raise RuntimeError(
                "Set both PROJECTX_API_KEY and PROJECTX_USERNAME env vars.\n"
                "Find your username in TopstepX platform (not your email).\n"
                "Generate an API key at topstepx.com/settings?tab=api"
            )
        self._token: Optional[_Token] = None
        self._session: Optional[aiohttp.ClientSession] = None
        # Cached account id from first get_account_info call
        self._account_id: Optional[int] = None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ProjectXClient":
        self._session = aiohttp.ClientSession()
        await self._ensure_auth()
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _ensure_auth(self) -> None:
        if self._token is None or self._token.is_expired():
            await self.authenticate()

    async def authenticate(self) -> None:
        """
        Obtain a bearer token via Topstep's loginKey endpoint.
        POST /Auth/loginKey  {userName, apiKey}  → {token, success, errorCode}
        """
        assert self._session is not None
        payload = {
            "userName": self._username,
            "apiKey": self._api_key,
        }
        async with self._session.post(
            f"{_BASE_REST}/Auth/loginKey",
            json=payload,
            headers={"accept": "text/plain", "Content-Type": "application/json"},
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        if not data.get("success"):
            code = data.get("errorCode")
            msg = data.get("errorMessage") or ""
            hints = {
                3: "Wrong userName or apiKey — use your platform login username, not email",
                7: "Accept pending agreements at topstepx.com first",
                9: "No active API subscription on this account",
                10: "API key auth is disabled — contact Topstep support",
            }
            raise RuntimeError(
                f"Topstep auth failed (errorCode={code}): {hints.get(code, msg) or data}"
            )

        self._token = _Token(access_token=data["token"])
        logger.info("Topstep token acquired (LIVE_MODE=%s)", LIVE_MODE)

    def _headers(self) -> dict[str, str]:
        assert self._token is not None
        return {"Authorization": f"Bearer {self._token.access_token}"}

    async def _get(self, path: str, **params: Any) -> Any:
        await self._ensure_auth()
        assert self._session is not None
        async with self._session.get(
            f"{_BASE_REST}{path}", headers=self._headers(), params=params
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        await self._ensure_auth()
        assert self._session is not None
        async with self._session.post(
            f"{_BASE_REST}{path}", headers=self._headers(), json=body
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _delete(self, path: str) -> Any:
        await self._ensure_auth()
        assert self._session is not None
        async with self._session.delete(
            f"{_BASE_REST}{path}", headers=self._headers()
        ) as resp:
            resp.raise_for_status()
            # 204 No Content is common on DELETE
            if resp.status == 204:
                return {}
            return await resp.json()

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    async def get_account_info(self) -> dict[str, Any]:
        """Return dict with cash and daily P&L from the first account."""
        data = await self._get("/accounts")
        # API may return list directly or wrapped in 'accounts' key
        accounts = data if isinstance(data, list) else data.get("accounts", data)
        if not accounts:
            raise RuntimeError("No ProjectX accounts found")
        acct = accounts[0]
        acct_id = acct.get("id") or acct.get("accountId")
        self._account_id = acct_id
        return {
            "account_id": acct_id,
            "name": acct.get("name") or acct.get("accountName"),
            "cash": float(acct.get("balance", acct.get("cashBalance", 0.0))),
            "daily_pnl": float(acct.get("dailyPnl", acct.get("openPnl", 0.0))),
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
            symbol:       e.g. "MESU4" or "MES"
            direction:    "Buy" or "Sell"
            qty:          number of contracts
            entry_price:  limit entry price
            stop_price:   stop-loss price
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

        body: dict[str, Any] = {
            "symbol": symbol,
            "side": direction,          # "Buy" | "Sell"
            "quantity": qty,
            "orderType": "Limit",
            "limitPrice": entry_price,
            "stopLoss": {
                "orderType": "Stop",
                "stopPrice": stop_price,
            },
            "takeProfit": {
                "orderType": "Limit",
                "limitPrice": target_price,
            },
        }
        if self._account_id is not None:
            body["accountId"] = self._account_id

        result = await self._post("/orders", body)
        # Accept 'orderId', 'id', or 'order_id' in response
        order_id: int = (
            result.get("orderId")
            or result.get("id")
            or result.get("order_id")
        )
        if order_id is None:
            raise RuntimeError(f"ProjectX order placement returned no id: {result}")
        logger.info("Bracket order placed: id=%s", order_id)
        return int(order_id)

    async def cancel_order(self, order_id: int) -> None:
        """Cancel an open order by id."""
        await self._delete(f"/orders/{order_id}")
        logger.info("Order %s cancelled", order_id)

    async def get_position(self, symbol: str) -> dict[str, Any]:
        """
        Return current position for symbol.
        Returns dict with net_pos (signed contracts) and avg_price.
        """
        data = await self._get("/positions")
        positions = data if isinstance(data, list) else data.get("positions", [])
        for pos in positions:
            pos_symbol = pos.get("symbol", "") or str(pos.get("contractId", ""))
            if symbol.upper() in pos_symbol.upper():
                return {
                    "symbol": symbol,
                    "net_pos": int(pos.get("netPosition", pos.get("netPos", 0))),
                    "avg_price": float(pos.get("averagePrice", pos.get("avgPrice", 0.0))),
                    "open_pnl": float(pos.get("unrealizedPnl", pos.get("openPnl", 0.0))),
                }
        return {"symbol": symbol, "net_pos": 0, "avg_price": 0.0, "open_pnl": 0.0}
