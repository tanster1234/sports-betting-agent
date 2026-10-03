"""ESPN public (unofficial) site API: scoreboard, game summary, injuries.

No key required.  Unofficial endpoints change without notice, so parsers
accept every odds schema observed in practice:

* 2026: ``odds[0]`` = {provider{name}, details, overUnder, spread (HOME
  perspective), moneyline.{home,away}.{open,close}.odds,
  pointSpread.{home,away}.{open,close}.{line,odds},
  total.{over,under}.{open,close}.{line,odds} ("o165.5")}.  The scoreboard
  no longer carries homeTeamOdds.moneyLine; the summary's ``pickcenter``
  also has legacy numeric fields (homeTeamOdds.moneyLine/spreadOdds,
  overOdds/underOdds).
* 2024: provider "ESPN BET" with ``open``/``current`` blocks whose values are
  {value, decimal, american, ...}.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import fetch_json

LEAGUES = {
    "wnba": ("basketball", "wnba"),
    "nba": ("basketball", "nba"),
    "ncaab": ("basketball", "mens-college-basketball"),
    "wncaab": ("basketball", "womens-college-basketball"),
    "nfl": ("football", "nfl"),
    "ncaaf": ("football", "college-football"),
    "mlb": ("baseball", "mlb"),
    "nhl": ("hockey", "nhl"),
}
SITE = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}"


def _base(league: str) -> str:
    key = league.lower()
    if key not in LEAGUES:
        raise KeyError(f"unknown league {league!r}; known {sorted(LEAGUES)}")
    sport, lg = LEAGUES[key]
    return SITE.format(sport=sport, league=lg)


def scoreboard_url(league: str, yyyymmdd: Optional[str] = None) -> str:
    u = f"{_base(league)}/scoreboard"
    return u + (f"?dates={yyyymmdd.replace('-', '')}" if yyyymmdd else "")


def summary_url(league: str, event_id: str) -> str:
    return f"{_base(league)}/summary?event={event_id}"


def injuries_url(league: str) -> str:
    return f"{_base(league)}/injuries"


# ---------------------------------------------------------------------------
# number helpers
# ---------------------------------------------------------------------------

_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _num(x: Any) -> Optional[float]:
    """'-110' -> -110.0, 'o165.5' -> 165.5, 'EVEN' -> 100.0, 'PK' -> 0.0, 3 -> 3.0."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if s.upper() in ("EVEN", "EV"):
        return 100.0
    if s.upper() in ("PK", "PICK", "PICK'EM"):
        return 0.0
    m = _NUM.search(s)
    return float(m.group()) if m else None


def _american(v: Any) -> Optional[float]:
    """Accept a raw number/string or a {american|value} dict."""
    if isinstance(v, dict):
        for k in ("american", "odds", "alternateDisplayValue", "displayValue", "value"):
            if k in v and v[k] is not None:
                n = _num(v[k])
                if n is not None and (abs(n) >= 100 or k in ("american", "odds")):
                    return n
        return None
    n = _num(v)
    return n


def _dig(d: Any, *path) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def parse_odds_block(o: dict) -> Dict[str, Any]:
    """Normalise one ESPN odds/pickcenter object.

    Returns keys: provider, details, home_spread, total, and for each of
    open/close: spread_home, spread_price_home, spread_price_away, total,
    over_price, under_price, ml_home, ml_away (None where absent).
    """
    out: Dict[str, Any] = {
        "provider": _dig(o, "provider", "name"),
        "details": o.get("details"),
        "home_spread": _num(o.get("spread")),
        "total": _num(o.get("overUnder")),
    }
    for when in ("open", "close"):
        row = {
            "spread_home": _num(_dig(o, "pointSpread", "home", when, "line")),
            "spread_price_home": _num(_dig(o, "pointSpread", "home", when, "odds")),
            "spread_price_away": _num(_dig(o, "pointSpread", "away", when, "odds")),
            "total": _num(_dig(o, "total", "over", when, "line")),
            "over_price": _num(_dig(o, "total", "over", when, "odds")),
            "under_price": _num(_dig(o, "total", "under", when, "odds")),
            "ml_home": _num(_dig(o, "moneyline", "home", when, "odds")),
            "ml_away": _num(_dig(o, "moneyline", "away", when, "odds")),
        }
        out[when] = row
    # legacy numeric fields (summary pickcenter) fill gaps in "close"
    c = out["close"]
    if c["ml_home"] is None:
        c["ml_home"] = _num(_dig(o, "homeTeamOdds", "moneyLine"))
    if c["ml_away"] is None:
        c["ml_away"] = _num(_dig(o, "awayTeamOdds", "moneyLine"))
    if c["spread_price_home"] is None:
        c["spread_price_home"] = _num(_dig(o, "homeTeamOdds", "spreadOdds"))
    if c["spread_price_away"] is None:
        c["spread_price_away"] = _num(_dig(o, "awayTeamOdds", "spreadOdds"))
    if c["over_price"] is None:
        c["over_price"] = _num(o.get("overOdds"))
    if c["under_price"] is None:
        c["under_price"] = _num(o.get("underOdds"))
    if c["spread_home"] is None:
        c["spread_home"] = out["home_spread"]
    if c["total"] is None:
        c["total"] = out["total"]
    # 2024 schema: open/current blocks
    for when, key in (("open", "open"), ("close", "current")):
        blk = o.get(key)
        if isinstance(blk, dict):
            row = out[when]
            if row["total"] is None:
                row["total"] = _num(_dig(blk, "total", "value")) or _num(_dig(blk, "total", "alternateDisplayValue"))
            if row["over_price"] is None:
                row["over_price"] = _american(blk.get("over"))
            if row["under_price"] is None:
                row["under_price"] = _american(blk.get("under"))
        for side, tkey in (("home", "homeTeamOdds"), ("away", "awayTeamOdds")):
            tb = _dig(o, tkey, key)
            if isinstance(tb, dict):
                row = out[when]
                if row[f"ml_{side}"] is None:
                    row[f"ml_{side}"] = _american(tb.get("moneyLine"))
                if row[f"spread_price_{side}"] is None:
                    row[f"spread_price_{side}"] = _american(tb.get("spreadOdds"))
                if side == "home" and row["spread_home"] is None:
                    row["spread_home"] = _num(_dig(tb, "pointSpread", "value")) if isinstance(tb.get("pointSpread"), dict) else _num(tb.get("pointSpread"))
    return out


