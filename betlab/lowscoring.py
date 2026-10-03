"""Low-scoring sports (MLB, NHL): moneyline / run line / puck line / totals from scoring rates.

Each team's score is a count distribution (Poisson, or negative binomial when
over-dispersed).  We walk the joint grid of (home score, away score) and apply
the sport's end-of-game rules, so winner, margin and final total stay
consistent:

* MLB: a 9-inning tie goes to extras; the home team wins it with
  ``p_home_extras``; the game is treated as a 1-run game and the total gains
  ``extras_runs`` (rounded) runs.
* NHL: a regulation tie goes to OT/shootout; the winner gets +1 goal, so the
  final margin is 1 and the final total is regulation + 1.  ``empty_net_shift``
  converts that share of 1-goal regulation wins into 2-goal wins (+1 to the
  total) to mimic pulled-goalie empty-netters.

These are approximations to turn a view on runs/goals into internally
consistent prices — calibrate dispersion and the constants on real data before
trusting small edges.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from .distributions import DiscreteDist, negbin_mean_var, poisson


def _team(mean: float, var_ratio: float) -> DiscreteDist:
    return negbin_mean_var(mean, mean * var_ratio) if var_ratio > 1.0 else poisson(mean)


def _joint(h: DiscreteDist, a: DiscreteDist, eps: float = 1e-12):
    for hs, ph in h.pmf.items():
        for as_, pa in a.pmf.items():
            p = ph * pa
            if p > eps:
                yield hs, as_, p


def _summarize(outcomes: Dict[Tuple[int, int], float], total_line: Optional[float]) -> dict:
    """outcomes: {(final_margin, final_total): prob} -> margin/total distributions."""
    margin: Dict[int, float] = {}
    total: Dict[int, float] = {}
    for (m, t), p in outcomes.items():
        margin[m] = margin.get(m, 0.0) + p
        total[t] = total.get(t, 0.0) + p
    md, td = DiscreteDist(margin), DiscreteDist(total)
    out = {
        "p_home_win": md.sf(0), "p_away_win": md.cdf(-1),
        "p_home_minus_1_5": md.sf(1.5), "p_away_plus_1_5": md.cdf(1.5),
        "p_away_minus_1_5": md.cdf(-1.5), "p_home_plus_1_5": md.sf(-1.5),
        "exp_total": td.mean(), "fair_total_line": td.median_line(),
    }
    if total_line is not None:
        o, u, p = td.over_under_push(total_line)
        out.update({"total_line": total_line, "p_over": o, "p_under": u, "p_push": p})
    return out


def mlb_game(home_runs: float, away_runs: float, var_ratio: float = 2.0, p_home_extras: float = 0.52,
             extras_runs: float = 1.0, total_line: Optional[float] = None) -> dict:
    """Prices from expected 9-inning runs for each team (run line = +/-1.5)."""
    h, a = _team(home_runs, var_ratio), _team(away_runs, var_ratio)
    add = int(round(extras_runs))
    outcomes: Dict[Tuple[int, int], float] = {}
    p_extras = 0.0
    for hs, as_, p in _joint(h, a):
        if hs != as_:
            k = (hs - as_, hs + as_)
            outcomes[k] = outcomes.get(k, 0.0) + p
        else:
            p_extras += p
            for m, w in ((1, p_home_extras), (-1, 1 - p_home_extras)):
                k = (m, hs + as_ + add)
                outcomes[k] = outcomes.get(k, 0.0) + p * w
    out = _summarize(outcomes, total_line)
    out["p_extras"] = p_extras
    return out


def nhl_game(home_goals: float, away_goals: float, var_ratio: float = 1.0, p_home_ot: float = 0.52,
             empty_net_shift: float = 0.0, total_line: Optional[float] = None) -> dict:
    """Prices from expected regulation goals for each team (puck line = +/-1.5)."""
    h, a = _team(home_goals, var_ratio), _team(away_goals, var_ratio)
    outcomes: Dict[Tuple[int, int], float] = {}
    p_ot = 0.0
    p_reg_home = 0.0

    def add(m: int, t: int, p: float):
        outcomes[(m, t)] = outcomes.get((m, t), 0.0) + p

    for hs, as_, p in _joint(h, a):
        m, t = hs - as_, hs + as_
        if m == 0:
            p_ot += p
            add(1, t + 1, p * p_home_ot)
            add(-1, t + 1, p * (1 - p_home_ot))
            continue
        if m > 0:
            p_reg_home += p
        if abs(m) == 1 and empty_net_shift > 0:
            add(2 * m, t + 1, p * empty_net_shift)
            add(m, t, p * (1 - empty_net_shift))
        else:
            add(m, t, p)
    out = _summarize(outcomes, total_line)
    out.update({"p_ot": p_ot, "p_home_regulation_win": p_reg_home,
                "p_away_regulation_win": 1.0 - p_ot - p_reg_home})
    return out
