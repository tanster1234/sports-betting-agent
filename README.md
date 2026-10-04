# Sports Betting Agent — Claude Code skills + tested betting math (WNBA in depth)

A disciplined sports-betting analysis system for [Claude Code](https://claude.com/claude-code):

- **11 Claude Code skills** (`.claude/skills/`) covering the whole workflow — slate analysis,
  WNBA, NBA/NFL/MLB/NHL/college context, odds math, props and SGPs, data ingestion, adversarial
  bet review, bankroll sizing, bet tracking, backtesting and responsible gambling.
- **`betlab`**, a standard-library-only Python package with a JSON CLI that does every number the
  skills need — devig (5 methods), EV, push-aware and simultaneous Kelly, CLV, spread/total/
  moneyline/alt/1H pricing, props, correlated parlays, playoff series, a Kalman rating model,
  MLB/NHL scoring models, a tamper-evident bet ledger, performance reports and a no-look-ahead
  backtester. **242 tests**, lint-clean, runs on Python 3.9+.
- **Real WNBA data**: 3,318 games (2013 → Oct 1, 2026) and DraftKings **opening and closing**
  lines for all 340 games of 2026, used to calibrate the model and to backtest it honestly.

It was built after reviewing three public projects
([magicjordan33/sports-betting-claude](https://github.com/magicjordan33/sports-betting-claude),
[OneWave-AI sports-betting-analyzer](https://github.com/OneWave-AI/claude-skills/tree/main/sports-betting-analyzer),
[sklls/betting-app-skill](https://github.com/sklls/betting-app-skill)); what was adopted and the
errors corrected are documented in [`docs/reference-repo-review.md`](docs/reference-repo-review.md).

> Analysis only. Claude never places bets. 21+, legal books only. Gambling problem? Call
> 1-800-MY-RESET (1-800-697-3738) or 1-800-522-4700, or text 800GAM.

## What the WNBA data says (headline findings)

Full tables: [`.claude/skills/wnba-betting/references/calibration.md`](.claude/skills/wnba-betting/references/calibration.md).

| Finding | Number |
|---|---|
| Modern WNBA home-court advantage | **~1.75 pts** (2021–26), down from ~2.9 (2013–19) — not NBA's "3–4" |
| SD of final margin vs DK closing spread | **12.7** · totals SD **18.7** |
| Back-to-back penalty | **−2.3 ± 1.0 pts**, and B2Bs are only 2–5% of games |
| 2026 scoring regime | record **174.1** avg total, ORtg 104.8, FT rate +12% (officiating emphasis) |
| DraftKings 2026 hold | sides/totals 4.7%, ML 4.3%; no significant home/fav/over bias |
| Totals market lag | closing totals ran 5.2 pts under results in June, then over-corrected in August |
| Model vs DK close (out-of-sample 2026) | margin RMSE 12.96 vs 12.69 — the close wins, as it should |
| Model vs DK **openers** on totals | disagreement predicts the line move (corr **0.53**, CI 0.42–0.61) |
| Walk-forward backtest, totals at open, blended | 49 bets, 32-17, **CLV +6.0% (t = 2.9)** — the one durable signal; spreads/ML show none |
| Raw (unblended) model EV claims | 10–26% per bet — fiction; blending with the market fixes it |

## Quick start

```bash
git clone https://github.com/tanster1234/sports-betting-agent && cd sports-betting-agent
cp config/profile.example.json config/profile.json      # set your bankroll, books, state
python3 -m pip install pytest && python3 -m pytest      # 242 tests, a few seconds
python3 -m betlab wnba predict --home ATL --away NY --date 2026-10-04 --playoff
claude                                                  # open Claude Code in the repo
```
Then ask things like:
- "What WNBA bets should I make today?" (→ `betting-analyst` + `wnba-betting`)
- "ATL -4.5 -110, total 168.5 o-110 — anything there for semis Game 1?"
- "Price the ATL–NY semifinal series." · "Is Wilson over 24.5 points good at -115?"
- "I'm down $300 this week, how do I win it back?" (→ `responsible-gambling`)
- "How am I doing?" (→ `bet-tracking` report) · "Would fading the public have worked?" (→ `backtesting`)

Optional: `export ODDS_API_KEY=...` (free tier at the-odds-api.com) for multi-book odds, props,
Pinnacle and prediction-market prices. ESPN data needs no key.

To use the skills from any directory: `python3 -m pip install -e .` (so `python3 -m betlab`
resolves everywhere) and copy or symlink `.claude/skills/*` into `~/.claude/skills/`.

## The skills

| Skill | Triggers on | What it does |
|---|---|---|
| [`betting-analyst`](.claude/skills/betting-analyst/SKILL.md) | "what should I bet", picks, "is this line good" | 7-step pipeline with gates: data → fair price → blended EV + information edge → red team → Kelly + caps → card → ledger |
| [`wnba-betting`](.claude/skills/wnba-betting/SKILL.md) | anything WNBA | calibrated numbers, model workflow, injury adjustments, playoffs/series, props, 2026 league snapshot |
| [`multi-sport-context`](.claude/skills/multi-sport-context/SKILL.md) | NBA / NFL / MLB / NHL / NCAAF / NCAAB | corrected sport parameters, pricing per sport, red flags |
| [`odds-math`](.claude/skills/odds-math/SKILL.md) | any betting number | command cookbook + common-formula corrections |
| [`player-props`](.claude/skills/player-props/SKILL.md) | props, SGPs | minutes × rate projections, WNBA dispersion, market-implied mean, correlation |
| [`sports-data-ingestion`](.claude/skills/sports-data-ingestion/SKILL.md) | odds, injuries, schedules | ESPN + The Odds API fetchers, value scan, WebSearch fallback, freshness rules |
| [`bet-red-team`](.claude/skills/bet-red-team/SKILL.md) | before any bet; "lock" | market-knows test, bias checklist, devil's-advocate subagent |
| [`bankroll-management`](.claude/skills/bankroll-management/SKILL.md) | stakes, units, drawdowns | fractional Kelly + caps, stop-loss, simulated drawdowns |
| [`bet-tracking`](.claude/skills/bet-tracking/SKILL.md) | logging, "how am I doing" | hash-chained ledger, CLV capture, significance-aware reviews |
| [`backtesting`](.claude/skills/backtesting/SKILL.md) | "would this have worked" | no-look-ahead engine, bundled 2026 WNBA test, how to judge any backtest |
| [`responsible-gambling`](.claude/skills/responsible-gambling/SKILL.md) | chasing, distress, limits | pause, support, current US resources |

Project-wide rules for Claude live in [`CLAUDE.md`](CLAUDE.md).

## `betlab` CLI cookbook

```bash
python3 -m betlab odds -135 115                          # hold + fair probs, all devig methods
python3 -m betlab ev --prob 0.56 --price -110 --other -110 --model-weight 0.35 --min-ev 0.02
python3 -m betlab kelly --prob 0.55 --price -110 --bankroll 2000 --simulate
echo '[{"label":"A","p_win":0.55,"price":"-110","game":"g1","sport":"WNBA"}]' | python3 -m betlab stake --json -
python3 -m betlab price convert --spread -6.5 --sigma 12.5          # spread -> win prob / fair ML
python3 -m betlab price period --spread -6.5 --total-line 171.5     # 1H lines
python3 -m betlab price alt --mu 5 --sigma 12.5 --home ATL --lines -10.5 -7.5 -4.5 -1.5
python3 -m betlab price mlb --home-rate 4.8 --away-rate 4.1 --total-line 8.5
python3 -m betlab price nhl --home-rate 3.3 --away-rate 2.8 --empty-net 0.25 --total-line 6.5
python3 -m betlab prop --stat points --mean 24.1 --line 23.5 --over -115 --under -105
python3 -m betlab prop implied --stat points --line 23.5 --over -115 --under -105
python3 -m betlab parlay --probs 0.6 0.55 --corr '[[1,0.35],[0.35,1]]' --offered 230
python3 -m betlab series --format 2-2-1 --rating-diff 3.5 --hca 1.75 --sigma 12.5
python3 -m betlab clv --bet -110 --line -3.5 --close -110 --close-other -110 --close-line -5.5
python3 -m betlab wnba ratings --season 2026
python3 -m betlab wnba price --home ATL --away NY --date 2026-10-04 --playoff \
    --spread -4.5 --spread-prices -110 -110 --total-line 168.5 --total-prices -110 -110 --ml -190 160
python3 -m betlab wnba series --high ATL --low NY --round semifinals --date 2026-10-04
python3 -m betlab backtest --markets total --price-at open --model-weight 0.35
python3 -m betlab fetch espn-scoreboard --league wnba --date 20261004
python3 -m betlab fetch value --league wnba --min-ev 0.02           # needs ODDS_API_KEY
python3 -m betlab ledger add --sport WNBA --event "NY @ ATL" --market total --selection "Over 168.5" \
    --line 168.5 --price -110 --stake 10 --model-prob 0.544
python3 -m betlab report --format md
python3 -m betlab live --bets tracker-bets/ --out patches/          # grade tracker legs from live ESPN scores
python3 -m betlab nfl price --spread -3 --total 44.5 --alt -2.5 -7 --teaser 6 \
    --offer spread:home:-2.5:-135 total:over:41.5:-150               # NFL alt lines/teasers off the main line
```

## Testing — four layers

1. **Unit + property tests** (`tests/`, 242): golden values for every formula, invariants
   (devig sums to 1, push-aware Kelly maximises log growth, series probabilities sum to 1,
   simulations hit their target moments), ledger integrity (double settlement refused,
   hash chain catches edits/deletions), parsers tested on real ESPN payloads.
2. **Golden-number regression tests** pin the calibration (2026 model RMSE, season HCA/ORtg,
   the top-8 ratings = the 8 playoff teams, the totals-vs-opener CLV finding).
3. **Walk-forward backtests** on real 2026 DraftKings lines, with a test that proves no
   look-ahead (`test_backtest_has_no_lookahead`).
4. **Skill evals** (`evals/`): 7 realistic prompts answered with and without the skills.
   Blind judges preferred the skilled answer **7 of 7** times (mean 9.4 vs 8.2 out of 10), and
   the skilled answers passed 37/37 objective assertions vs 35/37. The one weakness, clarity,
   was fixed in a second round (4.0 → 4.7 of 5) at no net cost. The three entry-point skills
   loaded for 28/28 should-trigger questions and 0/28 near-misses. See
   [`evals/README.md`](evals/README.md).

CI: `.github/workflows/tests.yml` (Python 3.9–3.13, ruff, pytest, CLI smoke test).

## Repository layout

```
.claude/skills/        11 skills (SKILL.md + references/)
.claude/settings.json  allow-list for betlab / pytest commands
CLAUDE.md              project rules for Claude
betlab/                odds, kelly, distributions, markets, props, parlay, clv, series,
                       ratings, wnba, nfl, lowscoring, ledger, report, backtest, profile, live, cli,
                       fetch/{espn, odds_api}
config/                profile.example.json  (copy to profile.json — gitignored)
data/wnba/             games.csv, lines_2026_draftkings.csv (+ README with provenance)
data/nfl/              calibration.json (NFL key-number model; raw games downloaded, not committed)
docs/                  reference-repo-review.md
evals/                 evals.json, README, results
examples/              real outputs: game analysis, series, props, backtest, performance review
scripts/               refresh_wnba_data.py, refresh_nfl_data.py
tests/                 pytest suite + real/structured fixtures
tracker/               bet-slip tracker page (claude.ai artifact source; data stays out of git)
```

## Limitations (read these)

- Markets are efficient. The bundled model loses to closing lines; its one validated signal
  (2026 totals vs openers) is one season at one book after 15–24 tried configurations. Treat
  every "edge" as a hypothesis until your own tracked CLV confirms it.
- Non-WNBA sport parameters are published-consensus approximations, not fitted here.
- `league-2026.md` is a snapshot dated 2026-10-03 (mid-playoffs); verify live.
- ESPN endpoints are unofficial and may change; parsers handle the 2024 and 2026 schemas.
- Nothing here is financial advice or a guarantee of profit.

## License and attribution

MIT. WNBA data derived from ESPN via the MIT-licensed
[sportsdataverse/wehoop](https://github.com/sportsdataverse) projects (see `data/README.md`).
