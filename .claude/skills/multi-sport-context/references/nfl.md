# NFL

## Market
- Extremely efficient by kickoff; most value is in early-week numbers after news, line shopping
  around key numbers, and derivative markets (team totals, props).
- Margins are lumpy: **3 and 7** are by far the most common final margins, then 10, 6, 4 and 14.
  Half-points around 3 and 7 are worth far more than elsewhere — price them with an empirical
  margin pmf (`MarginModel.from_pmf`) built from your data, not a normal curve.

## Numbers to use
| Quantity | Value |
|---|---|
| Home-field advantage | ~1.5–2 pts (declined from ~2.5–3 a decade ago) |
| SD of margin vs closing spread | ~13.5 (normal approx; key numbers matter more) |
| SD of total | ~10 |
| QB starter → backup | typically −3 to −7; −10+ only for elite-to-unplayable |
| Wind ≥ 15 mph sustained | passing/kicking suffer; totals −2 to −4 vs calm (markets react once forecasts firm) |
| Bye week | ~0–1 pt |

## What moves lines
1. QB availability and quality (by far the most important single position).
2. Offensive/defensive line injuries in clusters (several starters out matters; one usually doesn't).
3. Weather — wind more than cold or rain; check forecasts game-day morning.
4. Efficiency metrics (EPA/play, success rate — free via nflverse; DVOA moved to FTN after
   Football Outsiders closed) over win-loss records.

## Teasers
Six-point teasers that move a line through both 3 and 7 (roughly +1.5 to +2.5 → +7.5 to +8.5, and
-7.5 to -8.5 → -1.5 to -2.5) were historically +EV at standard prices. Books now price 2-team
6-point teasers around -120 to -140 and the 2015 extra-point change altered margin frequencies.
Breakeven per leg for a 2-team teaser at -120 ≈ 73.9% (√(1/1.833)). Price legs with
`parlay.teaser_legs` on an empirical pmf before assuming value.

## Red flags
- QB status unresolved by Friday; inactives come out ~90 minutes before kickoff.
- Short weeks (Thursday) amplify injuries; travel across time zones for early kickoffs matters a
  little, rarely enough alone.
- Divisional "familiarity" adjustments (no support), revenge/look-ahead narratives.
- Late-season games with playoff seeding locked (starters may rest).
