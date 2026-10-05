"""Live grading of bet legs from scoreboard data, for the bet-slip tracker.

Each tracked leg carries a small spec next to its free-text pick:

    {"league": "ncaaf", "event": "401858250", "market": "spread", "period": "game",
     "team": "UW", "line": 7.5}

``market`` is ``ml``, ``spread`` or ``total``; ``period`` is ``game`` (overtime
included) or ``1h`` (first two periods only); ``team`` is the ESPN team
abbreviation for ``ml``/``spread``; ``side`` is ``over``/``under`` for
``total``.  ``grade_leg`` turns a spec plus a parsed scoreboard game into the
leg's live state; ``apply_live`` updates a whole tracker bet and derives its
status the same way the tracker page does.

Player props use ``market: "player"`` and are graded from the ESPN game
summary (box score and scoring plays) instead of the scoreboard:

    {"league": "nfl", "event": "401872979", "market": "player",
     "player": "Bijan Robinson", "stat": "rushYards", "side": "over", "line": 59.5}

``stat`` is one of ``PLAYER_STATS`` (NFL yards, receptions, passing TDs and
``anytimeTD``; basketball points, rebounds, assists, threes).

Totals and player overs settle as soon as the line is passed (an over is won,
an under lost); everything else settles when its period ends.  Legs keep being
graded after their ticket has already lost, so every leg ends with a result.
"""

from __future__ import annotations

import math
import re
from typing import Dict, List, Optional

SETTLED = ("won", "lost", "push", "void", "cashout")

