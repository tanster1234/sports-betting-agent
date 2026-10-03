---
name: wnba-betting
description: >
  WNBA betting analysis backed by a model calibrated on 3,318 real games (2013-2026) and every
  2026 DraftKings opening and closing line. Use for anything WNBA: spreads, totals, moneylines,
  1H/1Q lines, team totals, player props, playoff series and Finals prices, futures/awards,
  injury impact (A'ja Wilson, Caitlin Clark, Napheesa Collier, Paige Bueckers...), back-to-backs,
  expansion teams (Valkyries, Tempo, Fire), the 2026 scoring surge, or "what's the play tonight"
  on a WNBA slate. Also use when someone applies NBA rules of thumb (home court, rest, star value)
  to the WNBA, or asks how WNBA markets differ — the numbers do not transfer.
---

# WNBA betting

The WNBA is a smaller, lower-limit, faster-changing market than the NBA, which cuts both ways:
prices are softer in places (openers, props, regime changes), but every number you borrow from
NBA lore is wrong here. This skill gives you the WNBA-specific numbers, a tested model, and the
workflow. Combine it with `betting-analyst` (pipeline + output), `odds-math`,
`bankroll-management`, `player-props`, `bet-red-team` and `bet-tracking`.

**All arithmetic goes through `python3 -m betlab ...`** (run from the repo root). The model and
data ship with the repo; the commands print JSON you can quote directly.

## What's different about the WNBA (calibrated, not folklore)

| Quantity | WNBA value | Typical NBA lore | Source |
|---|---|---|---|
| Home-court advantage | **1.75 pts** (2021–26: 1.4–1.8) | 3–4 pts | OLS + model fit |
| SD of margin vs a sharp closing spread | **12.5–12.7** | ~12 | 2026 DK closes |
| SD of total vs closing total | **18–18.7** (2026), ~16.5 before | ~18 | 2026 DK closes |
| Back-to-back penalty | **−2.3 ± 1.0 pts**, and B2Bs are only 2–5% of games | "−3 to −5, biggest edge" | residuals 2014–26 |
| Regulation length / OT | 40 min, 5-min OT, OT in ~3–4% of games | 48 min | data |
| 1H share of points / of margin | 50% / **60%** of the full-game margin | — | 2023–26 |
| Scoring environment | **2026: 174.1 avg total, ORtg 104.8, FT rate +12%** (record) | — | data |
| Key numbers | none; 1–2 pt finishes ~30% rarer than normal | — | 2021–26 |
| Market hold (DK) | sides/totals ~4.7%, ML ~4.3%, props ~6–7% | similar | 2026 |
| Limits | low; WNBA props get limited fast | higher | industry |

Full tables and methods: `references/calibration.md`. League snapshot (teams, CBA, standings,
playoff bracket, injuries, awards — dated 2026-10-03): `references/league-2026.md`.

## Workflow for one game

1. **Get the current facts** (see `references/data-sources.md`):
   ```bash
   python3 -m betlab fetch espn-scoreboard --league wnba --date YYYYMMDD   # games + DK open/close
   python3 -m betlab fetch espn-injuries --league wnba
   ```
   Cross-check the official injury report (5 p.m. local the day before; lineups 30 min
   pre-tip). If the network is blocked, use WebSearch and record source + time for every number.

2. **Model baseline** — what a results-only model thinks before any news:
   ```bash
   python3 -m betlab wnba predict --home ATL --away NY --date 2026-10-04 --playoff
   ```
   Returns expected margin, fair spread, win probability, expected total, team totals, rest
   days and notes (B2B, early season). The ratings know results through Oct 1, 2026; for later
   dates, add newer results (see "Keeping the model current").

3. **Adjust for what the model can't know**, in points, and say why:
   `--adj` (home margin) and `--total-adj`. The best calibrator for an injury is the market
   itself: if the news broke and the line moved 3 points, the market priced ~3 points. Only
   adjust beyond the market when you have information it doesn't (timing, confirmed minutes
   limit). Rough WNBA starting points when you must estimate before the market reacts:

   | Player absent | Margin impact (pts) | Total impact |
   |---|---|---|
   | MVP-level (e.g. Wilson, Collier at full health) | 4–7 | −2 to −4 |
   | All-WNBA / All-Star starter | 2.5–4 | −1 to −3 |
   | Rotation starter | 1–2 | ~−1 |
   | Bench player | 0–1 | ~0 |

   Rosters are 12 deep with top-heavy usage, so a star's minutes go to replacement-level
   players — but teams also slow down. These are priors; prefer the market's reaction.

