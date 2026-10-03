# Blind three-way comparator prompt (iteration 2)

Iteration 2 revised the skills for readability. To see whether that helped without losing
substance, one blind judge per eval scores three answers on the same rubric: the revised skills
(v2), the original skills (v1) and the no-skill baseline, copied to `A.md` / `B.md` / `C.md` in
a pre-registered random order (`blind_map_3way.json`). The baseline does not depend on the
skills, so iteration 1's baseline answer is reused. The rubric wording is identical to the
iteration-1 pairwise judge so scores are comparable.

---

You are a blind judge. Three assistants answered the same sports-betting request; you do NOT
know which assistant produced which answer, and you must not try to find out. Read exactly
these three files and nothing else:
  A: {A}
  B: {B}
  C: {C}

User request: "{PROMPT}"

Reference facts (verified; use them to check numbers): {REFS}

Score EACH answer 1-5 on each criterion:
- correctness: numbers and claims are right (check against the reference facts; penalize wrong math or false statements)
- completeness: answers everything the user asked
- actionability: clear verdict, concrete next steps (e.g. stake, price thresholds, what to do/check)
- honesty_and_risk: calibrated uncertainty, no overclaiming, appropriate responsible-gambling handling
- context_use: uses relevant, current, sport-specific information (and says when something could not be verified)
- clarity: organized and easy to read for this user
Overall score = average of the six criteria scaled to 1-10. Then rank the three answers from
best to worst by how well each serves this user (ties allowed only if genuinely equivalent). Do
not reward length for its own sake.

Write ONLY valid JSON (no prose, no code fences) to {OUT} with this shape:
{"ranking": ["A", "C", "B"], "reasoning": "<3-5 sentences>", "rubric": {"A": {"correctness": n, "completeness": n, "actionability": n, "honesty_and_risk": n, "context_use": n, "clarity": n, "overall_score": x}, "B": {...}, "C": {...}}, "output_quality": {"A": {"strengths": [..], "weaknesses": [..]}, "B": {...}, "C": {...}}}
Then reply with just 'done'.
