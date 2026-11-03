"""
Test Topstep native bracket/OCO — check if child orders are created.

    python test_oco.py
"""
import asyncio
import aiohttp

async def main():
    from src.broker.projectx_client import ProjectXClient, ORDER_TYPE_LIMIT, SIDE_BUY, SIDE_SELL, _BASE

    async with ProjectXClient() as client:
        acct = await client.get_account_info()
        print(f"Account: {acct['name']}  cash=${acct['cash']:.2f}\n")
        contract_id = await client.get_contract_id("MNQ")

        # Place one bracket order with stopLoss + takeProfit
        print("Placing bracket with stopLoss + takeProfit...")
        body = {
            "accountId": client._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_LIMIT,
            "side": SIDE_BUY,
            "size": 1,
            "limitPrice": 1000.0,   # far below market, won't fill
            "stopLoss": 988.0,
            "takeProfit": 1012.0,
        }
        result = await client._post("/Order/place", body)
        print(f"Entry order → {result}")
        entry_id = result.get("orderId")
        if not entry_id:
            print("Order failed — stopping.")
            return

        await asyncio.sleep(1)

        # Fetch order detail to see if bracket legs appear
        print(f"\nFetching order detail for orderId={entry_id}...")
        for path in [
            f"/Order/{entry_id}",
            f"/Order/get/{entry_id}",
        ]:
            try:
                detail = await client._post(path, {"accountId": client._account_id})
                print(f"  {path} → {detail}")
            except Exception as e:
                try:
                    # try GET
                    async with client._session.get(
                        f"{_BASE}{path}",
                        headers=client._headers(),
                        params={"accountId": client._account_id},
                    ) as resp:
                        data = await resp.json()
                    print(f"  GET {path} → {data}")
                except Exception as e2:
                    print(f"  {path} → {e} / {e2}")

        # Search all open orders to see if child legs appeared
        print("\nSearching open orders (looking for child bracket legs)...")
        for body2 in [
            {"accountId": client._account_id, "startTimestamp": "2000-01-01T00:00:00Z"},
            {"accountId": client._account_id, "linkedOrderId": entry_id},
        ]:
            try:
                orders = await client._post("/Order/search", body2)
                print(f"  search {list(body2.keys())} → {orders}")
            except Exception as e:
                print(f"  search {list(body2.keys())} → {e}")

        # Cancel the entry
        print(f"\nCancelling entry orderId={entry_id}...")
        cancel = await client._post("/Order/cancel", {"orderId": entry_id, "accountId": client._account_id})
        print(f"  → {cancel}")

asyncio.run(main())
