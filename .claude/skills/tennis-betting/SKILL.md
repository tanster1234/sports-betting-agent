---
name: tennis-betting
description: >
  Tennis betting (ATP and WTA): match winners, total games, game handicaps, set betting and live
  in-match prices from an exact point-by-point model fitted on 2019-2026 tour matches, a scanner
  that compares DraftKings/FanDuel with the sharp no-vig price across every in-season tournament,
  surface-aware Elo ratings for context, and tennis-specific rules (retirements, best-of-5, final-set
  tiebreaks, surface, scheduling, integrity in low tiers). Use for anything tennis — "who wins
  Sinner vs Alcaraz", "is over 22.5 games good", "+3.5 games", "2-0 in sets", "what's on in
  Shanghai", "live tennis bet", a tennis prop or parlay leg — even casually.
---

# Tennis betting

Tennis is two players and a fully known scoring system, so prices can be derived exactly: each
player's chance of winning a point on serve gives the chance of holding serve, winning a
tiebreak, a set and the match, and the whole distribution of total games, game margin and set
scores. The pipeline is market-first, like every other sport here.

1. **Fair match price = the sharp market.** Devig Pinnacle (or the sharp-weighted consensus).
2. **Derived markets from that price.** The model turns the match probability into total games,
   game handicaps and set scores. This is where soft books are most likely to be off.
3. **Compare DraftKings/FanDuel** to both. Same EV gates as everywhere (`betting-analyst`).

## Commands

```bash
python3 -m betlab tennis scan --tour all                       # every in-season event: DK/FD vs sharp, games priced
python3 -m betlab tennis price --ml -165 140 --surface hard --games 21.5 22.5 --handicap -3.5 -2.5 \
    --offer games:over:22.5:-110 handicap:b:3.5:-115 sets:a:2-0:+140 ml:b:0:+150
python3 -m betlab tennis price --p 0.62 --surface grass --best-of 5 --final-tb 10   # a Slam
python3 -m betlab tennis live --ml -165 140 --score "6-4 2-3" --points "15-40" --server a --games 25.5
python3 -m betlab tennis predict --tour atp --a "Sinner J." --b "Alcaraz C." --surface hard
python3 -m betlab tennis ratings --tour wta --surface clay --top 20
python3 -m betlab tennis validate                               # the fitted numbers below
```
`--ml` takes A then B (American) and devigs them — pass the sharpest pair you have; `--p` takes A's
probability directly. `--score` is from A's side ("6-4 2-3" = A won set 1, trails 2-3), `--points`
too ("30-15", "40-A", or tiebreak points "5-4"), `--server` is who serves now. `scan` costs Odds
API credits (markets × regions per tournament; about 6 per tournament with the defaults).

## What the model is and how well it fits

Fitted by `scripts/refresh_tennis_data.py` on tour matches with bookmaker closing odds
(tennis-data.co.uk results and odds, ATP 2000 to Mar 2026 and WTA 2007 to Nov 2025, plus Jeff
Sackmann's match stats; numbers in `data/tennis/calibration.json`, fitted 2026-10-06):

| Piece | Value |
|---|---|
| Tour serve points won, 2019-25 (measured) | ATP hard 64.4%, clay 61.7%, grass 65.8% · WTA hard 57.0%, clay 55.3%, grass 58.6% |
| Day-to-day form (spread of the serve gap) | 0.06-0.08 — without it, matches are predicted ~1-1.5 games too long |
| Held-out 2024+ mean total games (actual vs model) | ATP hard 23.57 v 23.62, clay 23.33 v 23.11, grass 24.72 v 24.66 · WTA hard 22.04 v 22.22, clay 21.69 v 21.97, grass 22.12 v 22.46 |
| ATP best-of-5 (Slams 2022+, n=2,057) | 36.93 v 37.12 games; straight sets 44.5% v 47.2% |
| Elo vs bookmaker closing odds (2023+) | log-loss ATP 0.627 v 0.586, WTA 0.620 v 0.587; any blend is worse |

What that means:
- **Totals and handicaps are calibrated in the middle of the range.** In heavy mismatches the
  model still overrates long matches: where it says 18-27% over, overs hit 10-18%. Don't bet
  overs (or underdog game handicaps) in big mismatches on the model alone — require ≥5% EV there.
- **WTA totals run ~0.2-0.3 games high**: shade WTA over prices accordingly.
- **Elo is context, not a price.** It loses to the market clearly; model weight for tennis
  moneylines is 0. Use `predict` when there's no market yet or to sanity-check a big line move,
  and say ratings run through the last results available (currently 2026-05-25).
- The live model averages the pregame form spread and doesn't re-weight it by the score so far,
  so after a lopsided start it trusts the pregame price a little too much. Compare live prices
  with a sharp live price when you have one (`live-betting` rules apply: read at changeovers and
  set breaks, never chase).

## Tennis rules that change the bet

- **Retirements and walkovers.** DraftKings and FanDuel settle these differently by market (often
  the match bet stands once a set is completed, while totals/handicaps are void unless the match
  finishes). Check the book's tennis rules before betting a player with an injury doubt — and
  say so in the answer.
- **Best of 5** (men's Grand Slams) favours the stronger player more than best of 3 —
  `--best-of 5`. All four Slams play a **10-point tiebreak at 6-6 in the final set** (since 2022):
  `--final-tb 10`.
- **Surface matters.** Grass and fast indoor hard favour servers (fewer breaks, more tiebreaks,
  longer sets); clay the reverse. `scan` guesses surface from the tournament name — confirm it.
- **Schedule and fatigue.** Late finishes, long previous matches (especially best-of-5), travel
  between continents, and players arriving straight from Davis/BJK Cup are real but usually
  priced. Treat them as information edges only when they're fresh (a late-night finish the market
  hasn't absorbed).
- **Integrity.** Match-fixing cases are concentrated in Challenger, ITF and qualifying matches.
  Stick to main-tour events; never act on "inside" information about a player's condition.
- **Low-ranked mismatches** carry the biggest bookmaker margins; the edge, if any, is usually
  in line shopping, not the model.

## Answer format

Same as `betting-analyst`: verdict and stake first; the few numbers that decide it (sharp no-vig
price, fair line for the market asked, book price, EV); the main risk (retirement rules, surface,
form); a "bet only at" price; commands in one short block at the end. Give totals and handicaps
as plain words ("over 22.5 games", "Mertens +3.5 games").

## Data and licences

Raw files are downloaded to `data/tennis/` (gitignored) by `scripts/refresh_tennis_data.py` from
Hugging Face mirrors: tennis-data.co.uk results and odds (compiled in Kaggle's "dissfya" daily
pull) and Jeff Sackmann's ATP/WTA match files (Tennis Abstract, CC BY-NC-SA 4.0 — credit him;
non-commercial use). Only aggregate fitted numbers are committed. tennis-data.co.uk itself
blocks cloud servers, which is why the mirrors are used.
