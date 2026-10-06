"""Post-mortems for settled parlay legs: why each one won or lost, and what that says about the next slip.

Every settled leg gets tags from facts, not hindsight:

* **chance** — what we gave it before the game (``long shot`` < 45%, ``coin flip``, ``favourite``
  >= 65%, ``strong favourite`` >= 80%); a lost long shot is an ``expected loss``, a lost leg we had
  at 70%+ is an ``upset``.
* **near miss** — lost by a catch, a few yards, or within a field goal / a run / a basket.
* **game script** — the game beat the spread or total by 1+ standard deviation in the direction
  this leg didn't want (using the same measured game-script links as ``betlab slips``).
* **volume** — a player prop lost because the player didn't get his usual work (carries, targets,
  pass attempts) rather than because he was inefficient with it; or **TDs went elsewhere**.
* **shared** — the same leg or player was on another ticket that day; **conflict** — it pulled
  against another leg on its own ticket; **only miss** — the one leg that sank its ticket.

``summary`` then counts tags on lost legs, checks calibration (did our 70-80% legs win 70-80%?) with
the sample size, and turns the counts into plain lessons — structural ones (shared legs, conflicts)
can be acted on at once; result-based ones need far more legs before they mean anything.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence

from . import slips
from .live import parse_box, player_name_key

# spread of results around the closing line, by league: (margin, total)
SCRIPT_SD = {"nfl": (13.2, 13.4), "ncaaf": (16.0, 16.5), "nba": (12.0, 17.0), "wnba": (11.0, 15.5),
             "mlb": (4.4, 4.5), "nhl": (2.4, 2.3)}
NEAR = {"nfl": 3, "ncaaf": 3, "nba": 3, "wnba": 3, "mlb": 1, "nhl": 1}
YARDS_PER = {"rushYards": 4.3, "recYards": 8.0, "passYards": 6.8}
BUCKETS = ((0.0, 0.45, "long shot"), (0.45, 0.65, "coin flip"), (0.65, 0.80, "favourite"), (0.80, 1.01, "strong favourite"))
LESSONS = {
    "shared": "The same leg or player was on more than one ticket — one miss sank several. Check a new ticket "
              "against the ones already placed, and keep each player on one ticket.",
    "same player twice": "The same player was on two tickets. This time only one leg lost, but an injury or benching "
                         "sinks both — keep each player on one ticket.",
    "conflict": "Legs on the same ticket needed opposite games. Build tickets where every leg wins in the same game.",
    "game script": "The game went the other way from what the leg needed. Pair legs that share a script, or bet the "
                   "script itself (side/total) instead of a prop that depends on it.",
    "volume": "The player didn't get his usual work. Check the injury report, snap/minutes news and the depth chart "
              "right before kickoff; the line assumes a normal workload.",
    "TDs went elsewhere": "Touchdowns went to other players. Anytime-TD legs are long shots individually; stack them "
                          "only with boosts and small stakes.",
    "near miss": "Near misses: a safer alternate line would have cashed. Compare its price before choosing the main line.",
    "upset": "Strong favourites lose sometimes; on its own this is variance, not a mistake. Check the calibration table "
             "before changing anything.",
    "expected loss": "Long shots lost, as expected. Fine at small stakes when the price is right.",
}


def _bucket(p: float) -> str:
    return next(name for lo, hi, name in BUCKETS if lo <= p < hi)


class _Fetcher:
    """Cached ESPN JSON fetches shared by the team/position lookup and the box scores."""

    def __init__(self, fetch: Optional[Callable[[str], dict]] = None):
        from .fetch import fetch_json
        self._fetch = fetch or (lambda url: fetch_json(url)[0])
        self.cache: Dict[str, dict] = {}

    def __call__(self, url: str) -> dict:
        if url not in self.cache:
            self.cache[url] = self._fetch(url)
        return self.cache[url]


def _game_facts(js: dict, league: str) -> dict:
    comp = js["header"]["competitions"][0]
    side = {c["homeAway"]: c for c in comp["competitors"]}
    hs, as_ = float(side["home"].get("score") or 0), float(side["away"].get("score") or 0)
    out = {"home": side["home"]["team"]["abbreviation"], "away": side["away"]["team"]["abbreviation"],
           "home_score": hs, "away_score": as_, "final": (comp.get("status") or {}).get("type", {}).get("completed", False)}
    pc = (js.get("pickcenter") or [{}])[0] if js.get("pickcenter") else {}
    sd_m, sd_t = SCRIPT_SD.get(league, (13.0, 13.0))
    if pc.get("spread") is not None:
        exp = -float(pc["spread"])                               # ESPN spread is the home team's line
        out.update(close_spread_home=float(pc["spread"]), z_margin_home=round((hs - as_ - exp) / sd_m, 2),
                   beat_spread_home=round(hs - as_ - exp, 1))
    if pc.get("overUnder") is not None:
        out.update(close_total=float(pc["overUnder"]), z_total=round((hs + as_ - float(pc["overUnder"])) / sd_t, 2))
    return out


def _player_facts(leg: slips.Leg, box: dict) -> dict:
    rec = box["players"].get(player_name_key(leg.player or ""), {})

    def g(group, key):
        return rec.get((group, key))
    return {"carries": g("rushing", "rushingAttempts"), "rush_yds": g("rushing", "rushingYards"),
            "targets": g("receiving", "receivingTargets"), "receptions": g("receiving", "receptions"),
            "rec_yds": g("receiving", "receivingYards"), "attempts": g("passing", "passingAttempts"),
            "pass_yds": g("passing", "passingYards"), "minutes": next((v for (gr, k), v in rec.items() if k == "minutes"), None),
            "points": next((v for (gr, k), v in rec.items() if k == "points"), None),
            "tds": box["td_scorers"].get(player_name_key(leg.player or ""), 0), "played": bool(rec)}


def _value(leg: slips.Leg, pf: dict) -> Optional[float]:
    return {"rushYards": pf["rush_yds"], "recYards": pf["rec_yds"], "receptions": pf["receptions"],
            "passYards": pf["pass_yds"], "anytimeTD": pf["tds"], "points": pf["points"]}.get(leg.stat)


def _leg_review(leg: slips.Leg, game: Optional[dict], box: Optional[dict], team_scorers: List[str]) -> dict:
    tags, why, facts = [], [], {}
    lost = leg.result == "lost"
    if lost and leg.p < 0.45:
        tags.append("expected loss")
    if lost and leg.p >= 0.7:
        tags.append("upset")
    lg = leg.league
    if game:
        facts.update({k: v for k, v in game.items() if k not in ("final",)})
        m, t, _ = slips.loadings(leg)
        zm, zt = game.get("z_margin_home"), game.get("z_total")
        script = []
        if zm is not None and abs(m) >= 0.1 and abs(zm) >= 1.0:
            winner = game["home"] if zm > 0 else game["away"]
            if m * zm < 0:
                script.append(f"{winner} beat the spread by {abs(game['beat_spread_home']):g}, the opposite of what this leg needed")
            elif not lost:
                facts["helped_by_script"] = True
        if zt is not None and abs(t) >= 0.1 and abs(zt) >= 1.0 and t * zt < 0:
            script.append("the game went " + ("well over" if zt > 0 else "well under") + f" the total ({game['close_total']:g})")
        if lost and script:
            tags.append("game script")
            text = "; ".join(script)
            why.append(text[0].upper() + text[1:])
        if lost and not leg.is_player and leg.market in ("ml", "spread", "total"):
            hm = game["home_score"] - game["away_score"]
            if leg.market == "total" and leg.line is not None:
                miss = abs(game["home_score"] + game["away_score"] - leg.line)
            else:
                own = hm if slips._side_sign(leg) == 1 else -hm
                miss = abs(own + (leg.line or 0)) if leg.market == "spread" else abs(own)
            facts["missed_by"] = miss
            if miss <= NEAR.get(lg, 3):
                tags.append("near miss")
                why.append(f"Missed by {miss:g}")
    if leg.is_player and box is not None:
        pf = _player_facts(leg, box)
        facts.update({k: v for k, v in pf.items() if v is not None})
        val = _value(leg, pf)
        if lost and val is not None and leg.line is not None and leg.stat != "anytimeTD" and leg.sign > 0:
            short = leg.line - val
            facts["missed_by"] = round(short, 1)
            if short <= max(1.0, 0.1 * leg.line):
                tags.append("near miss")
                why.append(f"Missed by {short:g}")
        if lost and leg.sign > 0:
            if leg.stat in ("rushYards", "recYards", "passYards"):
                work = {"rushYards": pf["carries"], "recYards": pf["targets"], "passYards": pf["attempts"]}[leg.stat]
                word = {"rushYards": "carries", "recYards": "targets", "passYards": "pass attempts"}[leg.stat]
                needed = (leg.line or 0) / YARDS_PER[leg.stat]
                if work is not None and needed > 0:
                    if work < 0.6 * needed:
                        tags.append("volume")
                        why.append(f"Only {work:g} {word} (a normal rate needed about {needed:.0f})")
                    else:
                        why.append(f"Got {work:g} {word} (about {needed:.0f} needed at a normal rate) for {val:g} yards")
            elif leg.stat == "receptions" and pf["targets"] is not None:
                if pf["targets"] < (leg.line or 0) + 1:
                    tags.append("volume")
                    why.append(f"Only {pf['targets']:g} targets")
                else:
                    why.append(f"{pf['targets']:g} targets but {pf['receptions'] or 0:g} catches")
            elif leg.stat == "anytimeTD":
                touches = (pf["carries"] or 0) + (pf["targets"] or 0)
                others = [s for s in team_scorers if s != player_name_key(leg.player or "")]
                if others:
                    tags.append("TDs went elsewhere")
                    why.append(f"{touches:g} touches, no TD; the team's TDs went to {', '.join(o.title() for o in others)}")
                else:
                    why.append(f"{touches:g} touches, no TD; the team didn't score a rushing/receiving TD")
            if not pf["played"]:
                tags.append("volume")
                why.append("No stats recorded (inactive or barely played)")
    if lost and leg.p_source == "price":
        facts["p_note"] = "chance taken from the price (no fair price was recorded)"
    return {"chance": _bucket(leg.p), "tags": tags, "why": why, "facts": facts}


def review(tickets: Sequence[dict], fetch: Optional[Callable[[str], dict]] = None) -> dict:
    """Post-mortem of every settled leg in ``tickets`` (tracker docs with ids)."""
    from .fetch import espn
    f = _Fetcher(fetch)
    tickets = [dict(t, id=str(t.get("id"))) for t in tickets]
    legs = {t["id"]: slips.legs_of(t) for t in tickets}
    slips.espn_resolver(fetch=f)([x for ls in legs.values() for x in ls if x.event and x.league])
    games: Dict[str, Optional[dict]] = {}
    boxes: Dict[str, Optional[dict]] = {}
    scorers: Dict[str, Dict[str, List[str]]] = {}
    for x in (x for ls in legs.values() for x in ls):
        if not x.event or not x.league or x.event in games:
            continue
        try:
            js = f(espn.summary_url(x.league, x.event))
            games[x.event] = _game_facts(js, x.league)
            boxes[x.event] = parse_box(js)
            by_team: Dict[str, List[str]] = {}
            for t in (js.get("boxscore") or {}).get("players") or []:
                ab = t["team"]["abbreviation"]
                names = {player_name_key(a["athlete"]["displayName"]) for c in t.get("statistics", [])
                         for a in c.get("athletes", [])}
                by_team[ab] = [k for k in boxes[x.event]["td_scorers"] if k in names]
            scorers[x.event] = by_team
        except Exception:  # noqa: BLE001 - review what we can without this game
            games[x.event], boxes[x.event], scorers[x.event] = None, None, {}
    # same-day exposure and within-ticket conflicts
    by_day: Dict[str, List[str]] = {}
    for t in tickets:
        by_day.setdefault(str(t.get("eventDate") or t.get("placedAt", ""))[:10], []).append(t["id"])
    records = []
    labels = {t["id"]: slips.ticket_label(t) for t in tickets}
    if len(set(labels.values())) < len(labels):
        labels = {k: f"{v} ({str(next(t for t in tickets if t['id'] == k).get('eventDate') or k)[:10]})"
                  for k, v in labels.items()}
    for t in tickets:
        ls = legs[t["id"]]
        others = [o for o in by_day.get(str(t.get("eventDate") or t.get("placedAt", ""))[:10], []) if o != t["id"]]
        settled = [x for x in ls if x.result in ("won", "lost")]
        n_lost = sum(1 for x in settled if x.result == "lost")
        for x in settled:
            game = games.get(x.event) if x.event else None
            team_sc = scorers.get(x.event, {}).get(x.team or "", []) if x.event else []
            r = _leg_review(x, game, boxes.get(x.event) if x.event else None, team_sc)
            if x.result == "lost":
                if n_lost == 1 and len(settled) > 1:
                    r["tags"].append("only miss")
                    r["why"].insert(0, "The only leg that missed — it sank the ticket")
                sank, also = set(), set()
                for o in others:
                    for y in legs[o]:
                        if y.identity == x.identity or (x.player and y.player and
                                                        player_name_key(x.player) == player_name_key(y.player)):
                            (sank if y.result == "lost" else also).add(o)
                if sank:
                    r["tags"].append("shared")
                    r["why"].append(f"Also on {', '.join(sorted(labels[o] for o in sank))}, where it lost too — "
                                    "one player sank both tickets")
                elif also:
                    r["tags"].append("same player twice")
                    r["why"].append(f"{x.player or 'This pick'} was also on {', '.join(sorted(labels[o] for o in also))} "
                                    "(that leg didn't lose, but one injury or benching would have sunk both)")
                for y in ls:
                    if y is not x and y.event == x.event:
                        c, _ = slips.pair_corr(x, y)
                        if c <= slips.CONFLICT:
                            r["tags"].append("conflict")
                            r["why"].append(f"Pulled against {y.short()} on the same ticket ({c:+.2f})")
                            break
            if x.result == "lost":
                chance = f"We gave it {x.p:.0%}" + (" (from the price)" if x.p_source == "price" else "")
                r["why"].append(chance + {"long shot": " — a long shot", "coin flip": " — a coin flip"}.get(r["chance"], ""))
            records.append({"id": f"{t['id']}:{x.index}", "ticket": t["id"], "ticket_label": labels[t["id"]], "date": str(t.get("eventDate") or "")[:10],
                            "sport": t.get("sport") or x.league.upper(), "book": t.get("book"), "pick": x.short(),
                            "p": round(x.p, 3), "p_source": x.p_source, "chance": r["chance"], "result": x.result,
                            "team": x.team, "tags": r["tags"], "why": ". ".join(r["why"]) + ("." if r["why"] else ""),
                            "facts": r["facts"]})
    return {"records": records, "summary": summary(records, tickets)}


def _ticket_p(ticket: dict, records: Sequence[dict]) -> float:
    """Pre-game chance the ticket cashed: its recorded fair price, else the product of its legs."""
    if ticket.get("fairProb"):
        return float(ticket["fairProb"])
    p = 1.0
    for r in records:
        if r["ticket"] == str(ticket.get("id")):
            p *= r["p"]
    return p


def summary(records: Sequence[dict], tickets: Sequence[dict] = ()) -> dict:
    """Calibration by chance bucket, tag counts on lost legs, and plain lessons."""
    n = len(records)
    won = sum(1 for r in records if r["result"] == "won")
    exp = sum(r["p"] for r in records)
    cal = []
    for lo, hi, name in BUCKETS:
        rs = [r for r in records if lo <= r["p"] < hi]
        if rs:
            e = sum(r["p"] for r in rs)
            cal.append({"bucket": name, "range": f"{lo:.0%}-{min(hi, 1):.0%}", "legs": len(rs), "expected_wins": round(e, 1),
                        "won": sum(1 for r in rs if r["result"] == "won"),
                        "sd": round(math.sqrt(sum(r["p"] * (1 - r["p"]) for r in rs)), 1)})
    lost = [r for r in records if r["result"] == "lost"]
    counts: Dict[str, int] = {}
    for r in lost:
        for tg in set(r["tags"]):
            counts[tg] = counts.get(tg, 0) + 1
    lessons = []
    for tg in ("shared", "same player twice", "conflict", "game script", "volume", "TDs went elsewhere", "near miss", "upset", "expected loss"):
        if counts.get(tg):
            lessons.append({"tag": tg, "lost_legs": counts[tg], "lesson": LESSONS[tg]})
    settled_t = [t for t in tickets if t.get("status") in ("won", "lost")]
    sd = math.sqrt(sum(r["p"] * (1 - r["p"]) for r in records)) if records else 0.0
    verdict = ("too few legs to judge calibration yet" if n < 100 else
               "legs are winning about as often as we priced them" if abs(won - exp) <= 2 * sd else
               "legs are winning less often than priced: lean harder on the market" if won < exp else
               "legs are winning more often than priced")
    return {"legs": n, "won": won, "expected_wins": round(exp, 1), "sd": round(sd, 1), "calibration": cal,
            "calibration_verdict": verdict, "lost_by_tag": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
            "lessons": lessons, "tickets": len(settled_t),
            "tickets_cashed": sum(1 for t in settled_t if t.get("status") == "won"),
            "tickets_expected": round(sum(_ticket_p(t, records) for t in settled_t), 1) if settled_t else None,
            "note": "Structural lessons (shared legs, conflicts) apply now; result-based ones need a few hundred legs."}
