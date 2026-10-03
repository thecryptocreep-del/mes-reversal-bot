# CLAUDE.md — mes-reversal-bot

## Hard Rules
- PAPER ACCOUNT ONLY. Never write code that places live orders unless `LIVE_MODE=1` env var is explicitly set AND the user has said "enable live mode" in this session.
- Risk limits (position size, daily loss, max trades, flatten time) live in `config/risk.py`. No model, filter, or strategy logic may override them.
- Jev is SHADOW MODE only: log its output to `data/jev_shadow.jsonl`, never act on it.
- Run `pytest` after every change. Add a test for every bug fixed.
- Never commit API keys, account numbers, `.env` files, or any credentials.
- Backtests must always include commissions and slippage (see SPEC.md). Report OOS results separately from IS.
- Ask before changing the three-bar reversal pattern definition.

## Development Workflow
1. Read SPEC.md before starting any new feature
2. Run `pytest` to confirm baseline before making changes
3. Make changes on the designated branch
4. Run `pytest` again after changes
5. Commit with clear messages and push

## Project Structure
```
mes-reversal-bot/
├── config/
│   ├── risk.py          # Hard risk limits — never override
│   └── settings.py      # IB connection, symbols, roll config
├── src/
│   ├── data/
│   │   └── download_history.py   # ib_async downloader
│   ├── strategy/
│   │   └── three_bar_reversal.py # Pattern detection
│   └── backtest/
│       └── engine.py             # Walk-forward backtester
├── tests/
│   ├── test_pattern.py
│   ├── test_risk.py
│   ├── test_downloader.py
│   └── test_backtest.py
├── data/
│   ├── raw/             # Downloaded CSVs
│   └── processed/       # Adjusted continuous series
├── SPEC.md
├── CLAUDE.md
├── requirements.txt
└── pyproject.toml
```

## Running Tests
```bash
pytest -v
```

## IB Gateway Connection
- Host: 127.0.0.1
- Paper port: 4002 (default)
- Live port: 4001 (never use unless LIVE_MODE=1)
- Client ID: configurable in config/settings.py
