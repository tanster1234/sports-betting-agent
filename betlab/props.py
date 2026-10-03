"""Player-prop pricing.

Counting stats are modelled as negative binomial (Poisson when there is no
over-dispersion).  The variance-to-mean relationship comes from WNBA
2024-2026 regular-season box scores for players averaging 20+ minutes
(241 player-seasons): var = a * mean ** b.  See .claude/skills/wnba-betting/references/calibration.md.

Two ways to build a projection:
  1. ``PropModel(stat, mean)`` — you already have a mean projection.
  2. ``project_from_rate(rate_per_min, minutes, ...)`` — rate x minutes with
     pace and matchup multipliers; optionally integrate over minutes
     uncertainty (``minutes_sd``), which matters a lot when a player's role
     is unsettled (injury return, minutes restriction, blowout risk).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .distributions import (
    DiscreteDist,
    gauss_hermite_normal_nodes,
    mixture,
    negbin_mean_var,
)
from .odds import OddsError, american_to_decimal, devig, ev

# var = a * mean ** b   (WNBA 2024-26, 20+ mpg, regular season)
WNBA_DISPERSION: Dict[str, Tuple[float, float]] = {
    "points": (4.580, 0.809),
    "rebounds": (1.169, 1.057),
    "assists": (1.076, 1.015),
    "threes": (1.114, 1.082),
    "steals": (1.043, 1.002),
    "blocks": (1.072, 0.995),
    "turnovers": (1.022, 0.930),
    "pra": (8.360, 0.632),
    "pr": (6.320, 0.716),
    "pa": (5.242, 0.755),
    "ra": (1.547, 0.945),
}

# Within-player game-to-game correlations (demeaned), same data set.
WNBA_STAT_CORR = {
    ("points", "rebounds"): 0.23, ("points", "assists"): 0.13, ("points", "threes"): 0.62,
    ("rebounds", "assists"): 0.14, ("rebounds", "threes"): 0.06, ("assists", "threes"): 0.07,
}
# Cross-player findings (same data): teammates' points ~ -0.01, opponents' ~ +0.04,
# player points vs own team points +0.23, vs game total +0.17.

ALIASES = {
    "pts": "points", "reb": "rebounds", "ast": "assists", "3pm": "threes", "3s": "threes",
    "stl": "steals", "blk": "blocks", "to": "turnovers", "tov": "turnovers",
    "p+r+a": "pra", "pts+reb+ast": "pra", "p+r": "pr", "p+a": "pa", "r+a": "ra",
}


def normalize_stat(stat: str) -> str:
    s = stat.strip().lower()
    return ALIASES.get(s, s)


def variance_for(stat: str, mean: float, table: Optional[Dict[str, Tuple[float, float]]] = None) -> float:
    t = table or WNBA_DISPERSION
    s = normalize_stat(stat)
    if s not in t:
        raise KeyError(f"no dispersion for stat {stat!r}; known {sorted(t)}")
    a, b = t[s]
    return a * max(mean, 1e-9) ** b


@dataclass
class PropModel:
    stat: str
    mean: float
    var: Optional[float] = None

    def __post_init__(self):
        self.stat = normalize_stat(self.stat)
        if self.mean < 0:
            raise OddsError("projection mean must be >= 0")
        if self.var is None:
            self.var = variance_for(self.stat, self.mean)

    @property
    def dist(self) -> DiscreteDist:
        return negbin_mean_var(self.mean, self.var)

    def probs(self, line: float) -> Tuple[float, float, float]:
        """(P(over), P(under), P(push))."""
        return self.dist.over_under_push(line)

    def fair_line(self) -> float:
        return self.dist.median_line()

    def evaluate(self, line: float, over_american: Optional[float] = None,
                 under_american: Optional[float] = None, devig_method: str = "multiplicative") -> dict:
        o, u, p = self.probs(line)
        out = {"stat": self.stat, "line": line, "mean": round(self.mean, 3), "sd": round(math.sqrt(self.var), 3),
               "p_over": round(o, 4), "p_under": round(u, 4), "p_push": round(p, 4),
               "fair_over_decimal": round(1 + u / o, 4) if o > 0 else None,
               "fair_under_decimal": round(1 + o / u, 4) if u > 0 else None}
        if over_american is not None:
            d = american_to_decimal(over_american)
            out["ev_over_pct"] = round(ev(o, d, p) * 100, 2)
        if under_american is not None:
            d = american_to_decimal(under_american)
            out["ev_under_pct"] = round(ev(u, d, p) * 100, 2)
        if over_american is not None and under_american is not None:
            fo, fu = devig([american_to_decimal(over_american), american_to_decimal(under_american)], devig_method)
            out["market_fair_over"] = round(fo, 4)
            out["market_fair_under"] = round(fu, 4)
            out["hold_pct"] = round((1 / american_to_decimal(over_american) + 1 / american_to_decimal(under_american) - 1) * 100, 2)
        return out

    def ladder(self, lines: Sequence[float]) -> List[dict]:
        return [self.evaluate(x) for x in lines]


def project_mean(rate_per_min: float, minutes: float, pace_factor: float = 1.0,
                 matchup_factor: float = 1.0, usage_factor: float = 1.0) -> float:
    """Mean projection = per-minute rate x minutes x adjustments.

    pace_factor    expected game possessions / player's typical possessions
    matchup_factor opponent allowed rate vs league for this stat (e.g. 1.05)
    usage_factor   role change, e.g. teammate out (1.08 = +8% usage)
    """
    if minutes < 0 or rate_per_min < 0:
        raise OddsError("rate and minutes must be >= 0")
    return rate_per_min * minutes * pace_factor * matchup_factor * usage_factor


def project_from_rate(stat: str, rate_per_min: float, minutes: float, minutes_sd: float = 0.0,
                      pace_factor: float = 1.0, matchup_factor: float = 1.0, usage_factor: float = 1.0,
                      nodes: int = 15) -> "MixturePropModel":
    """Projection that integrates over minutes uncertainty.

    Conditional on minutes M, X ~ NB(mean = rate*M*adj, var from the table
    scaled to that mean).  M ~ Normal(minutes, minutes_sd) truncated at 0.
    The calibrated dispersion already includes typical minutes noise, so
    pass ``minutes_sd`` only for *extra* role uncertainty.
    """
    adj = pace_factor * matchup_factor * usage_factor
    if minutes_sd <= 0:
        m = rate_per_min * minutes * adj
        return MixturePropModel(normalize_stat(stat), PropModel(stat, m).dist)
    comps = []
    for mval, w in gauss_hermite_normal_nodes(minutes, minutes_sd, nodes, lower=0.0):
        m = rate_per_min * max(mval, 0.0) * adj
        comps.append((w, PropModel(stat, m).dist if m > 0 else DiscreteDist({0: 1.0})))
    return MixturePropModel(normalize_stat(stat), mixture(comps))


@dataclass
class MixturePropModel:
    stat: str
    dist: DiscreteDist

    @property
    def mean(self) -> float:
        return self.dist.mean()

    def probs(self, line: float) -> Tuple[float, float, float]:
        return self.dist.over_under_push(line)

    def fair_line(self) -> float:
        return self.dist.median_line()


def prop_from_market(line: float, over_american: float, under_american: float, stat: str,
                     devig_method: str = "multiplicative") -> dict:
    """Back out the mean projection the book's devigged price implies.

    Useful to compare your projection against the market's in *stat units*
    ("book implies 17.2 points, I project 18.9").
    """
    fo, _ = devig([american_to_decimal(over_american), american_to_decimal(under_american)], devig_method)
    lo, hi = 0.01, max(4.0 * line + 10.0, 10.0)
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        o, u, p = PropModel(stat, mid).probs(line)
        p_over_ex_push = o / (o + u) if (o + u) > 0 else 0.5
        if p_over_ex_push < fo:
            lo = mid
        else:
            hi = mid
    return {"stat": normalize_stat(stat), "line": line, "market_fair_over": round(fo, 4), "implied_mean": round(0.5 * (lo + hi), 2)}


# ---------------------------------------------------------------------------
# Joint simulation (double-doubles, combos, same-player correlations)
# ---------------------------------------------------------------------------

def _cholesky(m: List[List[float]]) -> List[List[float]]:
    n = len(m)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                v = m[i][i] - s
                if v <= 0:
                    raise ValueError("correlation matrix is not positive definite")
                L[i][j] = math.sqrt(v)
            else:
                L[i][j] = (m[i][j] - s) / L[j][j]
    return L


def _quantile_table(dist: DiscreteDist):
    keys = list(dist.pmf.keys())
    cum = []
    acc = 0.0
    for k in keys:
        acc += dist.pmf[k]
        cum.append(acc)
    return keys, cum


def _draw(keys, cum, u: float) -> int:
    lo, hi = 0, len(cum) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cum[mid] < u:
            lo = mid + 1
        else:
            hi = mid
    return keys[lo]


def simulate_player(means: Dict[str, float], corr: Optional[Dict[Tuple[str, str], float]] = None,
                    n: int = 20000, seed: int = 11) -> List[Dict[str, int]]:
    """Gaussian-copula simulation of one player's stat line.

    Marginals are the calibrated NB distributions; ``corr`` defaults to the
    WNBA within-player correlations.  Returns n simulated stat lines.
    """
    stats = [normalize_stat(s) for s in means]
    corr = corr if corr is not None else WNBA_STAT_CORR
    k = len(stats)
    R = [[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]
    for i in range(k):
        for j in range(i + 1, k):
            c = corr.get((stats[i], stats[j]), corr.get((stats[j], stats[i]), 0.0))
            R[i][j] = R[j][i] = c
    L = _cholesky(R)
    tables = [_quantile_table(PropModel(s, means[orig]).dist) for s, orig in zip(stats, means)]
    rng = random.Random(seed)
    from statistics import NormalDist

    nd = NormalDist()
    out = []
    for _ in range(n):
        z = [rng.gauss(0, 1) for _ in range(k)]
        y = [sum(L[i][j] * z[j] for j in range(i + 1)) for i in range(k)]
        row = {}
        for i, s in enumerate(stats):
            u = min(max(nd.cdf(y[i]), 1e-12), 1 - 1e-12)
            row[s] = _draw(*tables[i], u)
        out.append(row)
    return out


def double_double_prob(points: float, rebounds: float, assists: float, n: int = 40000, seed: int = 5) -> float:
    sims = simulate_player({"points": points, "rebounds": rebounds, "assists": assists}, n=n, seed=seed)
    hits = 0
    for s in sims:
        tens = (s["points"] >= 10) + (s["rebounds"] >= 10) + (s["assists"] >= 10)
        hits += tens >= 2
    return hits / n
