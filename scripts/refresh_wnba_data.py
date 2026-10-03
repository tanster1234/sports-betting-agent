#!/usr/bin/env python3
"""Rebuild data/wnba/games.csv (and optionally the current-season DraftKings lines).

Sources (MIT, sportsdataverse/wehoop):
  team box + schedules: https://github.com/sportsdataverse/wehoop-wnba-data  (parquet)
  raw ESPN game JSON:   https://github.com/sportsdataverse/wehoop-wnba-raw   (pickcenter = DK open/close)

Requires: pandas, pyarrow (pip install pandas pyarrow) and access to raw.githubusercontent.com.
betlab itself stays dependency-free; only this maintenance script needs pandas.

Usage:
  python3 scripts/refresh_wnba_data.py                 # games 2013..current year
  python3 scripts/refresh_wnba_data.py --lines         # + current-season DK lines (one request per game)
  python3 scripts/refresh_wnba_data.py --first 2018 --last 2026
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import io
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "wnba"
DATA = "https://raw.githubusercontent.com/sportsdataverse/wehoop-wnba-data/main/wnba"
RAW = "https://raw.githubusercontent.com/sportsdataverse/wehoop-wnba-raw/main/wnba/json/raw"
KEEP_TYPES = {"STD", "RD16", "SEMI", "FINAL", "QTR", "CC"}
VAL = re.compile(r"'value':\s*(-?\d+(?:\.\d+)?)")


def _get(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except Exception:  # noqa: BLE001 - retry any transient failure
            if i == tries - 1:
                raise
            time.sleep(2 ** i)
    raise RuntimeError("unreachable")


def _parquet(url: str):
    import pandas as pd
    return pd.read_parquet(io.BytesIO(_get(url)))


def _half(ls):
    if ls is None:
        return None, None
    vals = [float(v) for v in VAL.findall(str(ls))]
    if len(vals) < 4:
        return None, None
    return int(sum(vals[:2])), len(vals)


def build_games(first: int, last: int):
    import pandas as pd
    rows = []
    for yr in range(first, last + 1):
        print(f"season {yr}", file=sys.stderr)
        tb = _parquet(f"{DATA}/team_box/parquet/team_box_{yr}.parquet")
        sc = _parquet(f"{DATA}/schedules/parquet/wnba_schedule_{yr}.parquet")
        sc = sc[sc["status_type_completed"] == True]  # noqa: E712
        for c in ("home_linescores", "away_linescores", "type_abbreviation"):
            if c not in sc.columns:
                sc[c] = None
        keep = ["game_id", "season", "season_type", "game_date", "team_abbreviation", "team_home_away", "team_score",
                "field_goals_attempted", "offensive_rebounds", "free_throws_attempted", "total_turnovers", "turnovers"]
        tb = tb[keep]
        h = tb[tb.team_home_away == "home"].set_index("game_id")
        a = tb[tb.team_home_away == "away"].set_index("game_id")
        g = h.join(a, lsuffix="_h", rsuffix="_a", how="inner")
        s = sc.set_index("game_id")[["neutral_site", "type_abbreviation", "status_period", "home_linescores", "away_linescores"]]
        s.index = s.index.astype(g.index.dtype)
        g = g.join(s, how="left").reset_index()
        for r in g.itertuples():
            gt = r.type_abbreviation if isinstance(r.type_abbreviation, str) else "STD"
            if gt not in KEEP_TYPES:
                continue
            h1, _ = _half(r.home_linescores)
            a1, _ = _half(r.away_linescores)
            poss = []
            for side in ("h", "a"):
                tov = getattr(r, f"total_turnovers_{side}")
                if pd.isna(tov):
                    tov = getattr(r, f"turnovers_{side}")
                poss.append(getattr(r, f"field_goals_attempted_{side}") - getattr(r, f"offensive_rebounds_{side}")
                            + tov + 0.44 * getattr(r, f"free_throws_attempted_{side}"))
            rows.append({
                "game_id": str(r.game_id), "season": int(r.season_h),
                "season_type": "playoff" if int(r.season_type_h) == 3 else "regular", "game_type": gt,
                "date": str(r.game_date_h)[:10], "home": r.team_abbreviation_h, "away": r.team_abbreviation_a,
                "home_pts": int(r.team_score_h), "away_pts": int(r.team_score_a),
                "neutral": int(bool(r.neutral_site) or int(r.season_h) == 2020),
                "periods": int(r.status_period) if not pd.isna(r.status_period) else 4,
                "home_1h": "" if h1 is None else h1, "away_1h": "" if a1 is None else a1,
                "poss": round(sum(poss) / 2, 1) if all(not pd.isna(x) for x in poss) else "",
            })
    df = pd.DataFrame(rows).sort_values(["date", "game_id"])
    df.to_csv(OUT / "games.csv", index=False)
    print(f"wrote {len(df)} games -> {OUT / 'games.csv'}", file=sys.stderr)
    return df


def _num(x):
    if x is None:
        return None
    s = str(x).strip().lstrip("ou")
    if s.upper() == "EVEN":
        return 100.0
    try:
        return float(s)
    except ValueError:
        return None


def _line_row(gid: str):
    d = json.loads(_get(f"{RAW}/{gid}.json"))
    pcs = d.get("pickcenter") or []
    if not pcs:
        return None
    p = pcs[0]
    def g(block, side, oc, key):
        try:
            return _num(p[block][side][oc][key])
        except (KeyError, TypeError):
            return None
    row = {"game_id": gid}
    for oc in ("open", "close"):
        row.update({
            f"spread_home_{oc}": g("pointSpread", "home", oc, "line"),
            f"spread_price_home_{oc}": g("pointSpread", "home", oc, "odds"),
            f"spread_price_away_{oc}": g("pointSpread", "away", oc, "odds"),
            f"total_{oc}": g("total", "over", oc, "line"),
            f"over_price_{oc}": g("total", "over", oc, "odds"),
            f"under_price_{oc}": g("total", "under", oc, "odds"),
            f"ml_home_{oc}": g("moneyline", "home", oc, "odds"),
            f"ml_away_{oc}": g("moneyline", "away", oc, "odds"),
        })
    return row


def build_lines(games_df, season: int):
    import pandas as pd
    gs = games_df[games_df.season == season]
    ids = gs.game_id.astype(str).tolist()
    with cf.ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(_line_row, ids) if r]
    lines = pd.DataFrame(rows)
    meta = gs[["game_id", "date", "season_type", "home", "away", "home_pts", "away_pts"]].astype({"game_id": str})
    out = meta.merge(lines, on="game_id")
    out.insert(7, "book", "DraftKings")
    out = out.dropna(subset=["spread_home_close", "total_close", "ml_home_close"])
    for c in [c for c in out.columns if "price" in c or c.startswith("ml_")]:
        out[c] = out[c].astype(int)
    out.sort_values(["date", "game_id"]).to_csv(OUT / f"lines_{season}_draftkings.csv", index=False)
    print(f"wrote {len(out)} lines -> {OUT / f'lines_{season}_draftkings.csv'}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", type=int, default=2013)
    ap.add_argument("--last", type=int, default=date.today().year)
    ap.add_argument("--lines", action="store_true", help="also fetch DK open/close lines for the last season")
    ap.add_argument("--out", help="output directory (default data/wnba)")
    a = ap.parse_args()
    global OUT
    if a.out:
        OUT = Path(a.out)
    OUT.mkdir(parents=True, exist_ok=True)
    df = build_games(a.first, a.last)
    if a.lines:
        build_lines(df, a.last)


if __name__ == "__main__":
    main()
