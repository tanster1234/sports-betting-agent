# Skill Benchmark: sports-betting-agent — iteration 1

**Executor**: same Claude model for both configurations
**Date**: 2026-10-03T02:25:35Z
**Evals**: 1, 2, 3, 4, 5, 6, 7 (1 run each per configuration)

## Summary

| Metric | With Skill | Without Skill | Delta |
|--------|------------|---------------|-------|
| Pass Rate | 100% ± 0% | 96% ± 11% | +0.04 |
| Time | 419.6s ± 111.2s | 460.0s ± 328.5s | -40.5s |
| Tokens | 146104 ± 23855 | 108298 ± 51676 | +37806 |

## Notes

- Assertions barely discriminate: 37/37 with skills vs 35/37 without. Six of seven evals are 100% for both; the only misses are the baseline's game card (no CLV/tracking mention, no helpline). A strong general model passes most objective checks unaided, so the pass-rate delta (+4 pts) understates the difference.
- Blind pairwise comparison (one comparator per eval, answers shown as A/B in random order): with-skill wins 7/7 (sign test p = 0.016), mean overall 9.42 vs 8.24 out of 10.
- Where the skills win (mean 1-5 rubric, with vs without): context use 4.57 vs 3.00 (bundled 2026 data, current helplines, Fever already eliminated, tout's rule tested on real lines), honesty/risk 5.00 vs 3.86 (market blending, PASS discipline, RG resources), actionability 5.00 vs 4.00 (bet-only-at prices, logging), completeness 5.00 vs 4.43, correctness 4.71 vs 4.43.
- Where they lose: clarity 4.00 vs 5.00 in all seven pairs. Judges flagged repo jargon (betlab, profile, ledger), CLI blocks mid-answer, dense cards for one-line questions, house caps presented as the user's rules, and one headline that called quarter Kelly 'Kelly'. Iteration 2 targets exactly this.
- Baseline failure modes the skills prevent: an outdated helpline (1-800-GAMBLER as the national line), advice framed around a game that no longer exists (eliminated team), unblended handicaps that lean toward betting a within-error edge, confidence-tier sizing, 'fun' bets on a no-edge angle, no responsible-gambling resource in 6 of 7 baseline answers (only the chasing-losses reply had one).
- Cost: with skills +35% tokens (146k vs 108k mean) but 9% less wall time (420 s vs 460 s); two baselines spent 14-17 minutes rebuilding WNBA data from public sources that the repo already bundles.
- Length: with-skill answers average 952 words vs 840 (+13%); the clarity gap is about jargon and structure more than length.
- Single run per configuration and one comparator per pair: treat as directional evidence, not a precise effect size.
