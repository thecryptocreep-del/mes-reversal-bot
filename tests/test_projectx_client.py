"""
Tests for ProjectXClient — all HTTP calls are mocked.
Auth: userName + apiKey → POST /Auth/loginKey → bearer token
Accounts: POST /Account/search
Contracts: POST /Contract/available
Orders: POST /Order/place
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(json_data, status=200):
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


AUTH_OK = {"token": "test-bearer-token", "success": True, "errorCode": 0, "errorMessage": None}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def set_credentials(monkeypatch):
    monkeypatch.setenv("PROJECTX_API_KEY", "test-api-key-abc")
    monkeypatch.setenv("PROJECTX_USERNAME", "testuser")


@pytest.fixture()
def client():
    from src.broker.projectx_client import ProjectXClient, _Token
    c = ProjectXClient()
    c._token = _Token(access_token="test-bearer-token")
    c._session = MagicMock()
    return c


# ---------------------------------------------------------------------------
# Construction / auth
# ---------------------------------------------------------------------------

def test_client_init_with_credentials():
    from src.broker.projectx_client import ProjectXClient
    c = ProjectXClient()
    assert c._api_key == "test-api-key-abc"
    assert c._username == "testuser"


def test_client_init_missing_api_key(monkeypatch):
    monkeypatch.delenv("PROJECTX_API_KEY", raising=False)
    from src.broker.projectx_client import ProjectXClient
    with pytest.raises(RuntimeError, match="PROJECTX_API_KEY"):
        ProjectXClient()


def test_client_init_missing_username(monkeypatch):
    monkeypatch.delenv("PROJECTX_USERNAME", raising=False)
    from src.broker.projectx_client import ProjectXClient
    with pytest.raises(RuntimeError, match="PROJECTX_USERNAME"):
        ProjectXClient()


def test_bearer_headers(client):
    headers = client._headers()
    assert headers == {"Authorization": "Bearer test-bearer-token"}


# ---------------------------------------------------------------------------
# authenticate — POST /Auth/loginKey
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_authenticate_success():
    from src.broker.projectx_client import ProjectXClient
    c = ProjectXClient()
    c._session = MagicMock()
    c._session.post = MagicMock(return_value=_make_response(AUTH_OK))
    await c.authenticate()
    assert c._token is not None
    assert c._token.access_token == "test-bearer-token"


@pytest.mark.asyncio
async def test_authenticate_invalid_credentials():
    from src.broker.projectx_client import ProjectXClient
    c = ProjectXClient()
    c._session = MagicMock()
    c._session.post = MagicMock(
        return_value=_make_response({"token": None, "success": False, "errorCode": 3})
    )
    with pytest.raises(RuntimeError, match="errorCode=3"):
        await c.authenticate()


@pytest.mark.asyncio
async def test_authenticate_agreements_not_signed():
    from src.broker.projectx_client import ProjectXClient
    c = ProjectXClient()
    c._session = MagicMock()
    c._session.post = MagicMock(
        return_value=_make_response({"token": None, "success": False, "errorCode": 7})
    )
    with pytest.raises(RuntimeError, match="agreements"):
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
# get_account_info — POST /Account/search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_account_info_list(client):
    accounts_data = [{"id": 42, "name": "Eval-1", "balance": 50000.0, "dailyPnl": -120.5}]
    client._session.post = MagicMock(return_value=_make_response(accounts_data))
    result = await client.get_account_info()
    assert result["account_id"] == 42
    assert result["name"] == "Eval-1"
    assert result["cash"] == 50000.0
    assert result["daily_pnl"] == -120.5
    assert client._account_id == 42


@pytest.mark.asyncio
async def test_get_account_info_wrapped(client):
    accounts_data = {"accounts": [{"id": 7, "name": "Paper", "balance": 10000.0}]}
    client._session.post = MagicMock(return_value=_make_response(accounts_data))
    result = await client.get_account_info()
    assert result["account_id"] == 7


@pytest.mark.asyncio
async def test_get_account_info_empty_raises(client):
    client._session.post = MagicMock(return_value=_make_response([]))
    with pytest.raises(RuntimeError, match="No active"):
        await client.get_account_info()


# ---------------------------------------------------------------------------
# get_contract_id — POST /Contract/available
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_contract_id_found(client):
    contracts_data = [
        {"id": "CON.F.US.MNQ.Z25", "name": "Micro E-mini Nasdaq MNQ Dec 2025"},
        {"id": "CON.F.US.ES.Z25", "name": "E-mini S&P 500 ES Dec 2025"},
    ]
    client._session.post = MagicMock(return_value=_make_response(contracts_data))
    cid = await client.get_contract_id("MNQ")
    assert cid == "CON.F.US.MNQ.Z25"


@pytest.mark.asyncio
async def test_get_contract_id_wrapped(client):
    data = {"contracts": [{"id": "CON.F.US.MNQ.Z25", "name": "MNQ Dec 2025"}]}
    client._session.post = MagicMock(return_value=_make_response(data))
    cid = await client.get_contract_id("MNQ")
    assert cid == "CON.F.US.MNQ.Z25"


@pytest.mark.asyncio
async def test_get_contract_id_cached(client):
    client._contract_cache["MNQ"] = "CON.F.US.MNQ.Z25"
    # Should not call the API at all
    client._session.post = MagicMock(side_effect=AssertionError("Should not call API"))
    cid = await client.get_contract_id("MNQ")
    assert cid == "CON.F.US.MNQ.Z25"


@pytest.mark.asyncio
async def test_get_contract_id_not_found_raises(client):
    client._session.post = MagicMock(return_value=_make_response([]))
    with pytest.raises(RuntimeError, match="not found"):
        await client.get_contract_id("UNKNOWN")


# ---------------------------------------------------------------------------
# place_bracket_order — POST /Order/place (x3: entry + stop + target)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_place_bracket_order_returns_order_id(client):
    client._account_id = 42
    client._contract_cache["MNQ"] = "CON.F.US.MNQ.Z25"
    client._session.post = MagicMock(return_value=_make_response({"orderId": 999, "success": True}))
    oid = await client.place_bracket_order(
        symbol="MNQ", direction="Buy", qty=1,
        entry_price=20000.0, stop_price=19960.0, target_price=20060.0,
    )
    assert oid == 999


@pytest.mark.asyncio
async def test_place_bracket_order_uses_id_key(client):
    client._account_id = 42
    client._contract_cache["MNQ"] = "CON.F.US.MNQ.Z25"
    client._session.post = MagicMock(return_value=_make_response({"id": 555, "success": True}))
    oid = await client.place_bracket_order("MNQ", "Sell", 1, 20000.0, 20040.0, 19940.0)
    assert oid == 555


@pytest.mark.asyncio
async def test_place_bracket_order_raises_if_no_id(client):
    client._account_id = 42
    client._contract_cache["MNQ"] = "CON.F.US.MNQ.Z25"
    client._session.post = MagicMock(return_value=_make_response({"status": "ok"}))
    with pytest.raises(RuntimeError, match="no id"):
        await client.place_bracket_order("MNQ", "Buy", 1, 20000.0, 19960.0, 20060.0)


@pytest.mark.asyncio
async def test_place_bracket_order_includes_account_id(client):
    client._account_id = 42
    posted_bodies: list = []

    async def mock_post(path, body):
        posted_bodies.append((path, body))
        return {"orderId": 1, "success": True}

    client._post = mock_post  # type: ignore[method-assign]
    client._contract_cache["MNQ"] = "CON.F.US.MNQ.Z25"
    oid = await client.place_bracket_order("MNQ", "Buy", 1, 20000.0, 19960.0, 20060.0)
    assert oid == 1
    assert all(b["accountId"] == 42 for _, b in posted_bodies)


@pytest.mark.asyncio
async def test_place_bracket_order_places_three_orders(client):
    client._account_id = 42
    call_paths: list = []

    async def mock_post(path, body):
        call_paths.append(path)
        return {"orderId": 1, "success": True}

    client._post = mock_post  # type: ignore[method-assign]
    client._contract_cache["MNQ"] = "CON.F.US.MNQ.Z25"
    await client.place_bracket_order("MNQ", "Buy", 1, 20000.0, 19960.0, 20060.0)
    assert call_paths.count("/Order/place") == 3


@pytest.mark.asyncio
async def test_place_bracket_order_buy_side_codes(client):
    client._account_id = 42
    bodies: list = []

    async def mock_post(path, body):
        bodies.append(body)
        return {"orderId": 1, "success": True}

    client._post = mock_post  # type: ignore[method-assign]
    client._contract_cache["MNQ"] = "CON.F.US.MNQ.Z25"
    await client.place_bracket_order("MNQ", "Buy", 1, 20000.0, 19960.0, 20060.0)
    from src.broker.projectx_client import SIDE_BUY, SIDE_SELL
    assert bodies[0]["side"] == SIDE_BUY    # entry
    assert bodies[1]["side"] == SIDE_SELL   # stop exit
    assert bodies[2]["side"] == SIDE_SELL   # target exit


@pytest.mark.asyncio
async def test_place_bracket_order_sell_side_codes(client):
    client._account_id = 42
    bodies: list = []

    async def mock_post(path, body):
        bodies.append(body)
        return {"orderId": 2, "success": True}

    client._post = mock_post  # type: ignore[method-assign]
    client._contract_cache["MNQ"] = "CON.F.US.MNQ.Z25"
    await client.place_bracket_order("MNQ", "Sell", 1, 20000.0, 20040.0, 19940.0)
    from src.broker.projectx_client import SIDE_BUY, SIDE_SELL
    assert bodies[0]["side"] == SIDE_SELL   # entry
    assert bodies[1]["side"] == SIDE_BUY    # stop exit
    assert bodies[2]["side"] == SIDE_BUY    # target exit


# ---------------------------------------------------------------------------
# cancel_order — POST /Order/cancel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_order(client):
    client._session.post = MagicMock(return_value=_make_response({"success": True}))
    await client.cancel_order(123)
    call_args = client._session.post.call_args
    assert "/Order/cancel" in call_args[0][0]


# ---------------------------------------------------------------------------
# get_position — POST /Position/search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_position_found(client):
    positions = [
        {"contractId": "CON.F.US.MNQ.Z25", "netPosition": 2, "averagePrice": 20001.0, "unrealizedPnl": 50.0}
    ]
    client._session.post = MagicMock(return_value=_make_response(positions))
    pos = await client.get_position("MNQ")
    assert pos["net_pos"] == 2
    assert pos["avg_price"] == 20001.0
    assert pos["open_pnl"] == 50.0


@pytest.mark.asyncio
async def test_get_position_not_found_returns_zero(client):
    client._session.post = MagicMock(return_value=_make_response([]))
    pos = await client.get_position("MNQ")
    assert pos["net_pos"] == 0
    assert pos["avg_price"] == 0.0


@pytest.mark.asyncio
async def test_get_position_wrapped_key(client):
    data = {"positions": [{"contractId": "CON.F.US.MNQ.Z25", "netPosition": -1, "averagePrice": 18000.0}]}
    client._session.post = MagicMock(return_value=_make_response(data))
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
        mock_sess.post = MagicMock(return_value=_make_response(AUTH_OK))
        MockSession.return_value = mock_sess
        c = ProjectXClient()
        async with c:
            assert c._session is not None
        mock_sess.close.assert_called_once()
