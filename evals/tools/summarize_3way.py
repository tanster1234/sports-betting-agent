"""Unblind the iteration-2 three-way judgments and the single-answer grades.

usage: python3 evals/tools/summarize_3way.py <workspace> [iteration-2]

Reads <workspace>/blind3/<eval>/{comparison.json,grades_v2.json} and
<workspace>/<iteration>/blind_map_3way.json. Writes grading.json for the v2 with_skill runs
(the baseline runs keep iteration 1's grading) and <iteration>/comparisons_3way.json, and
prints a summary.
"""
import json
import pathlib
import sys

ws = pathlib.Path(sys.argv[1])
it = ws / (sys.argv[2] if len(sys.argv) > 2 else 'iteration-2')
mapping = json.loads((it / 'blind_map_3way.json').read_text())
CRITERIA = ('correctness', 'completeness', 'actionability', 'honesty_and_risk', 'context_use', 'clarity')
CFGS = ('with_skill_v2', 'with_skill_v1', 'without_skill')

for name in mapping:
    g = ws / 'blind3' / name / 'grades_v2.json'
    if not g.exists():
        continue
    meta = json.loads((it / f'eval-{name}' / 'eval_metadata.json').read_text())
    exps = json.loads(g.read_text())['answer']
    assert len(exps) == len(meta['assertions']), name
    for e, text in zip(exps, meta['assertions']):
        e['text'], e['passed'] = text, bool(e['passed'])
    passed = sum(e['passed'] for e in exps)
    out = {'expectations': exps,
           'summary': {'passed': passed, 'failed': len(exps) - passed, 'total': len(exps),
                       'pass_rate': round(passed / len(exps), 4)},
           'grader': 'subagent grading the single answer (configuration not disclosed)'}
    (it / f'eval-{name}' / 'with_skill' / 'run-1' / 'grading.json').write_text(json.dumps(out, indent=1))
    print(f'graded  {name:28s} v2 {passed}/{len(exps)}')

rows = []
for name, lab in mapping.items():
    c = ws / 'blind3' / name / 'comparison.json'
    if not c.exists():
        continue
    comp = json.loads(c.read_text())
    inv = {v: k for k, v in lab.items()}
    rank = [lab[x] for x in comp['ranking']]
    rows.append({'eval': name, 'blind_labels': lab, 'ranking': rank, 'reasoning': comp['reasoning'],
                 'rubric': {cfg: comp['rubric'][inv[cfg]] for cfg in CFGS},
                 'output_quality': {cfg: comp['output_quality'][inv[cfg]] for cfg in CFGS}})

if rows:
    def mean(cfg, key):
        return round(sum(float(r['rubric'][cfg][key]) for r in rows) / len(rows), 2)

    def beats(a, b):
        return sum(r['ranking'].index(a) < r['ranking'].index(b) for r in rows)

    summary = {
        'n': len(rows),
        'first_place': {cfg: sum(r['ranking'][0] == cfg for r in rows) for cfg in CFGS},
        'v2_ranked_above_v1': beats('with_skill_v2', 'with_skill_v1'),
        'v2_ranked_above_without': beats('with_skill_v2', 'without_skill'),
        'v1_ranked_above_without': beats('with_skill_v1', 'without_skill'),
        'mean_overall': {cfg: mean(cfg, 'overall_score') for cfg in CFGS},
        'mean_by_criterion': {k: {cfg: mean(cfg, k) for cfg in CFGS} for k in CRITERIA},
    }
    (it / 'comparisons_3way.json').write_text(json.dumps({'summary': summary, 'evals': rows}, indent=1,
                                                          ensure_ascii=False))
    for r in rows:
        o = {cfg: r['rubric'][cfg]['overall_score'] for cfg in CFGS}
        print(f"judge   {r['eval']:28s} ranking={' > '.join(x.replace('with_skill_', '') for x in r['ranking'])}  {o}")
    print(json.dumps(summary, indent=1))
