# WNBA playoff and series betting

## Formats (2025 onward)

| Round | Length | Home pattern (higher seed) | betlab format |
|---|---|---|---|
| First round | best-of-3 | H, A, H (1-1-1) | `1-1-1` |
| Semifinals | best-of-5 | H, H, A, A, H (2-2-1) | `2-2-1` |
| Finals | best-of-7 | H, H, A, A, H, A, H (2-2-1-1-1) | `2-2-1-1-1` |

Seeding is by record with a fixed bracket (1/8 → vs 4/5 winner; 2/7 → vs 3/6 winner). Before
2025 the first round was 2 home games for the higher seed and the Finals were best-of-5; from
2016–2021 the first two rounds were single games (`1`).

## Pricing a single playoff game

```bash
python3 -m betlab wnba predict --home ATL --away NY --date 2026-10-04 --playoff
python3 -m betlab wnba price   --home ATL --away NY --date 2026-10-04 --playoff \
    --spread -4.5 --spread-prices -110 -110 --total-line 170.5 --total-prices -110 -110 --ml -190 160
```
- Home court: use the regular-season value (1.75). Playoff home teams beat the model by
  +1.5 ± 1.6 points historically — not significant, so no extra by default. If you want to
  express a view, pass `--adj` explicitly and say why.
- No back-to-backs in the playoffs; games are 2–3 days apart, so rest rarely matters — but
  minutes concentrate on starters, which raises star props and lowers bench props.
- Injuries dominate. Re-check the official report (5 p.m. local the day before) and lineups
  (30 minutes before tip). A late scratch after you bet is the main way playoff bets go stale.

## Pricing a series

```bash
# from the model's current ratings (uses home/away game probabilities for each venue)
python3 -m betlab wnba series --high ATL --low NY --round semifinals --date 2026-10-04
# mid-series: pass the current score
python3 -m betlab wnba series --high ATL --low NY --round semifinals --date 2026-10-07 --wins-high 1 --wins-low 0
# from your own per-game probabilities (e.g. after injury adjustments)
python3 -m betlab series --format 2-2-1 --p-home 0.66 --p-away 0.55
python3 -m betlab series --format 2-2-1 --rating-diff 3.5 --hca 1.75 --sigma 12.5
```
Output includes `p_higher_seed`, the exact-result distribution (`"3-1": ...`, for correct-score
markets) and the series-length distribution (for "total games" markets).

Worked example (ratings after the 2026 first round; *will be stale by the time you read this*):

| Semifinal | P(higher seed) | Game at higher seed | Game at lower seed | Most likely length |
|---|---|---|---|---|
| ATL (4) vs NY (8) | 0.72 | 0.66 | 0.56 | 4 games (0.36) |
| GS (2) vs LV (3), if GS advanced | 0.55 | 0.57 | 0.46 | 5 games (0.38) |
| LV (3) vs DAL (7), if DAL advanced | 0.71 | 0.66 | 0.55 | 4 games (0.36) |

These are model numbers before any injury or news adjustment and before blending with the
market. Longer series favour the better team: a 60% per-game edge becomes ~68% over five games.

## Consistency checks between markets

Books price series, game moneylines and exact results separately, and they can disagree.
1. Devig the series price: `python3 -m betlab odds -250 200`.
2. Back out the per-game probability it implies:
   `python3 -c "from betlab.series import implied_game_prob_from_series as f; print(f(0.70, '2-2-1', hca_gap=0.055))"`
   (`hca_gap` ≈ half the difference between home and road game probabilities, ~0.05 in the WNBA).
3. Compare with the devigged game-1 moneyline. A gap of several points means one market is
   stale — usually the one that moved last is right.

## Things that sound like edges but aren't (in the WNBA sample)

- **Zig-zag** (back the team that lost the last game): no reliable modern evidence, and WNBA
  playoffs produce only ~20–27 games a year — far too few to validate any situational trend.
- **"Must-win" / elimination-game motivation:** priced; unprovable.
- **Reacting hard to one game:** the model updates a rating by only ~3% of a game's surprise
  (a 20-point blowout moves a rating ~0.6 points). Markets often overreact more than that after
  a blowout — this is the more defensible direction to lean, and only with a price edge.

## Futures and series markets: hold and sizing

Series and futures markets carry more hold than game lines (often 6–10%+ on two-way series
prices, much more on outright champion boards). Devig futures boards with `--method power` or
`shin` (favourite-longshot bias), require EV ≥ 3% (series) / 6% (futures) after blending, and
remember the money is locked up: Kelly on a bet that resolves in three weeks is still Kelly, but
it occupies bankroll you cannot redeploy.
