"""Tennis pricing and ratings.

**Pricing** is exact: each player's chance of winning a point on serve
(``pa``, ``pb``) gives the chance of holding serve, winning a tiebreak, a set
and the match, and the full distribution of total games, the game handicap
and set scores (best of 3 or 5, standard 7-point tiebreaks at 6-6, and a
10-point final-set tiebreak where the event uses one).  Points within a game
are treated as independent with constant probabilities — the standard
assumption, and a good one for match and games markets.

**From the market**: ``solve_serve`` finds the pair (pa, pb) that reproduces a
match-win probability (for example the devigged moneyline) at the tour and
surface's average serve level, so total games, handicaps and set betting are
priced *from* the moneyline.  The serve levels are fitted so that the
predicted total games match real matches (``fit_serve_levels``).

**Ratings**: a surface-blended Elo (``Elo``) fitted walk-forward on tour
results; ``validate_elo`` scores it against bookmaker closing odds.

**Live**: ``live_state`` prices a match from any score (sets, games, points,
server) — win probability and the remaining total-games distribution.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .distributions import DiscreteDist, gauss_hermite_normal_nodes
from .odds import american_to_decimal, decimal_to_american, devig

Pmf = Dict[Tuple[int, int], float]


# ---------------------------------------------------------------------------
# Point -> game -> tiebreak -> set
# ---------------------------------------------------------------------------

def p_hold(p: float) -> float:
    """Chance the server wins a game when winning each service point with probability ``p``."""
    q = 1.0 - p
    deuce = p * p / (1.0 - 2.0 * p * q)
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * p ** 3 * q ** 3 * deuce


def game_from_points(p: float, server_pts: int, receiver_pts: int) -> float:
    """Chance the server wins the game from a point score (0,1,2,3,... = 0,15,30,40; deuce handled)."""
    q = 1.0 - p
    a, b = server_pts, receiver_pts
    while a >= 3 and b >= 3 and (a > 3 or b > 3):   # fold advantage scores back to deuce/advantage
        a, b = a - 1, b - 1
    deuce = p * p / (1.0 - 2.0 * p * q)

    @lru_cache(maxsize=None)
    def g(x: int, y: int) -> float:
        if x >= 4 and x - y >= 2:
            return 1.0
        if y >= 4 and y - x >= 2:
            return 0.0
        if x == 3 and y == 3:
            return deuce
        if x == 4 and y == 3:               # advantage server
            return p + q * deuce
        if x == 3 and y == 4:               # advantage receiver
            return p * deuce
        return p * g(x + 1, y) + q * g(x, y + 1)
    return g(a, b)


def _tb_server_is_first(k: int) -> bool:
    """Point k (0-based) of a tiebreak: the first server serves point 0, then each player serves two."""
    return ((k + 1) // 2) % 2 == 0


def tiebreak_win(pa: float, pb: float, a_serves_first: bool = True, target: int = 7,
                 pts: Tuple[int, int] = (0, 0)) -> float:
    """Chance A wins a tiebreak (first to ``target``, win by two) from a point score."""
    def a_wins_point(k: int) -> float:
        a_serving = _tb_server_is_first(k) == a_serves_first
        return pa if a_serving else 1.0 - pb
    tie = pa * (1 - pb) / (pa * (1 - pb) + (1 - pa) * pb)   # from a level score after an even number of points

    @lru_cache(maxsize=None)
    def t(i: int, j: int) -> float:
        if i >= target and i - j >= 2:
            return 1.0
        if j >= target and j - i >= 2:
            return 0.0
        if i == j and i >= target - 1:
            return tie
        w = a_wins_point(i + j)
        return w * t(i + 1, j) + (1 - w) * t(i, j + 1)
    return t(*pts)


def set_dist(pa: float, pb: float, a_serves_first: bool, tb_target: int = 7,
             games: Tuple[int, int] = (0, 0), current_game_a: Optional[float] = None) -> Pmf:
    """Final-score distribution {(games A, games B): p} of a set, from a games score.

    ``current_game_a`` (optional) is A's chance of winning the game in progress
    (from its point score); otherwise the next game starts at 0-0.
    """
    ha, hb = p_hold(pa), p_hold(pb)
    out: Pmf = {}

    def a_serves(ga: int, gb: int) -> bool:
        return ((ga + gb) % 2 == 0) == a_serves_first

    def done(ga: int, gb: int) -> bool:
        return (ga >= 6 or gb >= 6) and abs(ga - gb) >= 2 or ga == 7 or gb == 7

    frontier = {games: 1.0}
    first = True
    while frontier:
        nxt: Pmf = {}
        for (ga, gb), pr in frontier.items():
            if done(ga, gb):
                out[(ga, gb)] = out.get((ga, gb), 0.0) + pr
                continue
            if ga == 6 and gb == 6:
                if first and current_game_a is not None:
                    w = current_game_a
                else:
                    w = tiebreak_win(pa, pb, a_serves(ga, gb), tb_target)
            elif first and current_game_a is not None:
                w = current_game_a
            else:
                w = ha if a_serves(ga, gb) else 1.0 - hb
            for key, pw in (((ga + 1, gb), w), ((ga, gb + 1), 1.0 - w)):
                if pw > 0:
                    nxt[key] = nxt.get(key, 0.0) + pr * pw
        frontier = nxt
        first = False
    return out


# ---------------------------------------------------------------------------
# Match
# ---------------------------------------------------------------------------

@dataclass
class MatchDist:
    """Exact outcome distribution of a match (A's perspective)."""

    p_a: float
    total_games: DiscreteDist
    game_margin: DiscreteDist          # games A - games B
    set_scores: Dict[Tuple[int, int], float]
    best_of: int

    def over_under(self, line: float) -> Tuple[float, float, float]:
        return self.total_games.over_under_push(line)

    def handicap(self, line_a: float) -> Tuple[float, float, float]:
        """A at a games handicap (e.g. -3.5): (cover, push, fail)."""
        o, u, p = self.game_margin.over_under_push(-line_a)
        return o, p, u

    def sets_handicap(self, line_a: float) -> float:
        return sum(p for (sa, sb), p in self.set_scores.items() if sa - sb + line_a > 0)

    def summary(self) -> dict:
        tg = self.total_games
        return {"p_a": round(self.p_a, 4), "fair_ml_a": _am(self.p_a), "fair_ml_b": _am(1 - self.p_a),
                "exp_total_games": round(tg.mean(), 2), "median_total_games": tg.median_line(),
                "exp_game_margin_a": round(self.game_margin.mean(), 2),
                "set_scores": {f"{a}-{b}": round(p, 4) for (a, b), p in sorted(self.set_scores.items(), key=lambda x: -x[1])}}


def _am(p: float) -> Optional[str]:
    if not 0 < p < 1:
        return None
    return f"{decimal_to_american(1 / p):+.0f}"


def match_dist(pa: float, pb: float, best_of: int = 3, final_tb: int = 7, a_serves_first: Optional[bool] = None,
               sets: Tuple[int, int] = (0, 0), games_so_far: Tuple[int, int] = (0, 0),
               set_games: Tuple[int, int] = (0, 0), a_serves_next: Optional[bool] = None,
               current_game_a: Optional[float] = None) -> MatchDist:
    """Distribution of the match from a state (defaults: the start, first server a coin toss).

    ``games_so_far`` counts games in completed sets; ``set_games`` is the score
    in the current set; ``a_serves_next`` says who serves the current game.
    """
    if a_serves_first is None and a_serves_next is None and sets == (0, 0) and set_games == (0, 0):
        h = [match_dist(pa, pb, best_of, final_tb, flag) for flag in (True, False)]
        return MatchDist((h[0].p_a + h[1].p_a) / 2,
                         _avg(h[0].total_games, h[1].total_games), _avg(h[0].game_margin, h[1].game_margin),
                         {k: (h[0].set_scores.get(k, 0) + h[1].set_scores.get(k, 0)) / 2
                          for k in set(h[0].set_scores) | set(h[1].set_scores)}, best_of)
    need = best_of // 2 + 1
    first = a_serves_next if a_serves_next is not None else bool(a_serves_first)
    # the set in progress starts with whoever served game 1 of it
    gs = sum(set_games)
    set_first = first if gs % 2 == 0 else not first
    # state: (sa, sb, a_first_in_set) -> {(ga_total, gb_total): p}
    frontier: Dict[Tuple[int, int, bool], Pmf] = {(sets[0], sets[1], set_first): {games_so_far: 1.0}}
    tot: Dict[int, float] = {}
    marg: Dict[int, float] = {}
    sset: Dict[Tuple[int, int], float] = {}
    p_a = 0.0
    start = True
    while frontier:
        nxt: Dict[Tuple[int, int, bool], Pmf] = {}
        for (sa, sb, af), gdist in frontier.items():
            final = sa == need - 1 and sb == need - 1
            tb = final_tb if final else 7
            if start:
                sd = set_dist(pa, pb, af, tb, set_games, current_game_a)
            else:
                sd = _set_dist_cached(pa, pb, af, tb)
            for (ga, gb), ps in sd.items():
                ng = ga + gb
                nf = af if ng % 2 == 0 else not af           # next set: whoever didn't serve the last game
                key = (sa + (ga > gb), sb + (gb > ga), nf)
                for (ta, tbg), pg in gdist.items():
                    pr = ps * pg
                    na, nb = ta + ga, tbg + gb
                    if key[0] == need or key[1] == need:
                        tot[na + nb] = tot.get(na + nb, 0.0) + pr
                        marg[na - nb] = marg.get(na - nb, 0.0) + pr
                        sset[(key[0], key[1])] = sset.get((key[0], key[1]), 0.0) + pr
                        if key[0] == need:
                            p_a += pr
                    else:
                        d = nxt.setdefault(key, {})
                        d[(na, nb)] = d.get((na, nb), 0.0) + pr
        frontier = nxt
        start = False
    return MatchDist(p_a, DiscreteDist(tot), DiscreteDist(marg), sset, best_of)


@lru_cache(maxsize=4096)
def _set_dist_cached(pa: float, pb: float, af: bool, tb: int) -> Pmf:
    return set_dist(pa, pb, af, tb)


def _avg(a: DiscreteDist, b: DiscreteDist) -> DiscreteDist:
    keys = set(a.pmf) | set(b.pmf)
    return DiscreteDist({k: (a.prob(k) + b.prob(k)) / 2 for k in keys})


def solve_serve(p_match: float, serve_level: float, best_of: int = 3, final_tb: int = 7) -> Tuple[float, float]:
    """(pa, pb) averaging ``serve_level`` that give A a match-win probability of ``p_match``."""
    if not 0.0 < p_match < 1.0:
        raise ValueError("match probability must be between 0 and 1")
    lo, hi = -0.45, 0.45
    lo = max(lo, 2 * (serve_level - 0.995)) if serve_level > 0.5 else lo
    for _ in range(60):
        d = (lo + hi) / 2
        pa, pb = serve_level + d / 2, serve_level - d / 2
        pa, pb = min(max(pa, 0.01), 0.995), min(max(pb, 0.01), 0.995)
        if _p_match_fast(round(pa, 9), round(pb, 9), best_of, final_tb) < p_match:
            lo = d
        else:
            hi = d
    d = (lo + hi) / 2
    return serve_level + d / 2, serve_level - d / 2


@lru_cache(maxsize=65536)
def _p_match_fast(pa: float, pb: float, best_of: int, final_tb: int) -> float:
    """Match-win probability only (much faster than ``match_dist``): set win probs by first server."""
    need = best_of // 2 + 1
    # set win prob for A and whether the next set's first server flips, by who serves first in the set
    def set_outcomes(af: bool, tb: int):
        sd = _set_dist_cached(pa, pb, af, tb)
        win_same = sum(p for (ga, gb), p in sd.items() if ga > gb and (ga + gb) % 2 == 0)
        win_flip = sum(p for (ga, gb), p in sd.items() if ga > gb and (ga + gb) % 2 == 1)
        lose_same = sum(p for (ga, gb), p in sd.items() if gb > ga and (ga + gb) % 2 == 0)
        lose_flip = sum(p for (ga, gb), p in sd.items() if gb > ga and (ga + gb) % 2 == 1)
        return win_same, win_flip, lose_same, lose_flip

    @lru_cache(maxsize=None)
    def m(sa: int, sb: int, af: bool) -> float:
        if sa == need:
            return 1.0
        if sb == need:
            return 0.0
        tb = final_tb if sa == sb == need - 1 else 7
        ws, wf, ls, lf = set_outcomes(af, tb)
        return ws * m(sa + 1, sb, af) + wf * m(sa + 1, sb, not af) + ls * m(sa, sb + 1, af) + lf * m(sa, sb + 1, not af)
    return 0.5 * (m(0, 0, True) + m(0, 0, False))


# ---------------------------------------------------------------------------
# Day-to-day form: a mixture over the serve gap
# ---------------------------------------------------------------------------
# Real matches are more lopsided than independent points at fixed serve rates
# imply (players have good and bad days).  The gap d = pa - pb is drawn from a
# normal around d0 with standard deviation ``form_sd``; d0 is solved so the
# mixture still gives A the market's match-win probability.  Fitted per tour and
# surface on total games (``fit_serve_levels``).

_NODES = tuple(z for z, _ in gauss_hermite_normal_nodes(0.0, 1.0, 9))


def _clamp(x: float) -> float:
    return min(max(x, 0.02), 0.98)


def _node_pairs(level: float, d0: float, form_sd: float) -> List[Tuple[float, float]]:
    return [(round(_clamp(level + (d0 + form_sd * z) / 2), 4), round(_clamp(level - (d0 + form_sd * z) / 2), 4))
            for z in (_NODES if form_sd > 0 else (0.0,))]


@lru_cache(maxsize=200000)
def solve_gap(p_match: float, level: float, form_sd: float, best_of: int = 3, final_tb: int = 7) -> float:
    """Centre d0 of the serve gap so that the form mixture gives A ``p_match``."""
    if not 0.0 < p_match < 1.0:
        raise ValueError("match probability must be between 0 and 1")
    lo, hi = -0.9, 0.9
    for _ in range(45):
        d = (lo + hi) / 2
        pairs = _node_pairs(level, d, form_sd)
        pm = sum(_p_match_fast(a, b, best_of, final_tb) for a, b in pairs) / len(pairs)
        lo, hi = (d, hi) if pm < p_match else (lo, d)
    return (lo + hi) / 2


@lru_cache(maxsize=50000)
def mixture_dist(p_match: float, level: float, form_sd: float, best_of: int = 3, final_tb: int = 7) -> MatchDist:
    """Match distribution averaged over day-to-day form, matched to ``p_match``."""
    d0 = solve_gap(p_match, level, form_sd, best_of, final_tb)
    parts = [match_dist(a, b, best_of, final_tb) for a, b in _node_pairs(level, d0, form_sd)]
    n = len(parts)
    tot: Dict[int, float] = {}
    mar: Dict[int, float] = {}
    sets: Dict[Tuple[int, int], float] = {}
    for md in parts:
        for k, v in md.total_games.pmf.items():
            tot[k] = tot.get(k, 0.0) + v / n
        for k, v in md.game_margin.pmf.items():
            mar[k] = mar.get(k, 0.0) + v / n
        for k, v in md.set_scores.items():
            sets[k] = sets.get(k, 0.0) + v / n
    return MatchDist(sum(md.p_a for md in parts) / n, DiscreteDist(tot), DiscreteDist(mar), sets, best_of)


# ---------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------

_PT = {"0": 0, "15": 1, "30": 2, "40": 3, "A": 4, "AD": 4}


def parse_score(score: str) -> Tuple[List[Tuple[int, int]], Tuple[int, int]]:
    """'6-4 3-2' -> ([(6, 4)], (3, 2)): completed sets plus the current set's games.

    A finished set is one with a winner (6+ games, two clear, or 7-6/7-5).
    """
    sets = []
    for tok in score.split():
        m = re.fullmatch(r"(\d+)-(\d+)(?:\(\d+\))?", tok)
        if not m:
            raise ValueError(f"bad set score {tok!r}; use e.g. '6-4 3-2'")
        sets.append((int(m.group(1)), int(m.group(2))))
    done = []
    for ga, gb in sets:
        finished = (max(ga, gb) >= 6 and abs(ga - gb) >= 2) or max(ga, gb) == 7
        if finished:
            done.append((ga, gb))
        else:
            return done, (ga, gb)
    return done, (0, 0)


def live_state(pa: float, pb: float, score: str = "", points: str = "0-0", server: str = "a",
               best_of: int = 3, final_tb: int = 7) -> dict:
    """Price a match in progress: A's win probability and the final total-games distribution.

    ``score`` lists set scores from A's side ("6-4 3-2" = A won set 1, leads 3-2
    in set 2); ``points`` is the current game ("30-15", "40-A") or tiebreak
    points ("5-4") from A's side; ``server`` is who serves the current point
    (``a``/``b``).
    """
    done, cur = parse_score(score)
    sets = (sum(1 for a, b in done if a > b), sum(1 for a, b in done if b > a))
    need = best_of // 2 + 1
    if max(sets) >= need:
        raise ValueError("that score has already finished the match")
    games_so_far = (sum(a for a, _ in done), sum(b for _, b in done))
    a_srv = server.lower() == "a"
    pts = [x.strip().upper() for x in points.split("-")]
    if len(pts) != 2:
        raise ValueError("points look like '30-15' or, in a tiebreak, '5-4'")
    final = sets == (need - 1, need - 1)
    in_tb = cur == (6, 6)
    if in_tb:
        tb_target = final_tb if final else 7
        i, j = int(pts[0]), int(pts[1])
        # recover who served first in this tiebreak from who serves now
        k = i + j
        a_first = a_srv if _tb_server_is_first(k) else not a_srv
        w = tiebreak_win(pa, pb, a_first, tb_target, (i, j))
    else:
        i, j = _PT.get(pts[0], None), _PT.get(pts[1], None)
        if i is None or j is None:
            raise ValueError("game points are 0, 15, 30, 40 or A")
        w = game_from_points(pa, i, j) if a_srv else 1.0 - game_from_points(pb, j, i)
    # who served the first game of this set: game index = games played in the set
    md = match_dist(pa, pb, best_of, final_tb, sets=sets, games_so_far=games_so_far, set_games=cur,
                    a_serves_next=a_srv if not in_tb else (a_first if True else a_srv), current_game_a=w)
    played = games_so_far[0] + games_so_far[1] + cur[0] + cur[1]
    out = md.summary()
    out.update({"sets": f"{sets[0]}-{sets[1]}", "current_set": f"{cur[0]}-{cur[1]}", "points": points,
                "server": "a" if a_srv else "b", "p_win_current_game_a": round(w, 4), "games_played": played})
    out["_dist"] = md
    return out


def live_price(p_pre: float, tour: str = "atp", surface: str = "hard", best_of: int = 3, final_tb: int = 7,
               score: str = "", points: str = "0-0", server: str = "a", calibration: Optional[dict] = None) -> dict:
    """``live_state`` averaged over the same day-to-day form nodes as the pregame price, centred on the
    pregame (market) win probability ``p_pre``.  The nodes are not reweighted by the score so far, so
    a lopsided score is read only through the point model (a known simplification)."""
    s = serve_level(tour, surface, calibration)
    sd = form_sd(tour, surface, calibration)
    p = min(max(round(p_pre, 4), 0.005), 0.995)
    d0 = solve_gap(p, s, sd, best_of, final_tb)
    parts = [live_state(a, b, score, points, server, best_of, final_tb) for a, b in _node_pairs(s, d0, sd)]
    n = len(parts)
    tot: Dict[int, float] = {}
    for part in parts:
        for k, v in part["_dist"].total_games.pmf.items():
            tot[k] = tot.get(k, 0.0) + v / n
    td = DiscreteDist(tot)
    p_a = sum(x["p_a"] for x in parts) / n
    out = {k: parts[0][k] for k in ("sets", "current_set", "points", "server", "games_played")}
    out.update({"p_a": round(p_a, 4), "fair_ml_a": _am(p_a), "fair_ml_b": _am(1 - p_a),
                "p_win_current_game_a": round(sum(x["p_win_current_game_a"] for x in parts) / n, 4),
                "exp_total_games": round(td.mean(), 2), "median_total_games": td.median_line(),
                "pregame_p_a": p, "serve_level": s, "form_sd": sd})
    out["_total"] = td
    return out


# ---------------------------------------------------------------------------
# Tournaments: surface and format from a name (The Odds API gives no surface)
# ---------------------------------------------------------------------------

_CLAY = ("french open", "roland garros", "madrid", "rome", "italian", "monte carlo", "monte-carlo", "barcelona",
         "hamburg", "rio", "buenos aires", "estoril", "munich", "lyon", "geneva", "bastad", "gstaad", "umag",
         "kitzbuhel", "charleston", "stuttgart open clay", "strasbourg", "rabat", "bogota", "palermo", "prague",
         "parma", "warsaw", "lausanne", "iasi", "santiago", "cordoba", "houston", "marrakech", "bucharest", "budapest")
_GRASS = ("wimbledon", "queen", "halle", "s-hertogenbosch", "hertogenbosch", "eastbourne", "mallorca", "newport",
          "nottingham", "birmingham", "berlin", "bad homburg", "stuttgart")


def tournament_format(name: str, tour: str = "atp") -> dict:
    """Best guess of surface, best-of and final-set tiebreak from a tournament name or Odds API key."""
    n = name.lower().replace("_", " ")
    surface = "clay" if any(k in n for k in _CLAY) else "grass" if any(k in n for k in _GRASS) else "hard"
    slam = any(k in n for k in ("australian open", "french open", "roland garros", "wimbledon", "us open"))
    return {"surface": surface, "best_of": 5 if slam and tour.lower() == "atp" else 3, "final_tb": 10 if slam else 7,
            "grand_slam": slam}


# ---------------------------------------------------------------------------
# Pricing helpers (market -> derived markets)
# ---------------------------------------------------------------------------

DEFAULT_SERVE = {"atp": {"hard": 0.640, "clay": 0.615, "grass": 0.660, "carpet": 0.650},
                 "wta": {"hard": 0.565, "clay": 0.550, "grass": 0.580, "carpet": 0.570}}


def data_dir() -> Path:
    import os
    env = os.environ.get("BETLAB_DATA")
    base = Path(env) if env else Path(__file__).resolve().parent.parent / "data"
    return base / "tennis"


@lru_cache(maxsize=1)
def load_calibration(path: Optional[str] = None) -> dict:
    p = Path(path) if path else data_dir() / "calibration.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"serve_level": DEFAULT_SERVE, "note": "defaults; run scripts/refresh_tennis_data.py"}


DEFAULT_FORM = {"atp": 0.10, "wta": 0.12}


def serve_level(tour: str, surface: str, calibration: Optional[dict] = None) -> float:
    cal = calibration or load_calibration()
    lv = cal.get("serve_level", DEFAULT_SERVE)
    t, s = tour.lower(), surface.lower()
    if t not in lv:
        raise ValueError(f"tour must be one of {sorted(lv)}")
    return lv[t].get(s, lv[t].get("hard"))


def form_sd(tour: str, surface: str, calibration: Optional[dict] = None) -> float:
    cal = calibration or load_calibration()
    fs = cal.get("form_sd", {})
    t, s = tour.lower(), surface.lower()
    if t in fs:
        return fs[t].get(s, fs[t].get("hard"))
    return DEFAULT_FORM.get(t, 0.1)


def price(p_a: float, tour: str = "atp", surface: str = "hard", best_of: int = 3, final_tb: int = 7,
          calibration: Optional[dict] = None, games_lines: Sequence[float] = (), handicaps_a: Sequence[float] = ()) -> dict:
    """Derived markets (totals, handicaps, set betting) from A's match-win probability."""
    s = serve_level(tour, surface, calibration)
    sd = form_sd(tour, surface, calibration)
    p = min(max(round(p_a, 4), 0.005), 0.995)
    d0 = solve_gap(p, s, sd, best_of, final_tb)
    md = mixture_dist(p, s, sd, best_of, final_tb)
    pa, pb = s + d0 / 2, s - d0 / 2
    out = {"tour": tour.lower(), "surface": surface.lower(), "best_of": best_of, "final_set_tiebreak": final_tb,
           "serve_level": s, "form_sd": sd, "p_serve_a": round(pa, 4), "p_serve_b": round(pb, 4),
           "p_hold_a": round(p_hold(_clamp(pa)), 4), "p_hold_b": round(p_hold(_clamp(pb)), 4), **md.summary()}
    out["totals"] = [_ou(md, ln) for ln in games_lines]
    out["handicaps"] = [_hc(md, ln) for ln in handicaps_a]
    out["_dist"] = md
    return out


def _ou(md: MatchDist, line: float) -> dict:
    o, u, p = md.over_under(line)
    return {"line": line, "p_over": round(o, 4), "p_under": round(u, 4), "p_push": round(p, 4),
            "fair_over": _am(o / (o + u)) if o + u else None, "fair_under": _am(u / (o + u)) if o + u else None}


def _hc(md: MatchDist, line: float) -> dict:
    c, p, f = md.handicap(line)
    return {"line_a": line, "p_cover_a": round(c, 4), "p_cover_b": round(f, 4), "p_push": round(p, 4),
            "fair_a": _am(c / (c + f)) if c + f else None, "fair_b": _am(f / (c + f)) if c + f else None}


def evaluate_offer(md: MatchDist, market: str, side: str, line: Optional[float], american: float) -> dict:
    """EV of one offered price: ml a|b, games over|under LINE, handicap a|b LINE (that side's line),
    sets a|b 'x-y' (exact set score from that side, e.g. a 2-0)."""
    if market == "ml":
        p, push = (md.p_a if side == "a" else 1 - md.p_a), 0.0
    elif market == "games":
        o, u, push = md.over_under(float(line))
        p = o if side == "over" else u
    elif market == "handicap":
        if side == "a":
            p, push, _ = md.handicap(float(line))
        else:
            c, push, f = md.handicap(-float(line))
            p = f
    elif market == "sets":
        x, y = (int(v) for v in str(line).split("-"))
        key = (x, y) if side == "a" else (y, x)
        p, push = md.set_scores.get(key, 0.0), 0.0
    else:
        raise ValueError("market is ml, games, handicap or sets")
    dec = american_to_decimal(american)
    ev = p * (dec - 1) - (1 - p - push)
    return {"market": market, "side": side, "line": line, "price": american, "p_win": round(p, 4),
            "p_push": round(push, 4), "ev_pct": round(100 * ev, 2), "fair": _am(p / (1 - push)) if p < 1 - push else None}


# ---------------------------------------------------------------------------
# Data: results with bookmaker odds (tennis-data.co.uk via the Kaggle/Hugging Face mirrors)
# ---------------------------------------------------------------------------

def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return -1.0


def parse_sets(score: str) -> List[Tuple[int, int]]:
    out = []
    for tok in (score or "").split():
        m = re.fullmatch(r"(\d+)-(\d+)(?:\(\d+\))?", tok.strip())
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return out


def completed(sets: Sequence[Tuple[int, int]], best_of: int) -> Optional[int]:
    """1 if the first player won a completed match, 2 if the second did, None if retired/incomplete."""
    need = best_of // 2 + 1
    w1 = w2 = 0
    for a, b in sets:
        ok = (max(a, b) >= 6 and abs(a - b) >= 2) or (max(a, b) == 7 and min(a, b) in (5, 6)) or \
             (max(a, b) > 7 and abs(a - b) == 2)                       # long final sets (pre-2019)
        if not ok:
            return None
        if a > b:
            w1 += 1
        else:
            w2 += 1
    if w1 == need and w2 < need:
        return 1
    if w2 == need and w1 < need:
        return 2
    return None


def load_matches(tour: str, path: Optional[str] = None) -> List[dict]:
    """Matches from ``data/tennis/<tour>_odds.csv``: date, surface, best_of, players, winner,
    set scores (from player 1's side), bookmaker decimal odds and whether the match was completed."""
    p = Path(path) if path else data_dir() / f"{tour.lower()}_odds.csv"
    if not p.exists():
        raise FileNotFoundError(f"{p} not found; run python3 scripts/refresh_tennis_data.py")
    rows = []
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            bo = int(_f(r.get("Best of")) if _f(r.get("Best of")) > 0 else 3)
            sets = parse_sets(r.get("Score", ""))
            p1, p2, win = r["Player_1"].strip(), r["Player_2"].strip(), r["Winner"].strip()
            rows.append({"date": r["Date"][:10], "tournament": r.get("Tournament"), "series": r.get("Series", ""),
                         "surface": (r.get("Surface") or "Hard").strip().lower(), "best_of": bo, "round": r.get("Round"),
                         "p1": p1, "p2": p2, "winner": 1 if win == p1 else 2 if win == p2 else None,
                         "odd1": _f(r.get("Odd_1")), "odd2": _f(r.get("Odd_2")), "sets": sets,
                         "complete": completed(sets, bo) is not None})
    rows = [r for r in rows if re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"])]
    rows.sort(key=lambda r: r["date"])
    return rows


MAIN_LEVELS = {"atp": ("G", "M", "A", "F"), "wta": ("G", "PM", "P", "I", "F", "T1", "T2")}


def load_sackmann(tour: str, years: Iterable[int], folder: Optional[str] = None) -> List[dict]:
    """Main-tour results from Jeff Sackmann's match files (``<tour>_matches_<year>.csv``), in the same
    row shape as ``load_matches`` (winner as player 1, no odds), plus serve-point totals."""
    base = Path(folder) if folder else data_dir() / "sackmann"
    rows = []
    for y in years:
        f = base / f"{tour.lower()}_matches_{y}.csv"
        if not f.exists():
            continue
        with open(f, newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("tourney_level") not in MAIN_LEVELS[tour.lower()]:
                    continue
                d = r.get("tourney_date") or ""
                bo = int(_f(r.get("best_of")) if _f(r.get("best_of")) > 0 else 3)
                sets = parse_sets(r.get("score", ""))
                svpt = {side: (_f(r.get(f"{side}_svpt")), _f(r.get(f"{side}_1stWon")) + _f(r.get(f"{side}_2ndWon")))
                        for side in ("w", "l")}
                rows.append({"date": f"{d[:4]}-{d[4:6]}-{d[6:8]}", "tournament": r.get("tourney_name"),
                             "series": "Grand Slam" if r.get("tourney_level") == "G" else r.get("tourney_level"),
                             "surface": (r.get("surface") or "hard").strip().lower(), "best_of": bo, "round": r.get("round"),
                             "p1": r["winner_name"], "p2": r["loser_name"], "winner": 1, "odd1": -1.0, "odd2": -1.0,
                             "sets": sets, "complete": completed(sets, bo) is not None,
                             "match_num": int(_f(r.get("match_num")) if _f(r.get("match_num")) > 0 else 0), "svpt": svpt})
    rows.sort(key=lambda r: (r["date"], r["tournament"] or "", r["match_num"]))
    return rows


def serve_rates(rows: Iterable[dict]) -> Dict[str, dict]:
    """Share of serve points won by surface, from Sackmann rows with serve stats."""
    agg: Dict[str, List[float]] = {}
    for r in rows:
        for sv, won in (r.get("svpt") or {}).values():
            if sv > 0 and won >= 0:
                a = agg.setdefault(r["surface"], [0.0, 0.0])
                a[0] += won
                a[1] += sv
    return {k: {"rate": round(v[0] / v[1], 4), "serve_points": int(v[1])} for k, v in agg.items() if v[1] > 0}


def market_prob(row: dict) -> Optional[float]:
    """Devigged (multiplicative) chance player 1 wins, or None without usable odds."""
    if row["odd1"] <= 1 or row["odd2"] <= 1:
        return None
    return devig([row["odd1"], row["odd2"]])[0]


# ---------------------------------------------------------------------------
# Serve-level calibration from total games
# ---------------------------------------------------------------------------

SLAMS = ("australian open", "french open", "roland garros", "wimbledon", "us open")


def is_slam(row: dict) -> bool:
    t = (row.get("tournament") or "").lower()
    return row.get("series") == "Grand Slam" or any(s in t for s in SLAMS)


def final_tb_for(row: dict) -> int:
    """Grand Slams have played a 10-point tiebreak at 6-6 in the final set since 2022."""
    return 10 if is_slam(row) and row["date"] >= "2022" else 7


def model_for_row(row: dict, level: float, sd: float = 0.0) -> Optional[MatchDist]:
    """Model distribution for a historical match, from its devigged odds (rounded to 0.01)."""
    p1 = market_prob(row)
    if p1 is None:
        return None
    p1 = min(max(round(p1 * 100) / 100, 0.02), 0.98)
    return mixture_dist(p1, round(level, 4), round(sd, 4), row["best_of"], final_tb_for(row))


def total_games_loglik(rows: Iterable[dict], level: float, sd: float = 0.0) -> Tuple[float, int]:
    ll, n = 0.0, 0
    for r in rows:
        if not r["complete"]:
            continue
        md = model_for_row(r, level, sd)
        if md is None:
            continue
        tg = sum(a + b for a, b in r["sets"])
        ll += math.log(max(md.total_games.prob(tg), 1e-9))
        n += 1
    return ll, n


def fit_serve_levels(rows: Sequence[dict], levels: Sequence[float], sds: Sequence[float]) -> dict:
    """Best (serve level, form sd) for a set of matches: max likelihood of the observed total games,
    plus the same model's fit with no form variation for comparison."""
    scores = [(total_games_loglik(rows, g, sd)[0], g, sd) for g in levels for sd in sds]
    best = max(scores)
    plain = max((total_games_loglik(rows, g, 0.0)[0], g) for g in levels)
    n = total_games_loglik(rows, best[1], best[2])[1]
    done = [r for r in rows if r["complete"] and market_prob(r) is not None]
    actual = sum(sum(a + b for a, b in r["sets"]) for r in done) / max(len(done), 1)
    pred = sum(model_for_row(r, best[1], best[2]).total_games.mean() for r in done) / max(len(done), 1)
    return {"level": best[1], "form_sd": best[2], "n": n, "loglik": round(best[0], 1),
            "loglik_per_match": round(best[0] / max(n, 1), 4), "loglik_no_form": round(plain[0], 1),
            "level_no_form": plain[1], "mean_games_actual": round(actual, 2), "mean_games_model": round(pred, 2)}


def validate_totals(rows: Sequence[dict], level: float, sd: float, by_surface: Optional[dict] = None,
                    line: float = 22.5) -> dict:
    """Out-of-sample check of the games model on completed matches with odds: mean total games,
    log-likelihood vs the same model without form variation, straight-sets rate, and calibration
    of P(over ``line``) by predicted-probability bucket (for best-of-5 rows the line is 38.5)."""
    rs = [r for r in rows if r["complete"] and market_prob(r) is not None]
    if not rs:
        return {"n": 0}
    act = mod = ll = ll0 = 0.0
    straight_a = straight_m = 0.0
    buckets: Dict[int, List[float]] = {}
    for r in rs:
        lv, s_d = level, sd
        if by_surface:
            lv = by_surface["serve_level"]["atp"].get(r["surface"], level)
            s_d = by_surface["form_sd"]["atp"].get(r["surface"], sd)
        md = model_for_row(r, lv, s_d)
        md0 = model_for_row(r, lv, 0.0)
        tg = sum(a + b for a, b in r["sets"])
        act += tg
        mod += md.total_games.mean()
        ll += math.log(max(md.total_games.prob(tg), 1e-9))
        ll0 += math.log(max(md0.total_games.prob(tg), 1e-9))
        need = r["best_of"] // 2 + 1
        straight_a += 1.0 if len(r["sets"]) == need else 0.0
        straight_m += sum(p for (x, y), p in md.set_scores.items() if min(x, y) == 0)
        ln = 38.5 if r["best_of"] == 5 else line
        po = md.total_games.over_under_push(ln)[0]
        b = min(int(po * 10), 9)
        buckets.setdefault(b, [0, 0.0, 0.0])
        buckets[b][0] += 1
        buckets[b][1] += po
        buckets[b][2] += 1.0 if tg > ln else 0.0
    n = len(rs)
    return {"n": n, "mean_games": {"actual": round(act / n, 2), "model": round(mod / n, 2)},
            "loglik_per_match": {"model": round(ll / n, 4), "no_form": round(ll0 / n, 4)},
            "straight_sets": {"actual": round(straight_a / n, 3), "model": round(straight_m / n, 3)},
            "over_calibration": [{"predicted": round(v[1] / v[0], 3), "actual": round(v[2] / v[0], 3), "n": v[0]}
                                 for k, v in sorted(buckets.items()) if v[0] >= 30]}


# ---------------------------------------------------------------------------
# Surface-blended Elo
# ---------------------------------------------------------------------------

def name_key(name: str) -> str:
    """'Sinner J.' / 'Jannik Sinner' / 'Auger-Aliassime F.' -> comparable 'sinner j' style keys."""
    n = re.sub(r"\s+", " ", str(name).replace("-", " ").replace(".", " ").strip()).lower()
    parts = n.split(" ")
    if len(parts) >= 2 and len(parts[-1]) <= 2:            # 'sinner j' / 'zhang zh' (tennis-data style)
        return " ".join(parts[:-1]) + " " + parts[-1][0]
    if len(parts) >= 2:                                      # 'jannik sinner' (full name)
        return " ".join(parts[1:]) + " " + parts[0][0]
    return n


@dataclass
class EloParams:
    k_scale: float = 150.0       # K = k_scale / (matches + 5) ** k_power  (538-style; tuned on 2021-22)
    k_power: float = 0.4
    surface_weight: float = 0.3  # blend of surface-specific and overall rating
    slam_boost: float = 1.1      # best-of-5 results move ratings a little more


class Elo:
    def __init__(self, params: Optional[EloParams] = None):
        self.p = params or EloParams()
        self.r: Dict[str, float] = {}
        self.rs: Dict[Tuple[str, str], float] = {}
        self.n: Dict[str, int] = {}
        self.ns: Dict[Tuple[str, str], int] = {}
        self.last: Dict[str, str] = {}

    def rating(self, player: str, surface: str) -> float:
        k = name_key(player)
        w = self.p.surface_weight
        return (1 - w) * self.r.get(k, 1500.0) + w * self.rs.get((k, surface), 1500.0)

    def prob(self, a: str, b: str, surface: str, best_of: int = 3) -> float:
        d = self.rating(a, surface) - self.rating(b, surface)
        p3 = 1.0 / (1.0 + 10 ** (-d / 400.0))
        if best_of == 5:                       # longer matches favour the stronger player
            return _bo5_from_bo3(p3)
        return p3

    def update(self, a: str, b: str, a_won: bool, surface: str, best_of: int = 3, date: str = "") -> None:
        ka, kb = name_key(a), name_key(b)
        pa = self.prob(a, b, surface, 3)
        s = 1.0 if a_won else 0.0
        boost = self.p.slam_boost if best_of == 5 else 1.0
        for key, sign in ((ka, 1), (kb, -1)):
            kf = self.p.k_scale / (self.n.get(key, 0) + 5) ** self.p.k_power * boost
            self.r[key] = self.r.get(key, 1500.0) + sign * kf * (s - pa)
            ks = self.p.k_scale / (self.ns.get((key, surface), 0) + 5) ** self.p.k_power * boost
            self.rs[(key, surface)] = self.rs.get((key, surface), 1500.0) + sign * ks * (s - pa)
            self.n[key] = self.n.get(key, 0) + 1
            self.ns[(key, surface)] = self.ns.get((key, surface), 0) + 1
            if date:
                self.last[key] = date

    def table(self, surface: Optional[str] = None, since: str = "", top: int = 30) -> List[dict]:
        rows = []
        for k, r in self.r.items():
            if since and self.last.get(k, "") < since:
                continue
            rows.append({"player": k, "elo": round(r, 1), "surface_elo": round(self.rs.get((k, surface), 1500.0), 1) if surface else None,
                         "blended": round((1 - self.p.surface_weight) * r + self.p.surface_weight * self.rs.get((k, surface), 1500.0), 1) if surface else round(r, 1),
                         "matches": self.n.get(k, 0), "last": self.last.get(k)})
        rows.sort(key=lambda x: -x["blended"])
        return rows[:top]


@lru_cache(maxsize=4096)
def _bo5_from_bo3(p3: float) -> float:
    """Map a best-of-3 win probability to best-of-5 through the point model (hard-court ATP level)."""
    s = DEFAULT_SERVE["atp"]["hard"]
    pa, pb = solve_serve(min(max(p3, 0.001), 0.999), s, 3, 7)
    return _p_match_fast(round(pa, 6), round(pb, 6), 5, 10)


def validate_elo(rows: Sequence[dict], test_from: str, params: Optional[EloParams] = None,
                 weights: Sequence[float] = (0.0, 0.1, 0.2, 0.3, 0.5, 1.0)) -> dict:
    """Walk-forward: rate every match before ``test_from``; then predict, score and update.

    Scores the Elo probability, the devigged bookmaker probability and logit
    blends of the two (``weights`` = Elo share) on completed test matches with odds.
    """
    elo = Elo(params)
    preds = []
    for r in rows:
        if r["winner"] is None:
            continue
        a_won = r["winner"] == 1
        if r["date"] >= test_from:
            pm = market_prob(r)
            if pm is not None:
                pe = elo.prob(r["p1"], r["p2"], r["surface"], r["best_of"])
                preds.append((pe, pm, 1.0 if a_won else 0.0))
        elo.update(r["p1"], r["p2"], a_won, r["surface"], r["best_of"], r["date"])

    def score(fn):
        ll = br = 0.0
        for pe, pm, y in preds:
            p = min(max(fn(pe, pm), 1e-6), 1 - 1e-6)
            ll -= y * math.log(p) + (1 - y) * math.log(1 - p)
            br += (p - y) ** 2
        n = len(preds)
        return {"log_loss": round(ll / n, 4), "brier": round(br / n, 4)}

    def lg(x):
        return math.log(x / (1 - x))
    out = {"n": len(preds), "test_from": test_from, "elo": score(lambda pe, pm: pe), "market": score(lambda pe, pm: pm)}
    def blend(pe, pm, w):
        z = w * lg(min(max(pe, 1e-6), 1 - 1e-6)) + (1 - w) * lg(pm)
        return 1 / (1 + math.exp(-z))
    out["blends"] = {f"{w:.1f}": score(lambda pe, pm, w=w: blend(pe, pm, w)) for w in weights}
    return out
