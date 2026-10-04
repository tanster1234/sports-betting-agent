"""Live ("in-game") read for basketball: play-by-play facts plus a fair price.

Two halves, kept apart on purpose:

* **Facts from the play-by-play** (``game_facts``): score and clock, scoring
  runs, lead changes, foul trouble, who is on the floor, shooting against a
  typical rate, turnovers, technicals/flagrants/ejections.  These are the
  things a score alone hides.  They are context; none of them feeds the price.
* **A fair price** (``live_price``): the final margin and total given the
  pregame market line, the current score and the time left.  Fitted on WNBA
  halftime scores 2023-2026 (1,175 games; ``validate_halftime``): the second
  half adds ~0.48 x the pregame margin, a halftime lead *partly reverses*
  (-0.15 x the lead, 95% CI -0.21 to -0.09, the same sign in every season) and
  the second-half total is the pregame half-total plus only ~0.1 x the first
  half's pace surprise.  Other game times scale those halftime numbers with
  the time left (an assumption, flagged in the output); NBA reuses the WNBA
  shape with NBA spreads (not fitted).

``live_read`` combines both with optional book prices and a sharp live price
(devigged) so the comparison is "book vs sharp, with the model as a sanity
check" — live markets see the game first, so a model that disagrees with the
sharp price by a lot is missing something, not finding an edge.
"""

from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Sequence

from .distributions import DiscreteDist, discretized_normal, mixture
from .markets import MarginModel, sport_params
from .odds import american_to_decimal, decimal_to_american, devig_american

# Clock and reference shooting rates.  The 3PT / FT references are rough league
# averages used only to describe shooting luck, never to price.
CLOCK: Dict[str, dict] = {
    "WNBA": {"periods": 4, "period_s": 600, "ot_s": 300, "foul_out": 6, "three_ref": 0.34, "ft_ref": 0.80},
    "NBA": {"periods": 4, "period_s": 720, "ot_s": 300, "foul_out": 6, "three_ref": 0.36, "ft_ref": 0.78},
}

# Halftime fit (``validate_halftime`` on 2023-2026 WNBA; 2023-25 against the
# bundled model's pregame line, 2026 against DraftKings closes).  Second half:
#   margin = mu_share * pregame_margin + reversion * halftime_lead   (sd half_sd)
#   total  = pregame_total / 2 + total_offset + pace_carry * (first_half_total - pregame_total / 2)   (sd half_total_sd)
LIVE_PARAMS: Dict[str, dict] = {
    "WNBA": {"mu_share": 0.484, "reversion": -0.150, "half_sd": 9.54, "total_offset": -0.10,
             "pace_carry": 0.106, "half_total_sd": 12.43, "fitted": True},
    # NBA: the WNBA shape with sds scaled by the NBA full-game margin/total sigma (not fitted on NBA data)
    "NBA": {"mu_share": 0.5, "reversion": -0.150, "half_sd": round(9.54 * 12.0 / 12.69, 2), "total_offset": 0.0,
            "pace_carry": 0.106, "half_total_sd": round(12.43 * 18.0 / 18.63, 2), "fitted": False},
}

FOUL_TROUBLE_TEXT = ("technical", "flagrant", "ejected", "injur")


def _sport(sport: str) -> str:
    key = sport.upper()
    if key not in CLOCK:
        raise ValueError(f"live read supports {sorted(CLOCK)}, not {sport!r}")
    return key


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def clock_seconds(display) -> float:
    """'8:13' -> 493.0, '45.2' -> 45.2, None/'' -> 0."""
    if display in (None, ""):
        return 0.0
    s = str(display).strip()
    if ":" in s:
        m, sec = s.split(":", 1)
        return int(m) * 60 + float(sec)
    return float(s)


def time_left(period: int, clock_s: float, sport: str = "WNBA") -> dict:
    """Seconds left in regulation (or in the current overtime) and the regulation fraction left."""
    c = CLOCK[_sport(sport)]
    reg = c["periods"] * c["period_s"]
    period = max(int(period or 0), 1)
    if period <= c["periods"]:
        left = (c["periods"] - period) * c["period_s"] + max(float(clock_s), 0.0)
        return {"in_ot": False, "seconds_left": left, "frac_left": left / reg, "regulation_s": reg}
    return {"in_ot": True, "seconds_left": max(float(clock_s), 0.0), "frac_left": max(float(clock_s), 0.0) / reg,
            "regulation_s": reg}


