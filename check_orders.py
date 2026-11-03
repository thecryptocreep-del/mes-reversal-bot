"""
Check recent orders and positions on the account.
    python check_orders.py
"""
import asyncio

async def main():
    from src.broker.projectx_client import ProjectXClient

    async with ProjectXClient() as client:
        acct = await client.get_account_info()
        print(f"Account ID : {client._account_id}")
        print(f"Account    : {acct['name']}")
        print(f"Cash       : ${acct['cash']:.2f}\n")

        # Search open orders
        print("--- Open Orders ---")
        try:
            result = await client._post("/Order/search", {
                "accountId": client._account_id,
                "status": 1,  # open/working
            })
            orders = result if isinstance(result, list) else result.get("orders", result)
            if not orders:
                print("  (none)")
            else:
                for o in orders:
                    print(f"  {o}")
        except Exception as e:
            print(f"  Error: {e}")

        # Search all recent orders (no status filter)
        print("\n--- All Recent Orders ---")
        try:
            result = await client._post("/Order/search", {
                "accountId": client._account_id,
            })
            orders = result if isinstance(result, list) else result.get("orders", result)
            if not orders:
                print("  (none)")
            else:
                for o in (orders[:10] if isinstance(orders, list) else [orders]):
                    print(f"  {o}")
        except Exception as e:
            print(f"  Error (no filter): {e}")

        # Positions
        print("\n--- Open Positions ---")
        try:
            result = await client._post("/Position/search", {
                "accountId": client._account_id,
                "onlyOpen": True,
            })
            positions = result if isinstance(result, list) else result.get("positions", result)
            if not positions:
                print("  (flat)")
            else:
                for p in positions:
                    print(f"  {p}")
        except Exception as e:
            print(f"  Error: {e}")

asyncio.run(main())
