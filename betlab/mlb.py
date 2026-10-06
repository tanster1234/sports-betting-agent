"""MLB pricing from the market: an exact half-inning model of a baseball game.

A baseball score is built from 17-18 half-innings plus the rules that end a game
early or late: the home team skips the bottom of the 9th when it leads, a walk-off
ends the game the moment the winning run scores (so home wins in the 9th or later
are mostly by one run), and a tie after nine goes to extra innings — with an
automatic runner on second in the regular season (since 2020) and without one in
the postseason.  Those rules are what make run lines, alternate totals, team totals,
first-five-innings (F5) and first-inning (NRFI/YRFI) prices differ from a simple
two-Poisson model.

The model:

* Runs in a half-inning ~ negative binomial with mean ``mu_team × m_i`` and dispersion
  ``r`` (most innings are scoreless, a few are crooked numbers).  ``m_i`` are fitted
  per-inning multipliers (the 1st inning, with the top of the order up, scores most and has
  its own, smaller, dispersion: fewer scoreless first innings than its mean suggests).
* The 9th inning depends on the score: the road team's rate is scaled by whether it trails,
  is tied or leads after eight, and the home team's 9th (played only when it isn't ahead) by
  a "facing the closer" factor — all fitted.
* Extra innings: regular season uses a fitted automatic-runner inning distribution
  scaled by team strength; postseason uses an ordinary 9th inning.
* Walk-offs: the home team's winning margin in a walk-off inning is
  ``min(runs needed beyond the tie, J)`` with J drawn from a fitted distribution
  (a walk-off home run can win by up to four).

Everything is exact (convolutions, no simulation).  ``solve`` finds the two team
rates that reproduce the market's no-vig moneyline *and* total, so every other
market is priced consistently with the price you trust (best: the sharp book).
The fitted numbers live in ``data/mlb/calibration.json`` (rebuilt by
``scripts/refresh_mlb_data.py`` from ESPN scores and closing odds since 2023, the
pitch-clock era); the held-out check is on the 2026 season.

This prices *derivative* markets from a main line.  It does not predict games: the
moneyline input should be the sharp market, adjusted only for news it hasn't absorbed
(a scratched starter, a bullpen game, weather).
"""

from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .odds import american_to_decimal, decimal_to_american, devig

FIT_FIRST_SEASON = 2023                # pitch clock, shift ban, bigger bases
TEST_FROM = "2026-01-01"               # held-out season
MAX_RUNS = 30                          # per team, tail mass folded into the last bin
HALF_MAX = 15                          # runs in one half-inning
EXTRA_INNINGS = 14                     # extra innings followed before folding the remainder


def data_dir() -> Path:
    env = os.environ.get("BETLAB_DATA")
    base = Path(env) if env else Path(__file__).resolve().parent.parent / "data"
    return base / "mlb"


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Params:
    r: float = 0.42                                       # NB dispersion of a half-inning
    inning_mult: Tuple[float, ...] = (1.18, 0.93, 1.0, 1.0, 1.0, 1.0, 0.97, 0.95, 0.92)
    league_mu: float = 0.49                               # league runs per half-inning (innings 1-9)
    ghost_mean: float = 1.05                              # automatic-runner half-inning, league average
    ghost_r: float = 1.2
    walkoff_cap: Tuple[float, ...] = (0.0, 0.80, 0.08, 0.06, 0.06)   # P(J = 0..4); J=0 unused
    r_first: float = 0.0                                  # 1st-inning dispersion (0 = same as r)
    top9: Tuple[float, ...] = (1.0, 1.0, 1.0)             # away 9th-inning rate when trailing / tied / leading after 8
    bottom9: float = 1.0                                  # home 9th-inning rate when not leading (facing the closer)

    def to_json(self) -> dict:
        return {"r": self.r, "r_first": self.r_first, "inning_mult": list(self.inning_mult), "league_mu": self.league_mu,
                "ghost_mean": self.ghost_mean, "ghost_r": self.ghost_r, "walkoff_cap": list(self.walkoff_cap),
                "top9": list(self.top9), "bottom9": self.bottom9}

    @classmethod
    def from_json(cls, d: dict) -> "Params":
        return cls(r=d["r"], inning_mult=tuple(d["inning_mult"]), league_mu=d["league_mu"],
                   ghost_mean=d["ghost_mean"], ghost_r=d["ghost_r"], walkoff_cap=tuple(d["walkoff_cap"]),
                   r_first=d.get("r_first", 0.0), top9=tuple(d.get("top9", (1.0, 1.0, 1.0))), bottom9=d.get("bottom9", 1.0))


def load_calibration(path: Optional[str] = None) -> Optional[dict]:
    p = Path(path) if path else data_dir() / "calibration.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


@lru_cache(maxsize=1)
def default_params() -> Params:
    cal = load_calibration()
    return Params.from_json(cal["params"]) if cal and "params" in cal else Params()


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------

def nb_pmf(mean: float, r: float, kmax: int = HALF_MAX) -> List[float]:
    """Negative binomial pmf on 0..kmax (tail folded into kmax)."""
    mean = max(mean, 1e-9)
    q = mean / (r + mean)
    p = (r / (r + mean)) ** r
    out = [p]
    for k in range(kmax - 1):
        p *= (k + r) / (k + 1) * q
        out.append(p)
    out.append(max(0.0, 1.0 - sum(out)))
    return out


def convolve(a: Sequence[float], b: Sequence[float], cap: int = MAX_RUNS, eps: float = 1e-13) -> List[float]:
    out = [0.0] * min(len(a) + len(b) - 1, cap + 1)
    for i, x in enumerate(a):
        if x < eps:
            continue
        for j, y in enumerate(b):
            k = i + j
            if k > cap:
                out[cap] += x * sum(b[j:])
                break
            out[k] += x * y
    return out