def _competitors(comp: dict) -> Dict[str, dict]:
    teams = {}
    for c in comp.get("competitors", []):
        t = c.get("team", {})
        teams[c.get("homeAway")] = {
            "id": t.get("id"), "abbr": t.get("abbreviation"), "name": t.get("displayName"),
            "score": _num(c.get("score")), "winner": c.get("winner"),
            "linescores": [_num(x.get("value")) for x in c.get("linescores") or [] if isinstance(x, dict)],
            "record": next((r.get("summary") for r in c.get("records", []) if r.get("name") in ("overall", "All Splits")), None)
            if c.get("records") else c.get("record"),
        }
    return teams


def parse_scoreboard(js: dict) -> List[dict]:
    games = []
    for ev in js.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        teams = _competitors(comp)
        st = _dig(ev, "status", "type") or _dig(comp, "status", "type") or {}
        odds = comp.get("odds") or []
        games.append({
            "event_id": ev.get("id"), "date": ev.get("date"), "name": ev.get("shortName") or ev.get("name"),
            "state": st.get("state"), "completed": st.get("completed"), "status": st.get("shortDetail") or st.get("description"),
            "status_name": st.get("name"), "period": _dig(ev, "status", "period") or _dig(comp, "status", "period"),
            "clock": _dig(ev, "status", "displayClock") or _dig(comp, "status", "displayClock"),
            "neutral": comp.get("neutralSite"), "venue": _dig(comp, "venue", "fullName"),
            "home": teams.get("home"), "away": teams.get("away"),
            "odds": [parse_odds_block(o) for o in odds],
            "notes": [n.get("headline") for n in comp.get("notes", []) if n.get("headline")],
        })
    return games


def parse_summary(js: dict) -> dict:
    comp = (_dig(js, "header", "competitions") or [{}])[0]
    teams = _competitors(comp)
    st = _dig(comp, "status", "type") or {}
    players = []
    for team in _dig(js, "boxscore", "players") or []:
        abbr = _dig(team, "team", "abbreviation")
        for grp in team.get("statistics", []):
            keys = grp.get("keys") or grp.get("names") or []
            for a in grp.get("athletes", []):
                stats = dict(zip(keys, a.get("stats", [])))
                players.append({"team": abbr, "player": _dig(a, "athlete", "displayName"), "starter": a.get("starter"),
                                "dnp": a.get("didNotPlay"), "reason": a.get("reason"),
                                "minutes": _num(stats.get("minutes")), "points": _num(stats.get("points")),
                                "rebounds": _num(stats.get("rebounds")), "assists": _num(stats.get("assists")),
                                "threes": _num(str(stats.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "")).split("-")[0] or None)})
    return {
        "event_id": js.get("gameId") or comp.get("id"),
        "date": comp.get("date"), "state": st.get("state"), "completed": st.get("completed"),
        "home": teams.get("home"), "away": teams.get("away"),
        "odds": [parse_odds_block(o) for o in (js.get("pickcenter") or js.get("odds") or [])],
        "players": players,
        "series": [s.get("summary") for s in js.get("seasonseries", []) if s.get("summary")],
    }


def parse_injuries(js: dict) -> List[dict]:
    out = []
    for team in js.get("injuries", []):
        tname = team.get("displayName") or _dig(team, "team", "displayName")
        for inj in team.get("injuries", []):
            ath = inj.get("athlete", {}) or {}
            pid = ath.get("id")
            if not pid:
                for link in ath.get("links", []) or []:
                    m = re.search(r"/id/(\d+)", link.get("href", ""))
                    if m:
                        pid = m.group(1)
                        break
            out.append({"team": tname, "player": ath.get("displayName"), "player_id": pid,
                        "position": _dig(ath, "position", "abbreviation"), "status": inj.get("status"),
                        "type": _dig(inj, "type", "description") or _dig(inj, "details", "type"),
                        "return_date": _dig(inj, "details", "returnDate"),
                        "comment": inj.get("shortComment") or inj.get("longComment"), "date": inj.get("date")})
    return out


def get_scoreboard(league: str, yyyymmdd: Optional[str] = None) -> List[dict]:
    js, _ = fetch_json(scoreboard_url(league, yyyymmdd))
    return parse_scoreboard(js)


def get_summary(league: str, event_id: str) -> dict:
    js, _ = fetch_json(summary_url(league, event_id))
    return parse_summary(js)


def get_injuries(league: str) -> List[dict]:
    js, _ = fetch_json(injuries_url(league))
    return parse_injuries(js)
