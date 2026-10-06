# Bundled data

| File | What | Rows |
|---|---|---|
| `wnba/games.csv` | WNBA results 2013 → 2026 playoffs (through Oct 4, 2026): date, teams, scores, neutral flag, periods (OT), first-half points (2023+), possessions | 3,321 |
| `wnba/lines_2026_draftkings.csv` | DraftKings **opening and closing** spread / total / moneyline (with prices) for every 2026 game through Oct 4, 2026, plus final scores | 343 |

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

A refresh rewrites both files in a fixed row and column order, so new games show up as appended
rows only. The calibration in `calibration.md` and the golden-number tests use games before
2026-10-02 (`CALIBRATION_CUTOFF` in `tests/conftest.py`), so a refresh never changes them.

Then rebuild the playoff tracker and the results page:

```bash
python3 scripts/playoff_tracker.py                # JSON: every 2026 playoff game + upcoming calls
python3 scripts/build_lab_page.py                 # site/dist/wnba-betting-lab.html, ready to publish
```

## Personal data

`data/ledger/` holds your bet ledger and is gitignored. Don't commit it.
