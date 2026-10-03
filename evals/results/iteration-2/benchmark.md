# Skill Benchmark: sports-betting-agent — iteration 2 (readability revision)

**Executor**: same Claude model as iteration 1
**Date**: 2026-10-03T02:49:39Z
**Evals**: 1, 2, 3, 4, 5, 6, 7 (1 run each per configuration; baseline reused from iteration 1)

## Summary

| Metric | With Skill | Without Skill | Delta |
|--------|------------|---------------|-------|
| Pass Rate | 97% ± 8% | 96% ± 11% | +0.01 |
| Time | 427.4s ± 124.6s | 460.0s ± 328.5s | -32.7s |
| Tokens | 150347 ± 23300 | 108298 ± 51676 | +42049 |

## Notes

- Baseline (without_skill) answers are reused from iteration 1: the baseline never sees the skills, so re-running it would only add sampling noise.
- Assertions: revised skills 36/37 vs 35/37 without. The one miss: on '19-11 at -110, $100 a bet, +$690' the revised answer took 'risk $110 to win $100' as the main reading (the one that reproduces the user's +$690) and gave +$627 only as the alternative; the assertion expects a correction to $627.
- Blind three-way judge (revised v2, original v1, no skills; same rubric wording as iteration 1): both skill versions ranked above no-skills in 7/7. v2 placed first in 3 and v1 in 4; mean overall v2 9.63, v1 9.59, no skills 7.71.
- The revision hit its target: clarity 4.0 -> 4.71 (better in 5 of 7, worse in none), now level with the no-skill baseline (4.57), which judges always found readable.
- Cost: context use 4.86 -> 4.43 (one point lower in 3 of 7: a date caveat buried, sourcing that blurred bundled data with blocked live feeds, no first-round playoff context) and correctness 4.86 -> 4.71 (the stake-convention reading). Net overall change +0.04: a wash within judge noise.
- Follow-up applied after this run (not separately evaluated): the plain-answer template had lost its 'check before betting' block when its example was replaced, although betting-analyst's Step 6 still requires that step. It is restored, plus a 'plain is not thin' writing rule that keeps decision-changing checks near the top.
- Judge variance: the same baseline answers averaged 8.24/10 from iteration 1's pairwise judges and 7.71 from iteration 2's three-way judges; compare configurations within a round, not across rounds.
- Cost: revised skills average 150k tokens and 427 s per answer (iteration 1: 146k, 420 s).