def _period_label(period: int, sport: str) -> str:
    n = CLOCK[_sport(sport)]["periods"]
    if period > n:
        return f"OT{period - n if period - n > 1 else ''}"
    return f"Q{period}"


# ---------------------------------------------------------------------------
# Parsing the ESPN summary
# ---------------------------------------------------------------------------

def _num(x) -> Optional[float]:
    try:
        return float(str(x).replace("+", ""))
    except (TypeError, ValueError):
        return None


def _made_att(x) -> tuple:
    try:
        a, b = str(x).split("-")
        return int(a), int(b)
    except (TypeError, ValueError):
        return 0, 0


def parse_game(js: dict, sport: str = "WNBA") -> dict:
    """Normalise an ESPN basketball summary (live or final) into plays, players and team stats."""
    from .fetch.espn import parse_odds_block  # local import keeps liveread free of network code at import time

    sport = _sport(sport)
    comp = ((js.get("header") or {}).get("competitions") or [{}])[0]
    side, names, ids = {}, {}, {}
    for c in comp.get("competitors", []):
        ab = (c.get("team") or {}).get("abbreviation")
        side[c.get("homeAway")] = ab
        names[ab] = (c.get("team") or {}).get("displayName") or ab
        ids[str((c.get("team") or {}).get("id"))] = ab
    st = comp.get("status") or {}
    plays = []
    period_s = CLOCK[sport]["period_s"]
    ot_s = CLOCK[sport]["ot_s"]
    nper = CLOCK[sport]["periods"]
    for p in js.get("plays") or []:
        per = int((p.get("period") or {}).get("number") or 0)
        clk = clock_seconds((p.get("clock") or {}).get("displayValue"))
        if per <= nper:
            elapsed = (per - 1) * period_s + (period_s - clk)
        else:
            elapsed = nper * period_s + (per - nper - 1) * ot_s + (ot_s - clk)
        plays.append({"period": per, "clock": (p.get("clock") or {}).get("displayValue"), "elapsed_s": elapsed,
                      "home": int(p.get("homeScore") or 0), "away": int(p.get("awayScore") or 0),
                      "team": ids.get(str((p.get("team") or {}).get("id"))), "text": p.get("text") or "",
                      "type": (p.get("type") or {}).get("text"), "scoring": bool(p.get("scoringPlay")),
                      "points": int(p.get("scoreValue") or 0)})
    players = []
    for t in (js.get("boxscore") or {}).get("players") or []:
        ab = (t.get("team") or {}).get("abbreviation")
        for grp in t.get("statistics") or []:
            keys = grp.get("keys") or grp.get("names") or []
            for a in grp.get("athletes") or []:
                s = dict(zip(keys, a.get("stats") or []))
                fg = _made_att(s.get("fieldGoalsMade-fieldGoalsAttempted"))
                players.append({"team": ab, "name": (a.get("athlete") or {}).get("displayName"),
                                "starter": bool(a.get("starter")), "dnp": bool(a.get("didNotPlay")),
                                "ejected": bool(a.get("ejected")), "minutes": _num(s.get("minutes")),
                                "points": _num(s.get("points")), "fouls": _num(s.get("fouls")), "fg": fg})
    teams = {}
    for t in (js.get("boxscore") or {}).get("teams") or []:
        ab = (t.get("team") or {}).get("abbreviation")
        stats = {s.get("name"): s.get("displayValue") for s in t.get("statistics") or []}
        teams[ab] = {"fg": _made_att(stats.get("fieldGoalsMade-fieldGoalsAttempted")),
                     "three": _made_att(stats.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted")),
                     "ft": _made_att(stats.get("freeThrowsMade-freeThrowsAttempted")),
                     "turnovers": _num(stats.get("totalTurnovers") or stats.get("turnovers")),
                     "off_reb": _num(stats.get("offensiveRebounds")), "reb": _num(stats.get("totalRebounds")),
                     "fouls": _num(stats.get("fouls"))}
    home, away = side.get("home"), side.get("away")
    score = {}
    for c in comp.get("competitors", []):
        score[c.get("homeAway")] = int(_num(c.get("score")) or 0)
    score = {"home": score.get("home", 0), "away": score.get("away", 0)}
    if plays and plays[-1]["home"] + plays[-1]["away"] > score["home"] + score["away"]:
        score = {"home": plays[-1]["home"], "away": plays[-1]["away"]}     # header can lag the play-by-play
    odds = [parse_odds_block(o) for o in (js.get("pickcenter") or js.get("odds") or [])]
    return {"sport": sport, "event_id": comp.get("id"), "home": home, "away": away, "names": names,
            "state": (st.get("type") or {}).get("state"), "status": (st.get("type") or {}).get("shortDetail"),
            "period": int(st.get("period") or 0), "clock": st.get("displayClock"),
            "score": score, "plays": plays, "players": players, "teams": teams, "odds": odds}


def pregame_line(game: dict) -> dict:
    """Pregame home spread and total from the summary's odds (closing line when given)."""
    for o in game.get("odds") or []:
        close = o.get("close") or {}
        spread = close.get("spread_home", o.get("home_spread"))
        total = close.get("total", o.get("total"))
        if spread is not None and total is not None:
            return {"home_spread": float(spread), "total": float(total), "source": o.get("provider") or "ESPN odds"}
    return {}


# ---------------------------------------------------------------------------
# Facts from the play-by-play
# ---------------------------------------------------------------------------

def scoring_runs(plays: Sequence[dict], home: str, away: str, min_run: int = 7, window_s: float = 300) -> dict:
    """Runs of unanswered points, lead changes, ties, largest leads and the last ``window_s`` seconds of scoring."""
    prev = (0, 0)
    run_team, run_pts, run_start = None, 0, None
    runs, lead_changes, ties = [], 0, 0
    leader = None
    largest = {home: 0, away: 0}
    events = []                       # (elapsed, team, points)
    for p in plays:
        h, a = p["home"], p["away"]
        if (h, a) == prev:
            continue
        dh, da = h - prev[0], a - prev[1]
        prev = (h, a)
        if dh < 0 or da < 0:          # score correction
            continue
        scorer = home if dh > 0 else away
        pts = dh + da
        events.append((p["elapsed_s"], scorer, pts))
        when = f"{p['period']}|{p['clock']}"
        if scorer == run_team:
            run_pts += pts
        else:
            if run_team and run_pts >= min_run:
                runs.append({"team": run_team, "points": run_pts, "from": run_start})
            run_team, run_pts, run_start = scorer, pts, when
        now = home if h > a else away if a > h else None
        if now is None:
            ties += 1
        elif leader is not None and now != leader:
            lead_changes += 1
        if now is not None:
            leader = now
        largest[home] = max(largest[home], h - a)
        largest[away] = max(largest[away], a - h)
    end = plays[-1]["elapsed_s"] if plays else 0.0
    recent = {home: 0, away: 0}
    for t, team, pts in events:
        if t >= end - window_s:
            recent[team] += pts
    current = {"team": run_team, "points": run_pts, "from": run_start} if run_team else None
    if current and run_pts >= min_run:
        runs.append({**current, "ongoing": True})
    return {"current_run": current, "runs": runs, "lead_changes": lead_changes, "ties": ties,
            "largest_lead": largest, "last_window": {"seconds": window_s, "points": recent}}


def foul_trouble(players: Sequence[dict], period: int, sport: str = "WNBA") -> List[dict]:
    """Players at or above the usual foul-trouble mark for the period (2 in Q1, 3 in Q2, 4 in Q3, 5 after)."""
    c = CLOCK[_sport(sport)]
    limit = min(c["foul_out"] - 1, max(int(period or 1), 1) + 1)
    out = []
    for p in players:
        f = p.get("fouls")
        if f is not None and f >= limit and not p.get("dnp"):
            out.append({"team": p["team"], "name": p["name"], "fouls": int(f), "minutes": p.get("minutes"),
                        "starter": p.get("starter"), "fouled_out": f >= c["foul_out"]})
    return sorted(out, key=lambda x: (-x["fouls"], not x["starter"]))


_SUB = re.compile(r"^(.+?) enters the game for (.+?)\s*$")


def on_floor(players: Sequence[dict], plays: Sequence[dict]) -> Dict[str, List[str]]:
    """Five per team: starters, then every 'X enters the game for Y' substitution."""
    floor: Dict[str, set] = {}
    team_of = {}
    for p in players:
        team_of[p["name"]] = p["team"]
        if p.get("starter"):
            floor.setdefault(p["team"], set()).add(p["name"])
    for pl in plays:
        m = _SUB.match(pl["text"])
        if not m:
            continue
        inn, out = m.group(1).strip(), m.group(2).strip()
        team = team_of.get(out) or team_of.get(inn) or pl.get("team")
        if team is None:
            continue
        floor.setdefault(team, set()).discard(out)
        floor[team].add(inn)
    return {k: sorted(v) for k, v in floor.items()}


def shooting(teams: Dict[str, dict], sport: str = "WNBA") -> Dict[str, dict]:
    """Shooting lines plus points above/below a typical shooter on threes and free throws."""
    c = CLOCK[_sport(sport)]
    out = {}
    for ab, t in teams.items():
        (fgm, fga), (tpm, tpa), (ftm, fta) = t["fg"], t["three"], t["ft"]
        out[ab] = {"fg": f"{fgm}-{fga}", "three": f"{tpm}-{tpa}", "ft": f"{ftm}-{fta}",
                   "three_pct": round(tpm / tpa, 3) if tpa else None, "ft_pct": round(ftm / fta, 3) if fta else None,
                   "three_pts_vs_typical": round(3 * (tpm - c["three_ref"] * tpa), 1),
                   "ft_pts_vs_typical": round(ftm - c["ft_ref"] * fta, 1),
                   "turnovers": t.get("turnovers"), "off_reb": t.get("off_reb"), "reb": t.get("reb")}
    return out


def flagged_plays(plays: Sequence[dict]) -> List[str]:
    return [f"{_p_lbl(p)} {p['text']}" for p in plays if any(w in p["text"].lower() for w in FOUL_TROUBLE_TEXT)]


def _p_lbl(p: dict) -> str:
    return f"P{p['period']} {p['clock']}"


def game_facts(game: dict) -> dict:
    home, away = game["home"], game["away"]
    return {"runs": scoring_runs(game["plays"], home, away),
            "foul_trouble": foul_trouble(game["players"], game["period"], game["sport"]),
            "on_floor": on_floor(game["players"], game["plays"]),
            "shooting": shooting(game["teams"], game["sport"]),
            "flags": flagged_plays(game["plays"])}


# ---------------------------------------------------------------------------
# Live price
# ---------------------------------------------------------------------------

def _shape(frac_left: float, sport: str) -> dict:
    """Second-half parameters scaled to the regulation time left (exact at halftime)."""
    p = LIVE_PARAMS[_sport(sport)]
    k = frac_left / 0.5
    return {"mu_share": p["mu_share"] * k, "reversion": p["reversion"] * k,
            "sd": p["half_sd"] * math.sqrt(k), "total_offset": p["total_offset"] * k,
            "pace_carry": p["pace_carry"] * k, "total_sd": p["half_total_sd"] * math.sqrt(k)}


def live_price(pre_home_spread: float, pre_total: Optional[float], home_score: int, away_score: int,
               period: int, clock_s: float, sport: str = "WNBA") -> dict:
    """Fair final-margin and final-total distributions from the pregame line, the score and the clock."""
    sport = _sport(sport)
    sp = sport_params(sport)
    c = CLOCK[sport]
    tl = time_left(period, clock_s, sport)
    mu = -float(pre_home_spread)
    lead = home_score - away_score
    points = home_score + away_score
    ot_frac = c["ot_s"] / tl["regulation_s"]
    ot_margin = discretized_normal(mu * ot_frac, max(sp["margin_sigma"] * math.sqrt(ot_frac), 0.5))
    nz = {k: p for k, p in ot_margin.pmf.items() if k != 0}
    s = sum(nz.values())
    ot_nz = {k: p / s for k, p in nz.items()}
    if tl["in_ot"]:                   # inside an overtime: plain time scaling, no halftime shape
        f = tl["seconds_left"] / tl["regulation_s"]
        rem_mu, rem_sd = mu * f, max(sp["margin_sigma"] * math.sqrt(max(f, 1e-6)), 0.05)
        t_mu = (pre_total or 0) * f
        t_sd = max(sp["total_sigma"] * math.sqrt(max(f, 1e-6)), 0.05)
        shape = None
    else:
        shape = _shape(tl["frac_left"], sport)
        rem_mu = shape["mu_share"] * mu + shape["reversion"] * lead
        rem_sd = max(shape["sd"], 0.05)
        if pre_total is not None:
            elapsed_share = 1.0 - tl["frac_left"]
            surprise = points - pre_total * elapsed_share
            t_mu = pre_total * tl["frac_left"] + shape["total_offset"] + shape["pace_carry"] * surprise
        else:
            t_mu = None
        t_sd = max(shape["total_sd"], 0.05)
    rem = DiscreteDist({0: 1.0}) if tl["seconds_left"] <= 0 else discretized_normal(rem_mu, rem_sd)
    pmf: Dict[int, float] = {}
    p_tie = 0.0
    for r, p in rem.pmf.items():
        k = lead + r
        if k == 0:
            p_tie += p
        else:
            pmf[k] = pmf.get(k, 0.0) + p
    for k, q in ot_nz.items():
        pmf[k] = pmf.get(k, 0.0) + p_tie * q
    margin = MarginModel.from_pmf(pmf)
    total = None
    if t_mu is not None:
        base = DiscreteDist({points: 1.0}) if tl["seconds_left"] <= 0 else discretized_normal(points + t_mu, t_sd)
        ot_pts = discretized_normal((pre_total or 0) * ot_frac, max(sp["total_sigma"] * math.sqrt(ot_frac), 0.5))
        total = mixture([(1 - p_tie, base), (p_tie, base.convolve(ot_pts))]) if p_tie > 0 else base
    p_home = margin.p_home_win()
    out = {"sport": sport, "fitted": LIVE_PARAMS[sport]["fitted"], "at_halftime_shape": shape is not None,
           "seconds_left": round(tl["seconds_left"], 1), "frac_left": round(tl["frac_left"], 4),
           "lead_home": lead, "points": points,
           "exp_final_margin": round(margin.mean(), 2), "margin_sd": round(margin.dist.sd(), 2),
           "fair_home_spread": round(-margin.dist.median_line(), 1),
           "p_home_win": round(p_home, 4), "p_overtime": round(p_tie, 4),
           "fair_ml_home": _fmt_am(p_home), "fair_ml_away": _fmt_am(1 - p_home),
           "naive_p_home_win": round(_naive_p_home(mu, lead, tl, sp), 4)}
    if total is not None:
        out.update({"exp_final_total": round(total.mean(), 1), "total_sd": round(total.sd(), 2),
                    "fair_total": total.median_line()})
    out["_margin"], out["_total"] = margin, total
    return out


def _naive_p_home(mu: float, lead: int, tl: dict, sp: dict) -> float:
    """Plain time scaling (pregame rate x time left, no reversion) — shown for contrast."""
    f = max(tl["frac_left"], 1e-6)
    d = discretized_normal(lead + mu * f, max(sp["margin_sigma"] * math.sqrt(f), 0.5))
    return sum(p for k, p in d.pmf.items() if k > 0) + 0.5 * d.prob(0)


def _fmt_am(p: float) -> Optional[str]:
    if p <= 0 or p >= 1:
        return None
    return f"{decimal_to_american(1 / p):+.0f}"


def price_offer(lp: dict, market: str, side: str, line: Optional[float], american: float) -> dict:
    """Fair probability and EV of a live offer, from a ``live_price`` result."""
    margin: MarginModel = lp["_margin"]
    if market == "ml":
        p_home = margin.p_home_win()
        p, push = (p_home if side == "home" else 1 - p_home), 0.0
    elif market == "spread":
        c, pu, f = margin.spread_probs(line) if side == "home" else margin.away_spread_probs(line)
        p, push = c, pu
    elif market == "total":
        dist: Optional[DiscreteDist] = lp["_total"]
        if dist is None:
            raise ValueError("a total offer needs the pregame total")
        o, u, pu = dist.over_under_push(line)
        p, push = (o if side == "over" else u), pu
    else:
        raise ValueError(f"unknown market {market!r}")
    dec = american_to_decimal(american)
    return {"market": market, "side": side, "line": line, "price": american, "p_win": round(p, 4),
            "p_push": round(push, 4), "ev_pct": round(100 * (p * (dec - 1) - (1 - p - push)), 2)}


def sharp_fair(market: str, side: str, sharp: dict) -> Optional[float]:
    """No-vig probability of ``side`` from a sharp live two-way price (same market and line)."""
    s = sharp.get(market)
    if not s:
        return None
    a, b = devig_american([s["first"], s["second"]])
    return a if side in ("home", "over") else b


# ---------------------------------------------------------------------------
# One call: facts + price + offers
# ---------------------------------------------------------------------------

def live_read(game: dict, pre_home_spread: Optional[float] = None, pre_total: Optional[float] = None,
              offers: Sequence[dict] = (), sharp: Optional[dict] = None, min_ev: float = 0.03,
              max_disagreement: float = 0.06) -> dict:
    """Full read of a parsed game: facts, fair price, notes, and each offer checked against model and sharp."""
    line = pregame_line(game)
    spread = pre_home_spread if pre_home_spread is not None else line.get("home_spread")
    total = pre_total if pre_total is not None else line.get("total")
    home, away = game["home"], game["away"]
    facts = game_facts(game)
    out = {"game": f"{away} @ {home}", "status": game["status"], "state": game["state"],
           "score": {away: game["score"]["away"], home: game["score"]["home"]},
           "pregame": {"home_spread": spread, "total": total, "source": "given" if pre_home_spread is not None else line.get("source")},
           "facts": facts}
    lp = None
    if spread is not None and game["state"] == "in":
        lp = live_price(spread, total, game["score"]["home"], game["score"]["away"], game["period"],
                        clock_seconds(game["clock"]), game["sport"])
        out["price"] = {k: v for k, v in lp.items() if not k.startswith("_")}
    checked = []
    for o in offers:
        if lp is None:
            break
        r = price_offer(lp, o["market"], o["side"], o.get("line"), o["price"])
        r["book"] = o.get("book")
        fair = sharp_fair(o["market"], o["side"], sharp or {}) if sharp else None
        if fair is not None:
            want = o.get("line")
            if o["market"] == "spread" and want is not None and o["side"] == "away":
                want = -want                  # sharp spreads are quoted on the home line
            same_line = o["market"] == "ml" or (sharp or {}).get(o["market"], {}).get("line") == want
            dec = american_to_decimal(o["price"])
            r["sharp_p"] = round(fair, 4) if same_line else None
            r["qualifies"] = False            # a sharp price on a different line can't vouch for this one
            if same_line:
                r["ev_vs_sharp_pct"] = round(100 * (fair * dec - 1), 2)
                r["model_minus_sharp"] = round(r["p_win"] - fair, 4)
                r["qualifies"] = (r["ev_vs_sharp_pct"] >= 100 * min_ev and abs(r["model_minus_sharp"]) <= max_disagreement)
        else:
            r["qualifies"] = False
        checked.append(r)
    if checked:
        out["offers"] = checked
    out["notes"] = notes(game, facts, lp, checked, max_disagreement)
    if lp and sharp:
        out["notes"].extend(line_gaps(lp, sharp, home))
    return out


def line_gaps(lp: dict, sharp: dict, home: str, spread_gap: float = 3.0, total_gap: float = 4.0) -> List[str]:
    """Flag a sharp live spread/total far from the model's fair line (even when no offer shares its line)."""
    out = []
    t = sharp.get("total")
    if t and lp.get("fair_total") is not None and abs(t["line"] - lp["fair_total"]) >= total_gap:
        side = "more" if t["line"] > lp["fair_total"] else "less"
        out.append(f"Sharp live total {t['line']:g} vs fair {lp['fair_total']:g}: the market expects {side} scoring "
                   f"than the model — treat totals as a pass unless they converge.")
    s = sharp.get("spread")
    if s and abs(s["line"] - lp["fair_home_spread"]) >= spread_gap:
        out.append(f"Sharp live spread {home} {s['line']:+g} vs fair {lp['fair_home_spread']:+g}: big gap — "
                   f"the market likely knows something; pass on sides.")
    return out


def notes(game: dict, facts: dict, lp: Optional[dict], checked: Sequence[dict], max_disagreement: float = 0.06) -> List[str]:
    """Plain-language bullet points, most useful first."""
    home, away, sport = game["home"], game["away"], game["sport"]
    n: List[str] = []
    runs = facts["runs"]
    cur = runs.get("current_run")
    if cur and cur["points"] >= 6:
        per, clk = cur["from"].split("|")
        n.append(f"{cur['team']} on a {cur['points']}-0 run since {_period_label(int(per), sport)} {clk}.")
    recent = runs["last_window"]["points"]
    if recent and abs(recent[home] - recent[away]) >= 6:
        lead_team = home if recent[home] > recent[away] else away
        n.append(f"Last {int(runs['last_window']['seconds'] // 60)} minutes: {lead_team} "
                 f"{max(recent.values())}-{min(recent.values())}.")
    for p in facts["foul_trouble"][:4]:
        tag = "fouled out" if p["fouled_out"] else f"{p['fouls']} fouls"
        n.append(f"{p['name']} ({p['team']}{', starter' if p['starter'] else ''}) has {tag}.")
    for ab, s in facts["shooting"].items():
        luck = s["three_pts_vs_typical"] + s["ft_pts_vs_typical"]
        if abs(luck) >= 4:
            n.append(f"{ab} shooting {'hot' if luck > 0 else 'cold'}: {s['three']} from three, {s['ft']} FT "
                     f"({luck:+.1f} pts vs typical rates) — shooting luck tends not to last.")
    tos = {ab: s.get("turnovers") for ab, s in facts["shooting"].items() if s.get("turnovers") is not None}
    if len(tos) == 2 and abs(tos[home] - tos[away]) >= 5:
        worse = home if tos[home] > tos[away] else away
        n.append(f"Turnovers {away} {tos[away]:g}, {home} {tos[home]:g} — {worse} giving away possessions.")
    n.extend(f"Flag: {f}" for f in facts["flags"][-3:])
    if lp:
        lead = lp["lead_home"]
        if lead:
            leader = home if lead > 0 else away
            p_lead = lp["p_home_win"] if lead > 0 else 1 - lp["p_home_win"]
            naive = lp["naive_p_home_win"] if lead > 0 else 1 - lp["naive_p_home_win"]
            n.append(f"Fair: {leader} wins {p_lead:.0%} (simple time-scaling says {naive:.0%}; WNBA leads at the half "
                     f"have held less often than that since 2023).")
        if not lp["at_halftime_shape"]:
            n.append("In overtime: plain time scaling.")
        elif abs(lp["frac_left"] - 0.5) > 0.13:
            n.append("Price is fitted at halftime and scaled to this clock — treat it as rougher away from the half.")
        if not lp["fitted"]:
            n.append(f"{sport}: shape borrowed from the WNBA fit, not fitted on {sport} data.")
    for r in checked:
        if r.get("model_minus_sharp") is not None and abs(r["model_minus_sharp"]) > max_disagreement:
            n.append(f"Model and sharp live price disagree by {abs(r['model_minus_sharp']):.0%} on {r['market']} "
                     f"{r['side']}: assume the market knows something (lineups, injuries, shot quality) — pass.")
            break
    return n


# ---------------------------------------------------------------------------
# Validation (halftime, WNBA)
# ---------------------------------------------------------------------------

def halftime_rows(games: Sequence[dict], lines: Sequence[dict], model_factory) -> List[dict]:
    """One row per game with a halftime score: pregame margin/total (DK close if present, else the model's
    walk-forward prediction), halftime margin/total and final margin/total."""
    by_line = {str(l["game_id"]): l for l in lines}
    model = model_factory()
    rows = []
    for g in sorted(games, key=lambda g: (str(g["date"]), str(g["game_id"]))):
        if g.get("home_1h") not in ("", None):
            l = by_line.get(str(g["game_id"]))
            dk = l is not None and l.get("spread_home_close") is not None and l.get("total_close") is not None
            if dk:
                mu, tot = -float(l["spread_home_close"]), float(l["total_close"])
            else:
                p = model.predict(g["home"], g["away"], g["date"], season=int(g["season"]),
                                  neutral=bool(int(g.get("neutral") or 0)), playoff=g.get("season_type") == "playoff")
                mu, tot = p.mu, p.total_mu
            h1, a1 = float(g["home_1h"]), float(g["away_1h"])
            rows.append({"season": int(g["season"]), "source": "dk" if dk else "model", "mu": mu, "T": tot,
                         "m1": h1 - a1, "t1": h1 + a1, "fm": g["home_pts"] - g["away_pts"],
                         "ft": g["home_pts"] + g["away_pts"]})
        model.update(g)
    return rows


def _lstsq(X: Sequence[Sequence[float]], y: Sequence[float]):
    from .wnba import _solve
    k = len(X[0])
    A = [[sum(x[i] * x[j] for x in X) for j in range(k)] for i in range(k)]
    b = [sum(x[i] * yy for x, yy in zip(X, y)) for i in range(k)]
    coef = _solve(A, b)
    res = [yy - sum(c * xx for c, xx in zip(coef, x)) for x, yy in zip(X, y)]
    return coef, math.sqrt(sum(r * r for r in res) / len(res))


def fit_halftime(rows: Sequence[dict]) -> dict:
    (share, rev), sd = _lstsq([(r["mu"], r["m1"]) for r in rows], [r["fm"] - r["m1"] for r in rows])
    (off, carry), tsd = _lstsq([(1.0, r["t1"] - r["T"] / 2) for r in rows], [r["ft"] - r["t1"] - r["T"] / 2 for r in rows])
    return {"n": len(rows), "mu_share": round(share, 3), "reversion": round(rev, 3), "half_sd": round(sd, 2),
            "total_offset": round(off, 2), "pace_carry": round(carry, 3), "half_total_sd": round(tsd, 2)}


def _p_win(mean: float, sd: float) -> float:
    d = discretized_normal(mean, sd)
    return sum(p for k, p in d.pmf.items() if k > 0) + 0.5 * d.prob(0)


def validate_halftime(rows: Sequence[dict], full_sd: float = 12.69) -> dict:
    """Fit on the model-line seasons, test on the DraftKings-line season; plus pooled fit and calibration."""
    train = [r for r in rows if r["source"] == "model"]
    test = [r for r in rows if r["source"] == "dk"]
    fit_tr = fit_halftime(train)
    pooled = fit_halftime(rows)
    by_season = {s: fit_halftime([r for r in rows if r["season"] == s])["reversion"]
                 for s in sorted({r["season"] for r in rows})}

    def score(pfun):
        ll = br = 0.0
        for r in test:
            p = min(max(pfun(r), 1e-9), 1 - 1e-9)
            y = 1.0 if r["fm"] > 0 else 0.0
            ll -= y * math.log(p) + (1 - y) * math.log(1 - p)
            br += (p - y) ** 2
        return {"log_loss": round(ll / len(test), 4), "brier": round(br / len(test), 4)}

    half_sd_naive = full_sd / math.sqrt(2)
    fitted = lambda r: _p_win(r["m1"] + fit_tr["mu_share"] * r["mu"] + fit_tr["reversion"] * r["m1"], fit_tr["half_sd"])  # noqa: E731
    naive = lambda r: _p_win(r["m1"] + 0.5 * r["mu"], half_sd_naive)  # noqa: E731
    pregame = lambda r: _p_win(r["mu"], full_sd)  # noqa: E731
    bins = []
    for lo, hi in ((1, 5), (6, 10), (11, 20)):
        sel = [r for r in rows if lo <= abs(r["m1"]) <= hi]
        if not sel:
            continue

        def lead_p(r, f):
            p = f(r)
            return p if r["m1"] > 0 else 1 - p
        fit_p = lambda r: _p_win(r["m1"] + pooled["mu_share"] * r["mu"] + pooled["reversion"] * r["m1"], pooled["half_sd"])  # noqa: E731
        bins.append({"halftime_lead": f"{lo}-{hi}", "n": len(sel),
                     "leader_won": round(sum(1 for r in sel if (r["fm"] > 0) == (r["m1"] > 0)) / len(sel), 3),
                     "fitted": round(sum(lead_p(r, fit_p) for r in sel) / len(sel), 3),
                     "naive": round(sum(lead_p(r, naive) for r in sel) / len(sel), 3)})
    rmse = lambda f: round(math.sqrt(sum((r["ft"] - r["t1"] - f(r)) ** 2 for r in test) / len(test)), 2)  # noqa: E731
    return {"n_train": len(train), "n_test": len(test), "fit_train": fit_tr, "fit_pooled": pooled,
            "reversion_by_season": by_season,
            "test_win_prob": {"fitted": score(fitted), "naive_time_scaling": score(naive), "pregame_only": score(pregame)},
            "calibration_by_halftime_lead": bins,
            "test_2h_total_rmse": {"pregame_half": rmse(lambda r: r["T"] / 2),
                                   "fitted": rmse(lambda r: r["T"] / 2 + fit_tr["total_offset"] + fit_tr["pace_carry"] * (r["t1"] - r["T"] / 2)),
                                   "first_half_pace": rmse(lambda r: r["t1"])}}
