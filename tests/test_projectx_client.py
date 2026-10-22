"""
Tests for ProjectXClient — all HTTP calls are mocked.
"""
from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(json_data, status=200):
    """Return a mock aiohttp response context manager."""
    resp = AsyncMock()
    resp.status = status
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(return_value=json_data)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_delete_response(status=204):
    resp = AsyncMock()
    resp.status = status
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(return_value={})
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("PROJECTX_API_KEY", "test-api-key-abc")
    monkeypatch.delenv("PROJECTX_USERNAME", raising=False)
    monkeypatch.delenv("PROJECTX_PASSWORD", raising=False)


@pytest.fixture()
def client():
    # Import after env vars are set
    from src.broker.projectx_client import ProjectXClient
    return ProjectXClient()


# ---------------------------------------------------------------------------
# Construction / auth
# ---------------------------------------------------------------------------

def test_client_init_with_api_key():
    from src.broker.projectx_client import ProjectXClient
    c = ProjectXClient()
    assert c._api_key == "test-api-key-abc"


def test_client_init_with_username_password(monkeypatch):
    monkeypatch.delenv("PROJECTX_API_KEY", raising=False)
    monkeypatch.setenv("PROJECTX_USERNAME", "user")
    monkeypatch.setenv("PROJECTX_PASSWORD", "pass")
    from src.broker.projectx_client import ProjectXClient
    c = ProjectXClient()
    assert c._username == "user"
    assert c._password == "pass"


def test_client_init_no_credentials(monkeypatch):
    monkeypatch.delenv("PROJECTX_API_KEY", raising=False)
    monkeypatch.delenv("PROJECTX_USERNAME", raising=False)
    monkeypatch.delenv("PROJECTX_PASSWORD", raising=False)
    from src.broker.projectx_client import ProjectXClient
    with pytest.raises(RuntimeError, match="PROJECTX_API_KEY"):
        ProjectXClient()


def test_api_key_headers(client):
    headers = client._headers()
    assert headers == {"X-API-Key": "test-api-key-abc"}


@pytest.mark.asyncio
async def test_authenticate_with_username_password(monkeypatch):
    monkeypatch.delenv("PROJECTX_API_KEY", raising=False)
    monkeypatch.setenv("PROJECTX_USERNAME", "user")
    monkeypatch.setenv("PROJECTX_PASSWORD", "pass")
    from src.broker.projectx_client import ProjectXClient
    c = ProjectXClient()
    c._session = MagicMock()
    c._session.post = MagicMock(return_value=_make_response({"token": "tok123"}))
    await c.authenticate()
    assert c._token is not None
    assert c._token.access_token == "tok123"


@pytest.mark.asyncio
async def test_authenticate_raises_on_missing_token(monkeypatch):
    monkeypatch.delenv("PROJECTX_API_KEY", raising=False)
    monkeypatch.setenv("PROJECTX_USERNAME", "user")
    monkeypatch.setenv("PROJECTX_PASSWORD", "pass")
    from src.broker.projectx_client import ProjectXClient
    c = ProjectXClient()
    c._session = MagicMock()
    c._session.post = MagicMock(return_value=_make_response({"error": "bad creds"}))
    with pytest.raises(RuntimeError, match="no token"):
        await c.authenticate()


# ---------------------------------------------------------------------------
# Token expiry
# ---------------------------------------------------------------------------

def test_token_not_expired():
    from src.broker.projectx_client import _Token
    t = _Token(access_token="x")
    assert not t.is_expired()


def test_token_expired():
    from src.broker.projectx_client import _Token, TOKEN_TTL_SECONDS
    t = _Token(access_token="x", issued_at=time.time() - TOKEN_TTL_SECONDS - 1)
    assert t.is_expired()


# ---------------------------------------------------------------------------
# get_account_info
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_account_info_list(client):
    accounts_data = [{"id": 42, "name": "Eval-1", "balance": 50000.0, "dailyPnl": -120.5}]
    client._session = MagicMock()
    client._session.get = MagicMock(return_value=_make_response(accounts_data))
    result = await client.get_account_info()
    assert result["account_id"] == 42
    assert result["name"] == "Eval-1"
    assert result["cash"] == 50000.0
    assert result["daily_pnl"] == -120.5
    assert client._account_id == 42


