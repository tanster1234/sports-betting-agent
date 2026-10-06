---
name: player-props
description: >
  Price player props and same-game parlays with real distributions instead of gut feel: points,
  rebounds, assists, threes, steals/blocks, PRA and other combos, double-doubles, alternate prop
  ladders and SGPs — using WNBA-calibrated dispersion, minutes-based projections, injury/usage
  bumps, the market's implied projection, and correlation-aware parlay pricing. Use for any prop
  question ("is Wilson over 24.5 good?", "Clark assists tonight", "build me an SGP", "what's the
  fair line for Bueckers points?") in the WNBA or NBA, even when asked casually.
---

# Player props

Props are where books are thinnest — hundreds of markets per night, lower limits, higher hold
(~6–7% in the WNBA vs ~4.7% on sides). The edge, when there is one, comes from a better
**minutes and role** view, not from "she's been hot". Everything below runs through
`python3 -m betlab prop ...` (repo root).

## Workflow

1. **What does the market think?** Back out the projection implied by the two-way price:
   ```bash
   python3 -m betlab prop implied --stat points --line 23.5 --over -115 --under -105
   ```
   → e.g. "book implies 24.0 points". This turns "is the over good?" into "is my projection
   higher than 24.0, and by enough to clear hold?"

2. **Build your projection** — minutes × per-minute rate × adjustments:
   ```bash
   python3 -m betlab prop --stat points --rate 0.72 --minutes 33 --minutes-sd 4 \
       --pace 1.03 --matchup 1.02 --usage 1.00 --line 23.5 --over -115 --under -105
   ```
   - **Rate**: per-minute production over a relevant window (this season, weighted to recent
     *role*, not recent *luck*; 3-pt% swings regress hard).
   - **Minutes**: the most important input. Starters in the WNBA play ~28–34; playoffs
     concentrate minutes on starters; blowout risk cuts them. Minutes restrictions after injury
     (e.g. Collier's July 2026 return) are the classic mispricing.
   - **Pace**: expected game possessions vs the player's typical game (from the game total:
     a 178 total vs a 170-point team context ≈ 1.03).
   - **Matchup**: opponent's allowed rate for the stat vs league; keep within ±10% — matchup data
     is noisy.
   - **Usage** when a teammate sits: redistribute the absent player's shots/assists mostly to
     the primary handlers and starters at the same position; a star's absence typically lifts
     the next option's usage ~5–15%. Markets react to confirmed "Out" reports quickly (an
     independent 2023–26 study found no exploitable gradient after official reports) — the edge
     is in timing and minutes, not the obvious bump.
   - `--minutes-sd` adds *extra* role uncertainty; the calibrated dispersion already includes
     normal minute-to-minute noise (median within-player minutes SD ≈ 5.6).

3. **Distribution and EV.** Without `--rate`, pass a mean directly:
   ```bash
   python3 -m betlab prop --stat rebounds --mean 9.1 --line 8.5 --over +105 --under -135
   python3 -m betlab prop --stat pra --mean 31.0                       # fair line + ladder
   ```
   Output: P(over/under/push), fair prices, EV per side, the book's devigged probabilities
   and hold.

4. **Blend and gate.** Blend your probability with the devigged market at weight ≤ 0.5
   (`python3 -m betlab ev --prob <p> --price <offered> --other <other side> --model-weight 0.5`).
   Bet only if blended EV ≥ 4% (profile `min_ev.prop`) at the best available price. Size with
   `prop_kelly_multiplier` 0.15 and the per-game cap shared with any side/total on that game.

## WNBA dispersion (2024–26 box scores, 20+ mpg players)

| Stat | Variance ≈ | Shape |
|---|---|---|
| Points | 4.58 · mean^0.81 (≈ 2.85× mean) | negative binomial, right-skewed |
| Rebounds | 1.17 · mean^1.06 | slightly over-dispersed |
| Assists, steals, blocks, turnovers | ≈ mean | ~Poisson |
| Threes | 1.11 · mean^1.08 | over-dispersed (streaky) |
| PRA | 8.36 · mean^0.63 | — |

Consequence: for a 20-point scorer the SD is ~7 points, so the fair line is a range, not a number;
a one-point projection gap on points is worth only ~5% in probability. Rebounds/assists lines are
tighter. NBA: these fits are a reasonable starting point; recalibrate with NBA box scores.

## Same-game parlays

Correlation decides whether an SGP is good. Within one WNBA player: points–threes **0.62**,
points–rebounds 0.23, points–assists 0.13. Across players: teammates' points ≈ **−0.01**,
opponents' +0.04, player points vs own team score +0.23, vs game total +0.17.
```bash
python3 -m betlab parlay --probs 0.58 0.55 --corr '[[1,0.23],[0.23,1]]' --offered 240
python3 -m betlab prop dd --points 18 --rebounds 9.5 --assists 3   # double-double probability
```
Books already price obvious correlations (star over + team ML). Positive EV in SGPs is rare after
their extra hold — require 10% EV and keep stakes small. Never add a leg to "boost" a payout.

**NFL game script (measured, nflverse 2021-25, 90k player-games).** Relative to the line: a back's
rushing yards rise when his team beats the spread (+0.28) — so the *other* team's back falls
(the two backs' rushing overs: −0.15); a back's catches go slightly the other way (−0.08) and
are unrelated to his own rushing (+0.01); QB passing yards follow the total (+0.31) and his
receivers (WR yards +0.37); two backs on one team share the touchdowns (TD–TD −0.11). Run
`python3 -m betlab slips check` on any SGP or set of tickets — it applies these, flags legs that
need different games, and checks overlap with tickets already placed.

## Pitfalls

- **Median vs mean**: right-skewed stats (points) have medians below means — lines near the mean
  favour the under slightly. The NB model handles this; mental math doesn't.
- **DNP / void rules** differ by book (some grade a player who leaves early; Fanatics advertises
  first-half injury protection on props). Check before betting players with injury risk.
- **Alt ladders**: price each rung (`prop --stat points --mean 24` prints a ladder) instead of
  assuming linear pricing; books often shade the tails.
- **First basket / first field goal** markets carry very high hold; treat as entertainment.
- **Limits**: winning WNBA prop bettors get limited quickly — line shopping across books matters
  more than shaving another 0.5% off the model.
- **Integrity**: never bet props on information about a player's intent to underperform, and
  never target or contact players. The NBA restricted props on 10-day/two-way players after the
  2025 gambling indictments — expect similar scrutiny of thin WNBA markets.
