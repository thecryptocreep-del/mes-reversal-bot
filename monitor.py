"""
Live bot monitor — run in a second terminal alongside the bot.

    python monitor.py

Reads the latest log file in logs/ and refreshes every 5 seconds.
No extra dependencies — pure Python stdlib.
"""
import glob
import os
import re
import time
from datetime import datetime

_REFRESH = 5  # seconds


def latest_log() -> str | None:
    files = sorted(glob.glob("logs/bot_*.log"))
    return files[-1] if files else None


def parse_log(path: str) -> dict:
    bars = []
    signals = []
    orders = []
    errors = []
    reconnects = 0

    bar_re    = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] O=([\d.]+) H=([\d.]+) L=([\d.]+) C=([\d.]+) V=(\d+) \| trades=(\d+)/(\d+) pnl=\$([\d.+-]+)")
    signal_re = re.compile(r"SIGNAL (\w+) @ ([\d.]+)\s+stop=([\d.]+)\s+tgt=([\d.]+)")
    grade_re  = re.compile(r"Signal grade: (\S+) → (\d+) contract")
    order_re  = re.compile(r"Bracket placed: entry orderId=(\d+)")
    error_re  = re.compile(r"\[ERROR\].+?:\s+(.+)")
    recon_re  = re.compile(r"LiveFeed reconnecting")

    last_grade = ("C", "1")

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = bar_re.search(line)
            if m:
                bars.append({
                    "ts": m.group(1), "o": m.group(2), "h": m.group(3),
                    "l": m.group(4),  "c": m.group(5), "v": m.group(6),
                    "trades": m.group(7), "max": m.group(8), "pnl": m.group(9),
                })
            m = grade_re.search(line)
            if m:
                last_grade = (m.group(1), m.group(2))
            m = signal_re.search(line)
            if m:
                signals.append({
                    "dir": m.group(1), "entry": m.group(2),
                    "stop": m.group(3), "tgt": m.group(4),
                    "grade": last_grade[0], "qty": last_grade[1],
                    "ts": line[:19],
                })
            m = order_re.search(line)
            if m:
                orders.append({"id": m.group(1), "ts": line[:19]})
            m = error_re.search(line)
            if m:
                errors.append(line.strip()[-120:])
            if recon_re.search(line):
                reconnects += 1

    return {
        "bars": bars,
        "signals": signals,
        "orders": orders,
        "errors": errors[-5:],
        "reconnects": reconnects,
    }


def render(data: dict, log_path: str) -> str:
    W = 72
    bars     = data["bars"]
    signals  = data["signals"]
    orders   = data["orders"]
    errors   = data["errors"]

    lines = []
    div  = "─" * W
    def hdr(t): lines.append(f"  {t}")
    def row(t): lines.append(f"  {t}")
    def sep():  lines.append(div)

    lines.append(div)
    hdr(f"3-BAR REVERSAL BOT MONITOR   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    hdr(f"Log: {os.path.basename(log_path)}   Reconnects: {data['reconnects']}")
    sep()

    # Latest bars
    hdr("RECENT BARS  (last 6)")
    if bars:
        hdr(f"  {'Time':<17} {'Open':>8} {'High':>8} {'Low':>8} {'Close':>8} {'Vol':>7}")
        sep()
        for b in bars[-6:]:
            row(f"  {b['ts']:<17} {b['o']:>8} {b['h']:>8} {b['l']:>8} {b['c']:>8} {b['v']:>7}")
        latest = bars[-1]
        hdr(f"\n  Trades today: {latest['trades']}/{latest['max']}   P&L: ${latest['pnl']}")
    else:
        row("  No bars yet")
    sep()

    # Signals
    hdr(f"SIGNALS TODAY  ({len(signals)} total)")
    if signals:
        hdr(f"  {'Time':<19} {'Dir':<6} {'Grade':<5} {'Qty':<4} {'Entry':>8} {'Stop':>8} {'Target':>8}")
        sep()
        for s in signals[-8:]:
            row(f"  {s['ts']:<19} {s['dir']:<6} {s['grade']:<5} {s['qty']:<4} {s['entry']:>8} {s['stop']:>8} {s['tgt']:>8}")
    else:
        row("  No signals yet")
    sep()

    # Orders placed
    hdr(f"ORDERS PLACED  ({len(orders)} total)")
    if orders:
        for o in orders[-5:]:
            row(f"  {o['ts']}  orderId={o['id']}")
    else:
        row("  None")
    sep()

    # Errors
    if errors:
        hdr("RECENT ERRORS")
        for e in errors:
            row(f"  {e[-W+4:]}")
        sep()

    hdr(f"Refreshing every {_REFRESH}s — Ctrl+C to exit")
    lines.append(div)
    return "\n".join(lines)


def main() -> None:
    print("Bot monitor starting — looking for log files in logs/")
    while True:
        try:
            path = latest_log()
            if not path:
                print("No log file found yet. Waiting for bot to start...")
            else:
                data = parse_log(path)
                os.system("cls" if os.name == "nt" else "clear")
                print(render(data, path))
        except KeyboardInterrupt:
            print("\nMonitor stopped.")
            break
        except Exception as exc:
            print(f"Monitor error: {exc}")
        time.sleep(_REFRESH)


if __name__ == "__main__":
    main()
