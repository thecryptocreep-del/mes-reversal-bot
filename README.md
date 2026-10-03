# mes-reversal-bot

5-minute three-bar reversal futures bot for MES (Micro E-mini S&P 500) via Interactive Brokers.

**PAPER ACCOUNT ONLY** — live mode requires `LIVE_MODE=1` and explicit approval.

## Quick Start

```bash
git clone https://github.com/thecryptocreep-del/mes-reversal-bot
cd mes-reversal-bot
pip install -r requirements.txt
```

### Option A: Yahoo Finance data (no IB account needed)
```bash
# Downloads last ~60 days of 5-min MES bars
python -m src.data.download_yahoo

# Or get years of daily bars for longer backtest
python -m src.data.download_yahoo --interval 1d
```

### Option B: IB Gateway (paper account)
1. Start IB Gateway, log in to paper account, enable API on port 4002
2. Run:
```bash
python -m src.data.download_history
```

### Run the backtest
```bash
python -c "
import pandas as pd
from src.backtest.engine import run_is_oos, run_walk_forward, cost_sensitivity_table, print_report

df = pd.read_csv('data/raw/MES_5min_continuous.csv', index_col='datetime', parse_dates=True)
is_stats, oos_stats, _, _ = run_is_oos(df)
wf = run_walk_forward(df)
cost_table = cost_sensitivity_table(df)
print_report(is_stats, oos_stats, wf, cost_table)
"
```

### Run tests
```bash
pytest -v
```

## Project Structure
See `CLAUDE.md` for full layout and hard rules.
See `SPEC.md` for pattern definition, risk limits, and phase plan.
