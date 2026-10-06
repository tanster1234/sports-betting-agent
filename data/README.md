# Bundled data

| File | What | Rows |
|---|---|---|
| `wnba/games.csv` | WNBA results 2013 → 2026 first round (through Oct 1, 2026): date, teams, scores, neutral flag, periods (OT), first-half points (2023+), possessions | 3,318 |
| `wnba/lines_2026_draftkings.csv` | DraftKings **opening and closing** spread / total / moneyline (with prices) for every 2026 game through Oct 1, 2026, plus final scores | 340 |

| `nfl/calibration.json` | NFL margin/total model fitted on 2015–2025 closing lines and results: σ plus a weight per final margin (3, 7, 6, 10, 14 …) and per total — aggregate statistics only, with an out-of-sample check on 2024–25 | 3,028 games |
| `mlb/calibration.json` | MLB half-inning model: run dispersion, per-inning and score-dependent 9th-inning rates, automatic-runner extra innings, walk-off margins — fitted on 2023–25 closing lines and runs by inning, with a held-out 2026 check of run lines, alt totals, team totals, F5 and NRFI — aggregate statistics only | 7,383 fit / 2,446 test games |
| `tennis/calibration.json` | Tennis point model: tour serve-point rates by surface (2019–25), the fitted day-to-day form spread, held-out 2024+ checks of total games and set scores, and Elo vs bookmaker closing odds — aggregate statistics only | ATP 67,288 / WTA 43,512 matches |

## NFL data

`nfl/games.csv` is **not** in the repo. It is nflverse's game file
([nflverse/nfldata](https://github.com/nflverse/nfldata) `data/games.csv`, compiled by Lee Sharpe:
every game since 1999 with final score, closing spread/total/moneylines, starting QBs, rest, roof
and weather). That repository states no licence, so it is downloaded locally and gitignored;
only the derived calibration is committed.

```bash
python3 scripts/refresh_nfl_data.py                          # download + refit (stdlib only)
python3 scripts/refresh_nfl_data.py --last 2025 --validate-split 2023   # also store a 2024-25 holdout check
```
nflverse `spread_line` is positive when the home team is favoured; betlab flips it so that, as
everywhere else here, a negative home spread means the home team is favoured.

## Tennis data

The raw tennis files are **not** in the repo; `scripts/refresh_tennis_data.py` downloads them to
`data/tennis/` (gitignored) from Hugging Face mirrors and refits `tennis/calibration.json`:

- **Results with bookmaker closing odds** — tennis-data.co.uk (compiled in the Kaggle "dissfya"
  ATP/WTA daily-pull datasets): ATP 2000 → 2026-03-15, WTA 2007 → 2025-11-08, main tour only, odds
  with a ~5-7% margin (a mainstream book, not Pinnacle). Mirrors: `groundhog2107/atp_tennis`,
  `Nevoreuven/tennis-betting-odds-model`. tennis-data.co.uk itself blocks cloud servers.
- **Match statistics and later results** — Tennis databases, files, and algorithms by
  [Jeff Sackmann / Tennis Abstract](https://github.com/JeffSackmann), licensed
  [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) (non-commercial; credit
  required), via the `Aneeshers/tennis-sackmann-archive` mirror (results through 2026-05-25).

```bash
python3 scripts/refresh_tennis_data.py                 # download + fit + validate (stdlib only)
python3 scripts/refresh_tennis_data.py --no-download   # refit from local copies
```

## Provenance and license

Both files are derived from ESPN's public game data as collected and published by the
[sportsdataverse](https://github.com/sportsdataverse) **wehoop** project
(`wehoop-wnba-data` for schedules and team box scores, `wehoop-wnba-raw` for the raw game JSON
whose `pickcenter` block carries the DraftKings lines). wehoop is MIT-licensed
(© wehoop.wnba authors). Scores and betting lines are factual records; this repository adds
only cleaning (team-code normalisation is done at load time, see `betlab/wnba.py`).

ESPN keeps `pickcenter` odds only for the current season, so earlier seasons have results but
no lines.

## Columns

`games.csv`: `game_id, season, season_type (regular|playoff), game_type (STD|CC|RD16|SEMI|FINAL|QTR),
date, home, away, home_pts, away_pts, neutral (2020 bubble = 1), periods (4 = regulation),
home_1h, away_1h, poss`.

`lines_2026_draftkings.csv`: `game_id, date, season_type, home, away, home_pts, away_pts, book,
spread_home_{open,close}, spread_price_{home,away}_{open,close}, total_{open,close},
{over,under}_price_{open,close}, ml_{home,away}_{open,close}` (American odds; spreads from the
home team's perspective).

## Refresh

```bash
pip install pandas pyarrow
python3 scripts/refresh_wnba_data.py            # rebuild games.csv for 2013..current season
python3 scripts/refresh_wnba_data.py --lines    # also re-download current-season DK lines
```

## Personal data

`data/ledger/` holds your bet ledger and is gitignored. Don't commit it.

## MLB data

The raw MLB table is **not** in the repo; `scripts/refresh_mlb_data.py` builds it in
`data/mlb/games.csv` (gitignored) from ESPN's public endpoints — one scoreboard call per date
(final scores, runs by inning, regular season vs postseason) and one odds call per game (the
closing and opening moneyline, run line and total of the book ESPN shows: DraftKings in 2026,
ESPN BET in 2024–25, the consensus or ESPN BET line in 2023) — then refits `mlb/calibration.json`.
Rain-shortened and suspended games (linescores that don't add up) are dropped.

```bash
python3 scripts/refresh_mlb_data.py                  # download 2023..yesterday (resumes) + fit + validate
python3 scripts/refresh_mlb_data.py --no-download    # refit from the local copy (~10 min on 4 cores)
```
Probable pitchers, game logs, bullpen use and weather come live from the MLB Stats API
(statsapi.mlb.com, no key) via `betlab mlb context`.

