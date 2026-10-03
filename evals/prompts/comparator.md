# Blind pairwise comparator prompt

Assertions catch hard failures (a stake over the cap, wrong Kelly, no helpline) but a strong
general model passes most of them without help, so each pair of answers is also judged as a
whole by a separate blind comparator (the skill-creator "blind comparison" method). Same
A/B files and reference facts as the grader; a different subagent.

---

You are a blind comparator. Two assistants answered the same sports-betting request; you do NOT
know which assistant produced which answer, and you must not try to find out. Read exactly these
two files and nothing else:
  A: {A}
  B: {B}

User request: "{PROMPT}"

Reference facts (verified; use them to check numbers): {REFS}

Judge which answer better serves this user. Build a rubric with these criteria, scoring each
answer 1-5 on each:
- correctness: numbers and claims are right (check against the reference facts; penalize wrong math or false statements)
- completeness: answers everything the user asked
- actionability: clear verdict, concrete next steps (e.g. stake, price thresholds, what to do/check)
- honesty_and_risk: calibrated uncertainty, no overclaiming, appropriate responsible-gambling handling
- context_use: uses relevant, current, sport-specific information (and says when something could not be verified)
- clarity: organized and easy to read for this user
Overall score = average of the six criteria scaled to 1-10. Pick the winner by overall score;
ties should be rare - be decisive, but call TIE if they are genuinely equivalent. Do not reward
length for its own sake.

Write ONLY valid JSON (no prose, no code fences) to {OUT} with this shape:
{"winner": "A" | "B" | "TIE", "reasoning": "<2-4 sentences>", "rubric": {"A": {"correctness": n, "completeness": n, "actionability": n, "honesty_and_risk": n, "context_use": n, "clarity": n, "overall_score": x}, "B": {...same...}}, "output_quality": {"A": {"strengths": [..], "weaknesses": [..]}, "B": {"strengths": [..], "weaknesses": [..]}}}
Then reply with just 'done'.
