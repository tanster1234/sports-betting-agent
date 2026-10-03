"""Trigger eval with one temporary project per `claude -p` call.

skill-creator's run_eval.py writes every worker's command file into the same
.claude/commands/ directory, so with N parallel workers Claude sees ~N identical
copies of the skill and a call to another worker's copy is scored as a miss.
This wrapper reuses run_single_query unchanged but gives each call its own root.

usage: python3 trigger_eval_isolated.py <skill-creator-dir> <skill-dir> <eval-set.json> <out.json>
                                        <runs-per-query> <workers> <timeout-s> <scratch-dir>
"""
import json
import shutil
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1])))
from scripts.run_eval import run_single_query  # noqa: E402
from scripts.utils import parse_skill_md  # noqa: E402

SKILL_DIR, EVAL_SET, OUT = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
RUNS, WORKERS, TIMEOUT = int(sys.argv[5]), int(sys.argv[6]), int(sys.argv[7])
SCRATCH = Path(sys.argv[8])


def one(query, name, desc):
    root = Path(tempfile.mkdtemp(prefix="trig-", dir=SCRATCH))
    (root / ".claude").mkdir()
    try:
        return run_single_query(query, name, desc, TIMEOUT, str(root), None)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    name, desc, _ = parse_skill_md(SKILL_DIR)
    items = json.loads(EVAL_SET.read_text())
    t0 = time.time()
    trig = {it["query"]: [] for it in items}
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(one, it["query"], name, desc): it for it in items for _ in range(RUNS)}
        for f in as_completed(futs):
            it = futs[f]
            try:
                trig[it["query"]].append(bool(f.result()))
            except Exception as e:  # a crashed run counts as not triggered, but say so
                print("run failed:", e, file=sys.stderr)
                trig[it["query"]].append(False)

    results = []
    for it in items:
        t = trig[it["query"]]
        rate = sum(t) / len(t)
        ok = rate >= 0.5 if it["should_trigger"] else rate < 0.5
        results.append({"query": it["query"], "should_trigger": it["should_trigger"],
                        "trigger_rate": rate, "triggers": sum(t), "runs": len(t), "pass": ok})
    pos = [r for r in results if r["should_trigger"]]
    neg = [r for r in results if not r["should_trigger"]]
    summary = {
        "total": len(results),
        "passed": sum(r["pass"] for r in results),
        "recall_queries": f"{sum(r['pass'] for r in pos)}/{len(pos)}",
        "specificity_queries": f"{sum(r['pass'] for r in neg)}/{len(neg)}",
        "positive_trigger_rate": round(sum(r["triggers"] for r in pos) / max(1, sum(r["runs"] for r in pos)), 3),
        "negative_trigger_rate": round(sum(r["triggers"] for r in neg) / max(1, sum(r["runs"] for r in neg)), 3),
        "runs_per_query": RUNS,
        "seconds": round(time.time() - t0),
    }
    OUT.write_text(json.dumps({"skill_name": name, "description": desc, "method": "isolated project per call",
                               "results": results, "summary": summary}, indent=1))
    print(name, json.dumps(summary))
    for r in results:
        flag = "PASS" if r["pass"] else "FAIL"
        print(f"  [{flag}] {r['triggers']}/{r['runs']} expected={r['should_trigger']}: {r['query'][:80]}")


if __name__ == "__main__":
    main()
