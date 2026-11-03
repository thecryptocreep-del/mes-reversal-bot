"""
Test if SELL stop-limit with stopPrice ABOVE market rests as a take-profit.
Also tests BUY stop-limit with stopPrice BELOW market as short take-profit.

    python test_tp_stoplimit.py
"""
import asyncio

async def get_price(client, contract_id):
    import aiohttp, json
    token = client._token.access_token
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(
            "wss://rtc.topstepx.com/hubs/market",
            headers={"Authorization": f"Bearer {token}"},
        ) as ws:
            await ws.send_str('{"protocol":"json","version":1}\x1e')
            await ws.receive()
            await ws.send_str(json.dumps({"type":1,"invocationId":"1","target":"SubscribeContractTrades","arguments":[contract_id]})+"\x1e")
            async for msg in ws:
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
                            return float(args[1][-1]["price"])

async def main():
    from src.broker.projectx_client import ProjectXClient, SIDE_BUY, SIDE_SELL, ORDER_TYPE_STOP_LIMIT

    async with ProjectXClient() as client:
        acct = await client.get_account_info()
        print(f"Account: {acct['name']}  cash=${acct['cash']:.2f}")
        cid = await client.get_contract_id("MNQ")

        price = await get_price(client, cid)
        print(f"Live price: {price}\n")

        tp_above = round(price + 20, 2)  # 20pts above — shouldn't fill
        sl_below = round(price - 20, 2)  # 20pts below — shouldn't fill

        # Test 1: SELL stop-limit with stopPrice ABOVE market (long take-profit)
        print(f"Test 1: SELL stop-limit stopPrice={tp_above} (20pts above market {price})...")
        b1 = {
            "accountId": client._account_id,
            "contractId": cid,
            "type": ORDER_TYPE_STOP_LIMIT,
            "side": SIDE_SELL,
            "size": 1,
            "stopPrice": tp_above,
            "limitPrice": round(tp_above - 1, 2),
        }
        r1 = await client._post("/Order/place", b1)
        print(f"  → {r1}")
        await asyncio.sleep(3)
        # Check if it's still resting or filled
        from datetime import datetime, timezone, timedelta
        result = await client._post("/Order/search", {
            "accountId": client._account_id,
            "startTimestamp": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        })
        orders = result.get("orders", [])
        STATUS = {1: "Working", 2: "Filled", 3: "Cancelled"}
        for o in orders:
            if o.get("id") == r1.get("orderId"):
                print(f"  Status after 3s: {STATUS.get(o.get('status'), o.get('status'))} fillPx={o.get('filledPrice')}")
        if r1.get("orderId") and r1.get("success"):
            await client._post("/Order/cancel", {"orderId": r1["orderId"], "accountId": client._account_id})
            print(f"  Cancelled.")

        print()

        # Test 2: BUY stop-limit with stopPrice BELOW market (short take-profit)
        print(f"Test 2: BUY stop-limit stopPrice={sl_below} (20pts below market {price})...")
        b2 = {
            "accountId": client._account_id,
            "contractId": cid,
            "type": ORDER_TYPE_STOP_LIMIT,
            "side": SIDE_BUY,
            "size": 1,
            "stopPrice": sl_below,
            "limitPrice": round(sl_below + 1, 2),
        }
        r2 = await client._post("/Order/place", b2)
        print(f"  → {r2}")
        await asyncio.sleep(3)
        for o in (await client._post("/Order/search", {
            "accountId": client._account_id,
            "startTimestamp": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        })).get("orders", []):
            if o.get("id") == r2.get("orderId"):
                print(f"  Status after 3s: {STATUS.get(o.get('status'), o.get('status'))} fillPx={o.get('filledPrice')}")
        if r2.get("orderId") and r2.get("success"):
            await client._post("/Order/cancel", {"orderId": r2["orderId"], "accountId": client._account_id})
            print(f"  Cancelled.")

asyncio.run(main())
