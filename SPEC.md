# MES Three-Bar Reversal Bot — Specification

## Overview
Automated futures trading bot for Micro E-mini S&P 500 (MES) on Interactive Brokers.
**PAPER ACCOUNT ONLY** until explicitly enabled otherwise.

## Pattern: Three-Bar Reversal
On a 5-minute chart, a valid signal requires:
1. **Bar 1**: Establishes the extreme (high or low)
2. **Bar 2**: Closes beyond Bar 1's extreme (continuation)
3. **Bar 3**: Reverses and closes back through Bar 1's extreme

Long signal: Bar 3 closes above Bar 1's high after Bar 2 closed below it.
Short signal: Bar 3 closes below Bar 1's low after Bar 2 closed above it.

**Do not change this pattern definition without explicit approval.**

## Instrument
- Symbol: MES (Micro E-mini S&P 500)
- Exchange: CME GLOBEX
- Currency: USD
- Bar size: 5 minutes
- Contract: front month, rolled before expiration

## Contract Roll Rules
- MES expires quarterly: March (H), June (M), September (U), December (Z)
- Roll N days before expiration (configurable, default 4 business days)
- On roll day: close prior contract, open new contract at market open
- History CSV: continuous adjusted series — back-adjust prices on roll

## Risk Rules (hard-coded, not model-overridable)
- Max position: 1 contract
- Daily loss limit: $150
- Max trades per day: 6
- Flatten time: 15:55 ET (5 min before CME equity close)
- No overnight positions

## Commissions & Slippage (backtest)
- Commission: $0.62 per side ($1.24 round-trip) — IB MES rate
- Slippage: 0.25 points per side (1 tick) = $1.25 per side

## Jev (AI filter) — SHADOW MODE ONLY
- Log Jev signal alongside each trade signal
- Never act on Jev output until explicitly approved
- Shadow log location: `data/jev_shadow.jsonl`

## Out-of-Sample / Walk-Forward Evaluation
- In-sample: first 70% of history
- Out-of-sample: last 30%
- Walk-forward: expanding window, 6-month folds
- Report IS and OOS results separately; never blend them
- Cost-sensitivity table: show net P&L at 0×, 0.5×, 1×, 1.5×, 2× assumed cost

## Data
- Source: Interactive Brokers (paper account)
- Downloader: `src/data/download_history.py` using `ib_async`
- Output: `data/raw/MES_5min_continuous.csv`
- Columns: datetime, open, high, low, close, volume, contract

## Project Phases
- [x] Phase 0: Scaffold, SPEC, CLAUDE.md, tests baseline
- [ ] Phase 1: IB history downloader with contract rolls
- [ ] Phase 2: Backtester with walk-forward + cost-sensitivity
- [ ] Phase 3: Live paper trading loop (shadow mode)
- [ ] Phase 4: Jev integration (shadow only)
- [ ] Phase 5: Live mode (explicit approval required)
