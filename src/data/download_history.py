"""
Download 5-minute MES continuous history from IB Gateway (paper account).

Usage:
    python -m src.data.download_history [--start YYYY-MM-DD] [--end YYYY-MM-DD]

Output: data/raw/MES_5min_continuous.csv
Columns: datetime, open, high, low, close, volume, contract

Contract roll logic:
- Fetches front-month contract, then next contract when within ROLL_DAYS_BEFORE_EXPIRY
- Back-adjusts prices on roll: adds a constant offset so the series is continuous
- Appends new bars to existing CSV (idempotent — skips already-downloaded dates)

PAPER ACCOUNT ONLY. Live mode requires LIVE_MODE=1 env var.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config.settings import (
    BAR_SIZE,
    CONTINUOUS_CSV,
    CURRENCY,
    EXCHANGE,
    IB_CLIENT_ID,
    IB_HOST,
    IB_PORT,
    LIVE_MODE,
    RAW_DIR,
    ROLL_DAYS_BEFORE_EXPIRY,
    SYMBOL,
)

try:
    from ib_async import IB, Contract, util
except ImportError:
    raise ImportError("ib_async is required: pip install ib_async")


def _make_mes_contract(expiry: str) -> Contract:
    """Create a MES futures contract for a given expiry string (YYYYMM)."""
    c = Contract()
    c.symbol = SYMBOL
    c.secType = "FUT"
    c.exchange = EXCHANGE
    c.currency = CURRENCY
    c.lastTradeDateOrContractMonth = expiry
    return c


def _quarterly_expiries(start: date, end: date) -> list[str]:
    """Return list of YYYYMM quarterly expiry strings covering [start, end]."""
    expiries = []
    year = start.year
    for _ in range((end.year - start.year + 1) * 4 + 4):
        for month in (3, 6, 9, 12):
            exp_date = date(year, month, 1)
            if exp_date >= start - timedelta(days=90) and exp_date <= end + timedelta(days=90):
                expiries.append(f"{year}{month:02d}")
        year += 1
        if year > end.year + 1:
            break
    return sorted(set(expiries))


async def _fetch_bars(ib: IB, contract: Contract, end_dt: datetime, duration: str) -> pd.DataFrame:
    """Fetch historical bars for one contract segment."""
    bars = await ib.reqHistoricalDataAsync(
        contract,
        endDateTime=end_dt.strftime("%Y%m%d %H:%M:%S"),
        durationStr=duration,
        barSizeSetting=BAR_SIZE,
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
    )
    if not bars:
        return pd.DataFrame()

    df = util.df(bars)
    df = df.rename(columns={"date": "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df[["datetime", "open", "high", "low", "close", "volume"]].copy()
    df["contract"] = contract.lastTradeDateOrContractMonth
    return df


def _back_adjust(segments: list[pd.DataFrame]) -> pd.DataFrame:
    """
    Combine contract segments into a continuous back-adjusted series.
    On each roll, compute the gap between the old contract's last close
    and the new contract's first open, then shift all prior bars by that gap.
    """
    if not segments:
        return pd.DataFrame()

    adjusted = segments[0].copy()
    cumulative_offset = 0.0

    for next_seg in segments[1:]:
        if next_seg.empty:
            continue

        # Gap at the roll point
        prev_last_close = adjusted.iloc[-1]["close"]
        next_first_open = next_seg.iloc[0]["open"]
        gap = next_first_open - prev_last_close
        cumulative_offset += gap

        # Shift all prior price columns by the gap
        for col in ("open", "high", "low", "close"):
            adjusted[col] = adjusted[col] + gap

        adjusted = pd.concat([adjusted, next_seg.copy()], ignore_index=True)

    adjusted = adjusted.sort_values("datetime").reset_index(drop=True)
    adjusted = adjusted.drop_duplicates(subset="datetime")
    return adjusted


async def download_history(
    start: Optional[date] = None,
    end: Optional[date] = None,
    output_path: Optional[str] = None,
) -> pd.DataFrame:
    """
    Download MES 5-min history from IB Gateway and write to CSV.

    Args:
        start: Start date (default: 1 year ago)
        end: End date (default: today)
        output_path: CSV output path (default: CONTINUOUS_CSV from settings)

    Returns:
        DataFrame of the full continuous series written to disk.
    """
    if LIVE_MODE:
        raise RuntimeError(
            "download_history runs against paper account. "
            "Unset LIVE_MODE or use the paper port."
        )

    if start is None:
        start = date.today() - timedelta(days=365)
    if end is None:
        end = date.today()
    if output_path is None:
        output_path = CONTINUOUS_CSV

    os.makedirs(RAW_DIR, exist_ok=True)

    # Load existing data to avoid re-downloading
    existing = pd.DataFrame()
    if os.path.exists(output_path):
        existing = pd.read_csv(output_path, parse_dates=["datetime"])
        if not existing.empty:
            last_dt = existing["datetime"].max().date()
            if last_dt >= end:
                print(f"Data already up to date through {last_dt}, skipping download.")
                return existing
            start = last_dt + timedelta(days=1)
            print(f"Resuming download from {start}")

    ib = IB()
    await ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)

    try:
        expiries = _quarterly_expiries(start, end)
        segments = []

        for expiry in expiries:
            contract = _make_mes_contract(expiry)
            await ib.qualifyContractsAsync(contract)

            # Fetch up to 30 days per request (IB limit for 5-min bars)
            seg_end = min(end, date.today())
            seg_df = await _fetch_bars(
                ib,
                contract,
                datetime.combine(seg_end, datetime.min.time()),
                "30 D",
            )
            if not seg_df.empty:
                # Filter to the date range for this contract
                seg_df = seg_df[seg_df["datetime"].dt.date >= start]
                seg_df = seg_df[seg_df["datetime"].dt.date <= end]
                if not seg_df.empty:
                    segments.append(seg_df)
                    print(f"  {expiry}: {len(seg_df)} bars "
                          f"({seg_df['datetime'].min()} – {seg_df['datetime'].max()})")

        new_data = _back_adjust(segments)

        if new_data.empty:
            print("No new data downloaded.")
            return existing

        # Merge with existing
        combined = pd.concat([existing, new_data], ignore_index=True)
        combined = combined.drop_duplicates(subset="datetime").sort_values("datetime")
        combined = combined.reset_index(drop=True)

        combined.to_csv(output_path, index=False)
        print(f"Saved {len(combined)} bars to {output_path}")
        return combined

    finally:
        ib.disconnect()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Download MES 5-min history from IB Gateway")
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    util.startLoop()
    asyncio.run(download_history(args.start, args.end, args.output))


if __name__ == "__main__":
    main()
