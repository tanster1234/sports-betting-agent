---
name: multi-sport-context
description: >
  Sport-specific handicapping context and pricing for the NBA, NFL, MLB, NHL, college football and
  college basketball: what actually moves lines, modern home-field values, rest/travel, weather,
  starting pitchers and goalies, key numbers, injury reporting, market quirks and red flags — with
  numbers corrected against modern data (e.g. NBA home court ~2 pts, NFL ~1.5-2, not the old 3+).
  Use when analyzing or comparing any non-WNBA game or market; for WNBA use wnba-betting, for tennis
  use tennis-betting, for MLB pricing use mlb-betting.
---

# Multi-sport context

Same method in every sport: start from the market (consensus no-vig), express your view as an
adjustment **in points/runs/goals**, convert to probabilities with the right distribution, blend
with the market, and require a stated information edge. What changes by sport is the
distribution and the inputs that matter.

## Pricing by sport

| Sport | Distribution | betlab | Default σ / notes |
|---|---|---|---|
| NBA | normal margin, OT-resolved | `price game --sport NBA --mu M --sigma 12` | σ_margin ~12, σ_total ~18, HCA ~2.2 |
| NCAAB / WNCAAB | normal | `--sport NCAAB` | σ ~10.5 (men), HCA ~3 |
| NFL | **empirical** margin pmf (key numbers) | `MarginModel.from_pmf({...})`; normal only as a rough guide | σ ~13.5; 3 and 7 dominate |
| NCAAF | normal (rough) / empirical | `--sport NCAAF` | σ ~15.5, HCA ~2.5 |
| MLB | exact half-inning model priced from the sharp ML + total (use `mlb-betting`) | `mlb price --ml +120 -140 --total 8.5 -105 -115` | fitted on 2023–26 games; walk-offs, closers, extras rules |
| NHL | Poisson goals, OT/SO rule, empty-net shift | `price nhl --home-rate 3.2 --away-rate 2.9 --empty-net 0.25` | pure Poisson under-states OT (16% vs ~22–24% real) |

Approximate σ/HCA for non-WNBA sports are published-consensus figures, not fitted here —
recalibrate with your own closing-line data before trusting tenths (the WNBA module shows how).

## Read the sport file before analysing that sport

| Sport | File | Biggest levers |
|---|---|---|
| NBA | `references/nba.md` | injuries/rest decisions (timing), star value, pace |
| NFL | `references/nfl.md` | QB status, key numbers, weather (wind), injuries along the lines |
| MLB | `references/mlb.md` | starting pitchers, bullpen fatigue, park + weather, lineups |
| NHL | `references/nhl.md` | starting goalie, expected goals, OT/empty-net structure |
| NCAAF | `references/ncaaf.md` | talent gaps, QB/transfer churn, opt-outs, weather |
| NCAAB | `references/ncaab.md` | efficiency/tempo ratings, home court, tournament formats |

## Corrections to common rules of thumb (including the reference repo this replaced)

| Claim | Better estimate |
|---|---|
| NBA home court +3 to +4 | ~2–2.5 pts since 2020 (was ~3 before); Denver's altitude adds ~1 more, not +5–6 |
| NBA back-to-back −3 to −5 | ~1–2 pts for the tired team; more if travel + star rest, which you should model as rest |
| NBA star out −6 to −10 | MVP-level ~4–7; most All-Stars ~2.5–4; use the market's move as the calibrator |
| Referee crew ±3–5 on totals | small (≈ ±1–2); rarely an edge by itself |
| NFL QB out −15 to −20 | starter→backup typically −3 to −7; −10 only for elite-to-unplayable drops |
| NFL "reduce divisional spreads 20–25%" | no support; drop it |
| NFL bye week +1.5 to +2.5 | ~0–1 pt in modern data |
| NCAAF home field +6 to +10 | ~2.5–4 average; strong venues add ~1–2 |
| NCAAB home court +5 to +8 | ~3 average; elite environments ~+1–1.5 above that |
| "5-0 ATS in day games" (any sport) | noise; need hundreds of games and a mechanism |
| Brier < 0.22 = good model | meaningless for coin-flip bets; compare with the market's Brier |

## Universal red flags

- Starter / goalie / QB not confirmed → wait or pass.
- Line moved ≥ 2 points (basketball), through 3 or 7 (NFL), ≥ 20 cents (MLB/NHL ML) with no
  news you can find → assume you're missing information.
- Weather forecast > 24 h old for outdoor games.
- Motivation narratives (look-ahead, revenge, must-win) presented as the edge.
- Any trend with fewer than ~200 observations.
