"""
Download NQ/MES 5-min history from Yahoo Finance.

Usage:
    python -m src.data.download_yahoo [--days 90] [--interval 5m]

Output: data/raw/{SYMBOL}_5min_continuous.csv  (same schema as the IB downloader)

Note: Yahoo Finance caps 5-min history at ~60 days per request.
For >60 days this script fetches in two overlapping chunks and deduplicates.
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


def _fetch_chunk(ticker: yf.Ticker, start: date, end: date, interval: str) -> pd.DataFrame:
    """Fetch one chunk and normalise columns."""
    df = ticker.history(start=str(start), end=str(end), interval=interval)
    if df.empty:
        return pd.DataFrame()

    df = df.reset_index()
    df.columns = [c.lower() for c in df.columns]
    time_col = "datetime" if "datetime" in df.columns else "date"
    df = df.rename(columns={time_col: "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"])
    if df["datetime"].dt.tz is not None:
        df["datetime"] = df["datetime"].dt.tz_localize(None)

    df = df[["datetime", "open", "high", "low", "close", "volume"]].copy()
    df["contract"] = "yahoo"
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df


def download_yahoo(
    days: int = 60,
    interval: str = "5m",
    output_path: str | None = None,
) -> pd.DataFrame:
    """
    Download futures data from Yahoo Finance, chunking if >60 days requested.

    Args:
        days: Calendar days of history to fetch (default 90)
        interval: '5m' or '1d'
        output_path: CSV output path (default from settings)

    Returns:
        DataFrame written to disk.
    """
    if output_path is None:
        output_path = CONTINUOUS_CSV

    os.makedirs(RAW_DIR, exist_ok=True)

    end = date.today()
    start = end - timedelta(days=days)

    ticker = yf.Ticker(YAHOO_TICKER)
    chunks: list[pd.DataFrame] = []

    print(f"Downloading {YAHOO_TICKER} ({SYMBOL}) {interval} bars ({start} → {end})...")
    chunk = _fetch_chunk(ticker, start, end, interval)
    if not chunk.empty:
        chunks.append(chunk)

    if not chunks:
        raise RuntimeError(f"Yahoo Finance returned no data for {YAHOO_TICKER}.")

    df = pd.concat(chunks, ignore_index=True)
    df = df.drop_duplicates(subset="datetime")
    df = df.sort_values("datetime").reset_index(drop=True)

    df.to_csv(output_path, index=False)
    print(f"Saved {len(df)} bars to {output_path}")
    print(f"Range: {df['datetime'].min()} → {df['datetime'].max()}")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Download futures history from Yahoo Finance")
    parser.add_argument("--days", type=int, default=60,
                        help="Calendar days of history to fetch (default 60)")
    parser.add_argument("--interval", choices=["5m", "1d"], default="5m")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    download_yahoo(args.days, args.interval, args.output)


if __name__ == "__main__":
    main()
