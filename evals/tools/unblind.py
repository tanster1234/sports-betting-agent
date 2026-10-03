"""Map blind A/B grades and comparisons back to with_skill / without_skill.

usage: python3 evals/tools/unblind.py <workspace> [iteration-1]

Reads <workspace>/blind/<eval>/{grades,comparison}.json and <workspace>/<iteration>/blind_map.json;
writes grading.json into each run directory (the format skill-creator's aggregate_benchmark.py and
eval viewer expect) and prints a comparison summary, also saved as <iteration>/comparisons.json.
"""
import json
import pathlib
import sys

ws = pathlib.Path(sys.argv[1])
it = ws / (sys.argv[2] if len(sys.argv) > 2 else 'iteration-1')
mapping = json.loads((it / 'blind_map.json').read_text())
CRITERIA = ('correctness', 'completeness', 'actionability', 'honesty_and_risk', 'context_use', 'clarity')

for name, m in mapping.items():
    g = ws / 'blind' / name / 'grades.json'
    if not g.exists():
        continue
    grades = json.loads(g.read_text())
    meta = json.loads((it / f'eval-{name}' / 'eval_metadata.json').read_text())
    for label in ('A', 'B'):
        cfg = m[label]
        exps = grades[label]
        assert len(exps) == len(meta['assertions']), (name, label, len(exps))
        for e, text in zip(exps, meta['assertions']):
            e['text'] = text
            e['passed'] = bool(e['passed'])
        passed = sum(e['passed'] for e in exps)
        run = it / f'eval-{name}' / cfg / 'run-1'
        # no 'timing' key: aggregate_benchmark.py then reads time *and* tokens from timing.json
        out = {'expectations': exps,
               'summary': {'passed': passed, 'failed': len(exps) - passed, 'total': len(exps),
                           'pass_rate': round(passed / len(exps), 4)},
               'grader': 'blind subagent (saw responses as A/B in random order)'}
        (run / 'grading.json').write_text(json.dumps(out, indent=1))
        print(f'graded  {name:28s} {cfg:14s} {passed}/{len(exps)}')

rows = []
for name, m in mapping.items():
    c = ws / 'blind' / name / 'comparison.json'
    if not c.exists():
        continue
    comp = json.loads(c.read_text())
    winner = comp['winner']
    rows.append({'eval': name,
                 'winner': 'tie' if winner == 'TIE' else m[winner],
                 'with_skill': comp['rubric'][next(k for k in 'AB' if m[k] == 'with_skill')],
                 'without_skill': comp['rubric'][next(k for k in 'AB' if m[k] == 'without_skill')],
                 'reasoning': comp['reasoning']})
if rows:
    def mean(cfg, key):
        return round(sum(float(r[cfg][key]) for r in rows) / len(rows), 2)
    summary = {
        'n': len(rows),
        'wins': {k: sum(r['winner'] == k for r in rows) for k in ('with_skill', 'without_skill', 'tie')},
        'mean_overall': {cfg: mean(cfg, 'overall_score') for cfg in ('with_skill', 'without_skill')},
        'mean_by_criterion': {k: {cfg: mean(cfg, k) for cfg in ('with_skill', 'without_skill')} for k in CRITERIA},
    }
    (it / 'comparisons.json').write_text(json.dumps({'summary': summary, 'evals': rows}, indent=1))
    for r in rows:
        print(f"compare {r['eval']:28s} winner={r['winner']:14s} "
              f"with={r['with_skill']['overall_score']} without={r['without_skill']['overall_score']}")
    print(json.dumps(summary, indent=1))
