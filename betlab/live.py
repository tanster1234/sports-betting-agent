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

Totals settle as soon as the line is passed (an over is won, an under lost);
everything else settles when its period ends.
"""

from __future__ import annotations

from typing import Dict, List, Optional

SETTLED = ("won", "lost", "push", "void", "cashout")


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
        return (game.get("period") or 0) >= 3 or game.get("status_name") == "STATUS_HALFTIME"
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


def apply_live(bet: dict, games: Dict[str, dict], now_iso: str) -> Optional[dict]:
    """Patch for one tracker bet, or None when no leg is tracked.

    ``games`` maps ESPN event id -> parsed scoreboard game.  The patch carries
    ``legs`` (with ``live`` and any decided ``result``), the derived status
    fields, ``liveUpdatedAt``, and ``changed`` (anything besides timestamps).
    """
    legs = [dict(lg) for lg in bet.get("legs") or []]
    tracked = False
    changed = False
    for lg in legs:
        spec = lg.get("spec")
        game = games.get(str(spec.get("event"))) if spec else None
        if not game:
            continue
        tracked = True
        live = grade_leg(spec, game)
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
