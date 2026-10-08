# Sports betting agent — project instructions

This repo is a disciplined sports-betting analysis system for Claude Code: skills in
`.claude/skills/` (workflows and domain knowledge, WNBA in depth) plus `betlab/`, a tested,
standard-library-only Python package that does every calculation. Output is analysis for an
adult user to act on — Claude never places bets.

## Always

- **Do all betting math with `python3 -m betlab ...`** (run from the repo root). Conversions,
  devig, EV, Kelly, CLV, series, props, parlays — no mental arithmetic on odds.
- **Start from the market.** Blend model probabilities with the devigged market price
  (profile `model_weight`) before computing EV; raw model probabilities are overconfident.
- **Require a computed edge and a stated information edge** for any recommendation; otherwise
  output PASS with fair prices and "bet only at X or better" numbers. If the user has opted in
  (profile `quiet_day_pick`), a PASS day may add one **quiet-day pick**: the single bet closest to
  the sharp fair price, labelled "entertainment, not value", at a small fixed stake
  (`python3 -m betlab quietday`), logged with `--tier entertainment`.
- **Size with fractional Kelly + caps** (`python3 -m betlab stake`), never by confidence tiers.
- **Use current data** with timestamps; if live fetches are blocked (sandbox network policy),
  fall back to WebSearch/WebFetch and say so.
- **Log and measure**: give ledger commands for every bet; judge skill by CLV with sample sizes
  and confidence intervals, not by short-run results.
- **Write for the person asking, not for this repo.** Lead with the verdict and stake in plain
  words; define a term the first time you need it ("EV, the average profit per $1 bet") or skip
  it. Keep the machinery out of the reasoning — no module, function or file names, profile
  fields or ledger state unless the user asked; commands go in one short block at the end.
  Present caps as advice ("I'd keep any one bet under 3% of your bankroll"), not as rules the
  user already has. If the bankroll is unknown, give stakes as % of bankroll and ask for it
  rather than sizing off the example profile. Headlines must be literally true (quarter Kelly
  is not "Kelly"). Attribute facts from bundled notes or data to their source and date, and
  drop specifics you can't source.
- **Protect the user**: honour stop-losses, never encourage chasing, and switch to the
  `responsible-gambling` skill at any sign of harm. 21+ / legal books only. No help with
  harassment of players, insider information, or evading limits/self-exclusion.

## Skills (invoke the relevant ones; `betting-analyst` orchestrates)

| Skill | Use for |
|---|---|
| `betting-analyst` | "what should I bet", picks, slate scans, single-game analysis, output card |
| `wnba-betting` | anything WNBA — calibrated model, 2026 context, playoffs, props notes |
| `multi-sport-context` | NBA / NFL / MLB / NHL / NCAAF / NCAAB context and pricing |
| `tennis-betting` | ATP / WTA — match, total games, handicaps, sets, live, scan, surface Elo |
| `mlb-betting` | MLB — run lines, alt totals, team totals, F5, NRFI from the sharp ML + total; scan; pitchers/bullpen context |
| `odds-math` | conversions, devig, EV, hold, CLV, parlays, alt lines |
| `player-props` | props and same-game parlays |
| `sports-data-ingestion` | schedules, injuries, odds, line shopping, value scans |
| `bet-red-team` | bias checklist + adversarial subagent before a bet |
| `bankroll-management` | stakes, caps, drawdowns, stop-loss |
| `bet-tracking` | ledger, closing lines, performance reviews, leg post-mortems |
| `backtesting` | testing strategies honestly; bundled 2026 WNBA backtest |
| `live-betting` | games in progress — play-by-play read, comebacks, halftime/live prices vs sharp |
| `responsible-gambling` | warning signs, limits, help resources |

## Configuration

- Bettor profile: `config/profile.json` (gitignored; copy `config/profile.example.json`). Holds
  bankroll, Kelly fraction, caps, EV thresholds, model weights, books, state, ledger path.
- Odds API key: `export ODDS_API_KEY=...` (optional; ESPN fetches need no key).
- Ledger: `data/ledger/bets.jsonl` (gitignored, append-only, hash-chained).

## Development

```bash
python3 -m pytest -q          # ~300 tests, ~10 seconds, stdlib + pytest only
ruff check betlab tests       # lint (config in pyproject.toml)
python3 -m betlab -h          # CLI help
```
- `betlab` must stay standard-library only (no numpy/pandas) so skills run anywhere.
- WNBA numbers in skills come from `.claude/skills/wnba-betting/references/calibration.md`;
  golden-number tests in `tests/test_ratings_wnba.py` and `tests/test_backtest_fetch_cli.py`
  guard them — update the doc and tests together if the model changes.
- Live reads (`betlab liveread`) use `LIVE_PARAMS` in `betlab/liveread.py`, fitted by
  `python3 -m betlab liveread validate` on WNBA halftime scores; golden numbers in
  `tests/test_liveread.py` — refit, the `live-betting` skill table and tests together.
- Bundled data (`data/wnba/`) is refreshed with `scripts/refresh_wnba_data.py` (needs pandas +
  pyarrow and GitHub access).
- NFL pricing (`betlab nfl`) uses `data/nfl/calibration.json`, rebuilt by
  `scripts/refresh_nfl_data.py` (stdlib; downloads nflverse games to the gitignored
  `data/nfl/games.csv`). Golden numbers in `tests/test_nfl.py` — refit, docs and tests together.
- Tennis pricing (`betlab tennis`) uses `data/tennis/calibration.json`, rebuilt by
  `scripts/refresh_tennis_data.py` (stdlib; downloads results/odds and Sackmann stats to the gitignored
  `data/tennis/`). Golden numbers in `tests/test_tennis.py` — refit, the `tennis-betting` skill table and
  tests together.
- MLB pricing (`betlab mlb`) uses `data/mlb/calibration.json`, rebuilt by `scripts/refresh_mlb_data.py`
  (stdlib; downloads ESPN scores, runs by inning and closing odds since 2023 to the gitignored
  `data/mlb/games.csv`, fits on games before 2026 and validates on 2026). Golden numbers in
  `tests/test_mlb.py` — refit, the `mlb-betting` skill table and tests together.
- Parlay checks (`betlab slips`) use `data/nfl/leg_correlations.json` — how NFL props move with the game
  script and each other — rebuilt by `scripts/refresh_nfl_leg_correlations.py` (stdlib; nflverse weekly
  player stats to the gitignored `data/nfl/player_stats/`). Golden numbers in `tests/test_slips.py`;
  post-mortems (`betlab postmortem`) are tested there too.
- Skill evals live in `evals/` (see `evals/README.md`).
