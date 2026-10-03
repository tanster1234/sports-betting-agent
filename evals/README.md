# Skill evals

Do the skills actually change what Claude says? Each prompt in `evals.json` is run twice by
independent subagents:

- **with_skill** — working in this repo, told to read `CLAUDE.md` and the relevant
  `.claude/skills/*/SKILL.md` files and use `python3 -m betlab` for numbers;
- **without_skill** — a baseline general assistant that may use its own knowledge, Python and
  web search, but may not read this repo.

Each final answer is then graded **blind**: a separate grader subagent sees both answers as
"Response A / B" in random order, plus verified reference numbers, and marks every assertion
pass/fail with evidence. Assertions test correctness and safety (stake within caps, correct
devig/Kelly/series math, no fabricated EV, recognising chasing, sample-size honesty), not style.

| # | Eval | Main skills exercised |
|---|---|---|
| 1 | WNBA semifinal betting card from given lines | betting-analyst, wnba-betting, odds-math, bankroll-management |
| 2 | "Tier A = 10% of bankroll" vs Kelly | bankroll-management, odds-math |
| 3 | Caitlin Clark assists prop | player-props, odds-math |
| 4 | Chasing losses with a 4-leg parlay | responsible-gambling |
| 5 | Tout's 18-7 ATS "system" | backtesting, bet-red-team |
| 6 | Semifinal series price (2-2-1) | wnba-betting, odds-math |
| 7 | "19-11, am I sharp? double my bets?" | bet-tracking, bankroll-management |

## Re-running

The runs were orchestrated from a Claude Code session following the skill-creator workflow
(spawn with/without runs in parallel → record timing → blind grading → aggregate →
`eval-viewer/generate_review.py --static`). Workspaces are written to
`sports-betting-skills-workspace/` (gitignored); summaries are copied to `evals/results/`.

To re-run, ask Claude Code in this repo: *"Run the evals in evals/evals.json with and without
the skills, grade them blind, and update evals/results."*

## Results

See `results/benchmark.md` (pass rates, time and tokens per configuration) and
`results/review.html` (every answer side by side with its grades).
