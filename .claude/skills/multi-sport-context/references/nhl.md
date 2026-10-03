# NHL

## Market
- Moneylines, puck lines (±1.5), totals (5.5/6/6.5), regulation-time (3-way) markets, props.
- ~22–24% of games reach OT/shootout; OT/SO winners win by exactly one goal and add one goal to
  the final score.

## Numbers to use
| Quantity | Value |
|---|---|
| Home win rate | ~52–54% |
| Goals per team | ~3.0 (era-dependent); near-Poisson |
| OT/SO frequency | ~22–24% (a pure Poisson model gives ~16% — adjust or use regulation markets) |
| Empty-net goals | many 1-goal leads late become 2-goal wins; model with `--empty-net` |

## Inputs that matter
1. **Starting goalie** — confirmed at the morning skate or ~1 hour before puck drop. Use goals
   saved above expected (GSAx) over save percentage; a backup on the 2nd night of a road
   back-to-back is the classic spot.
2. **Expected goals (xGF%)** and shot quality at 5v5 — more predictive than Corsi alone.
3. **PDO** (shooting% + save%) regresses toward 100 — useful context, noisy over short spans.
4. **Special teams** matter less than raw PP% suggests once opportunities are accounted for.

## Pricing
```bash
python3 -m betlab price nhl --home-rate 3.3 --away-rate 2.8 --empty-net 0.25 --total-line 6.5
```
Puck line -1.5 requires a 2+ goal regulation win; regulation (3-way) markets avoid the OT coin
flip if your edge is about 60-minute strength.

## Red flags
- Goalie unconfirmed; travel back-to-backs; long road trips at the end.
- Totals bets that ignore both goalies' recent workload.
- Streak narratives ("won 8 straight") driven by high PDO.
