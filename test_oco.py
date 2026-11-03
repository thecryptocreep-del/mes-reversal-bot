"""
Test Topstep native bracket/OCO order parameters.
Tries linkedOrderId, bracketOrder, ocoGroupId, and stopLimitPrice combos.

    python test_oco.py
"""
import asyncio

async def main():
    from src.broker.projectx_client import ProjectXClient, ORDER_TYPE_LIMIT, ORDER_TYPE_STOP, SIDE_BUY, SIDE_SELL

    async with ProjectXClient() as client:
        acct = await client.get_account_info()
        print(f"Account: {acct['name']}  cash=${acct['cash']:.2f}\n")
        contract_id = await client.get_contract_id("MNQ")

        # Test 1: single order with stopLoss and takeProfit embedded
        print("Test 1: Embedded stopLoss + takeProfit in one order body...")
        body = {
            "accountId": client._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_LIMIT,
            "side": SIDE_BUY,
            "size": 1,
            "limitPrice": 1000.0,  # won't fill
            "stopLoss": 990.0,
            "takeProfit": 1012.0,
        }
        result = await client._post("/Order/place", body)
        print(f"  → {result}\n")
        oid = result.get("orderId")
        if oid and result.get("success"):
            await client._post("/Order/cancel", {"orderId": oid, "accountId": client._account_id})

        # Test 2: stopLossPrice / takeProfitPrice
        print("Test 2: stopLossPrice + takeProfitPrice field names...")
        body2 = {
            "accountId": client._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_LIMIT,
            "side": SIDE_BUY,
            "size": 1,
            "limitPrice": 1000.0,
            "stopLossPrice": 990.0,
            "takeProfitPrice": 1012.0,
        }
        result2 = await client._post("/Order/place", body2)
        print(f"  → {result2}\n")
        oid2 = result2.get("orderId")
        if oid2 and result2.get("success"):
            await client._post("/Order/cancel", {"orderId": oid2, "accountId": client._account_id})

        # Test 3: bracket field
        print("Test 3: bracket sub-object...")
        body3 = {
            "accountId": client._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_LIMIT,
            "side": SIDE_BUY,
            "size": 1,
            "limitPrice": 1000.0,
            "bracket": {
                "stopLoss": 990.0,
                "takeProfit": 1012.0,
            }
        }
        result3 = await client._post("/Order/place", body3)
        print(f"  → {result3}\n")
        oid3 = result3.get("orderId")
        if oid3 and result3.get("success"):
            await client._post("/Order/cancel", {"orderId": oid3, "accountId": client._account_id})

asyncio.run(main())
