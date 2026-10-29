"""Tests for key_levels module."""
from __future__ import annotations

import pandas as pd
import pytest
from src.strategy.key_levels import DayLevels, build_level_map, bar2_at_level


def _make_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df.pop("time"))
    return df


# ---------------------------------------------------------------------------
# bar2_at_level
# ---------------------------------------------------------------------------

def test_short_bar2_high_at_pdh():
    levels = DayLevels(date=pd.Timestamp("2024-01-02"), pdh=20100.0)
    # bar2 high poked into PDH (within 10pts)
    assert bar2_at_level(20095.0, 20050.0, signal_direction=-1, levels=levels, proximity_points=10.0)


def test_short_bar2_high_far_from_levels():
    levels = DayLevels(date=pd.Timestamp("2024-01-02"), pdh=20100.0)
    assert not bar2_at_level(19980.0, 19940.0, signal_direction=-1, levels=levels, proximity_points=10.0)


def test_long_bar2_low_at_pdl():
    levels = DayLevels(date=pd.Timestamp("2024-01-02"), pdl=19900.0)
    assert bar2_at_level(19950.0, 19905.0, signal_direction=1, levels=levels, proximity_points=10.0)


def test_long_bar2_low_far_from_levels():
    levels = DayLevels(date=pd.Timestamp("2024-01-02"), pdl=19900.0)
    assert not bar2_at_level(20050.0, 20010.0, signal_direction=1, levels=levels, proximity_points=10.0)


def test_no_levels_returns_false():
    levels = DayLevels(date=pd.Timestamp("2024-01-02"))
    assert not bar2_at_level(20000.0, 19980.0, signal_direction=-1, levels=levels)


def test_proximity_exactly_at_boundary():
    levels = DayLevels(date=pd.Timestamp("2024-01-02"), pdh=20100.0)
    # bar2_high = 20090, pdh = 20100, diff = 10 — exactly at boundary → True
    assert bar2_at_level(20090.0, 20050.0, signal_direction=-1, levels=levels, proximity_points=10.0)


def test_multiple_levels_any_match():
    levels = DayLevels(date=pd.Timestamp("2024-01-02"), pdh=20200.0, orh=20050.0)
    # bar2_high near ORH, far from PDH
    assert bar2_at_level(20055.0, 20010.0, signal_direction=-1, levels=levels, proximity_points=10.0)


# ---------------------------------------------------------------------------
# build_level_map
# ---------------------------------------------------------------------------

def _sample_df():
    """Two days of 5-min bars: Jan 2 and Jan 3 2024."""
    rows = []
    # Day 1: Jan 2 — 9:30–10:00 (6 bars)
    times_d1 = pd.date_range("2024-01-02 09:30", periods=6, freq="5min")
    for i, t in enumerate(times_d1):
        rows.append({"time": t, "open": 100 + i, "high": 105 + i, "low": 98 + i, "close": 102 + i, "volume": 100})
    # Day 2: Jan 3 — 9:30–10:00
    times_d2 = pd.date_range("2024-01-03 09:30", periods=6, freq="5min")
    for i, t in enumerate(times_d2):
        rows.append({"time": t, "open": 110 + i, "high": 115 + i, "low": 108 + i, "close": 112 + i, "volume": 100})
    return _make_df(rows)


def test_build_level_map_keys():
    df = _sample_df()
    lm = build_level_map(df)
    assert "2024-01-02" in lm
    assert "2024-01-03" in lm


def test_day1_no_prior_day():
    df = _sample_df()
    lm = build_level_map(df)
    d1 = lm["2024-01-02"]
    assert d1.pdh is None
    assert d1.pdl is None
    assert d1.pdc is None


def test_day2_has_prior_day():
    df = _sample_df()
    lm = build_level_map(df)
    d2 = lm["2024-01-03"]
    assert d2.pdh is not None
    assert d2.pdl is not None
    assert d2.pdc is not None


def test_day2_pdh_equals_day1_max_high():
    df = _sample_df()
    lm = build_level_map(df)
    d1_bars = df[df.index.normalize() == pd.Timestamp("2024-01-02")]
    expected_pdh = d1_bars["high"].max()
    assert lm["2024-01-03"].pdh == pytest.approx(expected_pdh)


def test_opening_range_computed():
    df = _sample_df()
    lm = build_level_map(df)
    d1 = lm["2024-01-02"]
    assert d1.orh is not None
    assert d1.orl is not None
    assert d1.orh >= d1.orl