@dataclass
class GameDist:
    """Joint distribution of final (away, home) runs plus F5 and first-inning pieces."""
    joint: Dict[Tuple[int, int], float]
    f5: Dict[Tuple[int, int], float]
    nrfi: float
    p_extra: float
    mu_away: float = 0.0
    mu_home: float = 0.0
    _cache: dict = field(default_factory=dict, repr=False)

    # -- full game --------------------------------------------------------
    def p_home(self) -> float:
        return sum(p for (a, h), p in self.joint.items() if h > a)

    def total_pmf(self) -> Dict[int, float]:
        if "total" not in self._cache:
            t: Dict[int, float] = {}
            for (a, h), p in self.joint.items():
                t[a + h] = t.get(a + h, 0.0) + p
            self._cache["total"] = t
        return self._cache["total"]

    def margin_pmf(self) -> Dict[int, float]:
        """Home margin (home - away)."""
        if "margin" not in self._cache:
            t: Dict[int, float] = {}
            for (a, h), p in self.joint.items():
                t[h - a] = t.get(h - a, 0.0) + p
            self._cache["margin"] = t
        return self._cache["margin"]

    def team_pmf(self, side: str) -> Dict[int, float]:
        key = "team_" + side
        if key not in self._cache:
            t: Dict[int, float] = {}
            for (a, h), p in self.joint.items():
                v = h if side == "home" else a
                t[v] = t.get(v, 0.0) + p
            self._cache[key] = t
        return self._cache[key]

    def mean_runs(self) -> Tuple[float, float]:
        return (sum(a * p for (a, h), p in self.joint.items()), sum(h * p for (a, h), p in self.joint.items()))

    # -- generic over/under and handicap ----------------------------------
    @staticmethod
    def _over_under(pmf: Dict[int, float], line: float) -> Tuple[float, float, float]:
        over = sum(p for v, p in pmf.items() if v > line)
        push = sum(p for v, p in pmf.items() if v == line)
        return over, 1.0 - over - push, push

    def over_under(self, line: float) -> Tuple[float, float, float]:
        return self._over_under(self.total_pmf(), line)

    def team_over_under(self, side: str, line: float) -> Tuple[float, float, float]:
        return self._over_under(self.team_pmf(side), line)

    def run_line(self, home_line: float) -> Tuple[float, float, float]:
        """(P home covers, P away covers, P push) for home at ``home_line`` (e.g. -1.5)."""
        m = self.margin_pmf()
        cover = sum(p for v, p in m.items() if v + home_line > 0)
        push = sum(p for v, p in m.items() if v + home_line == 0)
        return cover, 1.0 - cover - push, push

    # -- first five innings -----------------------------------------------
    def f5_result(self) -> Tuple[float, float, float]:
        """(P home leads after 5, P away leads, P tied)."""
        h = sum(p for (a, b), p in self.f5.items() if b > a)
        a_ = sum(p for (a, b), p in self.f5.items() if a > b)
        return h, a_, 1.0 - h - a_

    def f5_over_under(self, line: float) -> Tuple[float, float, float]:
        t: Dict[int, float] = {}
        for (a, h), p in self.f5.items():
            t[a + h] = t.get(a + h, 0.0) + p
        return self._over_under(t, line)

    def f5_run_line(self, home_line: float) -> Tuple[float, float, float]:
        cover = sum(p for (a, h), p in self.f5.items() if h - a + home_line > 0)
        push = sum(p for (a, h), p in self.f5.items() if h - a + home_line == 0)
        return cover, 1.0 - cover - push, push


def _trim(pmf: Sequence[float], eps: float = 1e-12) -> List[float]:
    """Drop the negligible tail (its mass goes to the last kept bin)."""
    n = len(pmf)
    while n > 1 and pmf[n - 1] < eps:
        n -= 1
    out = list(pmf[:n])
    out[-1] += sum(pmf[n:])
    return out


def _walkoff_margins(pmf: Sequence[float], cap: Sequence[float]) -> List[List[Tuple[int, float]]]:
    """For a home half-inning needing more than ``d`` runs to win: [(final margin, prob)] for each d.
    The game ends on the winning run unless a home run clears the bases, so the final margin is
    ``min(runs beyond the tie, J)`` with J ~ ``cap``."""
    out = []
    for d in range(len(pmf)):
        acc = [0.0] * len(cap)
        for k in range(d + 1, len(pmf)):
            b = k - d
            for j in range(1, len(cap)):
                acc[min(b, j)] += pmf[k] * cap[j]
        out.append([(m, v) for m, v in enumerate(acc) if v > 0])
    return out


def _extra_innings(xa: Sequence[float], xh: Sequence[float], cap: Sequence[float]) -> Dict[Tuple[int, int], float]:
    """Runs added by each team from a tie after 9 until decided: {(away_add, home_add): p}."""
    out: Dict[Tuple[int, int], float] = {}
    wm = _walkoff_margins(xh, cap)
    tied = {0: 1.0}                                   # accumulated runs each (equal) -> mass
    for _ in range(EXTRA_INNINGS):
        nxt: Dict[int, float] = {}
        for s, q in tied.items():
            for x, px in enumerate(xa):
                w = q * px
                if w < 1e-15:
                    continue
                sx = s + x
                for y in range(min(x, len(xh))):      # away wins the inning
                    k = (sx, s + y)
                    out[k] = out.get(k, 0.0) + w * xh[y]
                if x < len(xh):
                    nxt[sx] = nxt.get(sx, 0.0) + w * xh[x]
                    for mg, v in wm[x]:               # walk-off
                        k = (sx, sx + mg)
                        out[k] = out.get(k, 0.0) + w * v
        tied = nxt
        if sum(tied.values()) < 1e-10:
            break
    for s, q in tied.items():                         # vanishing remainder: split evenly
        out[(s + 1, s)] = out.get((s + 1, s), 0.0) + q / 2
        out[(s, s + 1)] = out.get((s, s + 1), 0.0) + q / 2
    return out


