"""
Desktop + email notifications for trading signals.

Desktop: Windows toast via win10toast (pip install win10toast)
         Falls back to a simple print if not on Windows or not installed.
Email:   SMTP — set ALERT_EMAIL_TO, ALERT_EMAIL_FROM, SMTP_HOST,
         SMTP_PORT, SMTP_USER, SMTP_PASS env vars to enable.
"""
from __future__ import annotations

import logging
import os
import smtplib
import threading
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_ALERT_EMAIL_TO   = os.getenv("ALERT_EMAIL_TO", "")
_ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
_SMTP_HOST        = os.getenv("SMTP_HOST", "smtp.gmail.com")
_SMTP_PORT        = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER        = os.getenv("SMTP_USER", "")
_SMTP_PASS        = os.getenv("SMTP_PASS", "")


def _toast(title: str, message: str) -> None:
    """Windows toast notification — silently skipped on non-Windows."""
    try:
        from win10toast import ToastNotifier  # type: ignore[import]
        notifier = ToastNotifier()
        notifier.show_toast(title, message, duration=10, threaded=True)
    except Exception:
        pass  # Not on Windows or win10toast not installed — no-op


def _send_email(subject: str, body: str) -> None:
    """Send email alert in a background thread so it never blocks the bot."""
    if not (_ALERT_EMAIL_TO and _SMTP_USER and _SMTP_PASS):
        return

    def _send() -> None:
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"]    = _ALERT_EMAIL_FROM or _SMTP_USER
            msg["To"]      = _ALERT_EMAIL_TO
            with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=10) as s:
                s.starttls()
                s.login(_SMTP_USER, _SMTP_PASS)
                s.send_message(msg)
            logger.info("Alert email sent to %s", _ALERT_EMAIL_TO)
        except Exception as exc:
            logger.warning("Email alert failed: %s", exc)

    threading.Thread(target=_send, daemon=True).start()


def send_signal_alert(
    direction: str,
    symbol: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    at_level: bool = True,
) -> None:
    """
    Fire desktop + email notification for a trading signal.

    Args:
        direction:    "LONG" or "SHORT"
        symbol:       e.g. "MNQ"
        entry_price:  bar4 open (estimated from bar3 close)
        stop_price:   stop loss price
        target_price: take profit price
        at_level:     whether signal passed the key level filter
    """
    level_tag = " [KEY LEVEL]" if at_level else ""
    title = f"3BR {direction}{level_tag} — {symbol}"
    body = (
        f"Signal:  {direction}{level_tag}\n"
        f"Symbol:  {symbol}\n"
        f"Entry:   {entry_price:.2f}  (Bar 4 open)\n"
        f"Stop:    {stop_price:.2f}\n"
        f"Target:  {target_price:.2f}\n"
    )

    logger.info("ALERT: %s  entry=%.2f  stop=%.2f  tgt=%.2f",
                title, entry_price, stop_price, target_price)
    _toast(title, body)
    _send_email(subject=title, body=body)
