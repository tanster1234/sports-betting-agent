# Where betting edges actually come from

Ranked by how reliably they survive real-world testing. Use this to decide where to spend
analysis time and how much model weight to give your own view.

## Tier 1 — structural, model-free

1. **Line shopping.** Taking -105 instead of -115 on a coin flip moves EV from -6.5% to -2.4% (~4 points);
   across a season it is the difference between losing heavily and nearly breaking even. Always quote the best price.
2. **Soft book vs sharp consensus.** When one book lags the devigged consensus of several
   (weighted toward Pinnacle/exchanges), its price can be +EV without any opinion about the game.
   `python3 -m betlab fetch value --league wnba --min-ev 0.02` (leave-one-out consensus).
   Expect limits if you do this a lot.
3. **Stale lines after news.** Books update at different speeds after an injury/lineup report.
   Being first with *confirmed* news is an edge; acting on rumours is not.

## Tier 2 — model-based, validated by CLV

4. **Openers that lag a regime change.** WNBA 2026 totals: openers trailed the league's scoring
   jump; model–opener disagreement predicted closing movement (corr 0.53). Bet early, small,
   and verify with CLV.
5. **Props with a real minutes/usage view.** Books post hundreds of props with thinner risk
   management; a better minutes projection (injury return, rotation change) is a genuine edge.
   Hold is higher (~6–7%), so thresholds are higher.

## Tier 3 — situational, weak alone

6. Rest/back-to-backs, travel, altitude, weather (outdoor sports), motivation spots. Mostly
   priced; useful only as an adjustment inside a computed number. WNBA B2B is worth ~2.3 points
   and is rare.

## Things that are not edges

| Claim | Why it fails |
|---|---|
| "They're 8-2 ATS in their last 10" | n = 10; ATS outcomes are ~coin flips; you need hundreds of games and a mechanism |
| "70% of the public is on the favourite, fade it" | Bet percentages are not a model; books balance risk, not tickets |
| "Reverse line movement = sharp money" (alone) | Moves have many causes; with no price edge it's just a story |
| "Due for a win/regression" | Gambler's fallacy unless a measurable process stat (shooting luck) supports it |
| "Lock", "can't lose", parlays to "juice" a pick | Every parlay leg compounds hold (4 legs ≈ 17% hold) |
| A model that beats the close in a backtest you tuned on the same data | Multiple testing; re-test forward |

## How much to trust your own number

| Situation | Model weight vs market |
|---|---|
| Liquid closing lines (NFL/NBA sides) | 0.05–0.15 |
| WNBA spreads / moneylines | 0.15 |
| WNBA totals vs openers | 0.35 (validated by 2026 CLV) |
| Props with a strong minutes view | 0.5 |
| Your own track record shows significant positive CLV in a market | raise gradually |
