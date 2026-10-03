# Example — pricing the 2026 WNBA semifinals

Ratings as of the end of the first round (bundled data through Oct 1, 2026). Before any injury
adjustment and before blending with market prices — compare against the book's series prices
and devig them first (`python3 -m betlab odds <fav> <dog> --method power`).

```bash
python3 -m betlab wnba series --high ATL --low NY --round semifinals --date 2026-10-04
python3 -m betlab wnba series --high GS --low LV --round semifinals --date 2026-10-04   # if GS beat DAL
python3 -m betlab wnba series --high LV --low DAL --round semifinals --date 2026-10-04  # if DAL beat GS
```

| Series (best-of-5, 2-2-1) | P(higher seed) | Game @ higher | Game @ lower | Fair series ML (higher / lower) |
|---|---|---|---|---|
| (4) ATL vs (8) NY | **71.8%** | 66.3% | 55.5% | −255 / +255 |
| (2) GS vs (3) LV | 54.6% | 56.9% | 45.7% | −120 / +120 |
| (3) LV vs (7) DAL | 71.3% | 66.0% | 55.2% | −248 / +248 |

Exact-result distribution, ATL vs NY: 3-0 24.4% · 3-1 24.6% · 3-2 22.7% · 2-3 11.5% · 1-3 11.6% ·
0-3 5.0%. Series length: 3 games 29.5% · 4 games 36.3% · 5 games 34.3%.

Mid-series update after ATL wins Game 1:
```bash
python3 -m betlab wnba series --high ATL --low NY --round semifinals --date 2026-10-07 --wins-high 1 --wins-low 0
```
(The date should be the next game; add Game 1's result to `data/wnba/games.csv` first so the
ratings learn from it.)

Sanity check against a game line: if a book has ATL −250 for the series but only −150 for
Game 1 at home, back out the per-game probability the series price implies with
`betlab.series.implied_game_prob_from_series` and see which market is out of line.

Caveat: these ratings know nothing about injuries or minutes restrictions; New York just swept
the 1 seed, and a results-only rating gives that only partial weight. Adjust per game with
`series --format 2-2-1 --p-home .. --p-away ..` once you have injury-adjusted game probabilities.
