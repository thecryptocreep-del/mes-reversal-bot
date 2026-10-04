"""
Walk-forward backtester for the three-bar reversal strategy.

Features:
- Applies commissions and slippage from config/risk.py
- Reports in-sample (IS) and out-of-sample (OOS) results separately
- Walk-forward: expanding window, configurable fold size
- Cost-sensitivity table: P&L at 0×, 0.5×, 1×, 1.5×, 2× assumed cost
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config.risk import (
    COMMISSION_PER_SIDE,
    DAILY_LOSS_LIMIT_USD,
    FLATTEN_TIME_ET,
    MAX_POSITION_CONTRACTS,
    MAX_TRADES_PER_DAY,
    MIN_BAR2_EXTENSION_POINTS,
    MES_POINT_VALUE,
    ROUND_TRIP_COST_USD,
    SESSION_END_ET,
    SESSION_START_ET,
    SLIPPAGE_POINTS_PER_SIDE,
    STOP_POINTS,
    TARGET_POINTS,
)
from config.settings import POINT_VALUE
from src.strategy.three_bar_reversal import Signal, scan_signals


@dataclass
class TradeResult:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int  # 1 = long, -1 = short
    entry_price: float
    exit_price: float
    gross_pnl: float
    cost: float
    net_pnl: float


@dataclass
class BacktestStats:
    total_trades: int
    wins: int
    losses: int
    gross_pnl: float
    total_cost: float
    net_pnl: float
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    sharpe: float  # daily Sharpe, annualized


# Session window pulled from config/risk.py — do not redefine here


def _in_session(ts: pd.Timestamp) -> bool:
    """Return True if timestamp falls within the allowed trading session."""
    t = (ts.hour, ts.minute)
    return SESSION_START_ET <= t <= SESSION_END_ET


def _simulate_trades(
    df: pd.DataFrame,
    cost_multiplier: float = 1.0,
    stop_loss_usd: float | None = None,
    contracts: int = 1,
    stop_points: float | None = None,
    target_points: float | None = None,
    min_extension: float | None = None,
) -> list[TradeResult]:
    """
    Simulate trades on a bar DataFrame.

    Entry:  next bar's open after signal fires (session window only).
    Exit:   first of — target hit, stop hit, flatten time, end of data.

    Args:
        stop_points:   stop distance in points (default: STOP_POINTS from config).
        target_points: profit target in points (default: TARGET_POINTS from config).
        stop_loss_usd: override stop_points via dollar amount (legacy param).
        min_extension: min bar2 extension filter (default: MIN_BAR2_EXTENSION_POINTS).
        contracts:     number of contracts (scales P&L and cost).
    """
    if stop_points is None and stop_loss_usd is None:
        stop_points = STOP_POINTS
    elif stop_loss_usd is not None:
        stop_points = stop_loss_usd / (POINT_VALUE * contracts)

    if target_points is None:
        target_points = TARGET_POINTS

    if min_extension is None:
        min_extension = MIN_BAR2_EXTENSION_POINTS

    signals = scan_signals(df, min_extension=min_extension)
    trades: list[TradeResult] = []

    flatten_hour, flatten_min = map(int, FLATTEN_TIME_ET.split(":"))

    daily_trades: dict[str, int] = {}
    daily_pnl: dict[str, float] = {}

    closes = df["close"].values
    opens  = df["open"].values
    highs  = df["high"].values
    lows   = df["low"].values
    index  = df.index

    i = 0
    while i < len(df) - 1:
        sig = signals.iloc[i]
        if sig == Signal.NONE:
            i += 1
            continue

        signal_time = index[i]
        day_key = str(signal_time.date())
        entry_time = index[i + 1]

        # Session window check — signal bar3 must close within session
        if not _in_session(signal_time):
            i += 1
            continue

        # Flatten time check on entry bar
        if entry_time.hour > flatten_hour or (
            entry_time.hour == flatten_hour and entry_time.minute >= flatten_min
        ):
            i += 1
            continue

        # Daily trade limit
        if daily_trades.get(day_key, 0) >= MAX_TRADES_PER_DAY:
            i += 1
            continue

        # Daily loss limit
        if daily_pnl.get(day_key, 0.0) <= -DAILY_LOSS_LIMIT_USD:
            i += 1
            continue

        direction = 1 if sig == Signal.LONG else -1
        entry_price = opens[i + 1]

        stop_price = entry_price - direction * stop_points
        target_price = entry_price + direction * target_points

        # Walk forward bar by bar until target/stop hit, flatten time, or end of day
        exit_price = None
        exit_time = None
        exit_idx = i + 1

        for j in range(i + 1, len(df)):
            bar_time = index[j]

            # Flatten at session end
            at_flatten = bar_time.hour > flatten_hour or (
                bar_time.hour == flatten_hour and bar_time.minute >= flatten_min
            )
            # New day — must have exited already (shouldn't happen, safety net)
            new_day = bar_time.date() != signal_time.date()

            # Check target hit first (favorable extreme)
            if direction == 1 and highs[j] >= target_price:
                exit_price = target_price
                exit_time = bar_time
                exit_idx = j
                break
            elif direction == -1 and lows[j] <= target_price:
                exit_price = target_price
                exit_time = bar_time
                exit_idx = j
                break

            # Check stop hit (adverse extreme)
            if direction == 1 and lows[j] <= stop_price:
                exit_price = stop_price
                exit_time = bar_time
                exit_idx = j
                break
            elif direction == -1 and highs[j] >= stop_price:
                exit_price = stop_price
                exit_time = bar_time
                exit_idx = j
                break

            if at_flatten or new_day:
                exit_price = closes[j - 1] if j > i + 1 else closes[i + 1]
                exit_time = index[j - 1] if j > i + 1 else index[i + 1]
                exit_idx = j
                break

        if exit_price is None:
            # Reached end of data — exit at last close
            exit_price = closes[-1]
            exit_time = index[-1]
            exit_idx = len(df) - 1

        gross_pnl = direction * (exit_price - entry_price) * POINT_VALUE * contracts
        cost = ROUND_TRIP_COST_USD * cost_multiplier * contracts
        net_pnl = gross_pnl - cost

        trades.append(TradeResult(
            entry_time=entry_time,
            exit_time=exit_time,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            gross_pnl=gross_pnl,
            cost=cost,
            net_pnl=net_pnl,
        ))

        daily_trades[day_key] = daily_trades.get(day_key, 0) + 1
        daily_pnl[day_key] = daily_pnl.get(day_key, 0.0) + net_pnl

        i = exit_idx

    return trades


def _compute_stats(trades: list[TradeResult]) -> BacktestStats:
    if not trades:
        return BacktestStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    pnls = [t.net_pnl for t in trades]
    gross_pnls = [t.gross_pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_pnl = sum(gross_pnls)
    total_cost = sum(t.cost for t in trades)
    net_pnl = sum(pnls)
    win_rate = len(wins) / len(pnls)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf")

    # Max drawdown on cumulative net P&L
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    drawdown = cum - peak
    max_drawdown = float(drawdown.min())

    # Daily Sharpe (annualized)
    daily_pnl_map: dict[str, float] = {}
    for t in trades:
        day = str(t.entry_time.date())
        daily_pnl_map[day] = daily_pnl_map.get(day, 0.0) + t.net_pnl
    daily_series = list(daily_pnl_map.values())
    if len(daily_series) > 1 and np.std(daily_series) > 0:
        sharpe = (np.mean(daily_series) / np.std(daily_series)) * np.sqrt(252)
    else:
        sharpe = 0.0

    return BacktestStats(
        total_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        gross_pnl=gross_pnl,
        total_cost=total_cost,
        net_pnl=net_pnl,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        sharpe=sharpe,
    )


def run_is_oos(
    df: pd.DataFrame,
    is_fraction: float = 0.70,
    stop_loss_usd: float | None = None,
    contracts: int = 1,
    stop_points: float | None = None,
    target_points: float | None = None,
    min_extension: float | None = None,
) -> tuple[BacktestStats, BacktestStats, list[TradeResult], list[TradeResult]]:
    """
    Split into in-sample / out-of-sample and run backtest on each.

    Returns: (is_stats, oos_stats, is_trades, oos_trades)
    """
    split = int(len(df) * is_fraction)
    is_df = df.iloc[:split]
    oos_df = df.iloc[split:]

    kw = dict(stop_loss_usd=stop_loss_usd, contracts=contracts,
              stop_points=stop_points, target_points=target_points,
              min_extension=min_extension)
    is_trades = _simulate_trades(is_df, **kw)
    oos_trades = _simulate_trades(oos_df, **kw)

    return _compute_stats(is_trades), _compute_stats(oos_trades), is_trades, oos_trades


def run_walk_forward(
    df: pd.DataFrame,
    fold_months: int = 6,
    is_fraction: float = 0.70,
    stop_loss_usd: float | None = None,
    contracts: int = 1,
    stop_points: float | None = None,
    target_points: float | None = None,
    min_extension: float | None = None,
) -> list[dict]:
    """
    Expanding-window walk-forward evaluation.
    """
    results = []
    df = df.copy()
    df.index = pd.to_datetime(df.index)

    start = df.index.min()
    end = df.index.max()

    fold_start = start
    while True:
        fold_end = fold_start + pd.DateOffset(months=fold_months)
        if fold_end > end:
            break

        fold_df = df[df.index < fold_end]
        split = int(len(fold_df) * is_fraction)
        oos_df = fold_df.iloc[split:]

        if len(oos_df) < 10:
            fold_start = fold_end
            continue

        oos_trades = _simulate_trades(oos_df, stop_loss_usd=stop_loss_usd, contracts=contracts,
                                      stop_points=stop_points, target_points=target_points,
                                      min_extension=min_extension)
        stats = _compute_stats(oos_trades)

        results.append({
            "fold_end": fold_end.strftime("%Y-%m-%d"),
            "oos_start": oos_df.index.min().strftime("%Y-%m-%d"),
            "oos_end": oos_df.index.max().strftime("%Y-%m-%d"),
            "trades": stats.total_trades,
            "win_rate": stats.win_rate,
            "net_pnl": stats.net_pnl,
            "sharpe": stats.sharpe,
            "max_drawdown": stats.max_drawdown,
        })

        fold_start = fold_end

    return results


def cost_sensitivity_table(
    df: pd.DataFrame,
    multipliers: tuple[float, ...] = (0.0, 0.5, 1.0, 1.5, 2.0),
    stop_loss_usd: float | None = None,
    contracts: int = 1,
    stop_points: float | None = None,
    target_points: float | None = None,
    min_extension: float | None = None,
) -> pd.DataFrame:
    """
    Show net P&L at various cost multiples to assess cost sensitivity.
    """
    rows = []
    for mult in multipliers:
        trades = _simulate_trades(df, cost_multiplier=mult,
                                  stop_loss_usd=stop_loss_usd, contracts=contracts,
                                  stop_points=stop_points, target_points=target_points,
                                  min_extension=min_extension)
        stats = _compute_stats(trades)
        assumed_cost = ROUND_TRIP_COST_USD * mult * contracts
        rows.append({
            "cost_multiple": mult,
            "assumed_round_trip_usd": round(assumed_cost, 2),
            "trades": stats.total_trades,
            "net_pnl": round(stats.net_pnl, 2),
            "win_rate": round(stats.win_rate, 3),
            "profit_factor": round(stats.profit_factor, 2),
            "max_drawdown": round(stats.max_drawdown, 2),
            "sharpe": round(stats.sharpe, 2),
        })
    return pd.DataFrame(rows)


def run_scenario(
    df: pd.DataFrame,
    label: str,
    stop_loss_usd: float | None = None,
    contracts: int = 1,
    stop_points: float | None = None,
    target_points: float | None = None,
    min_extension: float | None = None,
) -> None:
    """Print a full report for one trading scenario (instrument + stop + contracts)."""
    _stop = stop_points if stop_points is not None else STOP_POINTS
    _tgt  = target_points if target_points is not None else TARGET_POINTS
    _ext  = min_extension if min_extension is not None else MIN_BAR2_EXTENSION_POINTS
    stop_usd = stop_loss_usd if stop_loss_usd is not None else _stop * POINT_VALUE * contracts
    print(f"\n{'#'*60}")
    print(f"  SCENARIO: {label}")
    print(f"  Stop: {_stop}pt (${stop_usd:.0f})  Target: {_tgt}pt  "
          f"Min ext: {_ext}pt  Contracts: {contracts}")
    print(f"  Point value: ${POINT_VALUE}/pt  |  R:R {_tgt/_stop:.1f}:1")
    print(f"{'#'*60}")

    kw = dict(stop_loss_usd=stop_loss_usd, contracts=contracts,
              stop_points=stop_points, target_points=target_points,
              min_extension=min_extension)
    is_stats, oos_stats, _, _ = run_is_oos(df, **kw)
    wf = run_walk_forward(df, **kw)
    cost_table = cost_sensitivity_table(df, **kw)
    print_report(is_stats, oos_stats, wf, cost_table)


def print_report(
    is_stats: BacktestStats,
    oos_stats: BacktestStats,
    wf_results: list[dict],
    cost_table: pd.DataFrame,
) -> None:
    """Print a formatted backtest report to stdout."""
    def _fmt(stats: BacktestStats, label: str) -> None:
        print(f"\n{'='*50}")
        print(f"  {label}")
        print(f"{'='*50}")
        print(f"  Trades:         {stats.total_trades}")
        print(f"  Win Rate:       {stats.win_rate:.1%}")
        print(f"  Gross P&L:      ${stats.gross_pnl:,.2f}")
        print(f"  Total Cost:     ${stats.total_cost:,.2f}")
        print(f"  Net P&L:        ${stats.net_pnl:,.2f}")
        print(f"  Avg Win:        ${stats.avg_win:,.2f}")
        print(f"  Avg Loss:       ${stats.avg_loss:,.2f}")
        print(f"  Profit Factor:  {stats.profit_factor:.2f}")
        print(f"  Max Drawdown:   ${stats.max_drawdown:,.2f}")
        print(f"  Sharpe (ann):   {stats.sharpe:.2f}")

    _fmt(is_stats, "IN-SAMPLE RESULTS")
    _fmt(oos_stats, "OUT-OF-SAMPLE RESULTS")

    print(f"\n{'='*50}")
    print("  WALK-FORWARD SUMMARY (OOS folds)")
    print(f"{'='*50}")
    if wf_results:
        wf_df = pd.DataFrame(wf_results)
        print(wf_df.to_string(index=False))
    else:
        print("  (no folds)")

    print(f"\n{'='*50}")
    print("  COST SENSITIVITY TABLE")
    print(f"{'='*50}")
    print(cost_table.to_string(index=False))
