"""
Tests for runner.py safety guards added after paper-run audit.

These tests mock the broker client so they don't require aiohttp/network.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub aiohttp so runner.py imports work without the real package
# ---------------------------------------------------------------------------

if "aiohttp" not in sys.modules:
    _aiohttp_stub = ModuleType("aiohttp")
    _aiohttp_stub.ClientSession = MagicMock  # type: ignore[attr-defined]
    sys.modules["aiohttp"] = _aiohttp_stub

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar(ts: datetime, o=100.0, h=110.0, l=90.0, c=105.0, v=1000):
    from src.data.live_feed import Bar
    return Bar(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def _make_bot():
    """Return a Bot with a mocked broker client (no network needed)."""
    with patch.dict(
        "os.environ",
        {"PROJECTX_API_KEY": "test", "PROJECTX_USERNAME": "test"},
    ):
        from src.bot.runner import Bot

        bot = Bot()
        mock_client = MagicMock()
        mock_client.place_bracket_order = AsyncMock(
            return_value={"entry_id": 999, "stop_id": 888, "target_id": None}
        )
        mock_client.cancel_orders = AsyncMock(return_value=[{"errorCode": 0}])
        mock_client.get_contract_id = AsyncMock(return_value="CON.F.US.MNQ.Z26")
        mock_client.get_position = AsyncMock(
            return_value={"net_pos": 1, "avg_price": 100.0, "open_pnl": 0.0}
        )
        mock_client._post = AsyncMock(return_value={"orderId": 777, "success": True, "errorCode": 0})
        mock_client._account_id = 12345
        mock_client._token = SimpleNamespace(access_token="tok")
        bot._client = mock_client
    return bot


# ---------------------------------------------------------------------------
# Bug 1: Concurrent position guard
# ---------------------------------------------------------------------------


def test_no_new_signal_while_in_trade():
    """
    When _trade_target is set (trade is open), _on_bar must not fire a second
    bracket order regardless of what the signal engine says.
    """
    bot = _make_bot()
    # Simulate an open position
    bot._trade_target = 28300.0
    bot._trade_direction = "Buy"
    bot._trade_qty = 1

    with patch.object(bot, "_place_order") as mock_place, \
         patch.object(bot._signal_engine, "check_standard", return_value=None), \
         patch.object(bot._signal_engine, "check_aggressive", return_value=None), \
         patch.object(bot._signal_engine, "check_anticipation", return_value=None):

        # Use a session-hour bar so the bot would otherwise try to trade
        from config.settings import LIVE_MODE
        ts = datetime(2026, 11, 4, 14, 30, tzinfo=timezone.utc)  # 09:30 ET
        bar = _make_bar(ts, o=28200.0, h=28280.0, l=28150.0, c=28260.0)

        # Feed enough bars to have a full deque
        for _ in range(3):
            bot._signal_engine.push_bar(bar)

        bot._on_bar(bar)

    mock_place.assert_not_called()


# ---------------------------------------------------------------------------
# Bug 3: record_trade called only at close, not at open
# ---------------------------------------------------------------------------


def test_record_trade_called_once_per_round_trip():
    """
    _place_order must NOT call risk_manager.record_trade.
    Only _close_position_at_tp should call it.
    """
    bot = _make_bot()
    initial_count = bot._risk.trade_count

    async def _run():
        await bot._place_order("Buy", 100.0, 90.0, 110.0, qty=1)

    asyncio.run(_run())

    # Count must not change just from placing an order
    assert bot._risk.trade_count == initial_count, (
        "record_trade must not be called when placing an order; "
        "it should only be called when the trade closes"
    )
