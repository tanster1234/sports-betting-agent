# Review of the three reference repositories

What each project is, what this repo adopted, and the problems found (with the fix here).
Reviewed 2026-10-03 at their default branches.

## 1. magicjordan33/sports-betting-claude

**What it is.** A Claude *Project* (claude.ai) prompt system: `PROJECT_INSTRUCTIONS.md` plus
"skill" markdown files for data ingestion, edge detection, bankroll, performance tracking,
an anti-bias checklist, an output format, and sport files for NFL, NBA, MLB, NHL and NCAA. The
pipeline (ingest → edge → size → sport context → bias check → output) and the emphasis on
passing, CLV and logging are sound. No code, no tests, no WNBA (its CONTRIBUTING lists WNBA as
wanted).

**Adopted:** the layered pipeline; "no edge = no bet"; a fixed output card; the anti-bias
checklist idea; log-everything and monthly review; sport-specific red flags.

**Problems found → fix in this repo**

| # | Problem | Why it matters | Fix |
|---|---|---|---|
| 1 | Files have no YAML frontmatter, so they are not Claude Code skills (no `name`/`description`, no triggering) | They only work pasted into a claude.ai Project | 11 real skills under `.claude/skills/` with descriptions tuned for triggering |
| 2 | All math is done in prose by the model | LLM odds arithmetic is error-prone | `betlab` package does every calculation; 240 tests |
| 3 | Kelly in `bankroll-management` uses edge vs the **vig-free** probability: Kelly = edge·d/(d−1) | Over-states Kelly: p=57% at -110 → 14.7% instead of 9.7% | Textbook `(b·p − q)/b`, push-aware; test `test_reference_repo_formula_bug_is_not_reproduced` |
| 4 | Edge example compares 57% to "market 52.4% (after vig)" — 52.4% is the *vigged* implied prob; the same file's Step 1 says vig-free is 50% | Edge mis-measured by ~2.4 points | EV defined explicitly; both EV and probability edge reported |
| 5 | "Edge ≥ 2%" threshold never says EV or probability points | Off by a factor of d (2× at +100, 4× at +300) | Thresholds are EV after market blending, per market type |
| 6 | Kelly quick table: +140 rows wrong (4% edge → "6.3%" Kelly; correct 2.9% if edge is EV) | Inconsistent sizing | Sizing only from `kelly`/`stake` commands |
| 7 | Tier sizing: Tier A = 4–5 units at 2% = 8–10% of bankroll | For +4.8% EV at -110, full Kelly is 5.3% → 1.5–1.9× full Kelly, where growth heads to zero | Quarter Kelly first, caps can only reduce; tiers removed (test `test_reference_tier_sizing_exceeds_full_kelly`) |
| 8 | Brier "< 0.22 = good" | Any forecaster scores ≈0.25 on coin-flip bets; threshold is meaningless | Brier *skill score vs the market* in `report` |
| 9 | Red flag "win rate < 50% over last 20 bets" and trends "minimum 20 data points" | 20 bets/games is pure noise | Sample-size math (`bets_needed`), CLV-first verdicts, ≥ 200-obs rule for trends |
| 10 | NBA numbers: HCA +3–4, B2B −3 to −5 ("single biggest edge"), star out −6 to −10, refs ±3–5 on totals, Denver +5–6 | Outdated/overstated; over-adjusting creates fake edges | Corrected ranges in `multi-sport-context` (HCA ~2–2.5, B2B ~1–2, etc.) |
| 11 | NFL: QB out −15 to −20, "reduce divisional spreads 20–25%", bye +1.5–2.5; DVOA "from Football Outsiders" | Overstated / unsupported / stale source (FO closed 2023) | Corrected in `references/nfl.md`; key-number pricing via empirical pmf |
| 12 | NCAA home field +6 to +10 (football), +5 to +8 (basketball) | ~2× too large | ~2.5–4 and ~3 respectively |
| 13 | "A half-point on a spread moves win probability ~3%" | True only at key numbers; in basketball a half point across an integer changes *push* odds, not win odds | `price alt` / `half_point_value` compute it exactly |
| 14 | Data: "PointsBet" in book lists, Rotoworld/FO references; "access live odds APIs: no" | Stale; no automation | ESPN + The Odds API fetchers with tested parsers and network fallbacks |
| 15 | No WNBA | User requirement | `wnba-betting` skill + calibrated model + 2026 data + backtests |

## 2. OneWave-AI/claude-skills — `sports-betting-analyzer`

**What it is.** A short generic template (frontmatter + "You are an expert sports betting
analyst... include responsible gambling disclaimers" + placeholder output format and
"[Sample user request here]").

**Adopted:** correct Claude skill packaging (frontmatter `name` / `description`) and the
requirement to include responsible-gambling information.

**Problems:** no methodology, numbers, data sources or tests; generic placeholders; a
description too vague to trigger reliably. Every skill here has concrete workflows, commands,
calibrated numbers and "pushy" descriptions listing real trigger phrases.

## 3. sklls/betting-app-skill — `betting-app`

**What it is.** A real Claude skill (also shipped as a `.skill` zip) for *building* a
pari-mutuel betting web app (Next.js + Supabase): schema, atomic `place_bet` RPC with
`SELECT ... FOR UPDATE`, odds preview including the bettor's own stake, settlement with an
early-bird bonus, admin/leaderboard patterns, and with/without-skill evals.

**Adopted (translated to a single bettor's tooling):**
- financial logic must be deterministic and centralised → `betlab`, never prompt arithmetic;
- never trust client-supplied odds → every price is re-parsed and validated in code;
- an append-only transaction trail → the hash-chained JSONL ledger with idempotent settlement;
- evaluate the skill with vs without it → `evals/`.

**Problems found (relevant if you build their app):**
| Problem | Consequence |
|---|---|
| `place_bet` accepts `p_odds` from the caller, contradicting its own "never trust client odds" rule | Users can submit inflated odds |
| `place_bet` takes `p_user_id` and is `SECURITY DEFINER` | Any user could bet from another user's wallet unless the API layer forbids it; should use `auth.uid()` |
| `place_bet` never checks the market is `open` | Bets can be placed on closed/settled markets |
| `settle_market` pays `amount × odds_at_placement` (+10% early bird) | That is fixed-odds settlement on a pari-mutuel pool — payouts can exceed the pool (house insolvency) |
| `settle_market` sets `markets.updated_at`, a column the schema doesn't define | Settlement fails at runtime |
| Leaderboard view joins `bets` and `transactions` in one GROUP BY | Row fan-out multiplies `SUM(win amounts)` by the number of bets |
| `void` status and `refund` transaction type exist but nothing refunds voided bets; settlement doesn't check the market is closed (only bets still `pending` are paid, so re-running it doesn't double-pay) | Stakes on cancelled markets are lost; a market can be settled while still open |

None of these affect this repo (it does not run a betting app), but they are worth knowing
if you ever combine the two.
