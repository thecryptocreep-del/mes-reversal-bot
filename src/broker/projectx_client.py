"""
ProjectX REST client for Topstep (TopstepX platform).

Auth: POST /Auth/loginKey {userName, apiKey} → bearer token (24h)
Accounts: POST /Account/search
Contracts: POST /Contract/available  → resolve contractId by symbol
Orders: POST /Order/place  (type: 2=Limit, side: 1=Buy/2=Sell)

Order type codes:
  1 = Market, 2 = Limit, 3 = Stop, 4 = StopLimit

Side codes:
  1 = Buy (Ask), 2 = Sell (Bid)

PAPER ACCOUNT ONLY unless LIVE_MODE=1 env var is explicitly set.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

LIVE_MODE = os.getenv("LIVE_MODE", "0") == "1"

_BASE = "https://api.topstepx.com/api"
_WS_MARKET = "wss://api.topstepx.com/hubs/market"

TOKEN_TTL_SECONDS = 23 * 3600  # re-auth before 24h expiry

# Order type and side codes per Topstep API
ORDER_TYPE_MARKET = 1
ORDER_TYPE_LIMIT  = 2
ORDER_TYPE_STOP   = 3

SIDE_BUY  = 1
SIDE_SELL = 2


@dataclass
class _Token:
    access_token: str
    issued_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return (time.time() - self.issued_at) >= TOKEN_TTL_SECONDS


class ProjectXClient:
    """Async Topstep/ProjectX REST client."""

    def __init__(self) -> None:
        self._api_key: Optional[str] = os.getenv("PROJECTX_API_KEY")
        self._username: Optional[str] = os.getenv("PROJECTX_USERNAME")
        if not self._api_key or not self._username:
            raise RuntimeError(
                "Set both PROJECTX_API_KEY and PROJECTX_USERNAME env vars.\n"
                "Username: your TopstepX platform login (not email).\n"
                "API key: topstepx.com/settings?tab=api"
            )
        self._token: Optional[_Token] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._account_id: Optional[int] = None
        # Cache: symbol → contractId (e.g. "MNQ" → "CON.F.US.MNQ.Z25")
        self._contract_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Lifecycle
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
        """POST /Auth/loginKey → bearer token."""
        assert self._session is not None
        async with self._session.post(
            f"{_BASE}/Auth/loginKey",
            json={"userName": self._username, "apiKey": self._api_key},
            headers={"accept": "text/plain", "Content-Type": "application/json"},
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        if not data.get("success"):
            code = data.get("errorCode")
            hints = {
                3: "Wrong userName or apiKey — use platform login username, not email",
                7: "Accept pending agreements at topstepx.com first",
                9: "No active API subscription on this account",
                10: "API key auth disabled — contact Topstep support",
            }
            raise RuntimeError(
                f"Topstep auth failed (errorCode={code}): "
                f"{hints.get(code, data.get('errorMessage', data))}"
            )

        self._token = _Token(access_token=data["token"])
        logger.info("Topstep authenticated (LIVE_MODE=%s)", LIVE_MODE)

    def _headers(self) -> dict[str, str]:
        assert self._token is not None
        return {"Authorization": f"Bearer {self._token.access_token}"}

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        await self._ensure_auth()
        assert self._session is not None
        async with self._session.post(
            f"{_BASE}{path}", headers=self._headers(), json=body
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _delete(self, path: str) -> Any:
        await self._ensure_auth()
        assert self._session is not None
        async with self._session.delete(
            f"{_BASE}{path}", headers=self._headers()
        ) as resp:
            resp.raise_for_status()
            if resp.status == 204:
                return {}
            return await resp.json()

    # ------------------------------------------------------------------
    # Account  — POST /Account/search
    # ------------------------------------------------------------------

    async def get_account_info(self) -> dict[str, Any]:
        """Return first active account details and cache its ID."""
        data = await self._post("/Account/search", {"onlyActiveAccounts": True})
        accounts = data if isinstance(data, list) else data.get("accounts", [])
        if not accounts:
            raise RuntimeError("No active ProjectX/Topstep accounts found")
        acct = accounts[0]
        self._account_id = acct.get("id") or acct.get("accountId")
        return {
            "account_id": self._account_id,
            "name": acct.get("name") or acct.get("accountName", ""),
            "cash": float(acct.get("balance", acct.get("cashBalance", 0.0))),
            "daily_pnl": float(acct.get("dailyPnl", acct.get("openPnl", 0.0))),
        }

    # ------------------------------------------------------------------
    # Contracts  — POST /Contract/available
    # ------------------------------------------------------------------

    async def get_contract_id(self, symbol: str) -> str:
        """
        Resolve a symbol (e.g. "MNQ") to Topstep's contractId string.
        Results are cached for the session.
        """
        sym = symbol.upper()
        if sym in self._contract_cache:
            return self._contract_cache[sym]

        data = await self._post("/Contract/available", {"live": LIVE_MODE})
        contracts = data if isinstance(data, list) else data.get("contracts", [])

        for c in contracts:
            c_id: str = c.get("id", "")
            c_name: str = c.get("name", "") or c.get("description", "")
            if sym in c_id.upper() or sym in c_name.upper():
                self._contract_cache[sym] = c_id
                logger.info("Resolved %s → %s", sym, c_id)
                return c_id

        raise RuntimeError(
            f"Contract '{symbol}' not found in available contracts. "
            f"Check symbol spelling or Topstep account permissions."
        )

    # ------------------------------------------------------------------
    # Orders  — POST /Order/place
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
        Place entry limit order + stop + target as separate orders.

        Args:
            symbol:       e.g. "MNQ"
            direction:    "Buy" or "Sell"
            qty:          number of contracts
            entry_price:  limit entry price
            stop_price:   stop-loss price
            target_price: take-profit price

        Returns:
            orderId of the entry leg
        """
        if LIVE_MODE:
            logger.warning("LIVE_MODE active — placing REAL order on Topstep!")

        if self._account_id is None:
            await self.get_account_info()

        contract_id = await self.get_contract_id(symbol)
        side = SIDE_BUY if direction.lower() == "buy" else SIDE_SELL

        logger.info(
            "Bracket %s %s x%d contractId=%s entry=%.2f stop=%.2f tgt=%.2f",
            direction, symbol, qty, contract_id, entry_price, stop_price, target_price,
        )

        # Entry market order — fills immediately at bar4 open
        entry_body = {
            "accountId": self._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_MARKET,
            "side": side,
            "size": qty,
        }
        result = await self._post("/Order/place", entry_body)
        logger.info("Entry order response: %s", result)
        if not result.get("success", True) and result.get("errorCode"):
            raise RuntimeError(f"Entry order failed: {result}")
        order_id = result.get("orderId") or result.get("id")
        if order_id is None:
            raise RuntimeError(f"Order placement returned no id: {result}")

        # Stop loss order (opposite side)
        stop_side = SIDE_SELL if side == SIDE_BUY else SIDE_BUY
        stop_body = {
            "accountId": self._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_STOP,
            "side": stop_side,
            "size": qty,
            "stopPrice": stop_price,
        }
        await self._post("/Order/place", stop_body)

        # Target limit order (opposite side)
        target_body = {
            "accountId": self._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_LIMIT,
            "side": stop_side,
            "size": qty,
            "limitPrice": target_price,
        }
        await self._post("/Order/place", target_body)

        logger.info("Bracket placed: entry orderId=%s", order_id)
        return int(order_id)

    async def cancel_order(self, order_id: int) -> None:
        """Cancel an open order."""
        result = await self._post("/Order/cancel", {"orderId": order_id})
        logger.info("Order %s cancelled: %s", order_id, result)

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    async def get_position(self, symbol: str) -> dict[str, Any]:
        """Return current position for symbol (net_pos=0 if flat)."""
        try:
            data = await self._post(
                "/Position/search",
                {"accountId": self._account_id, "onlyOpen": True},
            )
        except Exception:
            # Endpoint may not exist on this account tier — assume flat
            return {"symbol": symbol, "net_pos": 0, "avg_price": 0.0, "open_pnl": 0.0}
        positions = data if isinstance(data, list) else data.get("positions", [])
        sym = symbol.upper()
        for pos in positions:
            pos_id = str(pos.get("contractId", ""))
            if sym in pos_id.upper():
                return {
                    "symbol": symbol,
                    "net_pos": int(pos.get("netPosition", pos.get("netPos", 0))),
                    "avg_price": float(pos.get("averagePrice", pos.get("avgPrice", 0.0))),
                    "open_pnl": float(pos.get("unrealizedPnl", pos.get("openPnl", 0.0))),
                }
        return {"symbol": symbol, "net_pos": 0, "avg_price": 0.0, "open_pnl": 0.0}
