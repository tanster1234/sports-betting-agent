# Example — performance review

Real output of `python3 -m betlab report --format md` on a ledger built by replaying the 136
bets the 2026 backtest placed at DraftKings openers (totals and spreads, model weight 0.35):
each bet was placed with `ledger add`, its DraftKings closing price recorded with `ledger close`,
and graded with `ledger settle`. The ledger's CLV numbers come from a separate code path than the
backtester's and match it exactly (totals +6.01%, spreads +0.52%).

How to read it: CLV first (t = 2.04, positive and significant → the *process* beat the market),
then ROI's confidence interval (spans zero → results alone don't prove anything yet), then
segments (all the CLV comes from totals; spreads are ~0 → stop betting spreads, keep totals),
then calibration (the model's 54–57% bets won ~59%: under-confident if anything, n is small) and
risk (11.2% max drawdown, 5-loss longest streak, no tilt).

---

# Performance review

**Record** 81-55-0  |  **Staked** 1928.87  |  **P&L** 236.3  |  **ROI** 12.25% (95% CI -4.78% to 29.45%)
**Avg CLV** 2.5% over 136 bets (t = 2.04, p = 0.042, share positive 0.515)

**Verdict:** Positive, statistically significant CLV: the process is beating the market. Results will follow with volume; keep sizing disciplined.

_At the current ROI you need ~232 bets before it is distinguishable from zero._

## By Market

| group | bets | W-L-P | ROI % | avg CLV % |
|---|---|---|---|---|
| spread | 87 | 49-38-0 | 2.68 | 0.52 |
| total | 49 | 32-17-0 | 32.86 | 6.01 |

## By Month

| group | bets | W-L-P | ROI % | avg CLV % |
|---|---|---|---|---|
| 2026-05 | 57 | 29-28-0 | -4.55 | 1.87 |
| 2026-06 | 34 | 23-11-0 | 30.28 | 4.05 |
| 2026-07 | 15 | 9-6-0 | 31.27 | 8.39 |
| 2026-08 | 19 | 12-7-0 | 13.48 | 1.13 |
| 2026-09 | 11 | 8-3-0 | 31.88 | -4.74 |

## Calibration (your probabilities vs outcomes)

| bin | n | predicted | actual |
|---|---|---|---|
| 0.50-0.55 | 79 | 0.54 | 0.595 |
| 0.55-0.60 | 53 | 0.566 | 0.585 |
| 0.60-0.70 | 4 | 0.605 | 0.75 |

## Brier

```
{'n': 136, 'brier_model': 0.2434, 'brier_market': 0.2506, 'brier_skill_vs_market': 0.029}
```

## Risk

```
{'max_drawdown': 115.71, 'longest_losing_streak': 5, 'current_drawdown': 0.0, 'max_drawdown_pct': 11.2, 'current_bankroll': 1236.3, 'current_drawdown_pct': 0.0, 'peak_bankroll': 1236.3}
{'avg_stake_after_losing_day': 14.07, 'avg_stake_after_winning_day': 14.03, 'ratio': 1.0, 'flag': False}
```
