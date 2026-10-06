#!/usr/bin/env python3
"""Download MLB games with closing odds and rebuild the committed MLB pricing calibration.

Sources (no key needed):
  * ESPN scoreboard, one call per date: final scores, runs by inning, regular season vs
    postseason.
  * ESPN odds, one call per game: the sportsbook ESPN shows for that game (DraftKings in
    2026, ESPN BET in 2024-25, the consensus line in 2023) — closing moneyline, run line and
    total with prices, plus the opener.

The raw table goes to ``data/mlb/games.csv`` (gitignored; it is ESPN's data); only the fitted
aggregate numbers are written to ``data/mlb/calibration.json``.

Standard library only.  Usage:
  python3 scripts/refresh_mlb_data.py                        # download 2023..today (resumes) + refit
  python3 scripts/refresh_mlb_data.py --no-download          # refit from the local copy
  python3 scripts/refresh_mlb_data.py --first 2023 --test-from 2026-01-01
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from betlab import mlb  # noqa: E402

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates={d}&limit=40"
ODDS = "https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/events/{e}/competitions/{e}/odds"
PROVIDERS = ("DraftKings", "ESPN BET", "consensus", "DraftKings (old)", "Caesars Sportsbook", "MGM", "Bet365")


def get_json(url: str, tries: int = 4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "betlab/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001 - retry any transient failure
            if i == tries - 1:
                return None
            time.sleep(1.5 * 2 ** i)
    return None


def day_games(d: date) -> list:
    js = get_json(SCOREBOARD.format(d=d.strftime("%Y%m%d")))
    out = []
    for e in (js or {}).get("events", []):
        season = e.get("season", {})
        comp = e["competitions"][0]
        st = comp["status"]["type"]
        if season.get("type") not in (2, 3) or not st.get("completed") or st.get("name") != "STATUS_FINAL":
            continue
        side = {c["homeAway"]: c for c in comp["competitors"]}
        if set(side) != {"home", "away"}:
            continue
        ls = {k: [int(float(x.get("value", 0) or 0)) for x in side[k].get("linescores", [])] for k in side}
        notes = "; ".join(n.get("headline", "") for n in comp.get("notes", []))
        out.append({
            "season": season.get("year"), "season_type": "post" if season.get("type") == 3 else "regular",
            "date": e["date"][:10], "event_id": e["id"],
            "away": side["away"]["team"]["abbreviation"], "home": side["home"]["team"]["abbreviation"],
            "away_score": int(float(side["away"].get("score", 0))), "home_score": int(float(side["home"].get("score", 0))),
            "innings": comp["status"].get("period"), "away_ls": ";".join(map(str, ls["away"])),
            "home_ls": ";".join(map(str, ls["home"])), "notes": notes,
        })
    return out


def _american(node, *path):
    for p in path:
        if not isinstance(node, dict):
            return None
        node = node.get(p)
    try:
        return float(str(node).replace("+", "")) if node not in (None, "", "OFF", "EVEN") else (100.0 if node == "EVEN" else None)
    except ValueError:
        return None


def game_odds(event_id: str) -> dict:
    js = get_json(ODDS.format(e=event_id))
    items = [i for i in (js or {}).get("items", []) if "Live" not in i.get("provider", {}).get("name", "")]
    if not items:
        return {}
    rank = {p: i for i, p in enumerate(PROVIDERS)}
    it = min(items, key=lambda i: rank.get(i["provider"]["name"], 99))
    h, a = it.get("homeTeamOdds", {}), it.get("awayTeamOdds", {})
    close_total = _american(it, "close", "total", "american")
    if close_total is None or not 4 <= close_total <= 20:      # some 2023 rows carry a price here
        close_total = it.get("overUnder")
    rl_line = _american(h, "close", "pointSpread", "american")
    rl_ok = rl_line is not None and 0.5 <= abs(rl_line) <= 3.5
    open_total = _american(it, "open", "total", "american")
    row = {
        "provider": it["provider"]["name"],
        "total": close_total,
        "over": _american(it, "close", "over", "american") or it.get("overOdds"),
        "under": _american(it, "close", "under", "american") or it.get("underOdds"),
        "ml_away": _american(a, "close", "moneyLine", "american") or a.get("moneyLine"),
        "ml_home": _american(h, "close", "moneyLine", "american") or h.get("moneyLine"),
        "rl_line_home": rl_line if rl_ok else None,
        "rl_home": _american(h, "close", "spread", "american") if rl_ok else None,
        "rl_away": _american(a, "close", "spread", "american") if rl_ok else None,
        "open_total": open_total if open_total is not None and 4 <= open_total <= 20 else None,
        "open_ml_away": _american(a, "open", "moneyLine", "american"),
        "open_ml_home": _american(h, "open", "moneyLine", "american"),
    }
    if not row["ml_home"] or not row["ml_away"] or not row["total"]:
        return {}
    return row


FIELDS = ["season", "season_type", "date", "event_id", "away", "home", "away_score", "home_score", "innings",
          "away_ls", "home_ls", "notes", "provider", "total", "over", "under", "ml_away", "ml_home",
          "rl_line_home", "rl_home", "rl_away", "open_total", "open_ml_away", "open_ml_home"]


def download(path: Path, first: int, last_day: date, workers: int = 16) -> int:
    have = {}
    if path.exists():
        with open(path, newline="") as f:
            have = {r["event_id"]: r for r in csv.DictReader(f)}
    days = [d for y in range(first, last_day.year + 1)
            for d in (date(y, 3, 15) + timedelta(n) for n in range(236)) if d <= last_day]
    with ThreadPoolExecutor(workers) as ex:
        games = [g for day in ex.map(day_games, days) for g in day]
    todo = [g for g in games if g["event_id"] not in have]
    print(f"{len(games):,} final games 2023+ on ESPN; {len(todo):,} new to fetch odds for", flush=True)
    with ThreadPoolExecutor(workers) as ex:
        for g, o in zip(todo, ex.map(lambda g: game_odds(g["event_id"]), todo)):
            if o:
                have[g["event_id"]] = {**g, **o}
    rows = sorted(have.values(), key=lambda r: (r["date"], r["event_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--first", type=int, default=mlb.FIT_FIRST_SEASON)
    ap.add_argument("--test-from", default=mlb.TEST_FROM, help="games on/after this date are held out")
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args(argv)

    path = mlb.data_dir() / "games.csv"
    if not a.no_download:
        n = download(path, a.first, date.today() - timedelta(1), a.workers)
        print(f"{n:,} games with closing odds -> {path}", flush=True)
    rows = mlb.load_games(str(path))
    cal = mlb.build_calibration(rows, a.test_from)
    cal["source"] = {"games": "ESPN scoreboard + ESPN odds (closing line of the book ESPN shows)",
                     "seasons": f"{a.first}-{rows[-1]['date'][:4]}", "n_games": len(rows),
                     "last_game": rows[-1]["date"], "fitted": date.today().isoformat()}
    out = mlb.data_dir() / "calibration.json"
    out.write_text(json.dumps(cal, indent=1) + "\n")
    print(json.dumps(cal.get("validation", {}).get("summary", {}), indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
