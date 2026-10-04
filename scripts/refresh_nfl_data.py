#!/usr/bin/env python3
"""Download NFL games and rebuild the committed NFL pricing calibration.

Source: nflverse/nfldata ``data/games.csv`` (Lee Sharpe / nflverse): every NFL
game since 1999 with final score, closing spread / total / moneylines,
starting QBs, rest, roof and weather.  The file has no licence, so it is
saved to ``data/nfl/games.csv`` (gitignored) and *not* committed; only the
derived calibration (σ and key-number weights — aggregate statistics) is
written to ``data/nfl/calibration.json``.

Standard library only.  Usage:
  python3 scripts/refresh_nfl_data.py                     # download + refit on 2015..last complete season
  python3 scripts/refresh_nfl_data.py --no-download       # refit from the local copy
  python3 scripts/refresh_nfl_data.py --last 2025 --validate-split 2023
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from betlab import nfl  # noqa: E402


def download(dest: Path, tries: int = 4) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for i in range(tries):
        try:
            with urllib.request.urlopen(nfl.NFLVERSE_GAMES_URL, timeout=120) as r:
                body = r.read()
            dest.write_bytes(body)
            return len(body)
        except Exception:  # noqa: BLE001 - retry any transient failure
            if i == tries - 1:
                raise
            time.sleep(2 ** i)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--first", type=int, default=nfl.FIT_FIRST_SEASON)
    ap.add_argument("--last", type=int, help="last season to fit (default: last complete season)")
    ap.add_argument("--validate-split", type=int, default=None,
                    help="also fit on first..SPLIT and score SPLIT+1..last (stored in the calibration)")
    a = ap.parse_args(argv)

    games_path = nfl.data_dir() / "games.csv"
    if not a.no_download:
        n = download(games_path)
        print(f"downloaded {n:,} bytes -> {games_path}")
    games = nfl.load_games(str(games_path))
    seasons = sorted({g["season"] for g in games})
    last = a.last or seasons[-1] - 1          # the newest season is usually still in progress
    cal = nfl.fit_calibration(games, a.first, last)
    cal["fitted"] = date.today().isoformat()
    if a.validate_split:
        cal["validation"] = nfl.validate(games, a.validate_split, a.validate_split + 1, last, a.first)
    out = nfl.data_dir() / "calibration.json"
    out.write_text(json.dumps(cal, indent=1) + "\n")
    print(json.dumps({k: v for k, v in cal.items() if k not in ("margin", "total")}, indent=1))
    print(f"margin sigma {cal['margin']['sigma']}, total sigma {cal['total']['sigma']} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
