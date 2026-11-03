"""
Test bracket order placement — tries different side codes to find what works.

Run AFTER the bot has placed an entry (or place one manually first).
Or runs standalone to test stop/limit order placement directly.

    python test_bracket.py
"""
import asyncio
import os

async def main():
    from src.broker.projectx_client import ProjectXClient, ORDER_TYPE_LIMIT, ORDER_TYPE_STOP

    async with ProjectXClient() as client:
        acct = await client.get_account_info()
        print(f"Account: {acct['name']}  cash=${acct['cash']:.2f}\n")
        contract_id = await client.get_contract_id("MNQ")

        # Try each possible side code for a sell-side order (exit from long)
        # Topstep may use 0=Buy, 1=Sell  OR  1=Buy, 2=Sell
        for side_code in [0, 1, 2]:
            print(f"Testing stop order with side={side_code}...")
            body = {
                "accountId": client._account_id,
                "contractId": contract_id,
                "type": ORDER_TYPE_STOP,
                "side": side_code,
                "size": 1,
                "stopPrice": 1000.0,   # far below market, won't fill
                "limitPrice": 1000.0,
            }
            result = await client._post("/Order/place", body)
            print(f"  side={side_code} → {result}\n")

            # Cancel immediately if it worked
            oid = result.get("orderId")
            if oid and result.get("success"):
                await client._post("/Order/cancel", {"orderId": oid, "accountId": client._account_id})
                print(f"  Cancelled orderId={oid}\n")

        # Also test limit sell
        print("Testing limit SELL orders...")
        for side_code in [0, 1, 2]:
            print(f"Testing limit sell with side={side_code}...")
            body = {
                "accountId": client._account_id,
                "contractId": contract_id,
                "type": ORDER_TYPE_LIMIT,
                "side": side_code,
                "size": 1,
                "limitPrice": 99999.0,  # far above market, won't fill
            }
            result = await client._post("/Order/place", body)
            print(f"  side={side_code} → {result}\n")

            oid = result.get("orderId")
            if oid and result.get("success"):
                await client._post("/Order/cancel", {"orderId": oid, "accountId": client._account_id})
                print(f"  Cancelled orderId={oid}\n")

asyncio.run(main())
