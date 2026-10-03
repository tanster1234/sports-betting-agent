"""Parlay, same-game-parlay and teaser pricing.

Independent legs: P = prod(p_i).  Correlated legs (same game): Gaussian
copula — leg i hits when Z_i < Phi^-1(p_i) with Z ~ MVN(0, R) — estimated by
Monte Carlo with a standard error.  The point of this module is to show how
fast hold compounds (a 4.5%-hold two-way market becomes ~17% on a 4-leg
parlay) and to quantify when a book's SGP price under-prices correlation.
"""

from __future__ import annotations

import math
import random
from statistics import NormalDist
from typing import List, Sequence

from .markets import MarginModel
from .odds import OddsError, american_to_decimal, parlay_decimal
from .props import _cholesky

_ND = NormalDist()


def independent_parlay(probs: Sequence[float], decimals: Sequence[float]) -> dict:
    if len(probs) != len(decimals) or not probs:
        raise OddsError("need matching, non-empty probs and prices")
    p = 1.0
    for x in probs:
        if not 0 < x < 1:
            raise OddsError(f"leg probability must be in (0,1), got {x}")
        p *= x
    d = parlay_decimal(decimals)
    return {"p_all": p, "decimal": d, "fair_decimal": 1 / p, "ev": p * d - 1.0}


def parlay_hold(leg_holds: Sequence[float]) -> float:
    """Effective hold of a parlay of fair-priced two-way legs each with ``hold``.

    Each leg returns (1 - h_i) of fair; the parlay returns prod(1 - h_i).
    """
    r = 1.0
    for h in leg_holds:
        r *= 1.0 - h
    return 1.0 - r


def correlated_parlay_prob(probs: Sequence[float], corr: Sequence[Sequence[float]],
                           n: int = 200000, seed: int = 3) -> dict:
    """Monte Carlo P(all legs hit) under a Gaussian copula.

    ``corr`` is the latent correlation matrix between legs (positive = legs
    tend to hit together, e.g. favourite ML + favourite's star over).
    """
    k = len(probs)
    if k == 0 or len(corr) != k:
        raise OddsError("corr must be k x k")
    L = _cholesky([list(map(float, row)) for row in corr])
    thresholds = [_ND.inv_cdf(min(max(p, 1e-12), 1 - 1e-12)) for p in probs]
    rng = random.Random(seed)
    hits = 0
    for _ in range(n):
        z = [rng.gauss(0, 1) for _ in range(k)]
        ok = True
        for i in range(k):
            y = 0.0
            row = L[i]
            for j in range(i + 1):
                y += row[j] * z[j]
            if y >= thresholds[i]:
                ok = False
                break
        hits += ok
    p = hits / n
    se = math.sqrt(max(p * (1 - p), 1e-12) / n)
    indep = 1.0
    for x in probs:
        indep *= x
    return {"p_all": p, "se": se, "p_independent": indep, "correlation_lift": p / indep if indep else float("nan")}


def sgp_ev(probs: Sequence[float], corr: Sequence[Sequence[float]], offered_american: float,
           n: int = 200000, seed: int = 3) -> dict:
    res = correlated_parlay_prob(probs, corr, n, seed)
    d = american_to_decimal(offered_american)
    res.update({"offered_decimal": d, "fair_decimal": 1 / res["p_all"] if res["p_all"] > 0 else float("inf"),
                "ev": res["p_all"] * d - 1.0,
                "ev_ci95": (((res["p_all"] - 1.96 * res["se"]) * d - 1.0), ((res["p_all"] + 1.96 * res["se"]) * d - 1.0))})
    return res


def teaser_legs(margin_models: Sequence[MarginModel], home_lines: Sequence[float], teaser_points: float,
                bet_home: Sequence[bool]) -> List[dict]:
    """Per-leg win/push probabilities after moving each line ``teaser_points`` in the bettor's favour."""
    out = []
    for mm, line, home in zip(margin_models, home_lines, bet_home):
        if home:
            new = line + teaser_points
            c, p, f = mm.spread_probs(new)
        else:
            new_away = -line + teaser_points
            c, p, f = mm.away_spread_probs(new_away)
            new = -new_away
        out.append({"home_line_after": new, "p_win": c, "p_push": p, "p_loss": f})
    return out


def teaser_ev(legs: Sequence[dict], offered_american: float, push_rule: str = "refund") -> dict:
    """EV of a teaser ticket.

    Books grade pushed teaser legs differently (reduce to fewer legs, refund,
    or loss).  This reports P(all legs win), P(no loss but >= 1 push) and
    P(loss), and computes EV with pushes either refunding the ticket
    (``push_rule='refund'``, a slight over-estimate when the book reduces) or
    losing it (``'lose'``).  Check your book's rule before trusting the EV.
    """
    p_all_win = 1.0
    p_no_loss = 1.0
    for leg in legs:
        p_all_win *= leg["p_win"]
        p_no_loss *= (leg["p_win"] + leg["p_push"])
    d = american_to_decimal(offered_american)
    p_loss = 1.0 - p_no_loss
    p_refund = p_no_loss - p_all_win
    if push_rule == "lose":
        p_loss += p_refund
        p_refund = 0.0
    return {"p_all_win": p_all_win, "p_refund_or_reduce": p_refund, "p_loss": p_loss,
            "ev_assuming_refund": p_all_win * (d - 1) - p_loss}
