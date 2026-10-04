# Bundled data

| File | What | Rows |
|---|---|---|
| `wnba/games.csv` | WNBA results 2013 → 2026 first round (through Oct 1, 2026): date, teams, scores, neutral flag, periods (OT), first-half points (2023+), possessions | 3,318 |
| `wnba/lines_2026_draftkings.csv` | DraftKings **opening and closing** spread / total / moneyline (with prices) for every 2026 game through Oct 1, 2026, plus final scores | 340 |

| `nfl/calibration.json` | NFL margin/total model fitted on 2015–2025 closing lines and results: σ plus a weight per final margin (3, 7, 6, 10, 14 …) and per total — aggregate statistics only, with an out-of-sample check on 2024–25 | 3,028 games |

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
