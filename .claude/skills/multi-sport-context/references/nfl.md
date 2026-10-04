# NFL

## Market
- Extremely efficient by kickoff; most value is in early-week numbers after news, line shopping
  around key numbers, and derivative markets (team totals, props).
- Margins are lumpy: **3 and 7** are by far the most common final margins, then 6, 14, 10 and 4.
  Half-points around 3 and 7 are worth far more than elsewhere — price them with the fitted NFL
  model (`python3 -m betlab nfl price ...`, below), not a normal curve.

## Numbers to use
| Quantity | Value |
|---|---|
| Home-field advantage | ~1.5–2 pts (declined from ~2.5–3 a decade ago) |
| SD of margin vs closing spread | **12.7** (2015–25, 3,028 games); key numbers matter more |
| SD of total vs closing total | **13.2** |
| Most common final margins (2015–25) | 3 (14.8%), 7 (8.7%), 6 (6.9%), 14 (5.2%), 10 (4.8%) |
| Favourite −3 / −7 | wins 59.8% / 75.0%; pushes 10.2% / 6.4% |
| Ties | 0.33% |
| QB starter → backup | typically −3 to −7; −10+ only for elite-to-unplayable |
| Wind ≥ 15 mph sustained | passing/kicking suffer; totals −2 to −4 vs calm (markets react once forecasts firm) |
| Bye week | ~0–1 pt |

## What moves lines
1. QB availability and quality (by far the most important single position).
2. Offensive/defensive line injuries in clusters (several starters out matters; one usually doesn't).
3. Weather — wind more than cold or rain; check forecasts game-day morning.
4. Efficiency metrics (EPA/play, success rate — free via nflverse; DVOA moved to FTN after
   Football Outsiders closed) over win-loss records.

## Pricing from the market line (`betlab nfl`)

The model is a normal curve around the line with a fitted weight on every final margin (and every
total), anchored so the posted line is the 50/50 point. It turns one trusted line — ideally the
sharp consensus, devigged — into fair prices for alt spreads, alt totals, moneylines,
half-points and teaser legs:

```bash
python3 -m betlab nfl price --spread -3 --total 44.5 --home NYG --away ARI \
  --alt -2.5 -3.5 -7 --alt-totals 41.5 47.5 --teaser 6 \
  --offer spread:home:-2.5:-135 spread:away:9:-280 total:over:41.5:-150 ml:away:0:130
```
`--offer market:side:line:price` returns EV for each offered price. Use the devigged market
probability when the main line is juiced: in Python, `nfl.price(..., p_home_cover=0.54)`.

Out of sample (fit 2015–23, test 2024–25, 570 games; `python3 -m betlab nfl validate`): margin
log-likelihood −3.83 vs −3.95 for a plain normal; spread-implied moneyline log-loss 0.599 vs 0.598
for the market's own moneyline (i.e. the conversion is as good as the market's); 6-point teaser
legs through 3 and 7 predicted 75.9% vs 73.6% actual (174 legs — within noise, watch it). It
prices *from* the market; it does not predict games. Refit yearly with
`python3 scripts/refresh_nfl_data.py` (golden numbers in `tests/test_nfl.py`).

## Team ratings (`betlab nfl ratings / predict / backtest`)

Power ratings from results (home edge 1.75, season-to-season regression 0.6) with a **3-point
handicap when someone other than a team's usual starter is listed at QB** (usual = most starts in
the team's last 4 games); the ratings learn from those games net of the handicap.
`python3 -m betlab nfl predict --date 2026-10-04` lists the model line next to the market's, with
QB notes. The schedule's projected starters can be stale — verify on game day.

Honest result, walk-forward 2021–25 against closing lines (1,424 games,
`python3 -m betlab nfl backtest`): margin RMSE **13.10 vs 12.66** for the closing spread; the
best blend weight on the model is **0**; when it disagreed with the close by 1/2/3+ points its side
covered **48.5% / 46.8% / 46.5%** (52.4% needed at -110). The QB handicap does help the model
(13.03–13.10 with it vs 13.12 without), but the market prices QBs better still. So the profile's
NFL model weight is 0: use the ratings for early-week numbers, news reactions and as a sanity
check — never as a reason to bet a closing line.

## Teasers
Six-point teasers that move a line through both 3 and 7 (roughly +1.5 to +2.5 → +7.5 to +8.5, and
-7.5 to -8.5 → -1.5 to -2.5) were historically +EV at standard prices. Books now price 2-team
6-point teasers around -120 to -140 and the 2015 extra-point change altered margin frequencies.
Breakeven per leg for a 2-team teaser at -120 ≈ 73.9% (√(1/1.833)). Price legs with
`betlab nfl price --teaser 6` (the fitted model puts a Wong leg at ~75%; 2024–25 actual 73.6%)
before assuming value.

## Red flags
- QB status unresolved by Friday; inactives come out ~90 minutes before kickoff.
- Short weeks (Thursday) amplify injuries; travel across time zones for early kickoffs matters a
  little, rarely enough alone.
- Divisional "familiarity" adjustments (no support), revenge/look-ahead narratives.
- Late-season games with playoff seeding locked (starters may rest).
