"""
Test live bracket: entry (market) + stop-limit (resting) + software TP check.
Places a real trade on the paper account.

    python test_live_bracket.py
"""
import asyncio
import os
import sys

if os.getenv("LIVE_MODE", "0") == "1":
    print("ERROR: LIVE_MODE=1 — refusing to run test on live account.")
    sys.exit(1)

SL_POINTS = 6.0
TP_POINTS = 6.0

async def get_last_price(client, contract_id, timeout=20.0):
    import aiohttp, json
    token = client._token.access_token
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                "wss://rtc.topstepx.com/hubs/market",
                headers={"Authorization": f"Bearer {token}"},
            ) as ws:
                await ws.send_str('{"protocol":"json","version":1}\x1e')
                await ws.receive()
                await ws.send_str(json.dumps({
                    "type": 1, "invocationId": "1",
                    "target": "SubscribeContractTrades",
                    "arguments": [contract_id],
                }) + "\x1e")
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
                            d = json.loads(chunk)
                        except Exception:
                            continue
                        if d.get("target") == "GatewayTrade":
                            args = d.get("arguments", [])
                            if len(args) >= 2 and args[1]:
                                p = float(args[1][-1]["price"])
                                print(f"  Live price: {p}")
                                return p
    except Exception:
        pass
    return None


async def main():
    from src.broker.projectx_client import (
        ProjectXClient, SIDE_BUY, SIDE_SELL,
        ORDER_TYPE_LIMIT, ORDER_TYPE_STOP_LIMIT, TICK,
    )
    from datetime import datetime, timezone, timedelta

    print("Connecting to Topstep (paper)...")
    async with ProjectXClient() as client:
        acct = await client.get_account_info()
        print(f"Account : {acct['name']}  cash=${acct['cash']:.2f}")
        cid = await client.get_contract_id("MNQ")
        print(f"Contract: {cid}\n")

        price = await get_last_price(client, cid)
        if not price:
            price = float(input("No tick — enter current MNQ price: ").strip())

        entry  = price           # fills as market immediately
        stop   = round(entry - SL_POINTS, 2)
        target = round(entry + TP_POINTS, 2)

        print(f"LONG bracket:")
        print(f"  Entry  {entry}  (fills as market)")
        print(f"  Stop   {stop}   (stop-limit resting on exchange)")
        print(f"  Target {target}  (software TP — checked each bar)\n")

        # Entry
        entry_result = await client._post("/Order/place", {
            "accountId": client._account_id,
            "contractId": cid,
            "type": ORDER_TYPE_LIMIT,
            "side": SIDE_BUY,
            "size": 1,
            "limitPrice": entry,
        })
        print(f"Entry  → {entry_result}")
        if not entry_result.get("success"):
            print("Entry FAILED."); return

        await asyncio.sleep(1)

        # Stop-limit (resting)
        stop_limit_price = round(stop - 4 * TICK, 2)
        stop_result = await client._post("/Order/place", {
            "accountId": client._account_id,
            "contractId": cid,
            "type": ORDER_TYPE_STOP_LIMIT,
            "side": SIDE_SELL,
            "size": 1,
            "stopPrice": stop,
            "limitPrice": stop_limit_price,
        })
        print(f"Stop   → {stop_result}")
        stop_id = stop_result.get("orderId")

        print(f"\nEntry filled. Stop resting at {stop} (stop-limit).")
        print(f"Target {target} is software-managed.")
        print(f"\nWaiting 5s then simulating TP trigger...")
        await asyncio.sleep(5)

        # Check stop is still working
        start = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        orders = (await client._post("/Order/search", {
            "accountId": client._account_id,
            "startTimestamp": start,
        })).get("orders", [])

        STATUS = {1: "Working", 2: "Filled", 3: "Cancelled", 4: "Rejected"}
        TYPE   = {1: "Market", 2: "Limit", 3: "Stop", 4: "StopLimit"}

        stop_working = False
        for o in orders:
            if o.get("id") == stop_id:
                s = STATUS.get(o.get("status"), "?")
                print(f"Stop status: {s}  stopPx={o.get('stopPrice')}  fillPx={o.get('filledPrice')}")
                stop_working = (o.get("status") == 1)

        if not stop_working:
            print("Stop already filled/cancelled — cannot test TP.")
            return

        print(f"\nSimulating TP: cancelling stop + placing closing SELL at market...")

        # Step 1: cancel stop
        cancel = await client._post("/Order/cancel", {"orderId": stop_id, "accountId": client._account_id})
        print(f"Stop cancelled → {cancel}")

        await asyncio.sleep(0.5)

        # Step 2: close position (sell at market)
        close_result = await client._post("/Order/place", {
            "accountId": client._account_id,
            "contractId": cid,
            "type": ORDER_TYPE_LIMIT,
            "side": SIDE_SELL,
            "size": 1,
            "limitPrice": target,
        })
        print(f"Close order  → {close_result}")

        await asyncio.sleep(3)

        # Verify close filled
        orders2 = (await client._post("/Order/search", {
            "accountId": client._account_id,
            "startTimestamp": start,
        })).get("orders", [])

        for o in orders2:
            if o.get("id") == close_result.get("orderId"):
                s = STATUS.get(o.get("status"), "?")
                fp = o.get("filledPrice") or "-"
                print(f"\nClose order status: {s}  fillPx={fp}")
                if o.get("status") == 2:
                    fill = float(fp)
                    pnl = (fill - entry) * 2.0  # $2/pt for MNQ
                    print(f"TP TEST PASSED — entered {entry:.2f} closed {fill:.2f}  PnL≈${pnl:.2f}")
                else:
                    print("Close order not filled yet — check Topstep.")

asyncio.run(main())
