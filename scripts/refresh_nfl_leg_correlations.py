#!/usr/bin/env python3
"""Measure how NFL player props move with the game script and with each other.

Used by ``betlab slips`` to tell whether the legs of a parlay need the same game to happen, and
how tickets that share a game win or lose together.

Data: nflverse weekly player stats (``stats_player_week_<season>.csv`` from the nflverse-data
releases) joined to nflverse game results with closing spread and total (``data/nfl/games.csv``,
downloaded by ``scripts/refresh_nfl_data.py``).  Raw files go to ``data/nfl/player_stats/``
(gitignored); only the aggregate correlations are written to ``data/nfl/leg_correlations.json``.

Method (regular season):
  * Game script per team-game: z_margin = (team margin - closing spread expectation) / sd and
    z_total = (total - closing total) / sd.
  * Each player's stat in a game is compared with his own average over his *other* games that
    season (a stand-in for the prop line), and turned into a normal score within its group
    (stat x position).  Touchdown props are yes/no and converted to the same latent scale.
  * Loadings = correlation of a prop with z_margin (own team) and z_total.  Pair correlations are
    measured for the same player, teammates and opponents in the same game; "beyond_script" is
    what's left after the game-script part.

Roles (by the player's average in his other games): QB 20+ pass attempts, RB 8+ carries,
WR 4+ targets, TE 3+ targets; players with 6+ games in a season.

Standard library only.  Usage:
  python3 scripts/refresh_nfl_leg_correlations.py                 # download 2021..2025 + fit
  python3 scripts/refresh_nfl_leg_correlations.py --no-download
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from betlab import nfl  # noqa: E402

URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{y}.csv"
ND = NormalDist()
STATS = {"pass_yds": "passing_yards", "rush_yds": "rushing_yards", "receptions": "receptions", "rec_yds": "receiving_yards"}
MIN_PAIR_N = 300


def download(dest: Path, years, tries: int = 4) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for y in years:
        for i in range(tries):
            try:
                with urllib.request.urlopen(URL.format(y=y), timeout=180) as r:
                    (dest / f"stats_player_week_{y}.csv").write_bytes(r.read())
                break
            except Exception:  # noqa: BLE001 - retry any transient failure
                if i == tries - 1:
                    raise
                time.sleep(2 ** i)


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def game_factors(games_csv: Path):
    games = {}
    with open(games_csv, newline="") as f:
        for g in csv.DictReader(f):
            if g.get("game_type", "REG") != "REG" or "NA" in (g["home_score"], g["spread_line"], g["total_line"]) \
                    or "" in (g["home_score"], g["spread_line"], g["total_line"]):
                continue
            games[g["game_id"]] = g
    res_m = {gid: _f(g["home_score"]) - _f(g["away_score"]) - _f(g["spread_line"]) for gid, g in games.items()}
    res_t = {gid: _f(g["home_score"]) + _f(g["away_score"]) - _f(g["total_line"]) for gid, g in games.items()}
    sd_m, sd_t = statistics.pstdev(res_m.values()), statistics.pstdev(res_t.values())
    fac = {}
    for gid, g in games.items():
        zm, zt = res_m[gid] / sd_m, res_t[gid] / sd_t
        fac[(gid, g["home_team"])] = (zm, zt)
        fac[(gid, g["away_team"])] = (-zm, zt)
    corr = statistics.correlation(list(res_m.values()), list(res_t.values()))
    return fac, {"sd_margin_resid": round(sd_m, 2), "sd_total_resid": round(sd_t, 2), "margin_total_corr": round(corr, 3)}


def observations(stats_dir: Path, years, fac):
    rows = []
    for y in years:
        with open(stats_dir / f"stats_player_week_{y}.csv", newline="") as f:
            rows += [r for r in csv.DictReader(f) if r["season_type"] == "REG"]
    by_ps = defaultdict(list)
    for r in rows:
        by_ps[(r["player_id"], r["season"])].append(r)
    obs = defaultdict(list)                       # (stat, pos) -> [(game, team, player, residual, td_flag)]
    for lst in by_ps.values():
        if len(lst) < 6:
            continue
        n, pos = len(lst), lst[0]["position"]
        tot = {k: sum(_f(r[v]) for r in lst) for k, v in STATS.items()}
        for k in ("carries", "targets", "attempts"):
            tot[k] = sum(_f(r[k]) for r in lst)
        tot["td"] = sum(1 for r in lst if _f(r["rushing_tds"]) + _f(r["receiving_tds"]) > 0)
        for r in lst:
            if (r["game_id"], r["team"]) not in fac:
                continue

            def loo(k, col=None):
                return (tot[k] - _f(r[col or k])) / (n - 1)
            roles = []
            if pos == "QB" and loo("attempts") >= 20:
                roles += ["pass_yds/QB", "rush_yds/QB"]
            if pos == "RB" and loo("carries") >= 8:
                roles += ["rush_yds/RB", "receptions/RB", "rec_yds/RB", "td/RB"]
            if pos == "WR" and loo("targets") >= 4:
                roles += ["receptions/WR", "rec_yds/WR", "td/WR"]
            if pos == "TE" and loo("targets") >= 3:
                roles += ["receptions/TE", "rec_yds/TE", "td/TE"]
            for role in roles:
                st = role.split("/")[0]
                if st == "td":
                    v = 1.0 if _f(r["rushing_tds"]) + _f(r["receiving_tds"]) > 0 else 0.0
                    obs[role].append((r["game_id"], r["team"], r["player_id"], v, v))
                else:
                    obs[role].append((r["game_id"], r["team"], r["player_id"], _f(r[STATS[st]]) - loo(st, STATS[st]), None))
    return obs, len(rows)


def latent_values(obs):
    """Normal scores for continuous stats; 0/1 for touchdowns (rescaled when correlated)."""
    out = {}
    for k, lst in obs.items():
        if k.startswith("td/"):
            out[k] = [(o[0], o[1], o[2], o[4]) for o in lst]
            continue
        order = sorted(range(len(lst)), key=lambda i: lst[i][3])
        u = [0.0] * len(lst)
        for rank, i in enumerate(order):
            u[i] = ND.inv_cdf((rank + 0.5) / len(lst))
        out[k] = [(o[0], o[1], o[2], u[i]) for i, o in enumerate(lst)]
    return out


def _to_latent(r: float, key: str, vals) -> float:
    """Point-biserial / phi correlation of a yes/no prop -> correlation on the latent normal scale."""
    if key.startswith("td/"):
        p = sum(vals) / len(vals)
        r = r * math.sqrt(p * (1 - p)) / ND.pdf(ND.inv_cdf(p))
    return r


def fit(lat, fac):
    loads = {}
    for k, lst in lat.items():
        zm = [fac[(o[0], o[1])][0] for o in lst]
        zt = [fac[(o[0], o[1])][1] for o in lst]
        v = [o[3] for o in lst]
        loads[k] = {"margin": round(_to_latent(statistics.correlation(v, zm), k, v), 3),
                    "total": round(_to_latent(statistics.correlation(v, zt), k, v), 3), "n": len(lst)}
    by_game = defaultdict(list)
    for k, lst in lat.items():
        for gid, team, pid, val in lst:
            by_game[gid].append((k, team, pid, val))
    acc = defaultdict(lambda: ([], []))
    for items in by_game.values():
        for i, (ka, ta, pa, va) in enumerate(items):
            for kb, tb, pb, vb in items[i + 1:]:
                if pa == pb and ka == kb:
                    continue
                rel = "same_player" if pa == pb else "teammate" if ta == tb else "opponent"
                k1, v1, k2, v2 = (ka, va, kb, vb) if ka <= kb else (kb, vb, ka, va)
                x, y = acc[(rel, k1, k2)]
                x.append(v1)
                y.append(v2)
    pairs = {"same_player": {}, "teammate": {}, "opponent": {}}
    for (rel, ka, kb), (x, y) in acc.items():
        if len(x) < MIN_PAIR_N or statistics.pstdev(x) == 0 or statistics.pstdev(y) == 0:
            continue
        r = _to_latent(_to_latent(statistics.correlation(x, y), ka, x), kb, y)
        sign = -1 if rel == "opponent" else 1
        script = loads[ka]["margin"] * loads[kb]["margin"] * sign + loads[ka]["total"] * loads[kb]["total"]
        pairs[rel][f"{ka}|{kb}"] = {"corr": round(r, 3), "beyond_script": round(r - script, 3), "n": len(x)}
    return loads, pairs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--first", type=int, default=2021)
    ap.add_argument("--last", type=int, default=2025)
    a = ap.parse_args(argv)
    years = range(a.first, a.last + 1)
    stats_dir = nfl.data_dir() / "player_stats"
    if not a.no_download:
        download(stats_dir, years)
    fac, game_meta = game_factors(nfl.data_dir() / "games.csv")
    obs, n_rows = observations(stats_dir, years, fac)
    loads, pairs = fit(latent_values(obs), fac)
    out = {"fitted": date.today().isoformat(), "seasons": f"{a.first}-{a.last}", "n_player_games": n_rows,
           **game_meta, "roles": "QB 20+ attempts, RB 8+ carries, WR 4+ targets, TE 3+ targets (average of his other games)",
           "loadings": dict(sorted(loads.items())), "pairs": {k: dict(sorted(v.items())) for k, v in pairs.items()},
           "source": "nflverse weekly player stats + nflverse games (closing spread/total)"}
    path = nfl.data_dir() / "leg_correlations.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out["loadings"], indent=1))
    print(f"{sum(len(v) for v in pairs.values())} pair types -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