# spec "stat" -> (ESPN box-score group, stat key, words for the tracker).  Basketball box scores
# have a single group, so their group is None.
PLAYER_STATS = {
    "passYards": ("passing", "passingYards", "pass yds"),
    "passTDs": ("passing", "passingTouchdowns", "pass TDs"),
    "rushYards": ("rushing", "rushingYards", "rush yds"),
    "recYards": ("receiving", "receivingYards", "rec yds"),
    "receptions": ("receiving", "receptions", "catches"),
    "anytimeTD": (None, None, "TD"),
    "points": (None, "points", "pts"),
    "rebounds": (None, "rebounds", "reb"),
    "assists": (None, "assists", "ast"),
    "threes": (None, "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "3PM"),
}


def _fmt(x: float) -> str:
    return f"{x:g}"


def _period_points(team: dict, period: str) -> float:
    if period == "1h":
        return float(sum(v or 0 for v in (team.get("linescores") or [])[:2]))
    return float(team.get("score") or 0)


def _period_over(game: dict, period: str) -> bool:
    if game.get("state") == "post" or game.get("completed"):
        return True
    if period == "1h":
        status = str(game.get("status") or "").lower()
        # ESPN shows "End of 2nd" (still STATUS_IN_PROGRESS) before it switches to halftime
        return ((game.get("period") or 0) >= 3 or game.get("status_name") == "STATUS_HALFTIME"
                or status.startswith("end of 2nd") or status.startswith("halftime"))
    return False


def _side(game: dict, abbr: str):
    for us, them in (("home", "away"), ("away", "home")):
        if (game.get(us) or {}).get("abbr") == abbr:
            return game[us], game[them]
    raise KeyError(f"team {abbr!r} is not in {game.get('name')!r}")


def grade_leg(spec: dict, game: dict) -> dict:
    """Live state of one leg: state, result (None until decided), now, score, clock, detail."""
    period = spec.get("period", "game")
    market = spec["market"]
    away, home = game.get("away") or {}, game.get("home") or {}
    a_pts, h_pts = _period_points(away, period), _period_points(home, period)
    prefix = "1H " if period == "1h" else ""
    out = {
        "state": "pre" if game.get("state") == "pre" else ("final" if _period_over(game, period) else "live"),
        "score": f"{prefix}{away.get('abbr')} {_fmt(a_pts)} – {home.get('abbr')} {_fmt(h_pts)}",
        "clock": game.get("status") or "",
        "result": None, "now": None, "detail": "",
    }
    if out["state"] == "pre":
        out["score"] = f"{away.get('abbr')} @ {home.get('abbr')}"
        return out
    done = out["state"] == "final"

    if market in ("ml", "spread"):
        us, them = _side(game, spec["team"])
        margin = _period_points(us, period) - _period_points(them, period)
        if market == "spread":
            cover = margin + float(spec["line"])
            out["now"] = "ahead" if cover > 0 else "behind" if cover < 0 else "level"
            out["detail"] = (f"covering by {_fmt(cover)}" if cover > 0 else
                             f"not covering by {_fmt(-cover)}" if cover < 0 else "exactly on the number")
        else:
            out["now"] = "ahead" if margin > 0 else "behind" if margin < 0 else "level"
            out["detail"] = (f"leading by {_fmt(margin)}" if margin > 0 else
                             f"trailing by {_fmt(-margin)}" if margin < 0 else "tied")
        if done:
            out["result"] = {"ahead": "won", "behind": "lost", "level": "push"}[out["now"]]
        return out

    if market == "total":
        line, total, over = float(spec["line"]), a_pts + h_pts, spec["side"] == "over"
        diff = total - line
        if diff > 0:
            out["now"] = "ahead" if over else "behind"
            out["result"] = "won" if over else "lost"          # a passed total cannot come back
            out["detail"] = f"{_fmt(total)} points, past {_fmt(line)}"
            out["state"] = "final" if done else out["state"]
        else:
            need = line - total
            out["now"] = ("behind" if over else "ahead") if diff < 0 else "level"
            out["detail"] = (f"{_fmt(total)} points, right on {_fmt(line)}" if need == 0 else
                             f"{_fmt(total)} points, needs {_fmt(need)} more" if over else
                             f"{_fmt(total)} points, {_fmt(need)} to spare")
            if done:
                out["result"] = "push" if diff == 0 else ("lost" if over else "won")
        return out

    raise ValueError(f"unknown market {market!r}")


def player_name_key(name: str) -> str:
    """'Kenneth Walker III' / 'R.J. Harvey' -> comparable keys ('kenneth walker', 'rj harvey')."""
    n = re.sub(r"[^a-z ]", "", str(name).lower().replace(".", "").replace("-", " "))
    return " ".join(w for w in n.split() if w not in ("jr", "sr", "ii", "iii", "iv", "v"))


def _stat_value(raw) -> Optional[float]:
    s = str(raw)
    if "-" in s and not s.startswith("-"):          # "3-7" made-attempted
        s = s.split("-")[0]
    try:
        return float(s)
    except ValueError:
        return None


def parse_box(js: dict) -> dict:
    """Player stats from an ESPN game summary (any sport): state, status text, per-player stats,
    who did not play (basketball lists them), and rushing/receiving/return TD scorers."""
    comp = ((js.get("header") or {}).get("competitions") or [{}])[0]
    st = (comp.get("status") or {}).get("type") or {}
    players: Dict[str, dict] = {}
    dnp = set()
    for team in (js.get("boxscore") or {}).get("players") or []:
        for grp in team.get("statistics") or []:
            keys = grp.get("keys") or []
            gname = grp.get("name")
            for a in grp.get("athletes") or []:
                key = player_name_key((a.get("athlete") or {}).get("displayName", ""))
                if a.get("didNotPlay"):
                    dnp.add(key)
                    continue
                rec = players.setdefault(key, {})
                for k, v in zip(keys, a.get("stats") or []):
                    val = _stat_value(v)
                    if val is not None:
                        rec[(gname, k)] = val
    tds: Dict[str, int] = {}
    for p in js.get("scoringPlays") or []:
        if ((p.get("scoringType") or {}).get("abbreviation")) != "TD":
            continue
        m = re.match(r"^(.+?) \d+ (?:Yd|Yard)", p.get("text") or "")
        if m:
            k = player_name_key(m.group(1))
            tds[k] = tds.get(k, 0) + 1
    return {"state": st.get("state"), "status": st.get("shortDetail") or "", "players": players,
            "dnp": dnp, "td_scorers": tds}


def grade_player_leg(spec: dict, box: dict) -> dict:
    """Live state of a player-prop leg from ``parse_box`` output (same shape as ``grade_leg``)."""
    stat = spec["stat"]
    if stat not in PLAYER_STATS:
        raise ValueError(f"unknown player stat {stat!r}; known: {sorted(PLAYER_STATS)}")
    group, key, words = PLAYER_STATS[stat]
    name = spec["player"]
    line = float(spec.get("line", 0.5))
    over = spec.get("side", "over") == "over"
    out = {"state": "pre", "score": name, "clock": box.get("status") or "", "result": None, "now": None, "detail": ""}
    if box.get("state") not in ("in", "post"):
        return out
    done = box["state"] == "post"
    out["state"] = "final" if done else "live"
    pk = player_name_key(name)
    rec = box["players"].get(pk)
    if stat == "anytimeTD":
        val = float(box["td_scorers"].get(pk, 0))
    elif rec is None:
        val = 0.0
    elif group is None:
        val = next((v for (g, k), v in rec.items() if k == key), 0.0)
    else:
        val = rec.get((group, key), 0.0)
    out["score"] = f"{name} {_fmt(val)} {words}"
    if pk in box.get("dnp", ()) and done:
        out.update(result="void", now="level", detail="did not play — books void this leg")
        return out
    if val > line:                                   # an over that's cleared can't come back; an under is gone
        out.update(result="won" if over else "lost", now="ahead" if over else "behind",
                   detail=f"{_fmt(val)} {words}, past {_fmt(line)}")
        return out
    need = line - val
    out["now"] = ("behind" if over else "ahead") if need > 0 else "level"
    if over:
        out["detail"] = f"{_fmt(val)} {words}, needs {_fmt(math.floor(line) + 1 - val)} more"
    else:
        out["detail"] = f"{_fmt(val)} {words}, {_fmt(need)} to spare"
    if done:
        if val == line:
            out["result"] = "push"
        elif rec is None and stat != "anytimeTD" and over:
            out["result"] = "lost"
            out["detail"] = "no stats recorded — if he was inactive the book voids this leg (mark it push)"
        else:
            out["result"] = "lost" if over else "won"
            out["detail"] = "no touchdown" if stat == "anytimeTD" else f"finished with {_fmt(val)} {words}"
    return out


def derive_status(bet: dict, legs: List[dict]) -> dict:
    """Bet status from leg results (mirrors the tracker page)."""
    if bet.get("status") in ("cashout", "void"):
        return {}
    results = [lg.get("result") or "pending" for lg in legs]
    if not results:
        return {}
    if "lost" in results:
        return {"status": "lost", "returned": 0, "needsReturn": False}
    if all(r == "won" for r in results):
        return {"status": "won", "returned": bet.get("toReturn"), "needsReturn": False}
    if "pending" not in results:
        if all(r == "push" for r in results):
            return {"status": "push", "returned": bet.get("stake"), "needsReturn": False}
        return {"status": "open", "returned": None, "needsReturn": True}   # book reprices a parlay with a push
    return {"status": "open", "returned": None, "needsReturn": False}


def apply_live(bet: dict, games: Dict[str, dict], now_iso: str,
               boxes: Optional[Dict[str, dict]] = None) -> Optional[dict]:
    """Patch for one tracker bet, or None when no leg is tracked.

    ``games`` maps ESPN event id -> parsed scoreboard game; ``boxes`` maps
    event id -> ``parse_box`` output for player-prop legs.  The patch carries
    ``legs`` (with ``live`` and any decided ``result``), the derived status
    fields, ``liveUpdatedAt``, and ``changed`` (anything besides timestamps).
    """
    legs = [dict(lg) for lg in bet.get("legs") or []]
    tracked = False
    changed = False
    for lg in legs:
        spec = lg.get("spec")
        if not spec:
            continue
        if spec.get("market") == "player":
            box = (boxes or {}).get(str(spec.get("event")))
            if not box:
                continue
            live = grade_player_leg(spec, box)
        else:
            game = games.get(str(spec.get("event")))
            if not game:
                continue
            live = grade_leg(spec, game)
        tracked = True
        res = live.pop("result")
        live["updatedAt"] = now_iso
        old = {k: v for k, v in (lg.get("live") or {}).items() if k != "updatedAt"}
        if old != {k: v for k, v in live.items() if k != "updatedAt"}:
            changed = True
        lg["live"] = live
        if res and lg.get("result") != res:
            lg["result"] = res
            changed = True
    if not tracked:
        return None
    patch = {"legs": legs, "liveUpdatedAt": now_iso}
    status = derive_status(bet, legs)
    for k, v in status.items():
        before = bool(bet.get(k)) if k == "needsReturn" else bet.get(k)
        if before != v:
            changed = True
        patch[k] = v
    if status.get("status") in SETTLED:
        patch["settledAt"] = bet.get("settledAt") if bet.get("status") == status["status"] and bet.get("settledAt") else now_iso
    elif status:
        patch["settledAt"] = None
    patch["changed"] = changed
    return patch
