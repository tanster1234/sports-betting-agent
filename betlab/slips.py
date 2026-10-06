"""Check bet slips together: shared exposure across tickets and whether a ticket's legs tell one story.

Two questions a parlay bettor should ask before placing a second ticket, and that the price of
each leg alone can't answer:

1. **Exposure** — do my tickets share a leg, a player or a game?  The same leg on two tickets
   means one miss sinks both; two tickets on one game ride on one game script.
2. **One story** — do the legs of a ticket need the same game to happen?  A running back's
   rushing yards need his team ahead; the other team's running back needs the opposite.

Legs are tied together through the game script — how far each team beats the spread and how far
the game beats the total — plus what is left between the same player's stats, teammates and
opponents.  For NFL (and college football, by assumption) these numbers are measured from
nflverse player stats 2021-25 (``data/nfl/leg_correlations.json``, rebuilt by
``scripts/refresh_nfl_leg_correlations.py``); game lines follow from the definitions; basketball
props use stated assumptions until they're measured.  Tickets are then simulated jointly
(Gaussian copula) to give each ticket's chance of cashing *given the others*, the chance that
none cash, and the spread of outcomes.

Leg format is the bet tracker's: ``{"pick", "fairProb" (or "p"), "price", "spec": {"event",
"league", "market": ml|spread|total|team_total|player|f5_ml|f5_total|nrfi, "team" (abbr, for
game legs), "side" (over/under/home/away), "line", "player", "stat"}}``.  ``spec`` may also carry
``team_side`` (home/away) and ``position`` (QB/RB/WR/TE) — otherwise :func:`resolve` looks them
up from ESPN.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from statistics import NormalDist
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .odds import american_to_decimal, american_to_prob

ND = NormalDist()
NFL_STATS = {"passYards": "pass_yds", "passTDs": "pass_yds", "rushYards": "rush_yds", "receptions": "receptions",
             "recYards": "rec_yds", "anytimeTD": "td"}
DEFAULT_POS = {"pass_yds": "QB", "rush_yds": "RB", "receptions": "WR", "rec_yds": "WR", "td": "RB"}
FOOTBALL = ("nfl", "ncaaf", "college-football")
BASKETBALL = ("wnba", "nba", "ncaab", "wncaab")
# Assumed (not yet measured) basketball prop links: scoring props rise with the total, a little
# less in blowouts (starters sit); the same player's stats move together; teammates share shots.
BASKETBALL_LOAD = {"points": (0.0, 0.30), "rebounds": (0.0, 0.15), "assists": (0.0, 0.20), "threes": (0.0, 0.25)}
BASKETBALL_SAME_PLAYER = 0.30
BASKETBALL_TEAMMATE = -0.08
TEAM_TOTAL_LOAD = (0.70, 0.71)          # team points vs (margin, total) surprises, from the definitions
PERIOD_LOAD = 0.75                      # F5 result/total vs the full game (assumed)
NRFI_TOTAL_LOAD = -0.40                 # a scoreless 1st vs the full-game total (assumed)
STORY, CONFLICT = 0.15, -0.10           # pair verdict thresholds (latent correlation)


@lru_cache(maxsize=1)
def football_model(path: Optional[str] = None) -> dict:
    p = Path(path) if path else Path(__file__).resolve().parent.parent / "data" / "nfl" / "leg_correlations.json"
    if not p.exists():
        return {"loadings": {}, "pairs": {"same_player": {}, "teammate": {}, "opponent": {}}}
    return json.loads(p.read_text())


def ticket_label(t: dict) -> str:
    """'the DraftKings Boosted SGP' — how a person refers to a ticket (falls back to its id)."""
    if t.get("label"):
        return str(t["label"])
    parts = [x for x in (t.get("book"), t.get("tier") or t.get("type")) if x]
    return "the " + " ".join(parts) if parts else str(t.get("id"))


def name_key(name: str) -> str:
    from .live import player_name_key
    return player_name_key(name)


# ---------------------------------------------------------------------------
# Legs
# ---------------------------------------------------------------------------

@dataclass
class Leg:
    ticket: str
    index: int
    pick: str
    p: float
    p_source: str
    price: Optional[float]
    result: Optional[str]
    event: Optional[str]
    league: str
    market: str
    sign: int                    # +1 for over / yes / the named team, -1 for under
    team: Optional[str] = None   # team abbreviation the leg is about (game legs, player's team)
    team_side: Optional[str] = None
    player: Optional[str] = None
    stat: Optional[str] = None
    position: Optional[str] = None
    line: Optional[float] = None
    home: Optional[str] = None
    away: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.ticket}#{self.index}"

    @property
    def identity(self) -> tuple:
        """Two legs with the same identity are the same bet."""
        who = name_key(self.player) if self.player else (self.team or self.team_side)
        return (self.event, self.market, who, self.stat, self.sign, self.line)

    @property
    def is_player(self) -> bool:
        return self.market == "player"

    def short(self) -> str:
        return self.pick or f"{self.player or self.team} {self.stat or self.market}"


def _leg_prob(leg: dict) -> Tuple[float, str]:
    for k in ("p", "fairProb", "fair_prob"):
        if leg.get(k) is not None:
            return float(leg[k]), "fair"
    price = leg.get("price")
    if price is None:
        return 0.5, "unknown"
    p = american_to_prob(float(price))
    haircut = 0.90 if (leg.get("spec") or {}).get("stat") == "anytimeTD" else 0.955
    return p * haircut, "price"


def legs_of(ticket: dict) -> List[Leg]:
    out = []
    tid = str(ticket.get("id") or ticket.get("doc_id") or ticket.get("label") or "ticket")
    for i, raw in enumerate(ticket.get("legs", [])):
        spec = raw.get("spec") or {}
        p, src = _leg_prob(raw)
        market = spec.get("market") or "other"
        side = str(spec.get("side") or "").lower()
        sign = -1 if side in ("under", "no") else 1
        if market == "nrfi" and side == "yrfi":
            sign = -1
        leg = Leg(ticket=tid, index=i, pick=raw.get("pick", ""), p=min(max(p, 1e-4), 1 - 1e-4), p_source=src,
                  price=raw.get("price"), result=raw.get("result"), event=str(spec["event"]) if spec.get("event") else None,
                  league=str(spec.get("league") or "").lower(), market=market, sign=sign,
                  team=spec.get("team"), team_side=spec.get("team_side"), player=spec.get("player"),
                  stat=spec.get("stat"), position=spec.get("position"), line=spec.get("line"),
                  home=spec.get("home"), away=spec.get("away"))
        if market in ("ml", "spread", "f5_ml", "f5_runline") and side in ("home", "away") and not leg.team_side:
            leg.team_side = side
        out.append(leg)
    return out


# ---------------------------------------------------------------------------
# Game-script loadings and pair correlations
# ---------------------------------------------------------------------------

def _side_sign(leg: Leg) -> Optional[int]:
    if leg.team_side in ("home", "away"):
        return 1 if leg.team_side == "home" else -1
    if leg.team and leg.home and leg.team == leg.home:
        return 1
    if leg.team and leg.away and leg.team == leg.away:
        return -1
    return None


def loadings(leg: Leg, model: Optional[dict] = None) -> Tuple[float, float, str]:
    """(load on the home team beating the spread, load on the game beating the total, source)."""
    model = model or football_model()
    s = _side_sign(leg)
    m = leg.market
    if m in ("ml", "spread", "runline", "f5_ml", "f5_runline"):
        w = PERIOD_LOAD if m.startswith("f5") else 1.0
        return ((s or 0) * w, 0.0, "definition" if s else "unknown team")
    if m in ("total", "f5_total"):
        w = PERIOD_LOAD if m == "f5_total" else 1.0
        return (0.0, leg.sign * w, "definition")
    if m == "nrfi":
        return (0.0, leg.sign * NRFI_TOTAL_LOAD, "assumed")
    if m == "team_total":
        return ((s or 0) * TEAM_TOTAL_LOAD[0] * leg.sign, TEAM_TOTAL_LOAD[1] * leg.sign, "definition")
    if m == "player":
        if leg.league in FOOTBALL and leg.stat in NFL_STATS:
            key = f"{NFL_STATS[leg.stat]}/{leg.position or DEFAULT_POS[NFL_STATS[leg.stat]]}"
            lo = model["loadings"].get(key)
            if lo:
                src = "measured (NFL 2021-25)" if leg.league == "nfl" else "NFL numbers (assumed for college)"
                return ((s or 0) * lo["margin"] * leg.sign, lo["total"] * leg.sign, src)
        if leg.league in BASKETBALL and leg.stat in BASKETBALL_LOAD:
            lm, lt = BASKETBALL_LOAD[leg.stat]
            return ((s or 0) * lm * leg.sign, lt * leg.sign, "assumed")
    return (0.0, 0.0, "not modelled")


def pair_corr(a: Leg, b: Leg, model: Optional[dict] = None) -> Tuple[float, str]:
    """Latent correlation between two legs (positive = they tend to win together) and its basis."""
    model = model or football_model()
    if a.identity == b.identity:
        return 1.0, "same bet"
    if not a.event or a.event != b.event:
        return 0.0, "different games"
    if a.is_player and b.is_player and a.player and b.player and name_key(a.player) == name_key(b.player) \
            and a.stat == b.stat:
        return float(a.sign * b.sign), "same player and stat (different line)"
    if a.market == b.market and not a.is_player and a.market in ("ml", "spread", "total", "runline") \
            and _side_sign(a) == _side_sign(b):
        return float(a.sign * b.sign) * 0.95, "same market, different line"
    ma, ta, _ = loadings(a, model)
    mb, tb, _ = loadings(b, model)
    r = ma * mb + ta * tb
    basis = "game script"
    if a.is_player and b.is_player and a.player and b.player:
        if a.league in FOOTBALL and a.stat in NFL_STATS and b.stat in NFL_STATS:
            ka = f"{NFL_STATS[a.stat]}/{a.position or DEFAULT_POS[NFL_STATS[a.stat]]}"
            kb = f"{NFL_STATS[b.stat]}/{b.position or DEFAULT_POS[NFL_STATS[b.stat]]}"
            same = name_key(a.player) == name_key(b.player)
            sa, sb = _side_sign(a), _side_sign(b)
            rel = "same_player" if same else ("teammate" if sa and sb and sa == sb else "opponent" if sa and sb else None)
            if rel:
                k1, k2 = sorted((ka, kb))
                hit = model["pairs"].get(rel, {}).get(f"{k1}|{k2}")
                if hit:
                    r += hit["beyond_script"] * a.sign * b.sign
                    basis = f"game script + {rel.replace('_', ' ')} (measured)"
        elif a.league in BASKETBALL:
            same = name_key(a.player) == name_key(b.player)
            if same:
                r += BASKETBALL_SAME_PLAYER * a.sign * b.sign
                basis = "same player (assumed)"
            elif _side_sign(a) and _side_sign(a) == _side_sign(b):
                r += BASKETBALL_TEAMMATE * a.sign * b.sign
                basis = "teammates share shots (assumed)"
    return max(-0.95, min(0.95, r)), basis


def _needs(leg: Leg, model: Optional[dict] = None) -> str:
    """What game this leg wants, in plain words."""
    m, t, _ = loadings(leg, model)
    team = leg.home if m > 0 else leg.away
    parts = []
    if abs(m) >= 0.1 and team:
        parts.append(f"{team} playing well (beating the spread)")
    elif abs(m) >= 0.1:
        parts.append("its team playing well" if m * (_side_sign(leg) or 1) > 0 else "its team trailing")
    if abs(t) >= 0.1:
        parts.append("a high-scoring game" if t > 0 else "a low-scoring game")
    return " and ".join(parts) or "not much from the score"


# ---------------------------------------------------------------------------
# Joint simulation
# ---------------------------------------------------------------------------

def _cholesky_psd(c: List[List[float]]) -> List[List[float]]:
    """Cholesky factor, shrinking off-diagonals until the matrix is positive definite."""
    n = len(c)
    shrink = 1.0
    for _ in range(60):
        m = [[c[i][j] * (shrink if i != j else 1.0) for j in range(n)] for i in range(n)]
        L = [[0.0] * n for _ in range(n)]
        ok = True
        for i in range(n):
            for j in range(i + 1):
                s = sum(L[i][k] * L[j][k] for k in range(j))
                if i == j:
                    v = m[i][i] - s
                    if v <= 1e-9:
                        ok = False
                        break
                    L[i][j] = math.sqrt(v)
                else:
                    L[i][j] = (m[i][j] - s) / L[j][j]
            if not ok:
                break
        if ok:
            return L
        shrink *= 0.95
    raise ValueError("could not build a valid correlation matrix")


def simulate(tickets: Sequence[dict], legs: Dict[str, List[Leg]], n: int = 40000, seed: int = 11,
             model: Optional[dict] = None) -> dict:
    """Joint outcome of all tickets.  Settled legs count as won/lost; voided legs drop out."""
    model = model or football_model()
    # Legs on the same underlying quantity share one latent variable (with a direction), so nested and
    # mutually exclusive legs come out exactly: ML/spread/run line on a game's margin, over/under on its
    # total, a player's stat at any line.
    groups: List[Leg] = []
    gindex: Dict[tuple, int] = {}
    leg_ref: Dict[tuple, Tuple[int, int]] = {}            # leg identity -> (group, direction)

    def group_key(x: Leg):
        if not x.event:
            return None
        if x.market in ("ml", "spread", "runline") and _side_sign(x):
            return (x.event, "margin")
        if x.market in ("f5_ml", "f5_runline") and _side_sign(x):
            return (x.event, "f5_margin")
        if x.market in ("total", "f5_total", "nrfi"):
            return (x.event, x.market)
        if x.is_player and x.player and x.stat:
            return (x.event, "player", name_key(x.player), x.stat)
        return None

    def direction(x: Leg) -> int:
        return (_side_sign(x) or 1) if x.market in ("ml", "spread", "runline", "f5_ml", "f5_runline") else x.sign

    for ls in legs.values():
        for leg in ls:
            if leg.identity in leg_ref:
                continue
            gk = group_key(leg) or ("leg",) + leg.identity
            if gk not in gindex:
                gindex[gk] = len(groups)
                groups.append(leg)
            rep = groups[gindex[gk]]
            leg_ref[leg.identity] = (gindex[gk], direction(leg) * direction(rep))
    k = len(groups)
    corr = [[1.0 if i == j else pair_corr(groups[i], groups[j], model)[0] for j in range(k)] for i in range(k)]
    L = _cholesky_psd(corr) if k else []

    def p_eff(leg):
        return 1.0 if leg.result == "won" else 0.0 if leg.result == "lost" else leg.p
    uniq = list({x.identity: x for ls in legs.values() for x in ls}.values())
    index = {x.identity: i for i, x in enumerate(uniq)}
    thr = [ND.inv_cdf(min(max(p_eff(x), 1e-9), 1 - 1e-9)) for x in uniq]
    ref = [leg_ref[x.identity] for x in uniq]
    t_legs = {tid: [index[x.identity] for x in ls if x.result not in ("void", "push")] for tid, ls in legs.items()}
    stake = {str(t.get("id")): float(t.get("stake") or 0) for t in tickets}
    dec = {}
    for t in tickets:
        tid = str(t.get("id"))
        odds = t.get("odds") if t.get("odds") is not None else t.get("price")
        if odds is not None:
            dec[tid] = american_to_decimal(float(odds))
        else:
            d = 1.0
            for x in legs[tid]:
                d *= american_to_decimal(float(x.price)) if x.price is not None else 1 / x.p
            dec[tid] = d
    rng = random.Random(seed)
    cash = {tid: 0 for tid in legs}
    n_cash = [0] * (len(legs) + 1)
    profits = []
    for _ in range(n):
        z = [rng.gauss(0, 1) for _ in range(k)]
        y = [sum(L[i][j] * z[j] for j in range(i + 1)) for i in range(k)]
        hit = [y[g] * d < t for (g, d), t in zip(ref, thr)]
        c = 0
        pr = 0.0
        for tid, ix in t_legs.items():
            ok = all(hit[i] for i in ix)
            if ok:
                cash[tid] += 1
                c += 1
                pr += stake.get(tid, 0) * (dec[tid] - 1)
            else:
                pr -= stake.get(tid, 0)
        n_cash[c] += 1
        profits.append(pr)
    profits.sort()
    out_t = []
    for tid, ix in t_legs.items():
        indep = 1.0
        for i in ix:
            indep *= ND.cdf(thr[i])
        out_t.append({"ticket": tid, "p_cash": round(cash[tid] / n, 4), "p_cash_if_independent": round(indep, 4),
                      "stake": stake.get(tid, 0), "decimal": round(dec[tid], 3),
                      "ev_per_dollar": round(cash[tid] / n * dec[tid] - 1, 3)})
    p_none_indep = 1.0
    for t in out_t:
        p_none_indep *= 1 - t["p_cash_if_independent"]
    return {"tickets": out_t, "p_none_cash": round(n_cash[0] / n, 4), "p_none_cash_if_independent": round(p_none_indep, 4),
            "p_all_cash": round(n_cash[-1] / n, 4) if len(n_cash) > 1 else None,
            "tickets_cashing": {str(i): round(c / n, 4) for i, c in enumerate(n_cash)},
            "profit": {"expected": round(sum(profits) / n, 2), "p05": round(profits[int(0.05 * n)], 2),
                       "median": round(profits[n // 2], 2), "p95": round(profits[int(0.95 * n) - 1], 2),
                       "max_loss": round(-sum(stake.values()), 2)},
            "sims": n}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def coherence(legs: Sequence[Leg], model: Optional[dict] = None) -> dict:
    """Do the legs of one ticket need the same game?"""
    pairs = []
    for i in range(len(legs)):
        for j in range(i + 1, len(legs)):
            a, b = legs[i], legs[j]
            if not a.event or a.event != b.event:
                continue
            r, basis = pair_corr(a, b, model)
            verdict = "same story" if r >= STORY else "pull against each other" if r <= CONFLICT else "mostly independent"
            pairs.append({"legs": [a.short(), b.short()], "corr": round(r, 3), "verdict": verdict, "basis": basis,
                          "needs": [_needs(a, model), _needs(b, model)]})
    conflicts = [p for p in pairs if p["verdict"] == "pull against each other"]
    story = [p for p in pairs if p["verdict"] == "same story"]
    verdict = ("conflicting" if conflicts else "one story" if story else
               "independent legs" if not pairs else "mostly independent")
    return {"verdict": verdict, "pairs": pairs}


def exposure(legs: Dict[str, List[Leg]], tickets: Sequence[dict], model: Optional[dict] = None) -> List[dict]:
    """Legs, players and games that more than one ticket depends on."""
    out = []
    ids = list(legs)
    stake = {str(t.get("id")): float(t.get("stake") or 0) for t in tickets}
    lab = {str(t.get("id")): ticket_label(t) for t in tickets}
    if len(set(lab.values())) < len(lab):                    # two tickets with the same name: add the id
        lab = {k: f"{v} ({k})" for k, v in lab.items()}
    seen_pairs = set()
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            A, B = legs[ids[x]], legs[ids[y]]
            for a in A:
                for b in B:
                    if a.result in ("won", "void") or b.result in ("won", "void"):
                        continue
                    key = (a.identity, b.identity, ids[x], ids[y])
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    if a.identity == b.identity:
                        out.append({"type": "same leg", "tickets": [ids[x], ids[y]], "legs": [a.short()],
                                    "note": f"{a.short()} is on both {lab[ids[x]]} and {lab[ids[y]]}: if it misses, both tickets lose"})
                    elif a.player and b.player and name_key(a.player) == name_key(b.player):
                        r, _ = pair_corr(a, b, model)
                        how = ("the same stat at different lines, so a quiet game sinks both" if a.stat == b.stat else
                               "they win or lose together" if r >= 0.5 else
                               "different stats that barely move together, but an injury or benching sinks both")
                        out.append({"type": "same player", "tickets": [ids[x], ids[y]], "legs": [a.short(), b.short()],
                                    "corr": round(r, 3),
                                    "note": f"{a.player} is on both {lab[ids[x]]} ({a.short()}) and {lab[ids[y]]} ({b.short()}): {how}"})
                    elif a.is_player is False and b.is_player is False and a.event == b.event and a.event and \
                            a.market == b.market and _side_sign(a) and _side_sign(a) == -(_side_sign(b) or 0):
                        out.append({"type": "opposite sides", "tickets": [ids[x], ids[y]], "legs": [a.short(), b.short()],
                                    "note": f"{a.short()} ({lab[ids[x]]}) and {b.short()} ({lab[ids[y]]}) take opposite sides: "
                                            "one ticket needs the other to lose"})
    games: Dict[str, set] = {}
    names: Dict[str, str] = {}
    for tid, ls in legs.items():
        for leg in ls:
            if leg.event and leg.result not in ("won", "void"):
                games.setdefault(leg.event, set()).add(tid)
                if leg.home and leg.away:
                    names[leg.event] = f"{leg.away} @ {leg.home}"
    for ev, tids in games.items():
        if len(tids) > 1:
            at_risk = sum(stake.get(t, 0) for t in tids)
            out.append({"type": "same game", "tickets": sorted(tids), "game": names.get(ev, ev), "stake_at_risk": at_risk,
                        "note": f"{len(tids)} tickets (${at_risk:g} staked) ride on {names.get(ev, 'game ' + ev)}"})
    return out


def check(tickets: Sequence[dict], resolver: Optional[Callable[[List[Leg]], None]] = None, sims: int = 40000,
          model: Optional[dict] = None) -> dict:
    """Full report for a set of tickets (open ones already placed + any proposed)."""
    model = model or football_model()
    tickets = [dict(t, id=str(t.get("id") or f"ticket{i + 1}")) for i, t in enumerate(tickets)]
    legs = {t["id"]: legs_of(t) for t in tickets}
    if resolver:
        resolver([leg for ls in legs.values() for leg in ls])
    per = []
    for t in tickets:
        ls = legs[t["id"]]
        coh = coherence(ls, model)
        weakest = min((x for x in ls if x.result not in ("won", "void")), key=lambda x: x.p, default=None)
        per.append({"ticket": t["id"], "book": t.get("book"), "legs": [
            {"pick": x.short(), "p": round(x.p, 3), "p_source": x.p_source, "result": x.result,
             "team": x.team, "position": x.position, "needs": _needs(x, model),
             "script_basis": loadings(x, model)[2]} for x in ls],
            "one_story": coh, "weakest_leg": weakest.short() if weakest else None})
    sim = simulate(tickets, legs, sims, model=model)
    by_t = {s["ticket"]: s for s in sim["tickets"]}
    for p in per:
        p.update({k: by_t[p["ticket"]][k] for k in ("p_cash", "p_cash_if_independent", "ev_per_dollar")})
    ex = exposure(legs, tickets, model)
    notes = []
    labels = {t["id"]: ticket_label(t) for t in tickets}
    for p in per:
        p["label"] = labels[p["ticket"]]
        for pr in p["one_story"]["pairs"]:
            if pr["verdict"] == "pull against each other":
                notes.append(f"{labels[p['ticket']][0].upper() + labels[p['ticket']][1:]}: {pr['legs'][0]} wants {pr['needs'][0]}; {pr['legs'][1]} wants "
                             f"{pr['needs'][1]} — they pull against each other.")
    for e in ex:
        if e["type"] in ("same leg", "same player", "opposite sides"):
            notes.append(e["note"] + ".")
    if len(tickets) > 1:
        notes.append(f"Chance no ticket cashes: {sim['p_none_cash']:.0%} "
                     f"(would be {sim['p_none_cash_if_independent']:.0%} if they were unrelated).")
    unresolved = sorted({x.short() for ls in legs.values() for x in ls
                         if (x.is_player and (not x.team_side and not (x.team and x.home)))
                         or (x.market in ("ml", "spread") and _side_sign(x) is None)})
    return {"tickets": per, "exposure": ex, "joint": sim, "notes": notes, "unresolved_team": unresolved,
            "model": {"football": f"measured from nflverse player stats {model.get('seasons', '?')}",
                      "basketball": "assumed links (not measured yet)",
                      "unmodelled": "other markets are treated as unrelated"}}


# ---------------------------------------------------------------------------
# Resolving teams and positions from ESPN
# ---------------------------------------------------------------------------

def espn_resolver(fetch: Optional[Callable[[str], dict]] = None) -> Callable[[List[Leg]], None]:
    """Fill home/away teams, each game leg's side, and each player's team and position."""
    from .fetch import espn
    from .fetch import fetch_json as _fj

    def get(url):
        return fetch(url) if fetch else _fj(url)[0]
    cache: Dict[str, dict] = {}

    def game(league, event):
        key = f"{league}:{event}"
        if key in cache:
            return cache[key]
        js = get(espn.summary_url(league, event))
        comp = js["header"]["competitions"][0]
        teams = {c["homeAway"]: {"abbr": c["team"]["abbreviation"], "id": c["team"]["id"]} for c in comp["competitors"]}
        players: Dict[str, Tuple[str, Optional[str]]] = {}
        side_of = {teams[s]["abbr"]: s for s in teams}
        for t in (js.get("boxscore") or {}).get("players", []) or []:
            s = side_of.get(t["team"]["abbreviation"])
            for cat in t.get("statistics", []):
                for a in cat.get("athletes", []):
                    players.setdefault(name_key(a["athlete"]["displayName"]), (s, None))
        sport = espn.LEAGUES[league][0] if league in espn.LEAGUES else "football"
        lg = espn.LEAGUES[league][1] if league in espn.LEAGUES else league
        for s, t in teams.items():
            try:
                ros = get(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{lg}/teams/{t['id']}/roster")
            except Exception:  # noqa: BLE001 - positions are optional
                continue
            groups = ros.get("athletes", [])
            items = [a for g in groups for a in (g.get("items", []) if isinstance(g, dict) and "items" in g else [g])]
            for a in items:
                pos = (a.get("position") or {}).get("abbreviation")
                k = name_key(a.get("displayName", ""))
                if k in players:
                    players[k] = (players[k][0], pos)
                else:
                    players.setdefault(k, (s, pos))
        cache[key] = {"teams": teams, "players": players}
        return cache[key]

    def resolve(legs: List[Leg]) -> None:
        for leg in legs:
            if not leg.event or not leg.league:
                continue
            try:
                g = game(leg.league, leg.event)
            except Exception as exc:  # noqa: BLE001 - leave the leg unresolved, say why
                leg.notes.append(f"couldn't look up the game: {exc}")
                continue
            leg.home = leg.home or g["teams"]["home"]["abbr"]
            leg.away = leg.away or g["teams"]["away"]["abbr"]
            if leg.is_player and leg.player:
                side, pos = g["players"].get(name_key(leg.player), (None, None))
                leg.team_side = leg.team_side or side
                leg.position = leg.position or (pos if pos in ("QB", "RB", "WR", "TE") else None)
                if side and not leg.team:
                    leg.team = g["teams"][side]["abbr"]
    return resolve
