---
name: odds-math
description: >
  Exact betting math via tested scripts: American/decimal/implied-probability conversion, vig
  removal (multiplicative, additive, power, Shin, odds-ratio), hold/overround, no-vig fair lines,
  EV and probability edge, breakeven and "worst acceptable price", model-market blending,
  spread<->moneyline conversion, alt lines and half-point value, 1H/1Q derivation, parlay/teaser/
  same-game-parlay pricing, playoff series math, and closing-line value. Use whenever ANY betting
  number is needed — even a "quick" conversion — so it is computed rather than estimated, and when
  explaining these concepts or auditing someone else's numbers (tout EV claims, Kelly formulas,
  "a half point is worth 3%").
---

# Odds math — compute, don't estimate

Language models are unreliable at odds arithmetic (sign conventions, vig, pushes). Every number
in a betting answer should come from `python3 -m betlab ...` (repo root; stdlib only, JSON out).
If you cannot run Python, say the figure is approximate.

## Cookbook

| Question | Command |
|---|---|
| Convert / implied prob of one price | `python3 -m betlab odds -135` |
| Hold + fair probs (all devig methods) | `python3 -m betlab odds -135 115` |
| 3+ way market (futures, soccer 1X2) | `python3 -m betlab odds 2.10 3.40 3.60 --method shin` |
| EV, edge, Kelly, fair price for my prob | `python3 -m betlab ev --prob 0.56 --price -110` |
| Same, blended with the market | `python3 -m betlab ev --prob 0.56 --price -110 --other -110 --model-weight 0.35` |
| Worst price that still clears 2% EV | `python3 -m betlab ev --prob 0.56 --price -110 --other -110 --model-weight 0.35 --min-ev 0.02` (threshold uses the blended prob when a weight is given; `worst_acceptable_basis` says which) |
| Spread → win prob / fair ML | `python3 -m betlab price convert --spread -6.5 --sigma 12.5` |
| Win prob → spread | `python3 -m betlab price spread-from-prob --prob 0.7 --sigma 12.5` |
| Price a whole game from my view | `python3 -m betlab price game --mu 5 --sigma 12.5 --total-mu 172 --total-sigma 18 --spread -4.5 --spread-prices -110 -110 --total-line 170.5 --total-prices -110 -110 --ml -190 160` |
| Alt-spread ladder | `python3 -m betlab price alt --mu 5 --sigma 12.5 --home ATL --lines -10.5 -7.5 -4.5 -1.5 2.5` |
| Margin frequencies (key numbers / pushes) | `python3 -m betlab price keys --mu 5 --sigma 12.5` |
| 1H / 1Q lines from full game | `python3 -m betlab price period --spread -6.5 --total-line 171.5 --period first_half` |
| Totals probability and EV | `python3 -m betlab price total --total-mu 174 --total-sigma 18 --total-line 170.5 --total-prices -110 -110` |
| Parlay (independent) + compounded hold | `python3 -m betlab parlay --probs 0.55 0.55 --prices -110 -110 --leg-hold 0.0455` |
| Same-game parlay with correlation | `python3 -m betlab parlay --probs 0.6 0.55 --corr '[[1,0.35],[0.35,1]]' --offered 230` |
| Series price | `python3 -m betlab series --format 2-2-1-1-1 --p-home 0.62 --p-away 0.52` |
| CLV (same number) | `python3 -m betlab clv --bet -105 --close -125 --close-other 105` |
| CLV (number moved) | `python3 -m betlab clv --bet -110 --line -3.5 --close -110 --close-other -110 --close-line -5.5` |

`--sport WNBA|NBA|NCAAB|NFL|NCAAF` selects calibrated σ/overtime handling in `price`.
Defaults: WNBA σ_margin 12.5, σ_total 18; NBA 12 / 18; NFL 13.5 / 10 (see `betlab/markets.py`).

## Definitions that prevent most mistakes

- **Decimal odds** include the stake: -110 → 1.909; +150 → 2.50.
- **Implied probability** of one price = 1/decimal (contains vig): -110 → 52.38%.
- **Overround** = Σ implied − 1 (-110/-110 → 4.76%). **Hold** = 1 − 1/Σ implied (→ 4.55%), the
  book's expected margin on balanced action.
- **Fair (devigged) probability**: remove the overround. Two-way markets: multiplicative is
  standard and all methods agree near 50/50. Lopsided/longshot/futures markets: use `power` or
  `shin`, which assign more of the margin to longshots (favourite-longshot bias). If methods
  disagree by more than your edge, you don't have an edge.
- **EV** (expected profit per 1 staked) = p_win·(d − 1) − p_loss; pushes return the stake.
- **Probability edge** = p − 1/d. EV = d × probability edge (no pushes). A 2-point probability
  edge is +3.8% EV at -110 but +8% at +300 — thresholds must say which one they mean. betlab
  thresholds are **EV**.
- **Blending**: `p = logit⁻¹(w·logit(p_model) + (1−w)·logit(p_market))`. Use it: raw model
  probabilities vs sharp markets are overconfident (WNBA 2026: raw model EV 10–26%, realised ~0).
- **CLV** = expected ROI if the closing line is true: p_close_fair × d_bet − 1. A bet with no
  line movement at -110/-110 has CLV ≈ −4.5% (the vig). Positive CLV means you beat the close by
  more than the vig.

## Known-wrong formulas to correct when you see them

| Claim | Correction |
|---|---|
| Kelly = edge × decimal / (decimal − 1) with edge vs the **vig-free** prob | Only correct with edge vs the *vigged* breakeven 1/d. With vig-free 50%, p=57% at -110 gives 14.7% instead of the true 9.7%. Use `kelly` (`(b·p − q)/b`). |
| "Edge ≥ 2%" without saying EV or probability | Ambiguous by a factor of d. Use EV. |
| "Half a point is worth ~3% of win probability" | Only near the median and only in sports with key numbers. WNBA: −5.5→−5 changes *push* probability by P(margin = 5) ≈ 3%, and win probability by 0. Use `price alt` / `half_point_value`. |
| "Brier < 0.22 means a good model" | For near-coin-flip bets every forecaster scores ≈ 0.25. Compare to the market's Brier (Brier skill score) instead — `report` does this. |
| "A 4-leg parlay of +EV legs is +EV" | Only if each leg's edge survives the compounded hold: four -110 legs carry ~17% hold. |
| Expected margin = spread "in the favourite's direction" | ESPN's `spread` field is from the **home** team's perspective; DK "LV -11.5" at POR shows `spread: 11.5`. |

## Sanity checks before quoting a number

- Probabilities in (0, 1) and both sides of a devigged market sum to 1.
- Favourite has the higher probability under every devig method.
- EV sign agrees with "fair price better or worse than offered".
- Integer lines produce a push probability; half-point lines don't.
