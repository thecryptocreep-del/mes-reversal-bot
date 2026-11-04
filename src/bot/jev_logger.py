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
        bar3: Optional[Bar],
        entry_price: float,
        mode: str = "standard",
        jev_signal: Optional[str] = None,
    ) -> None:
        """
        Append one record to data/jev_shadow.jsonl.

        Args:
            timestamp: bar-close time (UTC recommended)
            signal: the reversal signal
            bar1, bar2: always present (reference + extension/reversal bar)
            bar3: present for standard 3-bar only; None for 2-bar patterns
            entry_price: intended entry price
            mode: "standard" | "aggressive" | "anticipation"
            jev_signal: placeholder for future Jev output (None = not yet integrated)
        """

        def _bar_dict(b: Bar) -> dict[str, float]:
            return {"open": b.open, "high": b.high, "low": b.low, "close": b.close}

        record: dict[str, Any] = {
            "timestamp": timestamp.isoformat(),
            "signal": signal.name,
            "mode": mode,
            "entry_price": entry_price,
            "bar1": _bar_dict(bar1),
            "bar2": _bar_dict(bar2),
            "bar3": _bar_dict(bar3) if bar3 is not None else None,
            "jev_signal": jev_signal,  # placeholder — never acted upon
        }
        try:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError as exc:
            logger.error("JevLogger write error: %s", exc)