def game_dist(mu_away: float, mu_home: float, params: Optional[Params] = None, postseason: bool = False) -> GameDist:
    """Exact final-score distribution for team half-inning rates ``mu_*`` (runs per half-inning
    at an average inning)."""
    return _game_dist_fixed(mu_away, mu_home, params or default_params(), postseason)


def _game_dist_fixed(mu_away: float, mu_home: float, P: Params, postseason: bool) -> GameDist:
    m = P.inning_mult
    a_half = [_trim(nb_pmf(mu_away * m[i], P.r_first if (i == 0 and P.r_first > 0) else P.r)) for i in range(9)]
    h_half = [_trim(nb_pmf(mu_home * m[i], P.r_first if (i == 0 and P.r_first > 0) else P.r)) for i in range(9)]
    A = [1.0]
    H = [1.0]
    f5_a = f5_h = None
    for i in range(8):
        A = convolve(A, a_half[i])
        H = convolve(H, h_half[i])
        if i == 4:
            f5_a, f5_h = A, H
    # 9th inning depends on the score: a team protecting a lead brings in its closer
    top9 = [_trim(nb_pmf(mu_away * m[8] * f, P.r)) for f in P.top9]          # away trails / tied / leads after 8
    H = _trim(H)
    Hb9 = _trim(nb_pmf(mu_home * m[8] * P.bottom9, P.r))
    cap = P.walkoff_cap
    wm9 = _walkoff_margins(Hb9, cap)

    if postseason:
        xa, xh = top9[1], Hb9
    else:
        xa = _trim(nb_pmf(P.ghost_mean * mu_away / P.league_mu, P.ghost_r))
        xh = _trim(nb_pmf(P.ghost_mean * mu_home / P.league_mu, P.ghost_r))
    extra = _extra_innings(xa, xh, cap)
    joint: Dict[Tuple[int, int], float] = {}
    tie_at: Dict[int, float] = {}
    nb9 = len(Hb9)
    for h8, ph in enumerate(H):
        if ph < 1e-14:
            continue
        # away runs after its 9th, given the home team's 8-inning score
        parts = ([pa if a8 < h8 else 0.0 for a8, pa in enumerate(A)], [pa if a8 == h8 else 0.0 for a8, pa in enumerate(A)],
                 [pa if a8 > h8 else 0.0 for a8, pa in enumerate(A)])
        A9 = [0.0] * (MAX_RUNS + 1)
        for part, pmf in zip(parts, top9):
            if any(part):
                for a, v in enumerate(convolve(part, pmf)):
                    A9[a] += v
        for a, pa in enumerate(A9):
            p = pa * ph
            if p < 1e-15:
                continue
            if h8 > a:                                 # home leads: bottom 9th not played
                joint[(a, h8)] = joint.get((a, h8), 0.0) + p
                continue
            d = a - h8
            for k in range(min(d, nb9)):               # home doesn't catch up
                key = (a, h8 + k)
                joint[key] = joint.get(key, 0.0) + p * Hb9[k]
            if d < nb9:
                tie_at[a] = tie_at.get(a, 0.0) + p * Hb9[d]
                for mg, v in wm9[d]:                   # walk-off
                    key = (a, a + mg)
                    joint[key] = joint.get(key, 0.0) + p * v
    p_extra = sum(tie_at.values())
    for t, q in tie_at.items():
        for (xa_, xh_), pe in extra.items():
            k = (t + xa_, t + xh_)
            joint[k] = joint.get(k, 0.0) + q * pe

    f5 = {}
    for a, pa in enumerate(f5_a):
        if pa < 1e-13:
            continue
        for h, ph in enumerate(f5_h):
            if pa * ph > 1e-15:
                f5[(a, h)] = pa * ph
    nrfi = a_half[0][0] * h_half[0][0]
    return GameDist(joint, f5, nrfi, p_extra, mu_away, mu_home)


# ---------------------------------------------------------------------------
# Solving from the market
# ---------------------------------------------------------------------------

def market_probs(ml_away: float, ml_home: float, total: float, over: float = -110, under: float = -110,
                 method: str = "multiplicative") -> Tuple[float, float]:
    """No-vig (P home wins, P over | not push) from American prices."""
    p_away, p_home = devig([american_to_decimal(ml_away), american_to_decimal(ml_home)], method)
    p_over, _ = devig([american_to_decimal(over), american_to_decimal(under)], method)
    return p_home, p_over


def _targets(gd: GameDist, line: float) -> Tuple[float, float]:
    o, u, _ = gd.over_under(line)
    return gd.p_home(), o / (o + u) if o + u > 0 else 0.5


