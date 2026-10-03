"""Tests for the history downloader (offline / unit tests only — no IB connection)."""
import pandas as pd
import pytest

from src.data.download_history import _back_adjust, _quarterly_expiries
from datetime import date


def test_quarterly_expiries_includes_expected():
    expiries = _quarterly_expiries(date(2024, 1, 1), date(2024, 12, 31))
    assert "202403" in expiries
    assert "202406" in expiries
    assert "202409" in expiries
    assert "202412" in expiries


def test_quarterly_expiries_sorted():
    expiries = _quarterly_expiries(date(2023, 1, 1), date(2024, 12, 31))
    assert expiries == sorted(expiries)


def test_back_adjust_single_segment():
    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-02", periods=5, freq="5min"),
        "open": [100.0] * 5,
        "high": [101.0] * 5,
        "low": [99.0] * 5,
        "close": [100.5] * 5,
        "volume": [100] * 5,
        "contract": ["202403"] * 5,
    })
    result = _back_adjust([df])
    assert len(result) == 5
    assert list(result["close"]) == [100.5] * 5


def test_back_adjust_two_segments_continuous():
    seg1 = pd.DataFrame({
        "datetime": pd.date_range("2024-01-02 09:30", periods=3, freq="5min"),
        "open": [100.0, 101.0, 102.0],
        "high": [101.0, 102.0, 103.0],
        "low":  [ 99.0, 100.0, 101.0],
        "close":[100.5, 101.5, 102.5],
        "volume": [100, 100, 100],
        "contract": ["202403"] * 3,
    })
    # New contract opens 1 point higher — seg1 prices should shift up by 1
    seg2 = pd.DataFrame({
        "datetime": pd.date_range("2024-01-02 09:45", periods=3, freq="5min"),
        "open": [103.5, 104.0, 105.0],  # first open = 103.5, seg1 last close = 102.5 → gap = 1
        "high": [104.0, 105.0, 106.0],
        "low":  [103.0, 103.5, 104.5],
        "close":[103.8, 104.5, 105.5],
        "volume": [100, 100, 100],
        "contract": ["202406"] * 3,
    })
    result = _back_adjust([seg1, seg2])
    assert len(result) == 6
    # After adjustment seg1 closes should be shifted up by 1 (gap = 103.5 - 102.5 = 1.0)
    assert abs(result.iloc[2]["close"] - 103.5) < 1e-6


def test_back_adjust_empty_segments():
    result = _back_adjust([])
    assert result.empty


def test_back_adjust_deduplicates():
    df = pd.DataFrame({
        "datetime": pd.to_datetime(["2024-01-02 09:30", "2024-01-02 09:30", "2024-01-02 09:35"]),
        "open": [100.0, 100.0, 101.0],
        "high": [101.0, 101.0, 102.0],
        "low":  [ 99.0,  99.0, 100.0],
        "close":[100.5, 100.5, 101.5],
        "volume": [100, 100, 100],
        "contract": ["202403"] * 3,
    })
    result = _back_adjust([df])
    assert len(result) == 2
