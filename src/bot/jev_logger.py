"""
Jev shadow-mode logger.

SHADOW MODE ONLY — logs Jev signal data to data/jev_shadow.jsonl.
This module NEVER influences order execution.
See SPEC.md: "Never act on Jev output until explicitly approved."
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional

from src.strategy.three_bar_reversal import Bar, Signal

logger = logging.getLogger(__name__)

_SHADOW_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "jev_shadow.jsonl"
)


class JevLogger:
    """
    Appends Jev shadow-mode records to data/jev_shadow.jsonl.

    log_signal() is the only public method.
    This class contains NO logic that affects order placement.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or _SHADOW_LOG
        os.makedirs(os.path.dirname(os.path.abspath(self._path)), exist_ok=True)

    def log_signal(
        self,
        timestamp: datetime,
        signal: Signal,
        bar1: Bar,
        bar2: Bar,
        bar3: Bar,
        entry_price: float,
        jev_signal: Optional[str] = None,
    ) -> None:
        """
        Append one record to data/jev_shadow.jsonl.

        Args:
            timestamp: bar-close time (UTC recommended)
            signal: the three-bar reversal signal
            bar1, bar2, bar3: the three bars
            entry_price: intended entry price
            jev_signal: placeholder for future Jev output (None = not yet integrated)
        """
        record: dict[str, Any] = {
            "timestamp": timestamp.isoformat(),
            "signal": signal.name,
            "entry_price": entry_price,
            "bar1": {"open": bar1.open, "high": bar1.high, "low": bar1.low, "close": bar1.close},
            "bar2": {"open": bar2.open, "high": bar2.high, "low": bar2.low, "close": bar2.close},
            "bar3": {"open": bar3.open, "high": bar3.high, "low": bar3.low, "close": bar3.close},
            "jev_signal": jev_signal,  # placeholder — never acted upon
        }
        try:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError as exc:
            logger.error("JevLogger write error: %s", exc)
