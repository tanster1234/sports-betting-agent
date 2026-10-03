# Output formats

Numbers in every format come from `python3 -m betlab` output — copy them, don't retype them
from memory. Pick the shape from the request: a single question gets the **plain answer**;
picks, a card or a slate get a two-line plain summary followed by the **daily card** (cards stay
identical day to day so they are easy to log and audit).

## Writing rules (all formats)

- First two lines: the verdict and the stake (or "no bet"), in words a casual bettor uses.
- Define a term the first time it matters, in a few words: EV (average profit per $1 bet),
  devig / no-vig (the price with the bookmaker's cut removed), CLV (beating the final price
  before the game), Kelly (a staking formula; we use a quarter of it). Otherwise leave it out.
- Keep internals out of the reasoning: no `betlab` function names, file paths, profile fields,
  "the ledger is empty", or placeholder bankrolls. Commands live in the closing log block.
- Advice, not house rules: "I'd keep any single bet under 3% of your bankroll ($60)", not "my
  limits are 3%". If the bankroll is unknown, size in % and ask for it.
- Every headline is literally true: "quarter Kelly says $121" (not "Kelly says $121"); when
  model and market weights differ by market, say which weight produced which number.
- Facts from notes or bundled data carry their source and date; leave out specifics you can't
  source. One small table at most in a plain answer.
- Plain is not thin: shorten the machinery, never the checks that change the decision (date,
  opponent, team status, injuries, recent games, line moves). Put those near the top.

## Plain answer (default for a single question)

Example request: "[Player] threes 2.5, over +120 / under -150. She averages 2.6. Bet the over?"

```
**No bet at +120.** Her 2.6 average makes the over a 47% shot, but the market says 43%; blended,
it's about 45%, just under the 45.5% that +120 needs to break even.

Why
- The book's price with its cut removed (no-vig) puts the over at 43.1%. A season average is
  public, so it's already in that number; I weight our projection and the market 50/50 for props.
- That leaves an expected loss of about 1 cent per $1 bet. Nothing to size.

Check before betting (anything here can flip the answer)
- The game and price are current: date, opponent, still on the board (as of 6:40 PM ET).
- Status: tonight's injury report and lineup news.
- Say where each fact came from: "results through Oct 1 in the bundled data" is not the
  same as a live feed — and say which live sources failed.

What would change it
- News the line hasn't absorbed: a starter out, a minutes bump, a pace-up matchup.

Bet only at: over +132 or better (that clears the +4% edge I require on props).

Log it if you bet: python3 -m betlab ledger add ... (one block, at the end)

21+. Gambling problem? Call 1-800-MY-RESET (1-800-697-3738) or 1-800-522-4700, or text 800GAM.
```
(Numbers from `prop --stat threes --mean 2.6 --line 2.5 --over 120 --under -150` and
`ev --prob 0.4675 --price 120 --other -150 --model-weight 0.5 --min-ev 0.04`; regenerate yours.)

## Daily card

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATE: Sun Oct 4, 2026 (ET)       BANKROLL: $1,000   UNIT (1%): $10
EXPOSURE TODAY: $29 / $100 cap   DRAWDOWN FROM PEAK: 3.1%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BET 1 — WNBA · NY @ ATL (Semis G1, 3:00 PM ET)
  Market      Total
  Selection   Over 168.5          Best: FanDuel -108 (DK -110, MGM -112)
  Fair        -125 (55.6%)        Model 174.0 · market 168.5 · blend w=0.35
  Win prob    55.6% (blended)     EV +7.1%   Don't bet below: -120
  Stake       $19 (1.9u) — quarter Kelly, no caps binding
  Edge        Opener 166.5 lagged the 2026 scoring level; model–opener gap 7.5 pts.
  Risk        Both teams top-3 defenses in the first round; pace fell 4% in playoffs.
  CLV target  close ≥ 170
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASSED (no qualifying edge): LV @ GS spread (best +1.6% EV), NY ML (+0.4%)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LOG:
python3 -m betlab ledger add --sport WNBA --event "NY @ ATL" --event-date 2026-10-04 --market total \
  --selection "Over 168.5" --line 168.5 --price -108 --stake 19 --book FanDuel --model-prob 0.556
After the game: ledger close (closing price) → ledger settle (result).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
21+. Bet only what you can afford to lose. Gambling problem? Call 1-800-MY-RESET (1-800-697-3738)
or 1-800-522-4700, or text 800GAM.
```
(Illustrative numbers — always regenerate.)

## Single-game analysis

```
ANALYSIS: NY @ ATL — WNBA Semifinal G1 — Oct 4, 3:00 PM ET
Lines (best / book / time):  ATL -4.5 -105 FD 10:12 ET · Total 168.5 · ATL -190 / NY +165
Opener → now:                ATL -2.5 → -4.5 · Total 166.5 → 168.5   (signal: money on ATL and over)
Model (wnba predict):        ATL by 5.2 (σ 12.5) · total 174.0 (σ 17.7) · ATL win 66.3%
Adjustments:                 none (both teams healthy per 5 PM report)
Market fair (devigged):      ATL cover 50.4% · over 50.0% · ATL ML 63.9%
Blended (w): spread .15 / total .35 / ML .15
EV at best price:            ATL -4.5: -1.2% · Over 168.5: +7.1% · ATL ML: +0.8%
Bias check:                  passed (no recency/narrative flags; anonymised test passes)
Red team:                    "playoff pace drop" — checked: first-round totals still averaged 178
VERDICT:                     BET Over 168.5 (-108, FD), 1.9u.  PASS spread and ML.
Why:                         Totals vs openers is the one WNBA signal with significant CLV in
                             2026 backtests; the gap here (7.5 pts) is large.
```

## No qualifying bets

```
DATE: ...   BANKROLL: ...
NO QUALIFYING BETS TODAY — 9 games / 27 markets reviewed.
Closest: CHI +6.5 (+1.4% EV, threshold 2.0%). Fair prices below so you can act if lines move:
  CHI +6.5 fair -116 → bet only at +7 -110 or better
  LV/SEA Under 171.5 fair -109 → bet only at 173 or better
Passing is the right call. Bankroll protected.
```

## Performance summary (from `python3 -m betlab report --format md`)

Lead with CLV and sample size, then ROI with its confidence interval, then the verdict line the
report produces. Never headline "units won" without the CI.

## Required elements checklist

- [ ] verdict and stake in the first two lines, in plain words
- [ ] best price + book + time for every bet; fair price; blended probability; EV%
- [ ] stake in $ (or % of bankroll if unknown), with which cap (if any) bound
- [ ] information edge (one sentence) and main risk (one sentence)
- [ ] don't-bet-below price and CLV target
- [ ] passes with closest near-miss
- [ ] cards only: date, bankroll, unit, today's exposure, drawdown
- [ ] ledger commands in one closing block
- [ ] responsible-gambling footer
