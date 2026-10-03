---
name: bet-red-team
description: >
  Adversarial review of a proposed bet before money goes down: a cognitive-bias checklist
  (recency, narrative, confirmation, name-brand, small-sample trends, chasing, rooting interest,
  contrarian-for-its-own-sake), a "what does the market know that I don't?" test, stale-data and
  line-movement checks, and an independent subagent that argues the other side. Use whenever a
  bet is about to be recommended or placed, when the user sounds very sure ("lock", "free money",
  "hammer it", "can't lose"), after a bad beat, or when they ask "what am I missing?".
---

# Bet red team

The goal is not to talk the user out of every bet — it is to make sure the edge is the
computed number, not a story. Run this after a candidate clears the EV gate and before sizing.

## 1. The market-knows test (always first)

Answer in writing, one line each:
1. **What is my information edge?** Something specific the market hasn't priced (timing of
   confirmed news, a regime the opener lags, a soft book off consensus). "They're better" is not
   an edge — the line already says how much better.
2. **Where has the line gone since it opened, and why?** If it moved toward my side, part of my
   edge is gone (re-price at the current number). If it moved away by 2+ points (WNBA/NBA) or
   through a key number (NFL 3/7), find the reason before betting — someone may know more.
3. **What does the sharpest price say?** Pinnacle / exchange mid / consensus no-vig
   (`fetch value`, `fetch odds --regions us eu us_ex`). If my fair price disagrees with the sharp
   consensus by more than ~3% probability on a side or total, assume I'm missing something until
   I can name it.

## 2. Bias checklist

| Check | Red flag | Test |
|---|---|---|
| Recency | "They looked great last game" | Does the edge survive if the last 2–3 games are removed? |
| Narrative | "Revenge game", "due", "never loses in big spots" | State the edge with no story — is there a number left? |
| Confirmation | Three stats for, ignored two against | Write the best case for the other side (step 3) |
| Name / brand | Star or famous team carries the pick | Anonymise: "Team A −4.5 vs Team B" — still bet it? |
| Small samples | "8-2 ATS last 10", "5-0 in day games" | Trends need hundreds of games and a mechanism; ignore otherwise |
| Contrarian reflex | Fading the public *as the reason* | Is there a computed edge without the public % ? |
| Market-already-moved | "I knew about the injury first" | Did the line already move ≥ 1 pt? Then it's priced |
| Chasing / tilt | Bet after a loss, bigger size, unfamiliar sport "for action" | Would I make this bet after a winning day? Check `report` tilt metric |
| Rooting interest | Favourite team / hated team | No bet unless the EV is large and independently confirmed |
| Stale inputs | Injury status or line > 15 min old | Refresh before deciding |
| Correlation blindness | Spread + ML + over on the same team | Treat as one position; per-game cap |
| Parlay boosting | Adding legs to make the payout "worth it" | Each leg must be +EV alone; hold compounds |

Scoring: 0 flags → proceed · 1 flag → re-run the numbers cold and halve the stake if it survives
· 2 flags → bet only at a better price (recompute "don't bet below") or pass · 3+ → PASS,
regardless of EV.

## 3. Independent devil's advocate (top 1–3 bets)

Spawn a subagent (Agent tool) that has *not* seen your reasoning, so it can't anchor on it:

```
You are a skeptical professional sports bettor. Argue AGAINST this bet as strongly as the
evidence allows, then give a verdict (BET / SMALLER / PASS) with one sentence of reasoning.
Bet: <selection> at <price> (<book>), <sport>, <game, date/time>.
Market: open <line/price>, now <line/price>, consensus no-vig <prob>.
My fair probability: <p> (model <p_model>, blended at weight <w>), EV <ev%>.
Claimed edge: <one sentence>.
Known context: <injuries, rest, schedule, weather>.
Check specifically: news the market may have that I lack, stale data, line movement, sample
sizes, and whether the "edge" is a narrative. Do not use any betting systems or trends with
fewer than 200 observations. Be concise (<= 150 words).
```
Act on substance, not tone: if it surfaces a concrete fact you lacked (an injury, a lineup, a
weather change), re-price; if it only restates uncertainty, keep the bet and note the risk.

## 4. Pre-placement checklist

- [ ] Best available price confirmed in the last 15 minutes (≥ 2 books checked)
- [ ] Price still better than the "don't bet below" number
- [ ] No news in the last 2 hours that changes inputs
- [ ] Stake from `stake` command; per-game, daily and drawdown caps respected
- [ ] Ledger command ready; closing-line capture planned

## Tone with the user

Be direct and non-judgmental. When a user is emotionally invested ("I need this one", "I'm
down big today"), say what the numbers say, recommend the smaller/pass outcome when warranted,
and if it sounds like chasing, follow `responsible-gambling`.
