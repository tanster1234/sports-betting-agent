# Example — a points prop, and why "mean above the line" isn't enough

Scenario (illustrative): star scorer, points line 25.5, over −115 / under −105.

```bash
python3 -m betlab prop implied --stat points --line 25.5 --over -115 --under -105
python3 -m betlab prop --stat points --mean 26.0 --line 25.5 --over -115 --under -105
python3 -m betlab prop --stat points --rate 0.78 --minutes 34 --minutes-sd 3 --pace 1.02 --line 25.5 --over -115 --under -105
```

**1. What the market implies:** the devigged over is 51.1%, which corresponds to a projected
mean of **26.4** points under the WNBA points distribution.

**2. Your projection 26.0:** P(over 25.5) = **49.2%** — *below* 50% even though 26.0 > 25.5.
Points are right-skewed (SD ≈ 8.0 at this mean; variance ≈ 4.58 · mean^0.81), so the median sits
below the mean. EV: over −7.95%, under −0.89%. Neither side qualifies (props need ≥ 4% after
blending); and your projection is *below* the market's 26.4, so the market leans over more than
you do.

**3. A real edge needs a real input:** e.g. confirmed extra minutes (teammate out, 34+ minutes)
or a pace bump the market hasn't priced. Rebuild the projection with `--rate/--minutes`, blend at
≤ 0.5 with the market, and only bet if blended EV ≥ 4% at the best price across books.

**SGP note:** this player's points and threes correlate 0.62 game-to-game (WNBA 2024–26), so
"over points + over threes" is far from independent — books price that; don't assume an edge.
