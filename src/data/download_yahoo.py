"""
Download MES 5-min history from Yahoo Finance as a stand-in until IB Gateway is ready.

Usage:
    python -m src.data.download_yahoo [--start YYYY-MM-DD] [--end YYYY-MM-DD]

Output: data/raw/MES_5min_continuous.csv  (same schema as the IB downloader)

Note: Yahoo Finance free tier only provides ~60 days of 5-min intraday data.
For longer history use the 1-day interval fallback (--interval 1d).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config.settings import CONTINUOUS_CSV, RAW_DIR, SYMBOL, YAHOO_TICKER

try:
    import yfinance as yf
except ImportError:
    raise ImportError("yfinance is required: pip install yfinance")

import pandas as pd


def download_yahoo(
    start: date | None = None,
    end: date | None = None,
    interval: str = "5m",
    output_path: str | None = None,
) -> pd.DataFrame:
    """
    Download MES futures data from Yahoo Finance.

    Args:
        start: Start date (5m interval: max ~60 days back; 1d: years)
        end: End date (default: today)
        interval: '5m' or '1d'
        output_path: CSV output path

    Returns:
        DataFrame written to disk.
    """
    if end is None:
        end = date.today()
    if start is None:
        # Yahoo caps 5m history at ~60 days
        start = end - timedelta(days=59) if interval == "5m" else end - timedelta(days=730)
    if output_path is None:
        output_path = CONTINUOUS_CSV

    os.makedirs(RAW_DIR, exist_ok=True)

    print(f"Downloading {YAHOO_TICKER} ({SYMBOL}) {interval} bars from Yahoo Finance ({start} → {end})...")
    ticker = yf.Ticker(YAHOO_TICKER)
    df = ticker.history(start=str(start), end=str(end), interval=interval)

    if df.empty:
        raise RuntimeError(f"Yahoo Finance returned no data for {YAHOO_TICKER}. Try a shorter date range.")

    df = df.reset_index()

    # Normalise column names
    df.columns = [c.lower() for c in df.columns]
    time_col = "datetime" if "datetime" in df.columns else "date"
    df = df.rename(columns={time_col: "datetime"})

    df["datetime"] = pd.to_datetime(df["datetime"])
    # Drop timezone info for consistency with IB output
    if df["datetime"].dt.tz is not None:
        df["datetime"] = df["datetime"].dt.tz_localize(None)

    df = df[["datetime", "open", "high", "low", "close", "volume"]].copy()
    df["contract"] = "yahoo"  # placeholder — no roll handling needed for daily/short intraday

    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.sort_values("datetime").reset_index(drop=True)

    df.to_csv(output_path, index=False)
    print(f"Saved {len(df)} bars to {output_path}")
    print(f"Range: {df['datetime'].min()} → {df['datetime'].max()}")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Download MES history from Yahoo Finance")
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--interval", choices=["5m", "1d"], default="5m",
                        help="5m = intraday (60-day limit); 1d = daily (years of history)")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    download_yahoo(args.start, args.end, args.interval, args.output)


if __name__ == "__main__":
    main()
