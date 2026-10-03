# Skill evals

Do the skills actually change what Claude says, and do they load when they should? Three
kinds of test, all following the skill-creator method:

1. **Output evals** (`evals.json`, 7 realistic prompts). Each prompt is answered by two
   independent subagents:
   - **with_skill**: works in this repo, reads `CLAUDE.md` and the relevant
     `.claude/skills/*/SKILL.md`, and uses `python3 -m betlab` for numbers;
   - **without_skill**: a general assistant that may use its own knowledge, Python and web
     search, but may not read this repo.

   Both answers are then judged **blind**: they are copied to `A.md` / `B.md` in a random order
   (the order is recorded, never shown to the judges). Two judges work separately:
   - an **assertion grader** checks objective pass/fail assertions with quoted evidence;
   - a **pairwise comparator** scores both answers 1–5 on correctness, completeness,
     actionability, honesty/risk, context use and clarity, then picks a winner.

   Both judges check numbers against verified `reference_facts` stored with each eval. Their
   prompts are in `prompts/` (`comparator-3way.md` for iteration 2).
2. **Trigger evals** (`trigger/*.json`). For the three entry-point skills, 16–20 queries each:
   should-trigger and near-miss should-not-trigger. Each query runs 3× through `claude -p`, and
   the test records whether Claude's first action is to open the skill.
3. **Contamination check.** Executor transcripts are scanned to confirm that no run read
   `evals/` or another run's answers. In iteration 1, one run ran `stat` on `evals.json`
   (file metadata only) and another listed the `evals/` directory; neither opened a file there.

| # | Eval | Main skills exercised |
|---|---|---|
| 1 | WNBA semifinal betting card from given lines | betting-analyst, wnba-betting, odds-math, bankroll-management |
| 2 | "Tier A = 10% of bankroll" vs Kelly | bankroll-management, odds-math |
| 3 | Caitlin Clark assists prop | player-props, wnba-betting, odds-math |
| 4 | Chasing losses with a 4-leg parlay | responsible-gambling, bankroll-management |
| 5 | Tout's 18-7 ATS "system" | backtesting, bet-red-team |
| 6 | Semifinal series price (2-2-1) | wnba-betting, odds-math |
| 7 | "19-11, am I sharp? double my bets?" | bet-tracking, bankroll-management |

## Results — iteration 1

Full detail: `results/iteration-1/benchmark.md`, `comparisons.json` (each judge's reasoning,
strengths and weaknesses), and `review.html`, which shows every answer side by side with its
grades. Open `review.html` in a browser.

| Measure | With skills | Without | Note |
|---|---|---|---|
| Blind pairwise wins | **7 / 7** | 0 / 7 | sign test p ≈ 0.016 |
| Mean overall score (1–10) | **9.42** | 8.24 | |
| Assertions passed | 37 / 37 | 35 / 37 | baseline game card: no CLV/tracking, no helpline |
| Mean wall time | 420 s | 460 s | two baselines spent 14–17 min rebuilding data the repo bundles |
| Mean tokens | 146k | 108k | reading skills and running betlab |

Mean rubric scores (1–5) by criterion:

| Criterion | With | Without |
|---|---|---|
| context use | **4.57** | 3.00 |
| honesty & risk | **5.00** | 3.86 |
| actionability | **5.00** | 4.00 |
| completeness | **5.00** | 4.43 |
| correctness | **4.71** | 4.43 |
| clarity | 4.00 | **5.00** |

What the numbers say:
- **The assertions barely discriminate.** A strong general model passes most objective checks
  unaided, which is why the blind comparison matters.
