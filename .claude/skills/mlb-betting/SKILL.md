---
name: mlb-betting
description: >
  MLB betting: moneylines, run lines (±1.5 and alternates), totals and alternate totals, team
  totals, first-five-innings (F5) lines and first-inning NRFI/YRFI, all priced from the sharp
  moneyline + total with an exact half-inning model fitted on every 2023-2026 game (pitch-clock
  era) and checked on the held-out 2026 season; a scanner that compares DraftKings/FanDuel with
  those fair prices; and the day's context — probable pitchers, recent starts, bullpen workload,
  weather, playoff series state. Use for anything baseball — "Dodgers -1.5?", "is over 7.5 good",
  "NRFI", "F5 under", "team total", "who's pitching", "playoff game tonight", an MLB parlay leg —
  even casually.
---

# MLB betting

A baseball score is built from 17-18 half-innings plus the rules that end a game early or late:
the home team skips the bottom of the 9th when it leads, a walk-off ends the game when the
winning run scores (so most home wins in the 9th or later are by one run), and a tie goes to
extra innings — with an automatic runner on second in the regular season and **without** one in
the postseason. Those rules are why run lines, alternate totals, team totals, F5 and NRFI prices
can't be read off a simple runs model. The model here computes all of them exactly.

The pipeline is market-first, like every sport here:
1. **Fair moneyline and total = the sharp market** (Pinnacle no-vig). Adjust only for news it
   hasn't absorbed (a scratched starter, an opener, a bullpen game, wind blowing out).
2. **Every other market is derived from those two numbers** — run lines, alt totals, team totals,
   F5, first inning. This is where DraftKings/FanDuel are most often off.
3. **Compare** DK/FD with the fair price. Same EV gates as everywhere (`betting-analyst`):
   ML 2.5%, run line/total 2%, team totals 3%, F5/first inning 3%, parlays 8%.

## Commands

```bash
python3 -m betlab mlb scan                          # today's board: sharp ML+total -> fair prices, DK/FD checked
python3 -m betlab mlb scan --team LAD --deep         # + alt lines, team totals, F5, first inning (more credits)
python3 -m betlab mlb context [--date 2026-10-06] [--team ATL]   # probables, last starts, bullpen use, weather
python3 -m betlab mlb price --ml +120 -140 --total 8.5 -105 -115 [--postseason] \
    --offer runline:home:-1.5:+150:dk total:under:8.5:-110:fd team_total:away_over:3.5:-120 \
            f5_ml:home:0:-125 f5_total:under:4.5:-110 nrfi:nrfi:0:-120
python3 -m betlab mlb validate                       # the fitted numbers below
python3 -m betlab series --p-home 0.56 --p-away 0.47 --format 2-2-1 --wins-high 1 --wins-low 1   # playoff series
#   (higher seed's per-game win chance at home / away; MLB division series is 2-2-1, LCS/WS 2-3-2)
```
`--ml` is AWAY then HOME (American). `--total` is the line, then over and under prices. `scan`
uses about 6 Odds API credits for the board, plus 7 per game with `--deep`. Postseason is
detected from the date by `scan`; pass `--postseason` to `price` in October.

## What the model is and how well it fits

Fitted by `scripts/refresh_mlb_data.py` on 7,383 games from 2023-25 (closing lines and runs by
inning from ESPN) and checked on the held-out 2026 season (2,446 games through Oct 5, incl. 17
postseason); numbers in `data/mlb/calibration.json`, fitted 2026-10-06:

