"""
Market structure analysis for MNQ/NQ 5-min data.

Examines:
- ATR by time of day (to size stops properly)
- Volume by time of day (to confirm session window)
- Three-bar reversal setup statistics (bar ranges, follow-through)
- Optimal R-multiple targets based on actual post-signal price action

Run: python -m scripts.analyze_market_structure
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from config.settings import CONTINUOUS_CSV, POINT_VALUE
from src.strategy.three_bar_reversal import Signal, scan_signals


def load_data() -> pd.DataFrame:
    df = pd.read_csv(CONTINUOUS_CSV, index_col="datetime", parse_dates=True)
    # Keep only regular trading hours (remove overnight/weekend gaps)
    df = df.between_time("08:00", "16:00")
    return df


def atr_by_hour(df: pd.DataFrame) -> pd.DataFrame:
    """Average True Range per 5-min bar, grouped by hour."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    df2 = df.copy()
    df2["tr"] = tr
    df2["hour"] = df.index.hour

    result = df2.groupby("hour")["tr"].agg(
        avg_tr="mean", median_tr="median", p90_tr=lambda x: x.quantile(0.9)
    ).round(2)
    return result


def volume_by_hour(df: pd.DataFrame) -> pd.DataFrame:
    """Average volume per bar grouped by hour."""
    df2 = df.copy()
    df2["hour"] = df.index.hour
    return df2.groupby("hour")["volume"].mean().round(0).rename("avg_volume_per_bar").to_frame()


def setup_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    For every three-bar reversal signal, measure:
    - Bar 2 extension beyond Bar 1 extreme (in points)
    - Bar 3 range
    - Max favorable excursion (MFE) over next 1, 2, 4, 8 bars
    - Max adverse excursion (MAE) over next 1, 2, 4, 8 bars
    """
    signals = scan_signals(df)

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    index = df.index

    rows = []
    for i in range(2, len(df) - 8):
        sig = signals.iloc[i]
        if sig == Signal.NONE:
            continue

        # Only morning session
        hour = index[i].hour
        minute = index[i].minute
        if not (8 <= hour < 12 or (hour == 11 and minute <= 50)):
            continue

        direction = 1 if sig == Signal.LONG else -1
        entry = opens[i + 1]  # entry at next bar open

        # Bar 1, 2, 3 metrics
        b1_high, b1_low = highs[i - 2], lows[i - 2]
        b2_close = closes[i - 1]
        b3_close = closes[i]

        if direction == 1:
            bar2_extension = (b1_low - b2_close)   # how far below bar1 low
            bar3_reversal  = (b3_close - b1_high)  # how far above bar1 high
        else:
            bar2_extension = (b2_close - b1_high)
            bar3_reversal  = (b1_low - b3_close)

        # MFE and MAE over next N bars
        mfe = {}
        mae = {}
        for n in (1, 2, 4, 8):
            slice_h = highs[i + 1: i + 1 + n]
            slice_l = lows[i + 1: i + 1 + n]
            if direction == 1:
                mfe[n] = max(slice_h) - entry
                mae[n] = entry - min(slice_l)
            else:
                mfe[n] = entry - min(slice_l)
                mae[n] = max(slice_h) - entry

        rows.append({
            "time": index[i],
            "direction": "LONG" if direction == 1 else "SHORT",
            "bar2_extension_pts": round(bar2_extension, 2),
            "bar3_reversal_pts":  round(bar3_reversal, 2),
            "mfe_1bar":  round(mfe[1], 2),
            "mfe_2bar":  round(mfe[2], 2),
            "mfe_4bar":  round(mfe[4], 2),
            "mfe_8bar":  round(mfe[8], 2),
            "mae_1bar":  round(mae[1], 2),
            "mae_2bar":  round(mae[2], 2),
            "mae_4bar":  round(mae[4], 2),
            "mae_8bar":  round(mae[8], 2),
        })

    return pd.DataFrame(rows)


def print_separator(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main() -> None:
    df = load_data()
    print(f"Loaded {len(df)} bars  |  {df.index.min().date()} → {df.index.max().date()}")
    print(f"Point value: ${POINT_VALUE}/pt")

    # --- ATR by hour ---
    print_separator("ATR BY HOUR (points per 5-min bar)")
    atr = atr_by_hour(df)
    print(atr.to_string())

    # --- Volume by hour ---
    print_separator("AVG VOLUME BY HOUR")
    vol = volume_by_hour(df)
    print(vol.to_string())

    # --- Setup stats ---
    print_separator("THREE-BAR REVERSAL SETUP STATS (morning session only)")
    setups = setup_stats(df)
    if setups.empty:
        print("No setups found in this data window.")
        return

    print(f"\nTotal setups found: {len(setups)}")
    print(f"  Long:  {(setups['direction']=='LONG').sum()}")
    print(f"  Short: {(setups['direction']=='SHORT').sum()}")

    print_separator("BAR 2 EXTENSION (how far price went beyond Bar 1 extreme)")
    print(setups["bar2_extension_pts"].describe().round(2).to_string())

    print_separator("MAX FAVORABLE EXCURSION after entry (points)")
    for col in ("mfe_1bar", "mfe_2bar", "mfe_4bar", "mfe_8bar"):
        bars = col.split("_")[1]
        print(f"  {bars:>6}:  median={setups[col].median():.1f}  "
              f"mean={setups[col].mean():.1f}  "
              f"p25={setups[col].quantile(0.25):.1f}  "
              f"p75={setups[col].quantile(0.75):.1f}")

    print_separator("MAX ADVERSE EXCURSION after entry (points)")
    for col in ("mae_1bar", "mae_2bar", "mae_4bar", "mae_8bar"):
        bars = col.split("_")[1]
        print(f"  {bars:>6}:  median={setups[col].median():.1f}  "
              f"mean={setups[col].mean():.1f}  "
              f"p75={setups[col].quantile(0.75):.1f}  "
              f"p90={setups[col].quantile(0.90):.1f}")

    # --- Suggested stop ---
    print_separator("STOP / TARGET RECOMMENDATIONS")
    mae_p90_1bar = setups["mae_1bar"].quantile(0.90)
    mae_p90_2bar = setups["mae_2bar"].quantile(0.90)
    mfe_median_4bar = setups["mfe_4bar"].median()
    mfe_p25_4bar = setups["mfe_4bar"].quantile(0.25)

    stop_pts = round(mae_p90_1bar, 1)
    target_pts = round(mfe_median_4bar, 1)
    rr = round(target_pts / stop_pts, 2) if stop_pts > 0 else 0

    print(f"\n  Suggested stop:   {stop_pts} pts  "
          f"(90th pct MAE at 1 bar = covers worst immediate move)")
    print(f"  Suggested target: {target_pts} pts  "
          f"(median MFE at 4 bars = where price typically reaches)")
    print(f"  Implied R:R       {rr}:1")
    print(f"\n  Dollar stop   MNQ (x1): ${stop_pts * POINT_VALUE * 1:.0f}   "
          f"MNQ (x2): ${stop_pts * POINT_VALUE * 2:.0f}")
    print(f"  Dollar target MNQ (x1): ${target_pts * POINT_VALUE * 1:.0f}   "
          f"MNQ (x2): ${target_pts * POINT_VALUE * 2:.0f}")
    print(f"\n  Raw setup data:")
    print(setups[["time","direction","bar2_extension_pts","mfe_4bar","mae_2bar"]].to_string(index=False))


if __name__ == "__main__":
    main()