4. **Price the offered numbers** with market blending (WNBA weights: totals 0.35,
   spreads/ML 0.15 — see "Why blend"):
   ```bash
   python3 -m betlab wnba price --home ATL --away NY --date 2026-10-04 --playoff \
     --spread -4.5 --spread-prices -110 -110 --total-line 170.5 --total-prices -110 -110 --ml -190 160
   ```
   Each side gets model probability, devigged market probability, blended probability,
   **blended EV**, the profile threshold and `qualifies`. Use the *best available* price across
   books (`fetch odds --best`), never the first one you saw.

5. **WNBA checklist** before anything qualifies:
   - Injury report and lineup status current? Any player on a minutes restriction?
   - Back-to-back or long layoff (FIBA break, All-Star, Commissioner's Cup) affecting rest?
   - Line movement since open — has the market already moved toward your side (edge gone) or
     away (someone knows something)? Moves of 3+ points usually mean news; find it.
   - Early season or expansion team? The model's uncertainty is wider; demand more edge.
   - Scoring regime: in a new environment (like May–July 2026), totals priors lag — this is
     where the model's adaptive league level has shown value vs openers.
   - Motivation spots late in the season (seeding locked, lottery teams) — real but already
     priced unless news is fresh; never a standalone reason.
   - Small spreads (±1 to ±2.5): normal models overrate 1–2 pt finishes; lean on the moneyline.

6. **Size, red-team, log**: `bet-red-team` → `bankroll-management` (`stake` command) →
   `betting-analyst` output card → `bet-tracking` ledger entry. Record the closing line later.

## Why blend with the market (and what the evidence says)

Walk-forward backtests on all 340 2026 games (fit on 2013–2025, no look-ahead) show:

- The raw model claims 10–26% EV per bet against DraftKings. Realised closing-line value was
  roughly zero — a results-only model that disagrees with a sharp market is usually wrong.
  Blending in logit space (`model_weight` 0.15–0.35) makes claimed EV match realised CLV.
- **Spreads and moneylines:** no reliable edge at any weight. A +5% spread ROI at the open came
  with *negative* CLV (t = −1.8) — luck, not skill.
- **Totals vs openers: the one durable signal.** Model–opener disagreement predicted the line's
  later move (corr 0.53, 95% CI 0.42–0.61). At weight 0.35: 49 bets, 32-17, CLV +6.0% (t = 2.9).
  One season, one book, 24 configurations tried → treat as a hypothesis to validate with your
  own tracked CLV, sized small.
- **Against closing lines nothing works**, as expected.

So the practical WNBA edges, in order: (1) line shopping and soft-book value vs consensus
(`fetch value`), (2) early totals when the model and opener disagree by 3+ points,
(3) injury/lineup news before the market reacts, (4) props with a real minutes/usage view
(`player-props`). See `references/calibration.md` §8–11 for every number.

## Playoffs, series and futures

```bash
python3 -m betlab wnba series --high ATL --low NY --round semifinals --date 2026-10-04
python3 -m betlab wnba series --high ATL --low NY --round semifinals --date 2026-10-07 --wins-high 1 --wins-low 0
```
Formats: first round 1-1-1, semifinals 2-2-1, Finals 2-2-1-1-1. Output includes exact-result and
series-length distributions for correct-score and total-games markets. No extra playoff home
court by default (not statistically supported). Read `references/playoffs.md` for consistency
checks between series prices and game moneylines, and for why zig-zag/"must-win" angles are not
edges. Devig futures boards with `--method power` or `shin`.

## Props

WNBA dispersion is calibrated: points variance ≈ 2.85 × mean (well over Poisson), rebounds
slightly over-dispersed, assists/steals/blocks ≈ Poisson; points–threes correlation 0.62;
teammates' scoring ≈ uncorrelated. Use the `player-props` skill:
```bash
python3 -m betlab prop --stat points --mean 24.1 --line 23.5 --over -115 --under -105
python3 -m betlab prop implied --stat points --line 23.5 --over -115 --under -105   # market's mean
```
Prop holds run ~6–7%, limits are low, and no book is reliably sharp — line shopping matters more
than anywhere else.

## Keeping the model current

The bundled data ends Oct 1, 2026. To include later games either refresh the dataset
(`python3 scripts/refresh_wnba_data.py`, needs pandas + pyarrow and GitHub access) or append
rows to `data/wnba/games.csv` (game_id, season, season_type, game_type, date, home, away,
home_pts, away_pts, neutral, periods, home_1h, away_1h, poss — only the first 10 matter for
ratings). Use `--until YYYY-MM-DD` to reproduce what the model knew on a past date.

## Hard rules

- No WNBA bet without a computed, blended EV above the profile threshold *and* a one-sentence
  statement of what you know or price that the market hasn't. "They're due" is not information.
- Snapshot facts in `references/league-2026.md` decay fast — verify standings, injuries and
  series scores live before using them.
- Never help locate, contact, harass or blame players or officials; flag integrity concerns
  instead. If the user shows signs of chasing losses, switch to `responsible-gambling`.
