import sys, pandas as pd
sys.path.insert(0, '.')
from src.backtest.engine import run_is_oos

df = pd.read_csv('data/raw/NQ_5min_continuous.csv', index_col=0, parse_dates=True)
print(f"Loaded {len(df)} bars  ({df.index[0].date()} → {df.index[-1].date()})\n")

header = f"{'Filter':>22} | {'IS trades':>9} {'IS WR':>6} {'IS PF':>6} {'IS net':>8} | {'OOS trades':>10} {'OOS WR':>7} {'OOS PF':>7} {'OOS net':>8}"
print(header)
print("-" * len(header))

# Without key levels — varying min_extension
for ext in [0.0, 2.0, 3.0, 5.0]:
    is_s, oos_s, is_t, oos_t = run_is_oos(df, stop_points=40.0, target_points=60.0, min_extension=ext)
    label = f"no levels  ext={ext}"
    print(
        f"{label:>22} | {len(is_t):>9} {is_s.win_rate:>6.0%} {is_s.profit_factor:>6.2f} {is_s.net_pnl:>8.0f} |"
        f" {len(oos_t):>10} {oos_s.win_rate:>7.0%} {oos_s.profit_factor:>7.2f} {oos_s.net_pnl:>8.0f}"
    )

print()

# With key levels — varying proximity and min_extension
for ext in [0.0, 2.0, 5.0]:
    for prox in [5.0, 10.0, 20.0]:
        is_s, oos_s, is_t, oos_t = run_is_oos(
            df, stop_points=40.0, target_points=60.0, min_extension=ext,
            use_key_levels=True, level_proximity=prox,
        )
        label = f"levels ext={ext} prox={prox}"
        print(
            f"{label:>22} | {len(is_t):>9} {is_s.win_rate:>6.0%} {is_s.profit_factor:>6.2f} {is_s.net_pnl:>8.0f} |"
            f" {len(oos_t):>10} {oos_s.win_rate:>7.0%} {oos_s.profit_factor:>7.2f} {oos_s.net_pnl:>8.0f}"
        )
