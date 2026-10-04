---
name: live-betting
description: >
  In-game (live) betting reads for WNBA and NBA games in progress: what the play-by-play shows
  (runs, foul trouble, who is on the floor, shooting luck, turnovers), a fair live price from the
  score, clock and pregame line (fitted on WNBA halftime scores), and whether a live price at
  DraftKings/FanDuel beats the sharp live market. Use whenever someone asks about a game that is
  already on — "should I bet live?", "they're on a run", "can they come back?", "momentum",
  "halftime line", "second-half bet", "live total", "is this live price good?", or wants
  play-by-play analysis — even casually. Also use to answer "can you analyze play by play?".
---

# Live betting — read at the breaks, trust the sharp price

Live markets are where books are strongest: they see the game seconds before any free feed,
pause betting at the big moments, and price with lineup and shot data. So the job here is
narrow and honest:

1. **Describe what the score hides** (play-by-play facts).
2. **Put a fair number on the game** (a model validated at halftime).
3. **Compare the user's books to the sharp live price**, with the model only as a sanity check.
4. **Pass unless all three line up.** Most live checks end in PASS — say so plainly.

Scope: WNBA (fitted) and NBA (WNBA shape with NBA spreads — not fitted; say so). Not football:
there is no play-by-play model for it here.

## Workflow

```bash
# 1. find the game (ESPN event id) and the score
python3 -m betlab fetch espn-scoreboard --league wnba --date 20261004
# 2. live prices: books + Pinnacle (eu) for the sharp price. Cost = markets x regions credits.
python3 -m betlab fetch odds --league wnba --event ODDS_API_EVENT_ID --markets h2h spreads totals --regions us eu
# 3. the read (pregame line defaults to the ESPN summary's DraftKings close)
python3 -m betlab liveread --event 401918295 \
    --offer ml:home:0:-120:dk spread:away:1.5:-120:fd total:over:178.5:-115:dk \
    --sharp ml:-120:-101 spread:-1:-112:-108 total:176.5:-107:-113
```
`--offer` is `market:side:line:price[:book]` (ml line is ignored); `--sharp` is
`ml:HOME:AWAY`, `spread:HOME_LINE:HOME:AWAY`, `total:LINE:OVER:UNDER`. A sharp spread or total
is only compared with offers on the same line. Use `--summary FILE` to re-read a saved ESPN
summary, `--league nba` for the NBA.

Output: `facts` (runs, lead changes, largest leads, last-5-minute scoring, foul trouble, on-floor
fives, shooting vs typical rates, technical/flagrant/ejection/injury plays), `price` (fair win
probability and moneyline, fair spread and total, chance of overtime, and the naive
time-scaling number for contrast), `offers` (model probability, EV vs the model, sharp no-vig
probability, EV vs sharp, `qualifies`), and `notes` — plain-language bullets to build the
answer from.

## Decision rules

- **Qualifies only if** the book beats the sharp live no-vig price by ≥3% EV **and** the model
  is within 6 points of the sharp probability. No sharp live price → no bet: the model alone is
  not enough live.
- **Model vs sharp gap > 6 points → assume the market knows something** (a lineup, an injury in
  the locker room, shot quality) and pass. Don't argue with every book at once.
- **Best windows:** halftime, quarter breaks, long timeouts — the information has settled and
  prices are stable. Never fire mid-possession or right after a big run because it "feels"
  like a moment.
- **Same sizing as pregame:** quarter Kelly and the same caps (`python3 -m betlab stake`), and
  live bets count toward the day's budget. Check today's exposure first.
- **Live is the #1 chasing trap.** If the user is trying to win back an earlier loss, raising
  stakes, or betting every swing, stop and switch to `responsible-gambling`.

## What the data says (WNBA halftime scores, `python3 -m betlab liveread validate`)

Fitted on 1,175 games with halftime scores (2023-25 against the bundled model's pregame line,
2026 against DraftKings closes):

| Finding | Number |
|---|---|
| Second-half margin | 0.48 × pregame margin **− 0.15 × halftime lead** (sd 9.5) |
| Lead reversion | −0.15 per point (95% CI −0.21 to −0.09); −0.14 / −0.20 / −0.11 / −0.15 in 2023/24/25/26 |
| Leader by 6–10 at the half won | **77.8%** (n=338); fitted 77.7%, naive time-scaling 82.1% |
| Leader by 11–20 at the half won | **91.0%** (n=333); fitted 91.6%, naive 95.1% |
| 2026 out-of-sample win prob at half (log-loss) | fitted 0.430 · naive 0.434 · pregame-only 0.578 |
| Second-half total | pregame half-total + only **0.1 ×** the first half's pace surprise |
| 2026 second-half total error (RMSE) | pregame half 13.6 · first-half pace projection **16.6** |

What that means for answers:
- **Comebacks are real, modestly:** halftime leads hold less often than simple math says. The
  model already includes it; don't add more on top for "momentum".
- **Don't chase pace on totals.** A fast first half barely predicts a fast second half;
  projecting the first-half pace is much worse than the pregame number.
- Only halftime is validated. Other times scale the halftime shape with the time left — rougher
  in the first quarter, and plain time-scaling in overtime. The output says when.

## Signal vs story

| Usually signal (play-by-play shows it before the score) | Usually story |
|---|---|
| A starter in foul trouble (2 in Q1, 3 in Q2, 4 in Q3, 5 in Q4), a foul-out | "Momentum", "they want it more" |
| An injury exit, ejection, technical/flagrant trouble | A 10-0 run on its own |
| Shooting far above/below typical (hot threes, perfect FTs) — tends to fade | "Hot hand" streaks of a few shots |
| A big turnover gap — tends to narrow | "They always come back at home" |
| Starters resting vs on the floor at a break | Narrative revenge/rivalry angles |

The shooting-luck numbers compare to rough league rates (WNBA 34% 3PT / 80% FT, NBA 36% / 78%);
they describe the game and never feed the price.

## Answer format

Lead with the verdict in one line (PASS, or the bet with "only at X or better"), then:
- score and clock;
- the 2–4 facts that matter, in plain words;
- fair number vs the books vs the sharp price (one small table);
- when to look again (next break).
Keep commands in one block at the end. Say what the feed can't see (lag, lineups) when it
matters to the call.

## Limits

- ESPN's feed runs ~30–60 s behind the books; books suspend at big moments.
- No lineup, shot-quality or player-impact model; injuries in the locker room show up late.
- NBA uses the WNBA shape (not fitted); only WNBA halftime is validated.
- No live-odds history here, so there is no backtest against live prices — the model is a
  sanity check on the sharp market, not a replacement for it.