def solve(p_home: float, total_line: float, p_over: float = 0.5, params: Optional[Params] = None,
          postseason: bool = False, tol: float = 2e-4, max_iter: int = 12) -> GameDist:
    """Team rates that reproduce the market's no-vig home win probability and P(over the total)."""
    P = params or default_params()
    # starting point: split the total by a Pythagorean ratio (exponent ~1.83)
    ratio = (p_home / (1 - p_home)) ** (1 / 1.83)
    m = P.inning_mult
    x = [math.log(total_line / (1 + ratio) / sum(m)), math.log(total_line * ratio / (1 + ratio) / (sum(m[:8]) + 0.5 * m[8]))]
    target = (math.log(p_home / (1 - p_home)), math.log(p_over / (1 - p_over)))

    def f(v):
        gd = game_dist(math.exp(v[0]), math.exp(v[1]), P, postseason)
        ph, po = _targets(gd, total_line)
        ph = min(max(ph, 1e-6), 1 - 1e-6)
        po = min(max(po, 1e-6), 1 - 1e-6)
        return gd, (math.log(ph / (1 - ph)) - target[0], math.log(po / (1 - po)) - target[1])

    gd, r = f(x)
    for _ in range(max_iter):
        if abs(r[0]) < tol and abs(r[1]) < tol:
            break
        h = 1e-3
        _, r0 = f([x[0] + h, x[1]])
        _, r1 = f([x[0], x[1] + h])
        j = [[(r0[0] - r[0]) / h, (r1[0] - r[0]) / h], [(r0[1] - r[1]) / h, (r1[1] - r[1]) / h]]
        det = j[0][0] * j[1][1] - j[0][1] * j[1][0]
        if abs(det) < 1e-12:
            break
        dx0 = (r[0] * j[1][1] - r[1] * j[0][1]) / det
        dx1 = (r[1] * j[0][0] - r[0] * j[1][0]) / det
        step = 1.0
        for _ in range(6):                             # damped Newton
            cand = [x[0] - step * dx0, x[1] - step * dx1]
            gd2, r2 = f(cand)
            if abs(r2[0]) + abs(r2[1]) < abs(r[0]) + abs(r[1]):
                x, gd, r = cand, gd2, r2
                break
            step /= 2
        else:
            break
    return gd


def f5_dist(mu_away: float, mu_home: float, params: Optional[Params] = None) -> Dict[Tuple[int, int], float]:
    """Joint (away, home) runs after five innings."""
    P = params or default_params()
    m = P.inning_mult
    A, H = [1.0], [1.0]
    for i in range(5):
        r = P.r_first if (i == 0 and P.r_first > 0) else P.r
        A = convolve(A, _trim(nb_pmf(mu_away * m[i], r)))
        H = convolve(H, _trim(nb_pmf(mu_home * m[i], r)))
    return {(a, h): pa * ph for a, pa in enumerate(A) for h, ph in enumerate(H) if pa * ph > 1e-15}


def anchor_f5(gd: GameDist, line: float, p_over: float, p_home_no_tie: Optional[float] = None,
              params: Optional[Params] = None) -> GameDist:
    """Re-fit the first five innings to the sharp F5 total (and F5 moneyline, if given).

    The full-game solve splits runs across innings like an average game; with two aces (or two
    short-leash starters) the market's F5 line says otherwise.  Keeps the full-game distribution
    and replaces only the F5 piece."""
    P = params or default_params()
    x = [math.log(gd.mu_away), math.log(gd.mu_home)]

    def resid(v):
        f5 = f5_dist(math.exp(v[0]), math.exp(v[1]), P)
        tot: Dict[int, float] = {}
        for (a, h), p in f5.items():
            tot[a + h] = tot.get(a + h, 0.0) + p
        o = sum(p for t, p in tot.items() if t > line)
        u = sum(p for t, p in tot.items() if t < line)
        r_tot = math.log(o / u) - math.log(p_over / (1 - p_over))
        if p_home_no_tie is None:
            return f5, (r_tot, v[1] - v[0] - (x[1] - x[0]))          # keep the full-game ratio
        hl = sum(p for (a, h), p in f5.items() if h > a)
        al = sum(p for (a, h), p in f5.items() if a > h)
        return f5, (r_tot, math.log(hl / al) - math.log(p_home_no_tie / (1 - p_home_no_tie)))

    f5, r = resid(x)
    for _ in range(12):
        if abs(r[0]) < 1e-4 and abs(r[1]) < 1e-4:
            break
        h = 1e-3
        _, r0 = resid([x[0] + h, x[1]])
        _, r1 = resid([x[0], x[1] + h])
        j = [[(r0[0] - r[0]) / h, (r1[0] - r[0]) / h], [(r0[1] - r[1]) / h, (r1[1] - r[1]) / h]]
        det = j[0][0] * j[1][1] - j[0][1] * j[1][0]
        if abs(det) < 1e-12:
            break
        x = [x[0] - (r[0] * j[1][1] - r[1] * j[0][1]) / det, x[1] - (r[1] * j[0][0] - r[0] * j[1][0]) / det]
        f5, r = resid(x)
    return GameDist(gd.joint, f5, gd.nrfi, gd.p_extra, gd.mu_away, gd.mu_home)


def anchor_nrfi(gd: GameDist, p_nrfi: float) -> GameDist:
    """Use the sharp first-inning price instead of the model's (starter-specific)."""
    return GameDist(gd.joint, gd.f5, p_nrfi, gd.p_extra, gd.mu_away, gd.mu_home)


# ---------------------------------------------------------------------------
# Pricing and offers
# ---------------------------------------------------------------------------

def _fair(p: float) -> str:
    if p <= 0 or p >= 1:
        return "n/a"
    a = decimal_to_american(1 / p)
    return f"{a:+.0f}"


def _two_way(p_a: float, p_b: float, push: float) -> dict:
    s = p_a + p_b
    return {"p_a": round(p_a, 4), "p_b": round(p_b, 4), "p_push": round(push, 4),
            "fair_a": _fair(p_a / s) if s else "n/a", "fair_b": _fair(p_b / s) if s else "n/a"}


