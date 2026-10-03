---
name: bet-tracking
description: >
  Log, settle and review bets with an append-only, tamper-evident ledger: record each wager
  (price, line, book, stake, your probability), capture closing lines for CLV, settle results
  (win/loss/push/void/half), and produce honest performance reviews — ROI with confidence
  intervals, CLV significance, calibration and Brier skill vs the market, drawdown, losing
  streaks, tilt detection, by sport/market/book/month. Use whenever the user places or settles a
  bet, pastes a bet slip or history, asks "how am I doing?", "am I actually good or lucky?", wants
  a weekly/monthly review, or asks whether to change their unit size.
---

# Bet tracking

Without a log you are guessing; with results-only tracking you are still mostly guessing.
Closing-line value is the fast, honest signal — so every bet gets its closing price recorded.

## Ledger commands

Ledger path comes from the profile (`data/ledger/bets.jsonl`, gitignored); override with
`--ledger PATH`.

```bash
# place (side "over"/"under" is inferred from the selection text)
python3 -m betlab ledger add --sport WNBA --event "NY @ ATL" --event-date 2026-10-04 \
  --market total --selection "Over 168.5" --line 168.5 --price -108 --stake 19 \
  --book FanDuel --model-prob 0.556 --market-prob 0.50 --tier B --notes "opener lag"

# closing line (same number -> price CLV; moved number -> points CLV + model-based CLV EV)
python3 -m betlab ledger close  --bet-id <id> --close-price -115 --close-other -105 --close-line 170.5

# settle (win | loss | push | void | half_win | half_loss)
python3 -m betlab ledger settle --bet-id <id> --result win
python3 -m betlab ledger settle --bet-id <id> --result push --correction "stat correction"   # re-grade
python3 -m betlab ledger void   --bet-id <id> --reason "postponed"

python3 -m betlab ledger list --status open
python3 -m betlab ledger verify          # detects edited / deleted / reordered events
```
Markets: `spread total moneyline team_total prop future parlay sgp teaser period_spread
period_total period_moneyline series other`. Market values are validated; prices accept American
or decimal; settling twice is refused without a correction reason.

**Closing lines**: record the closing price of *your* side and the *other* side (for devig) and
the closing number. Get it from ESPN (`fetch espn-summary` → `odds[0].close`), the book, or an
odds screen right before start. Pinnacle or consensus closes are better than the book you used.

## Reviews

```bash
python3 -m betlab report --format md          # human-readable
python3 -m betlab report                      # full JSON (by sport, market, book, tier, month)
python3 -m betlab report --bankroll 1000      # drawdown % vs a starting bankroll
```
Read them in this order:
1. **Sample size.** < 50 settled bets: nothing about skill can be concluded — say so.
2. **CLV** (`clv_test`): mean, t-stat, share positive. Positive and t > 2 = the process beats the
   market; results will follow with volume. Negative and t < −2 = the market is ahead of you —
   cut stakes and review timing/inputs.
3. **ROI with its 95% CI** (bootstrap). If the CI spans 0, results are consistent with no edge.
   `bets_needed_to_confirm_current_roi` shows how far away proof is.
4. **Calibration**: are your 55% bets winning ~55%? Brier *skill vs market* > 0 means your
   probabilities beat the devigged market's on the same bets (raw Brier ≈ 0.25 is normal for
   coin-flip bets and means nothing alone).
5. **Risk**: max drawdown, current drawdown vs the stop-loss, longest losing streak.
6. **Tilt**: average stake after losing days vs winning days; ratio > 1.25 is flagged.
7. **Segments** (sport/market/book): only act on a segment with ≥ 100 bets *and* a CLV signal;
   otherwise it's noise.

The report ends with a `verdict` line — quote it, then explain it in plain words.

## Importing a history

Map the user's spreadsheet columns to `ledger add` flags and loop (keep `--price` exactly as
quoted, add `--event-date`), then settle each bet. Don't invent closing lines you don't have —
leave CLV empty rather than guessing.

## Monthly routine

1. `report` → summary for the month and all-time.
2. Update bankroll in `config/profile.json` (stakes are proportional; never raise units after a
   good month beyond what the new bankroll implies).
3. Drop or shrink markets with ≥ 100 bets and negative CLV; keep markets with positive CLV even if
   ROI is temporarily negative.
4. Re-check model weights: raise a market's `model_weight` only when your CLV there is
   significantly positive.
