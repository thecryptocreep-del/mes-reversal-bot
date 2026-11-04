"""
Live bot monitor — run in a second terminal alongside the bot.

    python monitor.py

Reads the latest log file in logs/ and refreshes every 5 s.
Shows individual trade results: entry, exit type, P&L per trade.
No extra dependencies — pure Python stdlib.
"""
import glob
import os
import re
import time
from datetime import datetime

_REFRESH = 5  # seconds
_W = 76


# ─────────────────────────────────────────────────────────
# Log parsing
# ─────────────────────────────────────────────────────────

def latest_log() -> str | None:
    files = sorted(glob.glob("logs/bot_*.log"))
    return files[-1] if files else None


def parse_log(path: str) -> dict:
    bars      = []
    trades    = []   # one entry per SIGNAL line
    errors    = []
    reconnects = 0

    # Regexes
    bar_re      = re.compile(
        r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] O=([\d.]+) H=([\d.]+) L=([\d.]+) C=([\d.]+) V=(\d+)"
        r" \| trades=(\d+)/(\d+) pnl=\$([\d.+-]+)"
    )
    # "Signal: LONG  mode=aggressive  grade=C  qty=1"
    sig_meta_re = re.compile(
        r"Signal: (\w+)\s+mode=(\S+)\s+grade=(\S+)\s+qty=(\d+)"
    )
    # "SIGNAL LONG @ 28414.00  stop=28374.00  tgt=28474.00  mode=aggressive"
    signal_re   = re.compile(
        r"SIGNAL (\w+) @ ([\d.]+)\s+stop=([\d.]+)\s+tgt=([\d.]+)"
    )
    # "Bracket placed: entry=12345 stop=12346 (TP managed in software)"
    bracket_re  = re.compile(
        r"Bracket placed: entry=(\d+) stop=(\S+)"
    )
    # "TP hit: target=28474.00 bar H=28480.00 L=28460.00"
    tp_hit_re   = re.compile(
        r"TP hit: target=([\d.]+) bar H=([\d.]+) L=([\d.]+)"
    )
    # "Trade recorded: pnl=120.00 | daily trades=2 pnl=120.00"
    recorded_re = re.compile(
        r"Trade recorded: pnl=([\d.+-]+) \| daily trades=(\d+) pnl=([\d.+-]+)"
    )
    error_re    = re.compile(r"\[ERROR\].+?:\s+(.+)")
    recon_re    = re.compile(r"LiveFeed reconnecting")

    # State machines
    pending_meta = {}       # mode/grade/qty — set just before SIGNAL line
    open_trade: dict | None = None   # most recent trade awaiting outcome

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            ts = line[:19]

            m = bar_re.search(line)
            if m:
                bars.append({
                    "ts": m.group(1), "o": m.group(2), "h": m.group(3),
                    "l": m.group(4),  "c": m.group(5), "v": m.group(6),
                    "trades": m.group(7), "max": m.group(8), "pnl": m.group(9),
                })
                continue

            m = sig_meta_re.search(line)
            if m:
                pending_meta = {
                    "mode": m.group(2), "grade": m.group(3), "qty": m.group(4),
                }
                continue

            m = signal_re.search(line)
            if m:
                # Mark prior open trade as "STOP?" if it never got a TP
                if open_trade and open_trade["outcome"] == "OPEN":
                    open_trade["outcome"] = "SL?"

                trade = {
                    "num":     len(trades) + 1,
                    "ts":      ts,
                    "dir":     m.group(1),
                    "entry":   float(m.group(2)),
                    "stop":    float(m.group(3)),
                    "target":  float(m.group(4)),
                    "mode":    pending_meta.get("mode", "?"),
                    "grade":   pending_meta.get("grade", "?"),
                    "qty":     int(pending_meta.get("qty", 1)),
                    "entry_id": None,
                    "stop_id":  None,
                    "outcome":  "OPEN",
                    "exit_px":  None,
                    "pnl":      None,
                }
                trades.append(trade)
                open_trade = trade
                pending_meta = {}
                continue

            m = bracket_re.search(line)
            if m and open_trade:
                open_trade["entry_id"] = m.group(1)
                open_trade["stop_id"]  = m.group(2).rstrip(")")
                continue

            m = tp_hit_re.search(line)
            if m and open_trade:
                open_trade["outcome"]  = "TP ✓"
                open_trade["exit_px"]  = float(m.group(1))
                continue

            m = recorded_re.search(line)
            if m and open_trade:
                pnl_val = float(m.group(1))
                if pnl_val > 0:
                    open_trade["pnl"] = pnl_val
                    if open_trade["outcome"] == "OPEN":
                        open_trade["outcome"] = "TP ✓"
                continue

            m = error_re.search(line)
            if m:
                errors.append(line.strip()[-120:])
                continue

            if recon_re.search(line):
                reconnects += 1

    return {
        "bars":       bars,
        "trades":     trades,
        "errors":     errors[-5:],
        "reconnects": reconnects,
    }


