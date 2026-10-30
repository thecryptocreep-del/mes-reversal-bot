"""
Fetch prior-day OHLC for key level seeding at bot startup.

Uses yfinance (NQ=F proxy for MNQ) so no extra API subscription is needed.
Falls back gracefully if the fetch fails — bot still runs without PDH/PDL.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Map internal symbol → yfinance ticker
_YF_SYMBOL_MAP = {
    "MNQ": "NQ=F",
    "MES": "ES=F",
    "MYM": "YM=F",
    "M2K": "RTY=F",
}


def fetch_prior_day(symbol: str) -> dict[str, Optional[float]]:
    """
    Return {"pdh": float, "pdl": float, "pdc": float} for the most recent
    completed trading day, or all-None on failure.
    """
    empty = {"pdh": None, "pdl": None, "pdc": None}
    try:
        import yfinance as yf
        yf_sym = _YF_SYMBOL_MAP.get(symbol.upper(), f"{symbol.upper()}=F")
        ticker = yf.Ticker(yf_sym)
        # Pull 5 days to ensure we get at least one completed session
        hist = ticker.history(period="5d", interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < 1:
            logger.warning("prior_day: no data returned for %s", yf_sym)
            return empty
        # Use second-to-last row if today is in the data, else last row
        row = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]
        pdh = float(row["High"])
        pdl = float(row["Low"])
        pdc = float(row["Close"])
        logger.info("Prior day levels: PDH=%.2f  PDL=%.2f  PDC=%.2f", pdh, pdl, pdc)
        return {"pdh": pdh, "pdl": pdl, "pdc": pdc}
    except Exception as exc:
        logger.warning("prior_day fetch failed (%s) — running without PDH/PDL/PDC", exc)
        return empty
