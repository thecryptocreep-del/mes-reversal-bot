import sys, pandas as pd
sys.path.insert(0, '.')
from src.backtest.engine import run_is_oos

df = pd.read_csv('data/raw/NQ_5min_continuous.csv', index_col=0, parse_dates=True)

print(f"{'ext':>6} | {'IS trades':>9} {'IS WR':>6} {'IS PF':>6} {'IS net':>8} | {'OOS trades':>10} {'OOS WR':>7} {'OOS PF':>7} {'OOS net':>8}")
print("-" * 80)

for ext in [0.0, 2.0, 3.0, 5.0]:
    is_stats, oos_stats, is_t, oos_t = run_is_oos(
        df, stop_points=40.0, target_points=60.0, min_extension=ext
    )
    print(
        f"{ext:>6} | {len(is_t):>9} {is_stats.win_rate:>6.0%} {is_stats.profit_factor:>6.2f} {is_stats.net_pnl:>8.0f} |"
        f" {len(oos_t):>10} {oos_stats.win_rate:>7.0%} {oos_stats.profit_factor:>7.2f} {oos_stats.net_pnl:>8.0f}"
    )
