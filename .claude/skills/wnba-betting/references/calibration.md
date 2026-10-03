# WNBA calibration — what the data actually says

Source of truth for every WNBA number used by the skills and by `betlab/wnba.py`.
Re-derive with `python3 -m betlab wnba calibrate` and `python3 -m betlab backtest ...`
(see "Reproduce" at the end).

Contents
1. Data
2. League environment by season
3. Home-court advantage
4. Margin and total noise (sigma)
5. Margin distribution and small numbers
6. Rest, back-to-backs, travel
7. First half / first quarter conversions
8. The 2026 DraftKings market
9. Opening vs closing lines
10. The rating model and how it compares to the market
11. Walk-forward backtests (what is and isn't an edge)
12. Player-stat dispersion and correlations (props / SGP)
13. Reproduce

---

## 1. Data

| File | Rows | Coverage |
|---|---|---|
| `data/wnba/games.csv` | 3,318 games | 2013 regular season → 2026 first round (through Oct 1, 2026) |
| `data/wnba/lines_2026_draftkings.csv` | 340 games | Every 2026 game through Oct 1: DraftKings **open and close** spread, total, moneyline with prices |

Derived from ESPN via the MIT-licensed sportsdataverse/wehoop projects (`wehoop-wnba-data`,
`wehoop-wnba-raw`). ESPN only retains `pickcenter` odds for the current season, so 2013–2025 have
results but no lines. Team codes are ESPN's; `CONN→CON`, `TUL→DAL`, `SA→LV` are franchise
continuations (handled by `betlab.wnba.ALIASES`).

## 2. League environment by season (regular season)

| Season | Games | Avg total | Total SD | Pace/40 | ORtg | Home win % | HCA (OLS ± SE) | Resid SD | OT rate | 3PA/FGA | FTA/FGA |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2013 | 204 | 151.3 | 17.3 | 78.7 | 95.4 | .608 | 3.45 ± 0.86 | 12.3 | .059 | .216 | .284 |
| 2014 | 204 | 154.2 | 17.1 | 78.2 | 97.1 | .578 | 2.46 ± 0.76 | 10.8 | .088 | .212 | .281 |
| 2015 | 204 | 150.3 | 17.7 | 77.8 | 95.7 | .618 | 3.42 ± 0.85 | 12.2 | .064 | .226 | .284 |
| 2016 | 204 | 163.8 | 16.7 | 80.3 | 100.5 | .552 | 2.42 ± 0.83 | 11.9 | .098 | .238 | .314 |
| 2017 | 204 | 162.9 | 17.4 | 80.9 | 99.8 | .593 | 3.26 ± 0.86 | 12.3 | .059 | .257 | .289 |
| 2018 | 203 | 165.6 | 17.9 | 81.2 | 101.5 | .542 | 1.56 ± 0.85 | 12.2 | .030 | .284 | .271 |
| 2019 | 204 | 157.4 | 17.5 | 81.3 | 96.5 | .608 | 3.97 ± 0.84 | 12.0 | .025 | .292 | .252 |
| 2020* | 132 | 166.1 | 16.5 | 82.4 | 100.5 | .500 | 0.83 ± 0.95 | 11.0 | .030 | .310 | .270 |
| 2021 | 193 | 161.2 | 16.8 | 81.1 | 98.5 | .536 | 0.45 ± 0.86 | 11.9 | .067 | .309 | .252 |
| 2022 | 217 | 164.6 | 17.4 | 81.9 | 99.8 | .544 | 0.85 ± 0.78 | 11.5 | .051 | .329 | .267 |
| 2023 | 241 | 165.4 | 17.7 | 82.2 | 100.1 | .519 | 1.52 ± 0.77 | 12.0 | .041 | .324 | .271 |
| 2024 | 241 | 163.4 | 17.2 | 81.8 | 99.3 | .525 | 0.81 ± 0.69 | 10.7 | .033 | .335 | .264 |
| 2025 | 287 | 163.3 | 17.1 | 80.7 | 100.9 | .559 | 2.58 ± 0.78 | 13.1 | .017 | .359 | .270 |
| **2026** | 331 | **174.1** | **20.3** | 82.6 | **104.8** | .542 | 1.80 ± 0.69 | 12.5 | .036 | .372 | **.302** |

\*2020 was played in a single-site bubble; treated as neutral by the model.

**2026 is a regime change.** Scoring jumped ~11 points per game (87.1 ppg, a league record),
driven by efficiency (ORtg +3.9) and free throws (FTA/FGA +12%) — the officiating
task-force emphasis on freedom of movement added ~4.5 fouls per game — plus two expansion
teams. Pace rose only ~2 possessions. Implication: priors built on 2013–2025 totals were
~10 points too low in May 2026; anything that adapts slowly (models *and* books) was exposed.

## 3. Home-court advantage

| Window | Pooled OLS HCA (points) |
|---|---|
| 2013–2019 | 2.92 ± 0.32 |
| 2021–2026 | 1.36 ± 0.31 |
| 2023–2026 | 1.63 ± 0.36 |
| Model log-likelihood optimum, 2021–25 | 1.5–1.75 |
| Model log-likelihood optimum, 2026 | 1.75–2.0 |
| DraftKings 2026 implied (avg closing home spread) | ~1.65 |

Default **1.75 points**. Home teams won 54% in 2021–26 vs ~59% in 2013–19 (consistent with a
2026 *Sports Medicine – Open* study: 64.3% in 2009 → 52.3% in 2024). Do **not** use NBA-style
"+3 to +4". Full-time charter flights since mid-2024 plausibly reduce road fatigue further.

Playoffs (2013–2026, 249 games): home teams won 61.4% with +3.99 average margin, but home teams
are usually the higher seed. Against the model (which already includes HCA 1.75 and ratings),
playoff home teams beat expectations by +1.54 ± 1.61 — suggestive, **not significant**; the
model uses no extra playoff HCA by default (`playoff_hca_extra=0`).

## 4. Margin and total noise (sigma)

| Quantity | Value |
|---|---|
| SD of final margin around DK **closing** spread (2026, n=340) | **12.71** (robust 11.86) |
| Sigma implied by DK's own spread↔moneyline mapping | 12.7 |
| Rating-model predictive SD (mid-season) | ~12.4–12.5 |
| SD of total around DK closing total (2026) | **18.65** (robust 17.79) |
| SD of total around model, 2014–2025 | ~16.5 |

Use **σ_margin = 12.5** and **σ_total = 18.0** for 2026-style environments (16.5 for pre-2026
scoring). The model tracks total variance online (100-game half-life) so it widens on its own
when a regime shifts.

## 5. Margin distribution and small numbers

P(|final margin| = k), 2021–2026:

| k | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| % | 3.6 | 4.9 | 5.5 | 5.1 | 6.3 | 6.0 | 5.9 | 6.5 | 5.4 | 5.5 | 5.5 | 3.2 | 3.8 | 3.3 | 2.8 | 3.3 |

No football-style key numbers. But **1- and 2-point finishes are ~30% rarer than a normal model
predicts** (late fouling stretches close games to 3–8 points). Consequences: the normal model
slightly overprices pick'em-area spreads (±1 to ±2.5) relative to moneylines; when a small spread
and the moneyline disagree, trust the moneyline-implied probability. Overtime occurs ~3–4% of
games (5-minute periods), handled by `betlab.markets.basketball_margin_dist`.

## 6. Rest, back-to-backs, travel

Residual analysis vs the rating model, regular seasons 2014–2026:

| Effect | Estimate |
|---|---|
| Team on 0 days rest (back-to-back) vs opponent not | **−2.32 ± 1.00 points** |
| Each extra day of rest difference (capped at 3) | +0.36 ± 0.25 points |
| Total when either team is on a B2B | +2.8 points vs +0.3 otherwise (n=210; weak) |
| Time-zone shift of the road team | no detectable pattern |

Back-to-backs are rare in the WNBA (2–5% of team-games; 1-day rest is the norm), so this is a
small, occasional adjustment — not the "single biggest edge" NBA lore claims. The model applies
`b2b_penalty=2.3` automatically when it can infer rest from the schedule.

## 7. First half / first quarter conversions (2023–2026)

| Quantity | Value |
|---|---|
| 1H share of total points | 0.503 (2026: 0.495) |
| 1Q share of total points | 0.255 |
| 1H expected margin ≈ | **0.60 ×** full-game expected margin (favourites build leads early) |
| 1H margin SD around that | 9.9 (≈ 0.78 × full-game σ) |
| 1H total ≈ | 0.50 × full-game total, SD 11.2 (≈ 0.60 × full-game σ_total) |
| 1H tie rate / 1Q tie rate | 3.9% / 4.7% (3-way or push risk) |

`python3 -m betlab price period --spread -6.5 --total-line 171.5` applies these.

## 8. The 2026 DraftKings market (n=340, closing lines)

| Metric | Value |
|---|---|
| Hold (overround): moneyline / spread / total | 4.27% / 4.71% / 4.74% |
| Home teams ATS | 53.2% ± 5.3 (not significant) |
| Favourites ATS | 48.2% |
| Overs | 52.4% ± 5.3; actual − closing total = +1.59 on average |
| Moneyline calibration (devigged) | well calibrated; Brier 0.197; slight favourite under-pricing at 65–80% (pred .72, actual .76; small n) |

Totals residual (actual − closing total) by month: May +0.9 (n=63), **June +5.2 (82)**,
**July +3.4 (71)**, Aug −2.9 (85), Sept +1.7 (38). Average closing total by month: 169.9 → 170.0 →
173.5 → 176.5 → 172.4 while actual scoring ran 170.8 → 175.3 → 176.9 → 173.6 → 174.1. The market
lagged the scoring surge into midsummer, then over-corrected in August. With five monthly
comparisons this is suggestive, not proof — but it is exactly the regime-lag pattern to watch for.

## 9. Opening vs closing lines (DraftKings 2026)

| Metric | Spreads | Totals |
|---|---|---|
| Games where the line moved | 75.9% | 87.1% |
| Mean absolute move | 1.65 pts | 2.27 pts |
| RMSE vs result: open → close | 12.82 → 12.69 | 19.14 → 18.69 |
| Betting the side the line later moved to, **at the open** | 55.4% ± 6.1 (n=258) | 55.4% ± 5.7 (n=296) |
| Same side at the **close** | 48.4% | — |

Closing lines are more accurate than openers, and the value of a bet is mostly decided by
whether the market later moves toward you. That is why closing-line value (CLV) is the
scoreboard.

## 10. The rating model vs the market

Kalman point ratings (`betlab/ratings.py`), parameters tuned on 2014–2025 log-likelihood,
**tested out-of-sample on 2026**:

| Metric (2026, n=340) | Model | DK close |
|---|---|---|
| Margin RMSE | 12.96 | 12.69 |
| Total RMSE | 18.97 | 18.69 |
| Moneyline Brier | 0.203 | 0.197 |

- Correlation with DK close: 0.90 (spreads), 0.94 (totals).
- Optimal blend weight on the model vs the **close**: margins 0.17 [95% CI −0.23, 0.60], totals
  −0.04 [−0.76, 0.64] → against closing lines the model adds nothing reliably.
- Versus **openers**, model disagreement predicts where the line goes:
  - spreads: corr 0.17 [0.05, 0.29]; line moves 0.13 pts toward the model per pt of disagreement
  - **totals: corr 0.53 [0.42, 0.61]; line moves 0.52 pts toward the model per pt of disagreement**

The model's league-scoring tracker adapted to the 2026 surge faster than DraftKings' openers.

End-of-first-round 2026 ratings (points vs average team, neutral court): ATL +7.7, GS +6.4,
LV +6.0, MIN +4.5, IND +4.4, NY +4.2, DAL +2.6, WSH +0.9, PHX −2.6, LA −3.1, POR −3.8, CHI −4.9,
SEA −6.4, CON −8.6, TOR −9.4 (the top eight are exactly the eight playoff teams).

## 11. Walk-forward backtests (2026, fit on 2013–2025, no look-ahead)

Quarter Kelly, 3% cap, min EV 2% after blending. `w` = weight on the model when blending with
the devigged market price (logit space). CLV = expected ROI if the closing line is true.

| Price | Market | w | Bets | Record | ROI (95% CI) | Model-claimed EV | Avg CLV (t) |
|---|---|---|---|---|---|---|---|
| open | spread | 1.0 (raw) | 226 | 121-105 | +5.1% (−9.0, +17.5) | 13.4% | **−1.5% (−1.8)** |
| open | total | 1.0 (raw) | 207 | 109-98 | +1.2% (−12.6, +15.3) | 10.1% | +0.95% (1.2) |
| open | moneyline | 1.0 (raw) | 228 | 83-145 | −2.6% | 25.7% | −0.7% |
| open | spread | 0.35 | 87 | 49-38 | +1.9% | 5.8% | +0.5% (0.4) |
| open | **total** | **0.35** | **49** | **32-17** | **+32.7% (+4.8, +55.9)** | 4.3% | **+6.0% (2.9)** |
| open | total | 0.5 | 100 | 56-44 | +15.4% (−4.4, +35.1) | 5.6% | +3.9% (2.9) |
| close | any | any | — | — | −9% to +10% on samples of 30+ bets (tiny samples swing wildly); every CI spans 0 | — | n/a |

How to read this honestly:
1. **Raw model EVs of 10–26% are fiction.** A results-only model that disagrees with a sharp
   market is usually wrong; blending with the market (w ≈ 0.15–0.35) brings claimed EV in line
   with realised CLV.
2. **Spread ROI of +5% with negative CLV is luck** — exactly the trap that makes bettors scale
   up a losing process.
3. **Totals vs openers is the one signal with significant CLV**, consistent across every weight
   tried (t ≈ 2–3) and with the opener-movement correlation above. It is one season, one book,
   and 24 configurations were tried — treat it as a *hypothesis to keep validating with tracked
   CLV*, sized small, not as a proven edge.
4. **Against closing lines nothing works** — a model with no information edge loses about the vig.

## 12. Player-stat dispersion and correlations (2024–2026, 20+ mpg, 241 player-seasons)

Variance-to-mean fits, `var = a · mean^b` (used by `betlab/props.py`):

| Stat | a | b | Median var/mean | NB k (pooled) |
|---|---|---|---|---|
| points | 4.580 | 0.809 | 2.84 | 7.3 |
| rebounds | 1.169 | 1.057 | 1.27 | 16.1 |
| assists | 1.076 | 1.015 | 1.07 | 22.1 |
| threes | 1.114 | 1.082 | 1.14 | 7.6 |
| steals / blocks / turnovers | ≈1.0 | ≈1.0 | ≈1.0 | — |
| PRA | 8.360 | 0.632 | 2.82 | 11.9 |

Within-player game-to-game correlations: points–threes **0.62**, points–rebounds 0.23,
points–assists 0.13, rebounds–assists 0.14; minutes drive everything (points–minutes 0.49).
Cross-player: teammates' points **−0.01** (usage competition cancels pace), opponents' points
+0.04, player points vs own team score +0.23, vs game total +0.17. Median within-player minutes
SD for 20+ mpg players: 5.6.

External evidence (independent study, 2023–26, low-medium confidence): average WNBA prop hold
≈6.75%; unders hit 1.6–2.8 pts more often than devigged prices implied but only break even
after line shopping; teammate overs showed no gradient with missing production after "Out"
reports ("the market prices injuries").

## 13. Reproduce

```bash
python3 -m betlab wnba calibrate                         # section 2 (stdlib re-implementation)
python3 -m betlab wnba ratings --season 2026              # section 10 ratings
python3 -m betlab backtest --markets total --price-at open --model-weight 0.35   # section 11 row
python3 -m betlab backtest --markets total --price-at open --sweep model_weight=none,0.5,0.35,0.2
python3 -m pytest tests/test_ratings_wnba.py tests/test_backtest_fetch_cli.py   # golden-number guards
```
Refresh the bundled data (needs `pip install pandas pyarrow`): `python3 scripts/refresh_wnba_data.py`.
