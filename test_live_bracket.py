"""
Place a REAL bracket order at current market price to verify end-to-end.
Uses 12-point SL and 12-point TP. Paper account only.

    python test_live_bracket.py
"""
import asyncio
import os
import sys

# Must run on paper account
if os.getenv("LIVE_MODE", "0") == "1":
    print("ERROR: LIVE_MODE=1 — refusing to run test on live account.")
    sys.exit(1)

async def get_last_price(client, contract_id: str, timeout: float = 20.0) -> float:
    """Subscribe to GatewayTrade for a few seconds and grab the last price."""
    import aiohttp
    import json

    token = client._token.access_token
    ws_url = "wss://rtc.topstepx.com/hubs/market"
    last_price = None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                ws_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientWSTimeout(ws_close=timeout),
            ) as ws:
                # SignalR handshake
                await ws.send_str('{"protocol":"json","version":1}\x1e')
                await ws.receive()  # handshake ack

                # Subscribe to trades
                sub = json.dumps({
                    "type": 1,
                    "invocationId": "1",
                    "target": "SubscribeContractTrades",
                    "arguments": [contract_id],
                }) + "\x1e"
                await ws.send_str(sub)

                deadline = asyncio.get_event_loop().time() + timeout
                async for msg in ws:
                    if asyncio.get_event_loop().time() > deadline:
                        break
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    for chunk in msg.data.split("\x1e"):
                        if not chunk.strip():
                            continue
                        try:
                            data = json.loads(chunk)
                        except Exception:
                            continue
                        if data.get("target") == "GatewayTrade":
                            args = data.get("arguments", [])
                            if len(args) >= 2 and args[1]:
                                ticks = args[1]
                                if isinstance(ticks, list) and ticks:
                                    last_price = float(ticks[-1].get("price", 0))
                                    print(f"  Got live price: {last_price}")
                                    return last_price
    except asyncio.TimeoutError:
        pass

    return last_price


async def main():
    from src.broker.projectx_client import ProjectXClient, SIDE_BUY, SIDE_SELL, ORDER_TYPE_LIMIT

    SL_POINTS = 12.0
    TP_POINTS = 12.0

    print("Connecting to Topstep (paper account)...")
    async with ProjectXClient() as client:
        acct = await client.get_account_info()
        print(f"Account: {acct['name']}  cash=${acct['cash']:.2f}")

        contract_id = await client.get_contract_id("MNQ")
        print(f"Contract: {contract_id}")

        print(f"\nFetching live price (waiting up to 20s for a tick)...")
        price = await get_last_price(client, contract_id)

        if not price:
            print("ERROR: No price tick received. Is the market open/session active?")
            print("Try again during market hours or paste the current MNQ price:")
            raw = input("Enter current MNQ price: ").strip()
            price = float(raw)

        direction = "Buy"  # long bracket
        side = SIDE_BUY
        exit_side = SIDE_SELL

        # Entry: 2 ticks above current price (aggressive fill)
        entry = round(price + 0.50, 2)
        stop  = round(entry - SL_POINTS, 2)
        target = round(entry + TP_POINTS, 2)

        print(f"\nPlacing LONG bracket:")
        print(f"  Entry  : {entry}  (2 ticks above {price})")
        print(f"  Stop   : {stop}   ({SL_POINTS} pts below entry)")
        print(f"  Target : {target}  ({TP_POINTS} pts above entry)")
        print(f"  Qty    : 1 contract\n")

        # --- Entry ---
        entry_body = {
            "accountId": client._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_LIMIT,
            "side": side,
            "size": 1,
            "limitPrice": entry,
        }
        result = await client._post("/Order/place", entry_body)
        print(f"Entry  → {result}")
        if not result.get("success"):
            print("Entry order FAILED. Check output above.")
            return

        order_id = result["orderId"]
        print(f"Entry orderId={order_id} ✓")

        await asyncio.sleep(1)

        # --- Stop ---
        stop_body = {
            "accountId": client._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_LIMIT,
            "side": exit_side,
            "size": 1,
            "limitPrice": stop,
        }
        stop_result = await client._post("/Order/place", stop_body)
        print(f"Stop   → {stop_result}")

        # --- Target ---
        target_body = {
            "accountId": client._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_LIMIT,
            "side": exit_side,
            "size": 1,
            "limitPrice": target,
        }
        target_result = await client._post("/Order/place", target_body)
        print(f"Target → {target_result}")

        print("\n--- DONE ---")
        print("Check Topstep web app — you should see 3 orders (entry/stop/target).")
        print("If entry fills, watch PnL move. One of stop/target will close the trade.")

asyncio.run(main())
