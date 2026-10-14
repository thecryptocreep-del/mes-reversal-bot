"""
Tradovate historical bar downloader.

Pulls 5-min MNQ bars via the Tradovate REST API and saves a continuous CSV
in the same format as download_yahoo.py (datetime index, ohlcv columns).

Credentials come from environment variables — never hardcode them:
    TRADOVATE_USERNAME  your Tradovate login email
    TRADOVATE_PASSWORD  your Tradovate password
    TRADOVATE_APP_ID    optional, defaults to "Sample App"
    TRADOVATE_CID       optional client id, defaults to 0
    TRADOVATE_SEC       optional secret, defaults to ""

Usage:
    python -m src.data.download_tradovate            # last 365 days
    python -m src.data.download_tradovate --days 730 # last 2 years
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from config.settings import CONTINUOUS_CSV, RAW_DIR, SYMBOL

# ---------------------------------------------------------------------------
# Endpoints — paper account uses the demo environment
# ---------------------------------------------------------------------------
DEMO_BASE  = "https://demo.tradovateapi.com/v1"
LIVE_BASE  = "https://live.tradovateapi.com/v1"

LIVE_MODE = os.getenv("LIVE_MODE", "0") == "1"
BASE_URL   = LIVE_BASE if LIVE_MODE else DEMO_BASE

# Tradovate contract symbols for MNQ quarterly expiries
# Format: MNQ + month code + last-two-digits-of-year  e.g. MNQZ6 = Dec 2026
MONTH_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}


def _quarterly_expirations(start: datetime, end: datetime) -> list[tuple[str, datetime, datetime]]:
    """
    Return list of (symbol, segment_start, segment_end) covering start→end.
    Rolls 4 business days before the third Friday of the expiry month.
    """
    expirations = []
    year = start.year
    month = start.month

    # Step to nearest future quarterly month
    for q in [3, 6, 9, 12]:
        if (year, q) >= (start.year, start.month):
            year, month = year, q
            break
    else:
        year, month = start.year + 1, 3

    while True:
        code = MONTH_CODES[month]
        symbol = f"{SYMBOL}{code}{str(year)[-1]}"  # e.g. MNQZ6

        # Third Friday of expiry month
        first_day = datetime(year, month, 1, tzinfo=timezone.utc)
        # weekday(): Monday=0, Friday=4
        days_to_friday = (4 - first_day.weekday()) % 7
        third_friday = first_day + timedelta(days=days_to_friday + 14)

        # Roll 4 business days before third Friday
        roll_date = third_friday
        bdays = 0
        while bdays < 4:
            roll_date -= timedelta(days=1)
            if roll_date.weekday() < 5:
                bdays += 1

        expirations.append((symbol, roll_date))

        # Advance to next quarter
        month += 3
        if month > 12:
            month = 3
            year += 1

        if roll_date > end + timedelta(days=90):
            break

    # Convert to segments
    segments = []
    for i, (sym, roll) in enumerate(expirations):
        seg_start = expirations[i - 1][1] if i > 0 else start
        seg_end = roll
        if seg_end < start:
            continue
        if seg_start > end:
            break
        segments.append((sym, max(seg_start, start), min(seg_end, end)))

    return segments


def _authenticate() -> str:
    """Authenticate with Tradovate and return an access token."""
    username = os.getenv("TRADOVATE_USERNAME")
    password = os.getenv("TRADOVATE_PASSWORD")

    if not username or not password:
        raise EnvironmentError(
            "Set TRADOVATE_USERNAME and TRADOVATE_PASSWORD environment variables.\n"
            "Add them to a .env file in the project root (never commit it)."
        )

    payload = {
        "name": username,
        "password": password,
        "appId": os.getenv("TRADOVATE_APP_ID", "Sample App"),
        "appVersion": "1.0",
        "cid": int(os.getenv("TRADOVATE_CID", "0")),
        "sec": os.getenv("TRADOVATE_SEC", ""),
    }

    resp = requests.post(f"{BASE_URL}/auth/accesstokenrequest", json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    token = data.get("accessToken")
    if not token:
        raise RuntimeError(f"Authentication failed: {data}")

    print(f"  Authenticated as {username}")
    return token


def _fetch_bars(
    token: str,
    symbol: str,
    start: datetime,
    end: datetime,
    bar_size: int = 5,
) -> pd.DataFrame:
    """
    Fetch 5-min bars for one contract symbol over [start, end].
    Returns DataFrame with columns [open, high, low, close, volume].
    """
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "symbol": symbol,
        "startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elementSize": bar_size,
        "elementSizeUnit": "Minute",
        "withHistogram": "false",
    }

    resp = requests.get(
        f"{BASE_URL}/history/barcharthistory",
        headers=headers,
        params=params,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    bars = data.get("bars", [])
    if not bars:
        return pd.DataFrame()

    rows = []
    for b in bars:
        rows.append({
            "datetime": pd.Timestamp(b["timestamp"], unit="ms", tz="UTC")
                          .tz_convert("America/New_York")
                          .tz_localize(None),
            "open":   b["open"],
            "high":   b["high"],
            "low":    b["low"],
            "close":  b["close"],
            "volume": b.get("upVolume", 0) + b.get("downVolume", 0),
        })

    df = pd.DataFrame(rows).set_index("datetime").sort_index()
    return df


def _back_adjust(segments: list[pd.DataFrame]) -> pd.DataFrame:
    """
    Panama-canal back-adjustment: shift older segments so the continuous
    series has no price gap at each roll.
    """
    if not segments:
        return pd.DataFrame()
    if len(segments) == 1:
        return segments[0]

    combined = segments[-1].copy()
    for i in range(len(segments) - 2, -1, -1):
        older = segments[i].copy()
        newer = segments[i + 1]

        # Find the last overlapping timestamp
        overlap = older.index.intersection(newer.index)
        if overlap.empty:
            # Use last bar of older / first bar of newer as gap reference
            gap = newer["close"].iloc[0] - older["close"].iloc[-1]
        else:
            ref = overlap[-1]
            gap = newer.loc[ref, "close"] - older.loc[ref, "close"]

        for col in ["open", "high", "low", "close"]:
            older[col] += gap

        combined = pd.concat([older[~older.index.isin(combined.index)], combined])

    return combined.sort_index()


def download_tradovate(
    days: int = 365,
    output_path: str | None = None,
) -> pd.DataFrame:
    """
    Download continuous MNQ 5-min history from Tradovate.

    Args:
        days: number of calendar days of history to pull
        output_path: override save location (default: config CONTINUOUS_CSV)
    """
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    print(f"Tradovate {'DEMO' if not LIVE_MODE else 'LIVE'} | {SYMBOL} | "
          f"{start.date()} → {end.date()} ({days} days)")

    token = _authenticate()

    segments_meta = _quarterly_expirations(start, end)
    print(f"  Contract segments: {len(segments_meta)}")

    segment_dfs = []
    for sym, seg_start, seg_end in segments_meta:
        print(f"  Fetching {sym}  {seg_start.date()} → {seg_end.date()} ...", end=" ")
        df = _fetch_bars(token, sym, seg_start, seg_end)
        if df.empty:
            print("(no data)")
        else:
            print(f"{len(df)} bars")
            segment_dfs.append(df)
        time.sleep(0.3)  # be polite to the API

    if not segment_dfs:
        print("No data returned.")
        return pd.DataFrame()

    continuous = _back_adjust(segment_dfs)

    # Keep only regular trading hours
    continuous = continuous.between_time("08:00", "16:00")

    out = output_path or CONTINUOUS_CSV
    os.makedirs(os.path.dirname(out), exist_ok=True)
    continuous.to_csv(out)
    print(f"\nSaved {len(continuous)} bars → {out}")
    print(f"Range: {continuous.index.min()} → {continuous.index.max()}")

    return continuous


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Tradovate MNQ history")
    parser.add_argument("--days", type=int, default=365, help="Calendar days of history")
    args = parser.parse_args()
    download_tradovate(days=args.days)
