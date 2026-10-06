"""MLB Stats API (statsapi.mlb.com, no key): schedule, probable pitchers, pitcher lines, bullpen use.

Split like the other fetchers: ``*_url`` builds the request, ``parse_*`` is a pure function on the
JSON (unit-tested on captured payloads), ``get_*`` does both.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta
from typing import Dict, List, Optional
from urllib.parse import urlencode

from . import fetch_json

BASE = "https://statsapi.mlb.com/api/v1"
GAME_TYPES = {"R": "regular", "F": "wild card", "D": "division series", "L": "league championship",
              "W": "world series", "S": "spring", "E": "exhibition", "A": "all-star"}


def schedule_url(day: str, team_id: Optional[int] = None, end: Optional[str] = None) -> str:
    q = {"sportId": 1, "hydrate": "probablePitcher,team,seriesStatus,weather,venue"}
    if end:
        q.update(startDate=day, endDate=end)
    else:
        q["date"] = day
    if team_id:
        q["teamId"] = team_id
    return f"{BASE}/schedule?" + urlencode(q)


def parse_schedule(js: dict) -> List[dict]:
    out = []
    for d in js.get("dates", []):
        for g in d.get("games", []):
            t = g["teams"]
            row = {"game_pk": g["gamePk"], "start": g["gameDate"], "game_type": GAME_TYPES.get(g.get("gameType"), g.get("gameType")),
                   "postseason": g.get("gameType") in ("F", "D", "L", "W"), "status": g.get("status", {}).get("detailedState"),
                   "venue": g.get("venue", {}).get("name"), "weather": g.get("weather") or None,
                   "series": (g.get("seriesStatus") or {}).get("result") or (g.get("seriesStatus") or {}).get("description")}
            for side in ("away", "home"):
                team = t[side]["team"]
                pp = t[side].get("probablePitcher")
                row[side] = {"id": team["id"], "abbr": team.get("abbreviation"), "name": team.get("name"),
                             "probable": {"id": pp["id"], "name": pp["fullName"]} if pp else None,
                             "score": t[side].get("score")}
            out.append(row)
    return out


def pitcher_stats_url(pid: int, season: int) -> str:
    return f"{BASE}/people/{pid}/stats?" + urlencode({"stats": "season,gameLog", "group": "pitching", "season": season})


def _line(st: dict) -> dict:
    keys = {"gamesStarted": "starts", "inningsPitched": "ip", "era": "era", "whip": "whip", "strikeOuts": "k",
            "baseOnBalls": "bb", "homeRuns": "hr", "battersFaced": "bf", "numberOfPitches": "pitches", "earnedRuns": "er"}
    out = {v: st.get(k) for k, v in keys.items() if st.get(k) is not None}
    bf = st.get("battersFaced") or 0
    if bf:
        out["k_pct"] = round(100 * st.get("strikeOuts", 0) / bf, 1)
        out["bb_pct"] = round(100 * st.get("baseOnBalls", 0) / bf, 1)
    return out


def parse_pitcher_stats(js: dict, last: int = 3) -> dict:
    out = {"season": None, "last_starts": []}
    for s in js.get("stats", []):
        kind = s.get("type", {}).get("displayName")
        if kind == "season" and s.get("splits"):
            out["season"] = _line(s["splits"][0]["stat"])
        elif kind == "gameLog":
            for sp in s.get("splits", [])[-last:]:
                out["last_starts"].append({"date": sp.get("date"), "opp": (sp.get("opponent") or {}).get("name"),
                                           **_line(sp["stat"])})
    return out


def boxscore_url(game_pk: int) -> str:
    return f"{BASE}/game/{game_pk}/boxscore"


def parse_pitchers(js: dict) -> Dict[str, List[dict]]:
    """Pitchers used per side: name, innings, pitches, starter flag."""
    out = {}
    for side in ("away", "home"):
        t = js["teams"][side]
        rows = []
        for pid in t.get("pitchers", []):
            pl = t["players"].get(f"ID{pid}", {})
            st = pl.get("stats", {}).get("pitching", {})
            rows.append({"name": pl.get("person", {}).get("fullName"), "ip": st.get("inningsPitched"),
                         "pitches": st.get("numberOfPitches"), "starter": bool(st.get("gamesStarted"))})
        out[side] = rows
    return out


def get_schedule(day: str) -> List[dict]:
    js, _ = fetch_json(schedule_url(day))
    return parse_schedule(js)


def bullpen_usage(team_id: int, day: str, days: int = 3) -> dict:
    """Relievers' pitches over the ``days`` days before ``day`` (who may be tired or unavailable)."""
    d = _date.fromisoformat(day)
    js, _ = fetch_json(schedule_url((d - timedelta(days)).isoformat(), team_id, (d - timedelta(1)).isoformat()))
    games = [g for g in parse_schedule(js) if g["status"] == "Final"]
    per: Dict[str, dict] = {}
    for g in games:
        side = "home" if g["home"]["id"] == team_id else "away"
        bx, _ = fetch_json(boxscore_url(g["game_pk"]))
        for p in parse_pitchers(bx)[side]:
            if p["starter"]:
                continue
            r = per.setdefault(p["name"], {"name": p["name"], "pitches": 0, "appearances": 0, "dates": []})
            r["pitches"] += p["pitches"] or 0
            r["appearances"] += 1
            r["dates"].append(g["start"][:10])
    rel = sorted(per.values(), key=lambda r: -r["pitches"])
    return {"games": len(games), "relief_pitches": sum(r["pitches"] for r in rel), "relievers": rel}


def game_context(day: str, team: Optional[str] = None, bullpen_days: int = 3) -> List[dict]:
    """Probable pitchers (season line + last starts), bullpen use, weather and series state."""
    season = int(day[:4])
    out = []
    for g in get_schedule(day):
        if team and team.upper() not in (g["away"]["abbr"], g["home"]["abbr"]):
            continue
        for side in ("away", "home"):
            pp = g[side]["probable"]
            if pp:
                js, _ = fetch_json(pitcher_stats_url(pp["id"], season))
                pp.update(parse_pitcher_stats(js))
            g[side]["bullpen_last_%dd" % bullpen_days] = bullpen_usage(g[side]["id"], day, bullpen_days)
        out.append(g)
    return out