def price(gd: GameDist, totals: Sequence[float] = (), run_lines: Sequence[float] = (-1.5, 1.5),
          team_totals: Sequence[Tuple[str, float]] = (), f5_totals: Sequence[float] = (4.5,)) -> dict:
    """Fair prices for the usual MLB markets from a solved game."""
    ph = gd.p_home()
    ma, mh = gd.mean_runs()
    tp = gd.total_pmf()
    out = {
        "p_home": round(ph, 4), "fair_home": _fair(ph), "fair_away": _fair(1 - ph),
        "exp_runs": {"away": round(ma, 2), "home": round(mh, 2), "total": round(ma + mh, 2)},
        "p_extra_innings": round(gd.p_extra, 4),
        "p_one_run_game": round(sum(p for v, p in gd.margin_pmf().items() if abs(v) == 1), 4),
        "median_total": next(t for t in sorted(tp) if sum(p for v, p in tp.items() if v <= t) >= 0.5),
        "totals": [], "run_lines": [], "team_totals": [], "f5": {}, "first_inning": {},
    }
    for line in totals:
        o, u, pu = gd.over_under(line)
        out["totals"].append({"line": line, **{k.replace("_a", "_over").replace("_b", "_under"): v
                                                 for k, v in _two_way(o, u, pu).items()}})
    for line in run_lines:
        c, a, pu = gd.run_line(line)
        out["run_lines"].append({"home_line": line, **{k.replace("_a", "_home").replace("_b", "_away"): v
                                                         for k, v in _two_way(c, a, pu).items()}})
    for side, line in team_totals:
        o, u, pu = gd.team_over_under(side, line)
        out["team_totals"].append({"team": side, "line": line, **{k.replace("_a", "_over").replace("_b", "_under"): v
                                                                    for k, v in _two_way(o, u, pu).items()}})
    fh, fa, ft = gd.f5_result()
    f5 = {"p_home_lead": round(fh, 4), "p_away_lead": round(fa, 4), "p_tie": round(ft, 4),
          "ml_no_tie": {"fair_home": _fair(fh / (fh + fa)), "fair_away": _fair(fa / (fh + fa))},
          "three_way": {"fair_home": _fair(fh), "fair_away": _fair(fa), "fair_tie": _fair(ft)}, "totals": []}
    c, a, pu = gd.f5_run_line(-0.5)
    f5["home_-0.5"] = {"p_home": round(c, 4), "fair_home": _fair(c), "fair_away_+0.5": _fair(1 - c)}
    for line in f5_totals:
        o, u, pu = gd.f5_over_under(line)
        f5["totals"].append({"line": line, **{k.replace("_a", "_over").replace("_b", "_under"): v
                                                for k, v in _two_way(o, u, pu).items()}})
    out["f5"] = f5
    out["first_inning"] = {"p_nrfi": round(gd.nrfi, 4), "fair_nrfi": _fair(gd.nrfi), "fair_yrfi": _fair(1 - gd.nrfi)}
    return out


def evaluate_offer(gd: GameDist, market: str, side: str, line: Optional[float], american: float) -> dict:
    """EV of a book price.  market: ml | runline | total | team_total | f5_ml | f5_runline | f5_total | nrfi.
    side: home/away, over/under, or for team_total 'home_over' etc.; nrfi side: nrfi/yrfi.
    Run lines are the selection's own line: away -1.5 is ``("runline", "away", -1.5)``."""
    if market == "ml":
        ph = gd.p_home()
        p, push = (ph if side == "home" else 1 - ph), 0.0
    elif market == "runline":
        hl = line if side == "home" else -line
        c, a, push = gd.run_line(hl)
        p = c if side == "home" else a
    elif market == "total":
        o, u, push = gd.over_under(line)
        p = o if side == "over" else u
    elif market == "team_total":
        team, ou = side.split("_")
        o, u, push = gd.team_over_under(team, line)
        p = o if ou == "over" else u
    elif market == "f5_ml":                           # two-way, tie = push (how DK/FD usually settle)
        fh, fa, ft = gd.f5_result()
        p, push = (fh if side == "home" else fa), ft
    elif market == "f5_runline":
        hl = line if side == "home" else -line
        c, a, push = gd.f5_run_line(hl)
        p = c if side == "home" else a
    elif market == "f5_total":
        o, u, push = gd.f5_over_under(line)
        p = o if side == "over" else u
    elif market == "nrfi":
        p, push = (gd.nrfi if side == "nrfi" else 1 - gd.nrfi), 0.0
    else:
        raise ValueError(f"unknown MLB market {market!r}")
    dec = american_to_decimal(american)
    ev = p * (dec - 1) - (1 - p - push)
    return {"market": market, "side": side, "line": line, "price": american, "p_win": round(p, 4),
            "p_push": round(push, 4), "ev_pct": round(100 * ev, 2),
            "fair": _fair(p / (1 - push)) if push < 1 else "n/a"}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _f(x):
    try:
        return float(x) if x not in (None, "") else None
    except ValueError:
        return None


