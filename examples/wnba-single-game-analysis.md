# Example — WNBA single-game analysis (NY @ ATL, semifinal Game 1, Oct 4, 2026)

Generated with the commands shown; model numbers are real outputs from the bundled data
(through Oct 1, 2026). **The sportsbook prices are illustrative** (written before the real
market was available) — rerun with live prices before acting.

## Commands

```bash
python3 -m betlab wnba predict --home ATL --away NY --date 2026-10-04 --playoff
python3 -m betlab wnba price --home ATL --away NY --date 2026-10-04 --playoff \
  --spread -4.5 --spread-prices -110 -110 --total-line 168.5 --total-prices -110 -110 --ml -190 160
echo '[{"label":"Over 168.5","p_win":0.5438,"price":"-110","game":"NY@ATL","sport":"WNBA","market":"total"}]' \
  | python3 -m betlab stake --json -
python3 -m betlab ev --prob 0.5438 --price -110 --min-ev 0.02
python3 -m betlab price period --spread -5.24 --total-line 174.04
```

## Model baseline (`wnba predict`)

| | Value |
|---|---|
| Expected margin | ATL by 5.24 (σ 12.45) → fair spread ATL −5.2 |
| ATL win probability | 66.3% |
| Expected total | 174.0 (σ 17.7) |
| Team totals | ATL 89.6 · NY 84.4 |
| Rest | ATL 3 days · NY 4 days (no back-to-back) |
| Fair 1H | ATL −3.1, total 87.0 |

## Pricing the offered lines (`wnba price`, WNBA blend weights)

| Side | Price | Model p | Market fair p | Blend w | Blended p | Blended EV | Qualifies (≥ threshold) |
|---|---|---|---|---|---|---|---|
| ATL ML | −190 | 66.5% | 63.0% | 0.15 | 63.5% | −3.0% | no |
| NY ML | +160 | 33.5% | 37.0% | 0.15 | 36.5% | −5.2% | no |
| ATL −4.5 | −110 | 53.0% | 50.0% | 0.15 | 50.5% | −3.7% | no |
| NY +4.5 | −110 | 47.0% | 50.0% | 0.15 | 49.6% | −5.4% | no |
| **Over 168.5** | −110 | **62.3%** | 50.0% | 0.35 | **54.4%** | **+3.8%** | **yes (≥ 2%)** |
| Under 168.5 | −110 | 37.7% | 50.0% | 0.35 | 45.6% | −12.9% | no |

Note how blending works: the raw model says 62.3% on the over (≈ +19% EV — not believable),
the market says 50%; at the WNBA totals weight of 0.35 the honest estimate is 54.4%, +3.8% EV.

## Red team (summary)

- *Information edge:* model total 174.0 vs 168.5; the model's league-scoring tracker has led
  DraftKings openers on totals all season (2026 backtest: CLV +6.0%, t = 2.9).
- *Against:* playoff defences tighten and rotations shorten. Checked: 2026 first-round games
  averaged 178 points; playoff totals historically ≈ regular season (161.8 vs ~163 in 2013–26).
- *Market check:* if the total has already moved to 170.5+, re-price — most of the edge is gone.
- *Biases:* none flagged (no narrative, recency, or rooting interest). Verdict: **BET, normal size**.

## Card

```
BET — WNBA · NY @ ATL (Semifinal G1)
  Over 168.5  -110 (best available)       fair -119 · don't bet below -114
  Blended win prob 54.4% · EV +3.8%
  Stake $10 (1.0u on a $1,000 bankroll) — quarter Kelly (full Kelly 4.2%), no caps bound
  Edge: model total 174 vs opener 168.5 in a record scoring season
  Risk: playoff pace/defence; late scratch — re-check lineups 30 min before tip
  CLV target: close ≥ 170
PASS: ATL -4.5, NY +4.5, both moneylines (all negative after blending)
LOG: python3 -m betlab ledger add --sport WNBA --event "NY @ ATL" --event-date 2026-10-04 --market total \
     --selection "Over 168.5" --line 168.5 --price -110 --stake 10 --book <book> --model-prob 0.5438
21+. Gambling problem? Call 1-800-MY-RESET (1-800-697-3738) or 1-800-522-4700, or text 800GAM.
```
