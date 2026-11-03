"""
Test ORDER_TYPE_STOP_LIMIT (type=4) — the correct order type for stop losses.
Places a stop-sell far below market (won't trigger) then cancels it.

    python test_stop_limit.py
"""
import asyncio

async def main():
    from src.broker.projectx_client import ProjectXClient, SIDE_BUY, SIDE_SELL, ORDER_TYPE_LIMIT, _BASE

    ORDER_TYPE_STOP_LIMIT = 4

    async with ProjectXClient() as client:
        acct = await client.get_account_info()
        print(f"Account: {acct['name']}  cash=${acct['cash']:.2f}\n")
        contract_id = await client.get_contract_id("MNQ")

        # Test stop-limit SELL: stopPrice triggers, limitPrice is worst acceptable fill
        # Set both far below market so it won't trigger
        test_stop  = 1000.0
        test_limit = 995.0  # 5 pts of slippage allowed

        print(f"Testing stop-limit SELL (type=4) stopPrice={test_stop} limitPrice={test_limit}...")
        body = {
            "accountId": client._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_STOP_LIMIT,
            "side": SIDE_SELL,
            "size": 1,
            "stopPrice": test_stop,
            "limitPrice": test_limit,
        }
        result = await client._post("/Order/place", body)
        print(f"  → {result}\n")

        oid = result.get("orderId")
        if oid and result.get("success"):
            print(f"SUCCESS — stop-limit order placed! orderId={oid}")
            await asyncio.sleep(1)
            cancel = await client._post("/Order/cancel", {"orderId": oid, "accountId": client._account_id})
            print(f"Cancelled: {cancel}")
        else:
            print("FAILED — stop-limit not supported on this account")
            print("Will need to use OCO monitor with limit orders instead.")

        # Also test stop-limit BUY (for short stop losses)
        print(f"\nTesting stop-limit BUY (type=4) stopPrice=99999 limitPrice=100004...")
        body2 = {
            "accountId": client._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_STOP_LIMIT,
            "side": SIDE_BUY,
            "size": 1,
            "stopPrice": 99999.0,
            "limitPrice": 100004.0,
        }
        result2 = await client._post("/Order/place", body2)
        print(f"  → {result2}\n")
        oid2 = result2.get("orderId")
        if oid2 and result2.get("success"):
            await asyncio.sleep(1)
            await client._post("/Order/cancel", {"orderId": oid2, "accountId": client._account_id})
            print(f"Cancelled orderId={oid2}")

asyncio.run(main())