def load_games(path: Optional[str] = None) -> List[dict]:
    """Rows of data/mlb/games.csv with numeric fields and linescores parsed."""
    p = Path(path) if path else data_dir() / "games.csv"
    rows = []
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            g = dict(r)
            for k in ("total", "over", "under", "ml_away", "ml_home", "rl_line_home", "rl_home", "rl_away",
                      "open_total", "open_ml_away", "open_ml_home"):
                g[k] = _f(r.get(k))
            g["away_score"], g["home_score"] = int(r["away_score"]), int(r["home_score"])
            g["innings"] = int(r["innings"] or 9)
            g["away_ls"] = [int(x) for x in r["away_ls"].split(";") if x != ""]
            g["home_ls"] = [int(x) for x in r["home_ls"].split(";") if x != ""]
            g["postseason"] = r["season_type"] == "post"
            if g["ml_away"] is None or g["ml_home"] is None or g["total"] is None:
                continue
            if g["over"] is None or g["under"] is None:
                g["over"] = g["under"] = -110.0
            rows.append(g)
    rows.sort(key=lambda g: (g["date"], g["event_id"]))
    return rows


def linescore_ok(g: dict) -> bool:
    """Linescores consistent with the final score (rain-shortened and suspended games fail)."""
    a, h = g["away_ls"], g["home_ls"]
    return (len(a) >= 9 and sum(a) == g["away_score"] and sum(h) == g["home_score"]
            and len(h) in (len(a), len(a) - 1))


# ---------------------------------------------------------------------------
# Fitting and validation (used by scripts/refresh_mlb_data.py)
# ---------------------------------------------------------------------------

def _row_inputs(g: dict) -> Tuple[float, float, float]:
    p_home, p_over = market_probs(g["ml_away"], g["ml_home"], g["total"], g["over"], g["under"])
    return p_home, g["total"], p_over


def _solve_row(args) -> Tuple[float, float]:
    g, params = args
    p_home, line, p_over = _row_inputs(g)
    gd = solve(p_home, line, p_over, params, g["postseason"])
    return gd.mu_away, gd.mu_home


def solve_rows(rows: Sequence[dict], params: Params, procs: int = 0) -> List[Tuple[float, float]]:
    """Market-implied team rates for every game (parallel; this is the slow step)."""
    args = [(g, params) for g in rows]
    if procs == 1 or len(rows) < 50:
        return [_solve_row(a) for a in args]
    from multiprocessing import Pool
    with Pool(procs or os.cpu_count() or 2) as pool:
        return pool.map(_solve_row, args, chunksize=20)


def nb_logpmf(k: int, mean: float, r: float) -> float:
    mean = max(mean, 1e-9)
    return (math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
            + r * math.log(r / (r + mean)) + k * math.log(mean / (r + mean)))


def _golden(f, lo: float, hi: float, iters: int = 40) -> float:
    """Maximise a unimodal f on [lo, hi]."""
    g = (math.sqrt(5) - 1) / 2
    a, b = lo, hi
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(iters):
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = f(d)
    return (a + b) / 2


def _half_innings(rows: Sequence[dict], mus: Sequence[Tuple[float, float]]) -> List[Tuple[int, int, float]]:
    """(inning index 0-8, runs, team rate) for every regulation half-inning not affected by the
    walk-off / skipped-bottom-9th rules: away innings 1-9 and home innings 1-8."""
    out = []
    for g, (ma, mh) in zip(rows, mus):
        for i in range(9):
            out.append((i, g["away_ls"][i], ma))
        for i in range(8):
            out.append((i, g["home_ls"][i], mh))
    return out


def fit_innings(rows: Sequence[dict], mus: Sequence[Tuple[float, float]], params: Params) -> Params:
    """Per-inning multipliers, league rate and NB dispersion, given each game's market rates."""
    obs = _half_innings(rows, mus)
    runs = [0.0] * 9
    expd = [0.0] * 9
    for i, k, mu in obs:
        runs[i] += k
        expd[i] += mu * params.inning_mult[i]
    mult = [params.inning_mult[i] * runs[i] / expd[i] for i in range(9)]
    s = sum(mult) / 9
    mult = [round(x / s, 4) for x in mult]
    # rates were solved with the old multipliers; rescale them so expected runs are unchanged
    obs = [(i, k, mu * s) for i, k, mu in obs]
    rest = [o for o in obs if o[0] > 0]
    first = [o for o in obs if o[0] == 0]
    r = _golden(lambda r: sum(nb_logpmf(k, mu * mult[i], r) for i, k, mu in rest), 0.1, 2.0)
    r1 = _golden(lambda r: sum(nb_logpmf(k, mu * mult[i], r) for i, k, mu in first), 0.1, 3.0)
    n_half = sum(1 for g in rows for _ in range(17))
    league = sum(sum(g["away_ls"][:9]) + sum(g["home_ls"][:8]) for g in rows) / n_half
    return replace(params, r=round(r, 4), r_first=round(r1, 4), inning_mult=tuple(mult), league_mu=round(league, 4))


def fit_ghost(rows: Sequence[dict], mus: Sequence[Tuple[float, float]], params: Params) -> Params:
    """Automatic-runner extra innings (regular season): away half-innings 10+ (home halves are cut
    short by walk-offs)."""
    obs = [(k, ma / params.league_mu) for g, (ma, _) in zip(rows, mus) if not g["postseason"]
           for k in g["away_ls"][9:]]
    if len(obs) < 100:
        return params

    def ll(mean, r):
        return sum(nb_logpmf(k, mean * s, r) for k, s in obs)
    mean = sum(k for k, _ in obs) / sum(s for _, s in obs)
    r = _golden(lambda r: ll(mean, r), 0.2, 20.0)
    mean = _golden(lambda m: ll(m, r), 0.5 * mean, 1.5 * mean)
    return replace(params, ghost_mean=round(mean, 4), ghost_r=round(r, 4))


