"""Performance reports that separate skill from variance.

The single most common analytical mistake in betting is reading meaning into
small samples.  Every number here comes with its uncertainty:

* ROI with a bootstrap 95% CI and a t-stat on per-bet returns
* CLV (the fast-converging skill signal) with SE / t / p-value
* calibration of your stated probabilities, and a Brier *skill* score vs
  the market's devigged probability — raw Brier near 0.25 is expected for
  near-coin-flip bets and says nothing on its own
* how many bets you'd need before the observed edge is distinguishable
  from zero
* drawdown, losing streaks, and a simple tilt detector (stake size after
  losing days vs after winning days)
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from statistics import NormalDist
from typing import Dict, Iterable, List, Optional, Sequence

_ND = NormalDist()
SETTLED = {"win", "loss", "push", "half_win", "half_loss"}
ENTERTAINMENT = "entertainment"     # quiet-day picks (betlab/quietday.py): no edge by design


def _ret(b: dict) -> float:
    return b["pnl"] / b["stake"]


def _summ(rows: Sequence[dict]) -> dict:
    n = len(rows)
    w = sum(b["status"] in ("win", "half_win") for b in rows)
    l = sum(b["status"] in ("loss", "half_loss") for b in rows)
    p = sum(b["status"] == "push" for b in rows)
    staked = sum(b["stake"] for b in rows)
    pnl = sum(b["pnl"] for b in rows)
    out = {"bets": n, "wins": w, "losses": l, "pushes": p, "staked": round(staked, 2), "pnl": round(pnl, 2),
           "roi_pct": round(100 * pnl / staked, 2) if staked else None,
           "win_pct_ex_push": round(100 * w / (w + l), 1) if (w + l) else None,
           "avg_decimal": round(sum(b["price_decimal"] for b in rows) / n, 3) if n else None}
    clv = [b["clv_ev"] for b in rows if b.get("clv_ev") is not None]
    if clv:
        out["avg_clv_pct"] = round(100 * sum(clv) / len(clv), 2)
        out["clv_n"] = len(clv)
    return out


def bootstrap_roi_ci(rows: Sequence[dict], reps: int = 2000, seed: int = 1) -> tuple:
    if not rows:
        return (None, None)
    rng = random.Random(seed)
    n = len(rows)
    vals = []
    for _ in range(reps):
        s = [rows[rng.randrange(n)] for _ in range(n)]
        st = sum(b["stake"] for b in s)
        vals.append(sum(b["pnl"] for b in s) / st if st else 0.0)
    vals.sort()
    return (vals[int(0.025 * reps)], vals[int(0.975 * reps) - 1])


def t_test(values: Sequence[float]) -> dict:
    n = len(values)
    if n < 2:
        return {"n": n}
    m = sum(values) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))
    se = sd / math.sqrt(n)
    t = m / se if se > 0 else float("nan")
    p = 2 * (1 - _ND.cdf(abs(t))) if t == t else float("nan")
    return {"n": n, "mean": m, "sd": sd, "se": se, "t": t, "p_value": p}


def bets_needed(edge: float, sd_per_bet: float = 0.95, z: float = 1.96) -> int:
    """Bets needed for a true per-bet ROI ``edge`` to be ~2 SE from zero.

    sd_per_bet ~0.95 at -110; larger for longshots (~1.4 at +200).
    """
    if edge <= 0:
        return 10 ** 9
    return int(math.ceil((z * sd_per_bet / edge) ** 2))


def calibration(rows: Sequence[dict], bins: Sequence[float] = (0, .35, .45, .5, .55, .6, .7, 1.0)) -> List[dict]:
    pts = [(b["model_prob"], 1.0 if b["status"] == "win" else 0.0) for b in rows
           if b.get("model_prob") is not None and b["status"] in ("win", "loss")]
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        sel = [(p, y) for p, y in pts if lo <= p < hi]
        if sel:
            out.append({"bin": f"{lo:.2f}-{hi:.2f}", "n": len(sel), "pred": round(sum(p for p, _ in sel) / len(sel), 3),
                        "actual": round(sum(y for _, y in sel) / len(sel), 3)})
    return out


def brier_scores(rows: Sequence[dict]) -> dict:
    pts = [b for b in rows if b["status"] in ("win", "loss") and b.get("model_prob") is not None]
    if not pts:
        return {}
    y = [1.0 if b["status"] == "win" else 0.0 for b in pts]
    bm = sum((b["model_prob"] - yi) ** 2 for b, yi in zip(pts, y)) / len(pts)
    out = {"n": len(pts), "brier_model": round(bm, 4)}
    mk = [(b.get("close_fair_prob") or b.get("market_prob")) for b in pts]
    if all(m is not None for m in mk):
        bk = sum((m - yi) ** 2 for m, yi in zip(mk, y)) / len(pts)
        out["brier_market"] = round(bk, 4)
        out["brier_skill_vs_market"] = round(1 - bm / bk, 4) if bk else None
    return out


def drawdown(rows: Sequence[dict], bankroll_start: Optional[float] = None) -> dict:
    seq = sorted(rows, key=lambda b: (b.get("settled_at") or "", b.get("placed_at") or ""))
    eq = bankroll_start or 0.0
    peak = eq
    mdd = 0.0
    mdd_pct = 0.0
    streak = longest = 0
    for b in seq:
        eq += b["pnl"]
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
        if bankroll_start and peak > 0:
            mdd_pct = max(mdd_pct, (peak - eq) / peak)
        if b["status"] in ("loss", "half_loss"):
            streak += 1
            longest = max(longest, streak)
        elif b["status"] in ("win", "half_win"):
            streak = 0
    out = {"max_drawdown": round(mdd, 2), "longest_losing_streak": longest, "current_drawdown": round(peak - eq, 2)}
    if bankroll_start:
        out.update({"max_drawdown_pct": round(100 * mdd_pct, 2), "current_bankroll": round(eq, 2),
                    "current_drawdown_pct": round(100 * (peak - eq) / peak, 2) if peak else None,
                    "peak_bankroll": round(peak, 2)})
    return out


def tilt_check(rows: Sequence[dict]) -> dict:
    """Average stake on days after a losing day vs after a winning day."""
    by_day: Dict[str, List[dict]] = defaultdict(list)
    for b in rows:
        day = (b.get("placed_at") or "")[:10]
        if day:
            by_day[day].append(b)
    days = sorted(by_day)
    after_loss, after_win = [], []
    for prev, cur in zip(days, days[1:]):
        pnl_prev = sum(b["pnl"] or 0 for b in by_day[prev] if b["status"] in SETTLED)
        stakes = [b["stake"] for b in by_day[cur]]
        (after_loss if pnl_prev < 0 else after_win).extend(stakes)
    res = {"avg_stake_after_losing_day": round(sum(after_loss) / len(after_loss), 2) if after_loss else None,
           "avg_stake_after_winning_day": round(sum(after_win) / len(after_win), 2) if after_win else None}
    if after_loss and after_win and res["avg_stake_after_winning_day"]:
        ratio = res["avg_stake_after_losing_day"] / res["avg_stake_after_winning_day"]
        res["ratio"] = round(ratio, 2)
        res["flag"] = ratio > 1.25
    return res


def verdict(n: int, roi_t: dict, clv_t: dict) -> str:
    if n < 50:
        return "Too few settled bets to judge (n < 50). Track CLV; ignore win/loss."
    if clv_t.get("n", 0) >= 30:
        if clv_t["mean"] > 0 and clv_t["t"] > 2:
            return "Positive, statistically significant CLV: the process is beating the market. Results will follow with volume; keep sizing disciplined."
        if clv_t["mean"] < 0 and clv_t["t"] < -2:
            return "Negative, significant CLV: the market is consistently ahead of you. Pause, review data timing and model, reduce stakes."
    if roi_t.get("t", 0) > 2:
        return "ROI significantly positive, but confirm with CLV — results alone are noisy and can be luck."
    if roi_t.get("t", 0) < -2:
        return "ROI significantly negative. Treat as model failure until CLV evidence says otherwise."
    return "Inconclusive: results are within normal variance of zero edge. Keep logging closing lines — CLV will answer faster than results."


def performance_report(bets: Iterable[dict], bankroll_start: Optional[float] = None,
                       group_by: Sequence[str] = ("sport", "market", "book", "tier")) -> dict:
    """Skill record (ROI, CLV, calibration, verdict) over value bets; money (drawdown, tilt) over every bet.

    Quiet-day picks (tier ``entertainment``) are bets with no edge by design, so they are kept out
    of the record that judges skill and summarised on their own.
    """
    every = [b for b in bets if b.get("status") in SETTLED and b.get("pnl") is not None]
    rows = [b for b in every if b.get("tier") != ENTERTAINMENT]
    fun = [b for b in every if b.get("tier") == ENTERTAINMENT]
    out: dict = {"overall": _summ(rows)}
    if fun:
        out["entertainment"] = _summ(fun)
    lo, hi = bootstrap_roi_ci(rows)
    if lo is not None:
        out["overall"]["roi_ci95_pct"] = [round(100 * lo, 2), round(100 * hi, 2)]
    roi_t = t_test([_ret(b) for b in rows])
    out["roi_test"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in roi_t.items()}
    clv_vals = [b["clv_ev"] for b in rows if b.get("clv_ev") is not None]
    clv_t = t_test(clv_vals)
    out["clv_test"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in clv_t.items()}
    if clv_vals:
        out["clv_test"]["share_positive"] = round(sum(v > 0 for v in clv_vals) / len(clv_vals), 3)
    for g in group_by:
        groups: Dict[str, List[dict]] = defaultdict(list)
        for b in rows:
            groups[str(b.get(g) or "-")].append(b)
        out[f"by_{g}"] = {k: _summ(v) for k, v in sorted(groups.items())}
    months: Dict[str, List[dict]] = defaultdict(list)
    for b in rows:
        months[(b.get("event_date") or b.get("placed_at") or "")[:7]].append(b)
    out["by_month"] = {k: _summ(v) for k, v in sorted(months.items())}
    out["calibration"] = calibration(rows)
    out["brier"] = brier_scores(rows)
    out["drawdown"] = drawdown(every, bankroll_start)
    out["tilt"] = tilt_check(every)
    roi = (out["overall"]["roi_pct"] or 0) / 100
    out["bets_needed_to_confirm_current_roi"] = bets_needed(roi) if roi > 0 else None
    out["verdict"] = verdict(len(rows), roi_t, clv_t)
    out["open_bets"] = sum(1 for b in bets if b.get("status") == "open") if isinstance(bets, list) else None
    return out


def render_markdown(rep: dict, title: str = "Performance review") -> str:
    o = rep["overall"]
    L = [f"# {title}", ""]
    roi = "n/a" if o["roi_pct"] is None else f"{o['roi_pct']}%"
    L.append(f"**Record** {o['wins']}-{o['losses']}-{o['pushes']}  |  **Staked** {o['staked']}  |  **P&L** {o['pnl']}  |  "
             f"**ROI** {roi}" + (f" (95% CI {o['roi_ci95_pct'][0]}% to {o['roi_ci95_pct'][1]}%)" if o.get("roi_ci95_pct") else ""))
    if "avg_clv_pct" in o:
        c = rep["clv_test"]
        t, pv = c.get('t'), c.get('p_value')
        L.append(f"**Avg CLV** {o['avg_clv_pct']}% over {o['clv_n']} bets (t = {t:.2f}, p = {pv:.3f}, share positive {c.get('share_positive')})"
                 if isinstance(t, float) and isinstance(pv, float) else f"**Avg CLV** {o['avg_clv_pct']}% over {o['clv_n']} bets")
    if rep.get("entertainment"):
        e = rep["entertainment"]
        L.append(f"**Quiet-day picks** (entertainment, not in the record above) {e['wins']}-{e['losses']}-{e['pushes']}"
                 f"  |  **Staked** {e['staked']}  |  **P&L** {e['pnl']}")
    L += ["", f"**Verdict:** {rep['verdict']}", ""]
    if rep.get("bets_needed_to_confirm_current_roi"):
        L.append(f"_At the current ROI you need ~{rep['bets_needed_to_confirm_current_roi']} bets before it is distinguishable from zero._\n")
    for key in [k for k in rep if k.startswith("by_")]:
        if len(rep[key]) < 2:
            continue  # a single group adds nothing to the overall line
        L += [f"## {key.replace('by_', 'By ').title()}", "", "| group | bets | W-L-P | ROI % | avg CLV % |", "|---|---|---|---|---|"]
        for k, s in rep[key].items():
            L.append(f"| {k} | {s['bets']} | {s['wins']}-{s['losses']}-{s['pushes']} | {s['roi_pct']} | {s.get('avg_clv_pct', '')} |")
        L.append("")
    if rep["calibration"]:
        L += ["## Calibration (your probabilities vs outcomes)", "", "| bin | n | predicted | actual |", "|---|---|---|---|"]
        for c in rep["calibration"]:
            L.append(f"| {c['bin']} | {c['n']} | {c['pred']} | {c['actual']} |")
        L.append("")
    if rep["brier"]:
        L += ["## Brier", "", "```", str(rep["brier"]), "```", ""]
    L += ["## Risk", "", "```", str(rep["drawdown"]), str(rep["tilt"]), "```"]
    return "\n".join(L)