# ─────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────

_MODE_ABBR = {
    "standard":     "STD ",
    "aggressive":   "AGGR",
    "anticipation": "ANT ",
    "?":            "?   ",
}

_OUTCOME_STYLE = {
    "TP ✓":  "TP ✓ ",
    "SL?":   "SL?  ",
    "OPEN":  "OPEN ",
}


def _fmt_pnl(trade: dict) -> str:
    if trade["pnl"] is not None:
        sign = "+" if trade["pnl"] >= 0 else ""
        return f"{sign}${trade['pnl']:.0f}"
    if trade["outcome"] == "SL?":
        pts = abs(trade["entry"] - trade["stop"])
        loss = -pts * trade["qty"] * 2.0  # MNQ $2/pt
        return f"~${loss:.0f}"
    return "  --"


def render(data: dict, log_path: str) -> str:
    bars   = data["bars"]
    trades = data["trades"]
    errors = data["errors"]

    lines = []
    div  = "─" * _W
    def row(t=""): lines.append(f"  {t}")
    def sep():     lines.append(div)
    def hdr(t):    lines.append(f"  {t}")

    sep()
    hdr(f"REVERSAL BOT MONITOR          {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    hdr(f"Log: {os.path.basename(log_path)}   Reconnects: {data['reconnects']}")
    sep()

    # Recent bars
    hdr("RECENT BARS  (last 6)")
    if bars:
        hdr(f"{'Time':<18} {'Open':>9} {'High':>9} {'Low':>9} {'Close':>9} {'Vol':>7}")
        sep()
        for b in bars[-6:]:
            row(f"{b['ts']:<18} {b['o']:>9} {b['h']:>9} {b['l']:>9} {b['c']:>9} {b['v']:>7}")
        latest = bars[-1]
        sep()
        hdr(f"Trades today: {latest['trades']}/{latest['max']}   Daily P&L: ${latest['pnl']}")
    else:
        row("No bars received yet")
    sep()

    # Per-trade results
    total_pnl = 0.0
    tps  = sum(1 for t in trades if t["outcome"] == "TP ✓")
    sls  = sum(1 for t in trades if t["outcome"] == "SL?")
    open_trades = sum(1 for t in trades if t["outcome"] == "OPEN")

    hdr(f"TRADES TODAY  ({len(trades)} total  |  TP: {tps}  SL: {sls}  Open: {open_trades})")
    if trades:
        sep()
        hdr(
            f"{'#':<3} {'Time':<8} {'Dir':<5} {'Mode':<5} {'Gr':<3} "
            f"{'Q':>2} {'Entry':>9} {'Stop':>9} {'Target':>9} "
            f"{'Exit':>9} {'Result':<7} {'P&L':>7}"
        )
        sep()
        for t in trades[-12:]:
            mode_s    = _MODE_ABBR.get(t["mode"], t["mode"][:4])
            outcome_s = _OUTCOME_STYLE.get(t["outcome"], t["outcome"])
            exit_s    = f"{t['exit_px']:.2f}" if t["exit_px"] else "  --"
            pnl_s     = _fmt_pnl(t)
            ts_short  = t["ts"][11:16] if len(t["ts"]) >= 16 else t["ts"]
            row(
                f"{t['num']:<3} {ts_short:<8} {t['dir']:<5} {mode_s:<5} {t['grade']:<3} "
                f"{t['qty']:>2} {t['entry']:>9.2f} {t['stop']:>9.2f} {t['target']:>9.2f} "
                f"{exit_s:>9} {outcome_s:<7} {pnl_s:>7}"
            )

        # Totals
        sep()
        tp_pnl  = sum(t["pnl"] for t in trades if t["pnl"] is not None)
        est_sl  = sum(
            abs(t["entry"] - t["stop"]) * t["qty"] * 2.0
            for t in trades if t["outcome"] == "SL?"
        )
        net = tp_pnl - est_sl
        hdr(f"TP proceeds: +${tp_pnl:.0f}   Est SL cost: -${est_sl:.0f}   Net est: {'+'  if net>=0 else ''}{net:.0f}")
    else:
        row("No trades today")
    sep()

    # Errors
    if errors:
        hdr("RECENT ERRORS")
        for e in errors:
            row(e[-(_W - 4):])
        sep()

    hdr(f"Refreshing every {_REFRESH}s — Ctrl+C to exit")
    lines.append(div)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────

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