def fit_late(rows: Sequence[dict], mus: Sequence[Tuple[float, float]], params: Params) -> Params:
    """Score-dependent 9th inning.  Away 9th by the state after 8 (trailing / tied / leading), and
    the home 9th when it isn't leading — censored at the walk-off (the game ends on the winning run)."""
    m9, r = params.inning_mult[8], params.r
    by_state: List[List[Tuple[int, float]]] = [[], [], []]
    home = []                                          # (runs or None, needed to win, base rate)
    for g, (ma, mh) in zip(rows, mus):
        a, h = g["away_ls"], g["home_ls"]
        a8, h8 = sum(a[:8]), sum(h[:8])
        st = 0 if a8 < h8 else 1 if a8 == h8 else 2
        by_state[st].append((a[8], ma * m9))
        a9 = a8 + a[8]
        if h8 <= a9 and len(h) >= 9:
            d = a9 - h8
            walkoff = len(h) == 9 and g["home_score"] > g["away_score"]
            home.append((None if walkoff else h[8], d, mh * m9))
    top9 = []
    for obs in by_state:
        def ll(f, obs=obs):
            return sum(nb_logpmf(k, mu * f, r) for k, mu in obs)
        top9.append(round(_golden(ll, 0.4, 1.8), 4) if len(obs) > 200 else 1.0)

    def ll_home(f):
        tot = 0.0
        for k, d, mu in home:
            if k is None:                              # walk-off: scored at least d+1
                pmf = nb_pmf(mu * f, r)
                tot += math.log(max(sum(pmf[d + 1:]), 1e-12))
            else:
                tot += nb_logpmf(k, mu * f, r)
        return tot
    b9 = _golden(ll_home, 0.4, 1.8) if len(home) > 200 else 1.0
    return replace(params, top9=tuple(top9), bottom9=round(b9, 4))


def _walkoff_obs(rows: Sequence[dict], mus: Sequence[Tuple[float, float]], params: Params):
    """(pmf of the home team's last half-inning, runs needed to tie, final margin) for walk-offs."""
    out = []
    for g, (_, mh) in zip(rows, mus):
        a, h = g["away_ls"], g["home_ls"]
        if g["home_score"] <= g["away_score"] or len(h) != len(a) or len(h) < 9:
            continue
        before = g["home_score"] - h[-1]
        d = g["away_score"] - before
        if d < 0:
            continue                                  # home already led: not a walk-off
        inn = len(h)
        if inn == 9 or g["postseason"]:
            pmf = nb_pmf(mh * params.inning_mult[8] * params.bottom9, params.r)
        else:
            pmf = nb_pmf(params.ghost_mean * mh / params.league_mu, params.ghost_r)
        out.append((pmf, d, g["home_score"] - g["away_score"]))
    return out


def fit_walkoff(rows: Sequence[dict], mus: Sequence[Tuple[float, float]], params: Params, iters: int = 200) -> Params:
    """EM for J, the walk-off margin cap (a walk-off single wins by 1; a homer by up to 4)."""
    obs = _walkoff_obs(rows, mus, params)
    if len(obs) < 50:
        return params
    J = len(params.walkoff_cap)
    cap = [0.0] + [1.0 / (J - 1)] * (J - 1)
    lik = []
    for pmf, d, m in obs:
        tail = sum(pmf[d + 1:]) or 1e-12
        pb = [pmf[d + b] / tail if d + b < len(pmf) else 0.0 for b in range(len(pmf))]   # P(beyond = b | walk-off)
        row = [0.0] * J
        for j in range(1, J):
            if m < j:
                row[j] = pb[m] if m < len(pb) else 0.0
            elif m == j:
                row[j] = sum(pb[j:])
        lik.append(row)
    for _ in range(iters):
        acc = [0.0] * J
        for row in lik:
            w = [cap[j] * row[j] for j in range(J)]
            s = sum(w)
            if s > 0:
                for j in range(J):
                    acc[j] += w[j] / s
        cap = [x / len(lik) for x in acc]
    return replace(params, walkoff_cap=tuple(round(c, 4) for c in cap))


def _poisson_joint_ll(ma: float, mh: float, a: int, h: int) -> float:
    def lp(k, m):
        return -m + k * math.log(m) - math.lgamma(k + 1)
    return lp(a, ma) + lp(h, mh)


def _game_metrics(args) -> dict:
    """Model probabilities and outcomes for one held-out game."""
    g, params = args
    p_home, line, p_over = _row_inputs(g)
    gd = solve(p_home, line, p_over, params, g["postseason"])
    a, h = g["away_score"], g["home_score"]
    al, hl = g["away_ls"], g["home_ls"]
    out = {"bin": {}, "ll": {}}
    b = out["bin"]
    b["home_-1.5"] = (gd.run_line(-1.5)[0], h - a >= 2)
    b["away_-1.5"] = (gd.run_line(1.5)[1], a - h >= 2)
    if g.get("rl_line_home") in (-1.5, 1.5) and g.get("rl_home") and g.get("rl_away"):
        pm = devig([american_to_decimal(g["rl_home"]), american_to_decimal(g["rl_away"])])[0]
        won = h - a + g["rl_line_home"] > 0
        out["rl_market"] = (gd.run_line(g["rl_line_home"])[0], pm, won)
    for off in (-2, -1, 1, 2):
        L = line + off
        o, u, pu = gd.over_under(L)
        t = a + h
        if t != L:
            b[f"total_{off:+d}"] = (o / (o + u), t > L)
    for side, runs in (("home", h), ("away", a)):
        for L in (2.5, 3.5, 4.5, 5.5):
            b[f"{side}_tt_o{L}"] = (gd.team_over_under(side, L)[0], runs > L)
    f5a, f5h = sum(al[:5]), sum(hl[:5])
    fh, fa, ft = gd.f5_result()
    b["f5_home_lead"] = (fh, f5h > f5a)
    b["f5_tie"] = (ft, f5h == f5a)
    b["f5_over_4.5"] = (gd.f5_over_under(4.5)[0], f5a + f5h > 4.5)
    b["nrfi"] = (gd.nrfi, al[0] + hl[0] == 0)
    b["extra_innings"] = (gd.p_extra, len(al) > 9)
    b["one_run"] = (sum(p for v, p in gd.margin_pmf().items() if abs(v) == 1), abs(h - a) == 1)
    pj = gd.joint.get((a, h), 1e-9)
    ma, mh = gd.mean_runs()
    out["ll"] = {"model": math.log(max(pj, 1e-9)), "poisson": _poisson_joint_ll(ma, mh, a, h)}
    out["exp_total"] = ma + mh
    out["total"] = a + h
    out["post"] = g["postseason"]
    return out


