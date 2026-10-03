---
name: bankroll-management
description: >
  Bet sizing and bankroll risk: fractional (push-aware) Kelly, simultaneous Kelly for a slate,
  per-bet / per-game / per-sport / daily caps, units, drawdown and stop-loss rules, risk-of-ruin
  and drawdown simulation, and bankroll recalibration. Use whenever stakes come up — "how much
  should I bet", units, bet sizing for a card, parlay sizing, monthly growth targets, "should I go
  bigger on this one", or "how do I win back what I lost" — and to push back on oversized bets or
  aggressive tier systems.
---

# Bankroll management

A correct edge with the wrong stake still goes broke. Sizing is the one part of betting that is
fully under your control, so it gets strict rules.

## The rules

1. **Stake = fractional Kelly, then caps that can only reduce it.**
   Quarter Kelly by default (profile `kelly_multiplier` 0.25; props 0.15 because projections are
   noisier). Never above half Kelly — `profile.validate` refuses it.
2. **Caps (fractions of current bankroll):** 3% per bet · 4% per game (all markets on one game
   combined — spread, ML and total on the same team are one position) · 8% per sport per day ·
   10% new exposure per day. Hard ceiling of 5% on any single bet.
3. **Units are display only.** 1 unit = 1% of bankroll (profile `unit_pct`). Never size by
   "confidence tier"; size by Kelly and report the result in units.
4. **Recalibrate** the bankroll figure after big swings and at least monthly; Kelly is
   proportional, so stakes shrink automatically in drawdowns.
5. **Stop-losses:** −5% in a day → done for the day. −20% from peak → 48-hour pause and a
   process review (`bet-tracking` report: is CLV still positive?) before betting again.
6. **No chasing, no doubling.** Losses don't change tomorrow's stake except through the smaller
   bankroll. Requests to "win it back" get acknowledged and declined; see `responsible-gambling`.

## Commands

```bash
python3 -m betlab kelly --prob 0.55 --price -110 --bankroll 2000            # full / fractional stake
python3 -m betlab kelly --prob 0.55 --price -110 --fraction 0.25 --simulate # + 1,000-bet simulation
python3 -m betlab ev --prob 0.50 --push 0.06 --price +100                   # push-aware EV / Kelly
echo '[{"label":"A","p_win":0.55,"price":"-110","game":"g1","sport":"WNBA"},
       {"label":"B","p_win":0.57,"price":"-105","game":"g1","sport":"WNBA"},
       {"label":"C","p_win":0.36,"price":"+210","game":"g2","sport":"NBA"}]' | python3 -m betlab stake --json -
python3 -m betlab stake --json slate.json --exposed '{"__day__":0.04,"game:g1":0.02}'
```
`stake` reads `config/profile.json` (falls back to the example) and returns, per bet: full Kelly %,
target %, stake, units, and which caps bound. Biggest-EV bets are sized first so caps bind on the
marginal ones. For several *independent* bets settling together, `betlab.kelly.simultaneous_kelly`
gives the joint optimum (≈ individual Kelly when edges are small).

## Why these numbers

- **Kelly maximises long-run growth only if your probability is right.** Real estimates are
  noisy, and over-betting is punished far more than under-betting: growth falls to *zero* at ~2×
  full Kelly (`kelly` prints `overbet_multiple_where_growth_turns_negative`). Quarter Kelly keeps
  ~44% of the maximum growth rate while cutting the variance of bankroll swings by ~94% (variance
  scales with the square of the Kelly fraction).
- **Tier systems over-bet.** The reference repo this project replaced staked "Tier A" bets at
  4–5 units of 2% (8–10% of bankroll). For a +4.8% EV bet at -110, full Kelly is 5.3%, so a
  4-unit tier bet is ~1.5× full Kelly — the zone where long-run growth heads toward zero.
- **Correlated bets are one bet.** Same-game spread + ML + over on the favourite move together;
  per-game caps stop accidental 3× exposure.

## Realistic expectations (tell users this)

| Edge (EV per bet, -110) | Quarter-Kelly stake | Bets to be 95% sure it's not luck | Median worst drawdown in 1,000 bets | 1-in-10 worst drawdown | Median bankroll after 1,000 bets |
|---|---|---|---|---|---|
| +1% | 0.27% | ~35,000 | 8% | 13% | ×1.02 |
| +2% | 0.55% | ~8,700 | 14% | 23% | ×1.11 |
| +3% | 0.83% | ~3,900 | 19% | 30% | ×1.25 |
| +5% | 1.38% | ~1,400 | 26% | 39% | ×1.87 |

(Bets needed ≈ (1.96 × 0.95 / edge)²; drawdowns from `betlab.kelly.risk_of_ruin_mc`, 2,000 simulated
seasons each.) Note what this means for the stop-loss: **even a real 3–5% edge usually hits a 20%
drawdown somewhere in 1,000 bets.** The 48-hour pause is a review checkpoint — is CLV still
positive? are the inputs still fresh? — not proof the model failed. Long-run ROI for
genuinely skilled bettors is low single digits; "20% a month" claims are variance or fiction.
Losing streaks of 8–10 at -110 are routine over a season even with a real edge.

## Parlays, SGPs, teasers, futures

- Size each as a single bet with its own probability (`parlay` / `series` commands) — never as
  "fun money" outside the bankroll rules. Thresholds: parlays 8% EV, SGPs 10%, futures 6% (more
  hold, more model error, capital locked up).
- Futures tie up capital for weeks: count open futures exposure against the bankroll when sizing
  new bets (pass it in `--exposed`).
