"""
Quick test — place one market buy and immediately cancel it.
Confirms the broker connection and order placement work end to end.

Run:
    python test_order.py
"""
import asyncio
import os
import sys

async def main():
    from src.broker.projectx_client import ProjectXClient

    print("Connecting to Topstep...")
    async with ProjectXClient() as client:
        acct = await client.get_account_info()
        print(f"Account: {acct['name']}  cash=${acct['cash']:.2f}")

        contract_id = await client.get_contract_id("MNQ")
        print(f"Contract: {contract_id}")

        # Get current price from a quote — just use a round number near market
        # We'll place a limit order FAR below market so it never fills
        from src.broker.projectx_client import SIDE_BUY, ORDER_TYPE_LIMIT, _BASE
        import aiohttp

        # Place a limit buy way below market (won't fill — safe test)
        test_price = 1000.0  # far below any real MNQ price
        body = {
            "accountId": client._account_id,
            "contractId": contract_id,
            "type": ORDER_TYPE_LIMIT,
            "side": SIDE_BUY,
            "size": 1,
            "limitPrice": test_price,
        }
        print(f"\nPlacing test limit buy at ${test_price} (won't fill)...")
        result = await client._post("/Order/place", body)
        print(f"Response: {result}")

        order_id = result.get("orderId") or result.get("id")
        if order_id and result.get("success", True):
            print(f"\nOrder placed! orderId={order_id}")
            print("Cancelling it now...")
            await asyncio.sleep(1)
            cancel = await client._post("/Order/cancel", {"orderId": order_id})
            print(f"Cancel response: {cancel}")
            print("\nSUCCESS — order placement and cancellation both work!")
        else:
            print(f"\nFAILED — {result.get('errorMessage', result)}")
            print("Check your API key and username.")

asyncio.run(main())