def _binary_summary(pairs: Sequence[Tuple[float, bool]]) -> dict:
    n = len(pairs)
    if not n:
        return {"n": 0}
    pred = sum(p for p, _ in pairs) / n
    act = sum(1 for _, y in pairs if y) / n
    ll = -sum(math.log(min(max(p if y else 1 - p, 1e-9), 1)) for p, y in pairs) / n
    base = -(act * math.log(act) + (1 - act) * math.log(1 - act)) if 0 < act < 1 else 0.0
    return {"n": n, "predicted": round(pred, 4), "actual": round(act, 4), "log_loss": round(ll, 4),
            "log_loss_base_rate": round(base, 4)}


def _calibration_bins(pairs: Sequence[Tuple[float, bool]], k: int = 5) -> List[dict]:
    s = sorted(pairs)
    out = []
    for i in range(k):
        chunk = s[i * len(s) // k:(i + 1) * len(s) // k]
        if chunk:
            out.append({"predicted": round(sum(p for p, _ in chunk) / len(chunk), 3),
                        "actual": round(sum(1 for _, y in chunk if y) / len(chunk), 3), "n": len(chunk)})
    return out


def validate(rows: Sequence[dict], params: Params, procs: int = 0) -> dict:
    """Held-out check: every derived market priced from the closing moneyline + total, against results."""
    args = [(g, params) for g in rows]
    if procs == 1 or len(rows) < 50:
        res = [_game_metrics(a) for a in args]
    else:
        from multiprocessing import Pool
        with Pool(procs or os.cpu_count() or 2) as pool:
            res = pool.map(_game_metrics, args, chunksize=20)
    keys = sorted({k for r in res for k in r["bin"]})
    out = {"n_games": len(res), "n_postseason": sum(1 for r in res if r["post"]), "markets": {}, "calibration": {}}
    for k in keys:
        pairs = [r["bin"][k] for r in res if k in r["bin"]]
        out["markets"][k] = _binary_summary(pairs)
        if k in ("home_-1.5", "away_-1.5", "nrfi", "total_+1", "total_-1", "f5_home_lead"):
            out["calibration"][k] = _calibration_bins(pairs)
    rl = [r["rl_market"] for r in res if "rl_market" in r]
    if rl:
        def ll(i):
            return -sum(math.log(max(x[i] if x[2] else 1 - x[i], 1e-9)) for x in rl) / len(rl)
        out["run_line_vs_market"] = {"n": len(rl), "log_loss_model": round(ll(0), 4), "log_loss_market": round(ll(1), 4),
                                     "mean_abs_diff": round(sum(abs(x[0] - x[1]) for x in rl) / len(rl), 4),
                                     "actual_cover": round(sum(1 for x in rl if x[2]) / len(rl), 4),
                                     "model_mean": round(sum(x[0] for x in rl) / len(rl), 4),
                                     "market_mean": round(sum(x[1] for x in rl) / len(rl), 4)}
    n = len(res)
    out["final_score_loglik_per_game"] = {"model": round(sum(r["ll"]["model"] for r in res) / n, 4),
                                          "independent_poisson": round(sum(r["ll"]["poisson"] for r in res) / n, 4)}
    out["mean_total"] = {"model": round(sum(r["exp_total"] for r in res) / n, 3),
                         "actual": round(sum(r["total"] for r in res) / n, 3)}
    return out


def build_calibration(rows: Sequence[dict], test_from: str = TEST_FROM, passes: int = 2, procs: int = 0,
                      log=print) -> dict:
    """Fit on games before ``test_from`` and validate on the rest."""
    ok = [g for g in rows if linescore_ok(g)]
    train = [g for g in ok if g["date"] < test_from]
    test = [g for g in ok if g["date"] >= test_from]
    params = Params()
    for i in range(passes):
        mus = solve_rows(train, params, procs)
        params = fit_innings(train, mus, params)
        params = fit_late(train, mus, params)
        params = fit_ghost(train, mus, params)
        params = fit_walkoff(train, mus, params)
        log(f"pass {i + 1}: {params}")
    v = validate(test, params, procs)
    summary = {k: v["markets"][k] for k in ("home_-1.5", "nrfi", "extra_innings", "one_run", "total_+1", "f5_tie")
               if k in v["markets"]}
    summary["run_line_vs_market"] = v.get("run_line_vs_market")
    summary["final_score_loglik_per_game"] = v["final_score_loglik_per_game"]
    v["summary"] = summary
    return {"params": params.to_json(), "fit": {"n_train": len(train), "n_test": len(test), "test_from": test_from,
                                               "dropped_bad_linescores": len(rows) - len(ok)},
            "validation": v}