- **The skills win on substance.** They use current context (the Fever had already been
  eliminated when the Clark prop was asked; the tout's rule was tested on real 2026 lines),
  they blend with the market and pass on within-error edges, and they give bet-only-at prices,
  logging steps and current helplines. Six of seven baseline answers had no
  responsible-gambling resource, and one cited an outdated national helpline.
- **The skills lose on clarity every time.** Judges flagged repo jargon (betlab, profile,
  ledger), CLI blocks in the middle of answers, dense cards for one-line questions, house caps
  presented as the user's rules, and one headline that called quarter Kelly "Kelly".
  Iteration 2 revises `CLAUDE.md` and `betting-analyst` (plain-answer template, writing rules)
  to fix this.

## Results — iteration 2 (readability revision)

Iteration 1's only consistent weakness was clarity. Commit `f2d5ee8` added three things:
- a "write for the person asking" rule in `CLAUDE.md`;
- a plain-answer format for single questions in `betting-analyst`;
- writing rules in its `output-format.md`.

All seven prompts were then re-run with the revised skills. One blind judge per prompt scored
three answers on the same rubric: revised (v2), original (v1) and no skills. The no-skill
answers are reused from iteration 1, since the baseline never sees the skills. Full detail is
in `results/iteration-2/` (`comparisons_3way.json`, and `review.html` with the iteration-1
answers alongside).

| Measure | Revised (v2) | Original (v1) | No skills |
|---|---|---|---|
| Ranked above no skills | 7 / 7 | 7 / 7 | — |
| First place | 3 | 4 | 0 |
| Mean overall (1–10) | **9.63** | 9.59 | 7.71 |
| Clarity (1–5) | **4.71** | 4.00 | 4.57 |
| Context use (1–5) | 4.43 | **4.86** | 3.14 |
| Correctness (1–5) | 4.71 | **4.86** | 4.00 |
| Assertions | 36 / 37 | 37 / 37 | 35 / 37 |

- **The target was hit.** Clarity improved in 5 of 7 answers and got worse in none; the skilled
  answers now read as clearly as the plain assistant's.
- **It cost some context.** Three answers lost a context point: one buried a date caveat, one
  blurred the bundled data with a blocked live feed, and one skipped first-round context.
- **One assertion miss.** On "19-11 … $100 a bet, +$690", the revised answer took "risk $110
  to win $100" as its main reading. That reading reproduces the user's +$690; it gave +$627 only
  as the alternative, and the assertion expects a correction to $627.
- **Overall it's a wash.** +0.04 is well within judge noise. The same baseline answers scored
  8.24 from iteration 1's judges and 7.71 from iteration 2's, so compare within a round only.

**Kept:** the revision, because it fixes the only weakness at no net cost. **Follow-up, not
separately evaluated:** when the plain-answer template's example was replaced, its "check before
betting" block was dropped, although `betting-analyst` Step 6 still requires that step. The
block is now restored, together with a "plain is not thin" rule that keeps decision-changing
checks near the top. A third iteration would test that.

### Trigger evals

| Skill | Should-trigger queries passed | Should-not passed | Trigger rate on should-trigger runs | False-trigger rate |
|---|---|---|---|---|
| `wnba-betting` | 10 / 10 | 10 / 10 | 100% | 0% |
| `betting-analyst` | 10 / 10 | 10 / 10 | 100% | 0% |
| `responsible-gambling` | 8 / 8 | 8 / 8 | 96% | 0% |

A first attempt with skill-creator's `run_eval.py` defaults scored about 10% recall. That
result was an artifact of the harness: 10 parallel workers wrote their temporary skill copies
into one `.claude/commands/` folder, so each `claude -p` call saw about 10 identical skills.
When Claude opened another worker's copy, the run was scored as a miss.
`tools/trigger_eval_isolated.py` gives each call its own project folder; the per-skill files
in `results/trigger/` keep both runs.

## Re-running

The runs are orchestrated from a Claude Code session following the skill-creator workflow:

1. Spawn the with/without runs in parallel and record timing.
2. Grade blind with `prompts/grader.md` and compare blind with `prompts/comparator.md`.
3. Run `python3 evals/tools/unblind.py <workspace>` (iteration 2:
   `evals/tools/summarize_3way.py`).
4. Run skill-creator's `aggregate_benchmark`.
5. Build the static viewer with `eval-viewer/generate_review.py --static`.

Workspaces go to `sports-betting-skills-workspace/`, which is gitignored; summaries are copied
to `results/`.

To re-run, ask Claude Code in this repo: *"Run the evals in evals/evals.json with and without
the skills, grade and compare them blind, and update evals/results."*

To re-run the trigger evals, use the skill-creator skill directory (`$SC`):

```bash
python3 evals/tools/trigger_eval_isolated.py $SC .claude/skills/wnba-betting \
  evals/trigger/wnba-betting.json /tmp/out.json 3 8 60 /tmp/trigger-roots
```

The arguments after the skill path are: eval set, output file, runs per query, workers,
timeout in seconds, and a scratch folder for the per-call projects.
