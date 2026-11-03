"""
Show recent order history with statuses.
    python check_orders.py
"""
import asyncio
from datetime import datetime, timezone, timedelta

async def main():
    from src.broker.projectx_client import ProjectXClient

    async with ProjectXClient() as client:
        acct = await client.get_account_info()
        print(f"Account: {acct['name']}  cash=${acct['cash']:.2f}\n")

        start = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result = await client._post("/Order/search", {
            "accountId": client._account_id,
            "startTimestamp": start,
        })
        orders = result.get("orders", result) if isinstance(result, dict) else result

        STATUS = {0: "Unknown", 1: "Working", 2: "Filled", 3: "Cancelled", 4: "Rejected"}
        SIDE   = {0: "Buy", 1: "Sell"}
        TYPE   = {1: "Market", 2: "Limit", 3: "Stop", 4: "StopLimit"}

        print(f"{'ID':<14} {'Side':<6} {'Type':<10} {'Status':<10} {'LimitPx':<10} {'StopPx':<10} {'FillPx':<10} {'Time'}")
        print("-" * 90)
        for o in (orders if isinstance(orders, list) else []):
            oid     = o.get("id", "")
            side    = SIDE.get(o.get("side"), str(o.get("side")))
            otype   = TYPE.get(o.get("type"), str(o.get("type")))
            status  = STATUS.get(o.get("status"), str(o.get("status")))
            lp      = o.get("limitPrice") or "-"
            sp      = o.get("stopPrice") or "-"
            fp      = o.get("filledPrice") or "-"
            ts      = o.get("creationTimestamp", "")[:19]
            print(f"{oid:<14} {side:<6} {otype:<10} {status:<10} {lp:<10} {sp:<10} {fp:<10} {ts}")

asyncio.run(main())
