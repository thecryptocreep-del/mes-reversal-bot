"""
List ALL accounts on this API key so we can find the right one.
    python check_orders.py
"""
import asyncio

async def main():
    from src.broker.projectx_client import ProjectXClient, _BASE

    async with ProjectXClient() as client:
        # List ALL accounts
        data = await client._post("/Account/search", {"onlyActiveAccounts": True})
        accounts = data if isinstance(data, list) else data.get("accounts", [])

        print(f"Found {len(accounts)} account(s):\n")
        for i, a in enumerate(accounts):
            acct_id = a.get("id") or a.get("accountId")
            name    = a.get("name") or a.get("accountName", "")
            balance = a.get("balance") or a.get("cashBalance", 0)
            print(f"  [{i}] ID={acct_id}  name={name}  balance=${float(balance):.2f}")

        print()
        print("Set PROJECTX_ACCOUNT_ID=<id> in your .env to force a specific account.")

asyncio.run(main())