@pytest.mark.asyncio
async def test_get_account_info_wrapped(client):
    accounts_data = {"accounts": [{"id": 7, "name": "Paper", "balance": 10000.0}]}
    client._session = MagicMock()
    client._session.get = MagicMock(return_value=_make_response(accounts_data))
    result = await client.get_account_info()
    assert result["account_id"] == 7


@pytest.mark.asyncio
async def test_get_account_info_empty_raises(client):
    client._session = MagicMock()
    client._session.get = MagicMock(return_value=_make_response([]))
    with pytest.raises(RuntimeError, match="No ProjectX accounts"):
        await client.get_account_info()


# ---------------------------------------------------------------------------
# place_bracket_order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_place_bracket_order_returns_order_id(client):
    client._session = MagicMock()
    client._session.post = MagicMock(return_value=_make_response({"orderId": 999}))
    oid = await client.place_bracket_order(
        symbol="MES",
        direction="Buy",
        qty=1,
        entry_price=5000.0,
        stop_price=4990.0,
        target_price=5010.0,
    )
    assert oid == 999


@pytest.mark.asyncio
async def test_place_bracket_order_uses_id_key(client):
    client._session = MagicMock()
    client._session.post = MagicMock(return_value=_make_response({"id": 555}))
    oid = await client.place_bracket_order("MES", "Sell", 1, 5000.0, 5010.0, 4990.0)
    assert oid == 555


@pytest.mark.asyncio
async def test_place_bracket_order_raises_if_no_id(client):
    client._session = MagicMock()
    client._session.post = MagicMock(return_value=_make_response({"status": "ok"}))
    with pytest.raises(RuntimeError, match="no id"):
        await client.place_bracket_order("MES", "Buy", 1, 5000.0, 4990.0, 5010.0)


@pytest.mark.asyncio
async def test_place_bracket_order_includes_account_id(client):
    client._account_id = 42
    posted_body: list = []

    async def fake_post(url, headers=None, json=None):
        posted_body.append(json)
        return _make_response({"orderId": 1}).__aenter__.return_value

    # Patch _post directly to capture payload
    async def mock_post(path, body):
        posted_body.append(body)
        return {"orderId": 1}

    client._post = mock_post  # type: ignore[method-assign]
    oid = await client.place_bracket_order("MES", "Buy", 1, 5000.0, 4990.0, 5010.0)
    assert oid == 1
    assert posted_body[0]["accountId"] == 42


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_order(client):
    client._session = MagicMock()
    client._session.delete = MagicMock(return_value=_make_delete_response(204))
    # Should not raise
    await client.cancel_order(123)


# ---------------------------------------------------------------------------
# get_position
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_position_found(client):
    positions = [
        {"symbol": "MES", "netPosition": 2, "averagePrice": 5001.0, "unrealizedPnl": 50.0}
    ]
    client._session = MagicMock()
    client._session.get = MagicMock(return_value=_make_response(positions))
    pos = await client.get_position("MES")
    assert pos["net_pos"] == 2
    assert pos["avg_price"] == 5001.0
    assert pos["open_pnl"] == 50.0


@pytest.mark.asyncio
async def test_get_position_not_found_returns_zero(client):
    client._session = MagicMock()
    client._session.get = MagicMock(return_value=_make_response([]))
    pos = await client.get_position("MES")
    assert pos["net_pos"] == 0
    assert pos["avg_price"] == 0.0


@pytest.mark.asyncio
async def test_get_position_wrapped_key(client):
    data = {"positions": [{"symbol": "MNQ", "netPosition": -1, "averagePrice": 18000.0}]}
    client._session = MagicMock()
    client._session.get = MagicMock(return_value=_make_response(data))
    pos = await client.get_position("MNQ")
    assert pos["net_pos"] == -1


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_manager():
    import aiohttp as _aiohttp
    from src.broker.projectx_client import ProjectXClient
    with patch.object(_aiohttp, "ClientSession") as MockSession:
        mock_sess = AsyncMock()
        mock_sess.close = AsyncMock()
        MockSession.return_value = mock_sess
        c = ProjectXClient()
        async with c:
            assert c._session is not None
        mock_sess.close.assert_called_once()
