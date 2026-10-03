# MLB

## Market
- Moneylines (no spread), run lines (±1.5), totals, first-five (F5) markets, team totals and props.
- Starting pitchers dominate pricing; a late scratch voids "listed pitcher" bets at most books but
  not "action" bets — know which you placed.

## Numbers to use
| Quantity | Value |
|---|---|
| Home team win rate | ~53–54% |
| Team runs per game | over-dispersed: variance ≈ 2 × mean (use `price mlb --var-ratio 2`) |
| Games to extra innings | ~9% (the automatic-runner rule shortened extras) |
| SD of game total | ~4.3–4.6 runs |

## Inputs that matter, in order
1. **Starting pitchers**: use estimators that strip luck — xFIP, SIERA, xERA, K−BB%, plus
   expected innings (pitch counts, recent workload, openers/bulk arrangements).
2. **Bullpens**: who is available today (pitched 2 of the last 3 days? high-leverage arms used
   yesterday?) — bullpen state changes daily and is under-tracked by the public.
3. **Park factors**: Coors Field inflates scoring far more than any other park; use current
   multi-year run factors (Statcast/FanGraphs) rather than folklore percentages.
4. **Weather**: temperature (warmer → ball carries), wind speed/direction relative to the park's
   orientation (Wrigley is the extreme case), roof open/closed.
5. **Lineups and platoons**: confirmed lineups ~2–4 hours before first pitch; handedness splits.

## Pricing
```bash
python3 -m betlab price mlb --home-rate 4.7 --away-rate 4.1 --total-line 8.5 --total-prices -110 -110 --ml -145 125
```
Use F5 when your edge is about the starters (removes bullpen variance). Run line -1.5 needs a
2+ run win; extra-inning games are treated as 1-run games.

## Red flags
- Starter not confirmed; opener/bulk games; pitcher returning from injury with a pitch limit.
- Day game after a night game (lineup rest), getaway days.
- Totals without a current wind/temperature check.
- "Pitcher is 8-1 in day games" — sample-size noise.
