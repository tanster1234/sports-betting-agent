# Example — 2026 WNBA walk-forward backtest vs DraftKings

Real output. Model fit on 2013–2025 results only, then walked through all 340 games of 2026 in
date order (each date priced before learning from it). Bets at DraftKings' actual opening or
closing price incl. vig; quarter Kelly, 3% cap, $1,000 start, minimum blended EV 2%.

```bash
python3 -m betlab backtest --markets total --price-at open --sweep model_weight=none,0.5,0.35,0.2
python3 -m betlab backtest --markets spread --price-at open --sweep model_weight=none,0.5,0.35,0.2
python3 -m betlab backtest --markets moneyline --price-at open --sweep model_weight=none,0.5,0.35,0.2
python3 -m betlab backtest --markets spread total moneyline --price-at close --sweep model_weight=none,0.35,0.15
```

## Betting the opener (CLV measured against DraftKings' close)

| Market | Model weight | Bets | Record | ROI (95% CI) | Avg CLV | CLV t |
|---|---|---|---|---|---|---|
| Total | raw | 207 | 109-98 | +1.2% (−12.6, +15.3) | +0.95% | 1.15 |
| Total | 0.5 | 100 | 56-44 | +15.4% (−4.4, +35.1) | +3.86% | 2.94 |
| **Total** | **0.35** | **49** | **32-17** | **+32.7% (+4.8, +55.9)** | **+6.01%** | **2.86** |
| Total | 0.2 | 6 | 5-1 | (too few bets) | +19.96% | 5.05 |
| Spread | raw | 226 | 121-105 | +5.1% (−9.0, +17.5) | **−1.50%** | −1.77 |
| Spread | 0.5 | 132 | 77-55 | +7.5% (−10.0, +25.9) | −1.02% | −0.89 |
| Spread | 0.35 | 87 | 49-38 | +1.9% (−20.8, +24.2) | +0.52% | 0.35 |
| Spread | 0.2 | 24 | 11-13 | −7.0% | +3.98% | 1.22 |
| Moneyline | raw | 228 | 83-145 | −2.6% (−23.0, +19.6) | −0.71% | −0.54 |
| Moneyline | 0.35 | 118 | 32-86 | +1.2% | +2.77% | 1.32 |
| Moneyline | 0.2 | 63 | 17-46 | +10.2% (−41.8, +67.4) | +6.39% | 2.07 |

## Betting the close (no CLV possible — you *are* the close)

| Model weight | Bets | Record | ROI (95% CI) |
|---|---|---|---|
| raw | 694 | 305-389 | −4.5% (−14.2, +5.2) |
| 0.35 | 320 | 131-189 | +5.0% (−10.9, +20.6) |
| 0.15 | 75 | 23-52 | +4.8% (−32.8, +44.5) |

## Reading it like a professional

1. **ROI without CLV is a coin toss.** Spreads at the open made +5% with *negative* CLV — that
   profit was luck and would be the worst possible reason to scale up.
2. **Raw model probabilities are overconfident.** Unblended, the model "found" 200+ bets per
   market at claimed EVs of 10–26%; blending with the market (w 0.2–0.5) cuts the bet count and
   lines claimed EV up with realised CLV.
3. **Totals vs openers is the robust signal** — positive CLV at every weight, significant at
   0.35–0.5, and consistent with the independent finding that model–opener disagreement on totals
   predicts the closing move (corr 0.53). Mechanism: the model's league-scoring level adapted to
   2026's officiating-driven scoring surge faster than the openers did.
4. **Moneyline dogs at w=0.2** (CLV t = 2.1, 63 bets) are a weaker, borderline signal.
5. **Nothing beats the close** with statistical confidence — expected for a results-only model.
6. **Multiple testing:** 15 configurations here. The best rows are biased upward; the honest
   claim is "totals-vs-opener CLV is positive and worth validating forward with small stakes",
   not "+32% ROI".

Forward test: log every qualifying total the model flags at the open with
`ledger add ... --tags paper`, record DraftKings (or better, consensus) closes, and run
`python3 -m betlab report` after 100+ bets.
