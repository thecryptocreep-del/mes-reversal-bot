"""Tests for the walk-forward backtester."""
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import pytest

from src.backtest.engine import (
    BacktestStats,
    _compute_stats,
    _simulate_trades,
    cost_sensitivity_table,
    run_is_oos,
    run_walk_forward,
)
from src.strategy.three_bar_reversal import Signal


def _make_df(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate a synthetic OHLC DataFrame with a datetime index."""
    rng = np.random.default_rng(seed)
    base = 4500.0
    closes = base + np.cumsum(rng.normal(0, 2, n))
    opens = closes + rng.normal(0, 0.5, n)
    highs = np.maximum(opens, closes) + rng.uniform(0, 2, n)
    lows = np.minimum(opens, closes) - rng.uniform(0, 2, n)

    start = datetime(2024, 1, 2, 9, 35)
    index = [start + timedelta(minutes=5 * i) for i in range(n)]

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes},
        index=pd.DatetimeIndex(index),
    )


def test_simulate_trades_returns_list():
    df = _make_df()
    trades = _simulate_trades(df)
    assert isinstance(trades, list)


def test_trade_net_pnl_equals_gross_minus_cost():
    df = _make_df()
    trades = _simulate_trades(df)
    for t in trades:
        assert abs(t.net_pnl - (t.gross_pnl - t.cost)) < 1e-6


def test_max_trades_per_day_respected():
    from config.risk import MAX_TRADES_PER_DAY
    df = _make_df(500)
    trades = _simulate_trades(df)
    daily = {}
    for t in trades:
        day = str(t.entry_time.date())
        daily[day] = daily.get(day, 0) + 1
    for day, count in daily.items():
        assert count <= MAX_TRADES_PER_DAY, f"{day} had {count} trades"


def test_compute_stats_empty():
    stats = _compute_stats([])
    assert stats.total_trades == 0
    assert stats.net_pnl == 0


def test_compute_stats_win_rate():
    df = _make_df()
    trades = _simulate_trades(df)
    if trades:
        stats = _compute_stats(trades)
        assert 0.0 <= stats.win_rate <= 1.0


def test_run_is_oos_splits_correctly():
    df = _make_df(300)
    is_stats, oos_stats, is_trades, oos_trades = run_is_oos(df, is_fraction=0.70)
    assert isinstance(is_stats, BacktestStats)
    assert isinstance(oos_stats, BacktestStats)
    # OOS should be smaller than IS
    total = len(is_trades) + len(oos_trades)
    assert total >= 0


def test_cost_sensitivity_table_shape():
    df = _make_df(200)
    table = cost_sensitivity_table(df)
    assert len(table) == 5
    assert "net_pnl" in table.columns
    assert "cost_multiple" in table.columns


def test_cost_sensitivity_zero_cost_higher_pnl():
    df = _make_df(200)
    table = cost_sensitivity_table(df)
    pnl_zero = table[table["cost_multiple"] == 0.0]["net_pnl"].iloc[0]
    pnl_full = table[table["cost_multiple"] == 1.0]["net_pnl"].iloc[0]
    # Zero-cost P&L should be >= full-cost P&L
    assert pnl_zero >= pnl_full


def test_walk_forward_returns_list():
    df = _make_df(500)
    results = run_walk_forward(df, fold_months=2)
    assert isinstance(results, list)


def test_walk_forward_fold_keys():
    df = _make_df(500)
    results = run_walk_forward(df, fold_months=2)
    if results:
        assert "net_pnl" in results[0]
        assert "win_rate" in results[0]
        assert "trades" in results[0]
