---
name: backtesting
description: >
  Design, run and critique betting backtests without fooling yourself: walk-forward evaluation
  with no look-ahead, betting the price actually available (opener vs close) including vig,
  CLV as the primary metric, bootstrap confidence intervals, multiple-testing discipline and
  sample-size math — with a ready-to-run 2026 WNBA backtest against real DraftKings openers and
  closers. Use when someone wants to test a model, system, trend, "angle", tout record or
  staking plan, asks "would this have made money?", or shares backtest results to evaluate.
---

# Backtesting

Most published betting backtests are wrong in one of five ways: look-ahead, betting prices that
weren't available, ignoring vig/pushes, tiny samples, or picking the best of many tries. The
engine in `betlab/backtest.py` makes the first three impossible and reports what you need to
judge the last two.

## Run the bundled WNBA test

Model fit on 2013–2025, then walk-forward through all 340 games of 2026 against DraftKings:

```bash
python3 -m betlab backtest --markets total --price-at open --model-weight 0.35
python3 -m betlab backtest --markets spread total moneyline --price-at close
python3 -m betlab backtest --markets total --price-at open --sweep model_weight=none,0.5,0.35,0.2
python3 -m betlab backtest --markets total --price-at open --model-weights '{"total":0.35}' --bets-out bets.json
```
Flags: `--min-ev`, `--kelly`, `--start/--end`, `--no-playoffs`, `--min-disagreement` (points).
The summary has record, ROI with bootstrap 95% CI, average model-claimed EV, **average CLV with
t-stat** (when pricing at the open), final bankroll and max drawdown, by market.

What it found (details in `.claude/skills/wnba-betting/references/calibration.md` §11):
raw model EVs of 10–26% were fiction; spreads/ML showed no edge (one +5% ROI came with negative
CLV — luck); **totals vs openers had significant positive CLV (+6.0%, t = 2.9 at weight 0.35)**;
nothing beat closing lines. 24 configurations were tried, so even the good row is optimistic.

## Rules the engine enforces

1. **No look-ahead.** A date's games are all priced before the model learns any of their
   results (`tests/test_backtest_fetch_cli.py::test_backtest_has_no_lookahead` proves it).
2. **Real prices.** Bets use the opener or closer actually posted, with its vig; never the
   devigged line.
3. **Real grading.** Pushes on integer lines; moneylines settle on the winner.
4. **Real staking.** Fractional Kelly on the running bankroll with a per-bet cap.
5. **Honest summaries.** Bootstrap CI on ROI; CLV t-stat; `configs_tried` warning on sweeps.

## Judging any backtest (yours or someone else's)

| Question | Bad sign |
|---|---|
| Were inputs known at bet time? | Uses season-end stats, final injury lists, closing lines to pick openers |
| Which price was bet? | "Closing line" for a strategy that needs early bets, or no vig |
| How many bets? | < 300 for sides/totals; ROI CI that spans 0 |
| How many variants were tried? | Thresholds/filters chosen after seeing results; no out-of-sample period |
| CLV? | Positive ROI with zero or negative CLV = luck |
| Mechanism? | A trend with no reason to persist ("teams in green jerseys on Tuesdays") |
| Stability? | Edge concentrated in one month/team; disappears when one season is removed |

Sample-size anchor: to show a true +3% ROI is not luck at -110 you need ~3,900 bets
(`report.bets_needed`). CLV converges far faster — a few hundred bets — which is why it is the
primary metric.

## Bring your own data

`run_backtest(games, lines, model_factory, cfg)` needs:
- `games`: dicts with `game_id, season, date (YYYY-MM-DD), home, away, home_pts, away_pts,
  neutral, season_type` — any sport.
- `lines`: dicts with `game_id, date` and any of `spread_home_{open,close}`,
  `spread_price_home_*`, `spread_price_away_*`, `total_*`, `over_price_*`, `under_price_*`,
  `ml_home_*`, `ml_away_*` (American odds).
- `model_factory`: returns an object with `update(game)` and
  `predict(home, away, date, season=, neutral=, playoff=)` → `.mu .sd .total_mu .total_sd`
  (e.g. `KalmanRatings(RatingParams(...))` with sport-appropriate HCA/sigma).

## Forward testing

The only test that can't be overfit is the future. Paper-trade a strategy for a month by logging
every qualifying bet with `ledger add` (tag `--tags paper`) and recording closes; then `report`.
Promote it to real money only with positive CLV over 100+ bets.