| Piece | Value |
|---|---|
| Runs per half-inning | league 0.50; spread fitted (most innings scoreless); 1st inning +4% with fewer scoreless frames than its average suggests |
| 9th inning by score | road team trailing after 8: ×0.89, tied ×0.91, leading ×1.12; home team batting in the 9th (not ahead): ×0.86 — closers |
| Extra innings | automatic-runner inning 1.16 runs on average (regular season); postseason has none |
| Walk-offs | 76% end exactly on the winning run; the rest are homers that win by 2-4 |
| Run line vs DraftKings' closing run line (2026) | log-loss 0.6762 vs 0.6766 — as good as the book's own run line |
| Alt totals 1-2 runs off the main line (2026) | predicted vs actual over: line+1 40.7% v 40.2%, +2 32.5% v 32.7%, −1 59.9% v 60.1%, −2 69.9% v 70.0% |
| Team totals over 4.5 (2026) | home 43.0% v 44.4%, road 42.2% v 41.9% |
| First five innings (2026) | tied after 5: 15.4% v 15.5%; home leads 44.5% v 45.1%; F5 over 4.5 49.0% v 50.0% |
| No run in the 1st (2026) | 50.0% v 49.3% |
| Known lean (2026) | one-run games 29.7% v 27.6%, extra innings 10.0% v 8.6%, home −1.5 34.9% v 36.2% |
| Final scores | log-likelihood −4.77 per game vs −5.29 for two independent Poissons |

What that means:
- **Run lines, alt totals, team totals, F5 and NRFI are priced from the moneyline and total,
  consistently.** On held-out games the model's run-line prices were as accurate as the book's
  own closing run line, so a soft book's run line that disagrees with the model is a real price
  difference, not model error. That's the main use: find DK/FD derived prices that are stale or
  shaded relative to the sharp moneyline + total.
- **The model leans about 2 points toward one-run games** (and extra innings): it slightly
  overrates +1.5 underdogs and underrates −1.5 favourites. `scan` prices any line the sharp book
  posts (main run line, main total, moneyline, F5, first inning) from the sharp book itself; for
  lines only the model prices (alternate run lines, alternate totals, team totals) require ≥4% EV,
  and treat a +1.5 underdog edge under 5% as noise.
- **F5 and NRFI assume the starters and bullpens are typical for the full-game price.** An ace
  with a bad bullpen makes the F5 side stronger than the full-game price implies (and vice versa);
  an opener or a short-leash starter (check `context`: last three starts' innings) makes F5 more
  like the full game's bullpen. `scan --deep` re-fits F5 and the first inning to the sharp book's
  own F5 and first-inning lines when they're posted (two aces on Oct 6, 2026: sharp NRFI 61% vs
  the average-split model's 58%) — never bet F5/NRFI off the model alone when a sharp line exists.
- **No team-strength model.** The moneyline input is the sharp market. Starting-pitcher news is
  the main thing that can make it stale.

## Baseball rules that change the bet

- **Listed pitchers.** DK/FD moneylines, totals and run lines are usually "action" (stand whatever
  the starter); some markets or bet types are void if a listed pitcher doesn't start. Check
  before betting early, and re-price if the starter changes.
- **Postseason extra innings have no automatic runner**: extras last longer but add fewer runs
  per inning. `scan` handles it from the date; `price` needs `--postseason`.
- **F5 moneyline** at DK/FD is usually two-way with a push if tied after five (about 1 in 6
  games); the three-way version pays the tie. The model prices both.
- **Run line -1.5 on the home favourite** needs a 2-run win, and walk-offs end at one run — that's
  why home -1.5 pays more than road -1.5 at the same moneyline.
- **Weather and park.** Wind out at Wrigley, heat, Coors Field: the total should already include
  it — check the forecast against the posted total when the line hasn't moved.
- **Bullpen fatigue** (who threw 25+ pitches yesterday, or two days in a row) matters most in
  October, when managers lean on their best three relievers. `context` lists it.

## Answer format

Same as `betting-analyst`: verdict and stake first; the few numbers that decide it (sharp no-vig
moneyline and total, the fair price for the market asked, the book's price, EV); the main risk
(starter's leash, bullpen, weather, rule quirks); a "bet only at" price; commands in one short
block at the end.

## Data

`scripts/refresh_mlb_data.py` downloads every MLB game since 2023 from ESPN — final score,
runs by inning, and the closing moneyline/run line/total from the book ESPN shows (DraftKings in
2026, ESPN BET in 2024-25, the consensus or ESPN BET in 2023) — to `data/mlb/games.csv`
(gitignored), and fits `data/mlb/calibration.json` (committed; aggregate numbers only). Probable
pitchers, game logs, bullpen use and weather come from the MLB Stats API (statsapi.mlb.com, no
key).
