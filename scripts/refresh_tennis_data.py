#!/usr/bin/env python3
"""Download tennis results and odds, then rebuild the committed tennis calibration.

Sources (downloaded to data/tennis/, gitignored — not committed):
  * ATP 2000-2026 and WTA 2007-2025 main-tour results with pre-match bookmaker odds
    (tennis-data.co.uk, compiled in the Kaggle "dissfya" daily-pull datasets) via Hugging Face
    mirrors: groundhog2107/atp_tennis and Nevoreuven/tennis-betting-odds-model.
  * Jeff Sackmann's ATP/WTA match files (serve statistics, and results past the odds files'
    end date) via the Aneeshers/tennis-sackmann-archive Hugging Face mirror.
    Tennis databases, files, and algorithms by Jeff Sackmann / Tennis Abstract, CC BY-NC-SA 4.0
    (https://github.com/JeffSackmann).

Only aggregate, derived numbers are written to data/tennis/calibration.json (serve-point rates,
the fitted form variation, validation results).  Standard library only.  Usage:
  python3 scripts/refresh_tennis_data.py                 # download + fit + validate
  python3 scripts/refresh_tennis_data.py --no-download   # refit from the local copies
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

from betlab import tennis  # noqa: E402

HF = "https://huggingface.co/datasets"
ODDS = {"atp": f"{HF}/groundhog2107/atp_tennis/resolve/main/atp_tennis.csv",
        "wta": f"{HF}/Nevoreuven/tennis-betting-odds-model/resolve/main/wta%20(1).csv"}
SACKMANN = HF + "/Aneeshers/tennis-sackmann-archive/resolve/main/{tour}/{tour}_matches_{year}.csv"
SERVE_YEARS = range(2019, 2027)
FORM_GRID = (0.0, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14)


def download(url: str, dest: Path, tries: int = 4) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
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
    ap.add_argument("--fit-from", default="2019", help="first season used to fit the form variation")
    ap.add_argument("--test-from", default="2024", help="first season held out for validation")
    ap.add_argument("--elo-test-from", default="2023-01-01")
    a = ap.parse_args(argv)
    d = tennis.data_dir()
    if not a.no_download:
        for tour, url in ODDS.items():
            print(f"{tour} odds: {download(url, d / f'{tour}_odds.csv'):,} bytes")
        for tour in ("atp", "wta"):
            for y in SERVE_YEARS:
                try:
                    download(SACKMANN.format(tour=tour, year=y), d / "sackmann" / f"{tour}_matches_{y}.csv")
                except Exception as exc:  # noqa: BLE001 - a missing year is fine
                    print(f"  {tour} {y}: {exc}")
    cal = {"fitted": date.today().isoformat(), "sources": {
        "odds": "tennis-data.co.uk results + bookmaker odds (Kaggle dissfya daily pull) via Hugging Face mirrors",
        "stats": "Jeff Sackmann / Tennis Abstract match files (CC BY-NC-SA 4.0) via Hugging Face mirror"},
        "serve_level": {}, "form_sd": {}, "fit": {}, "validation": {}, "elo": {}, "coverage": {}}
    for tour in ("atp", "wta"):
        rows = tennis.load_matches(tour)
        sack = tennis.load_sackmann(tour, SERVE_YEARS)
        cal["coverage"][tour] = {"odds_matches": len(rows), "odds_first": rows[0]["date"], "odds_last": rows[-1]["date"],
                                 "results_last": sack[-1]["date"] if sack else None}
        rates = tennis.serve_rates(sack)
        cal["serve_level"][tour] = {s: v["rate"] for s, v in rates.items() if s in ("hard", "clay", "grass")}
        cal["serve_level"][tour].setdefault("carpet", cal["serve_level"][tour].get("hard"))
        cal["form_sd"][tour], cal["fit"][tour], cal["validation"][tour] = {}, {}, {}
        for surf in ("hard", "clay", "grass"):
            lvl = cal["serve_level"][tour][surf]
            base = [r for r in rows if r["surface"] == surf and r["best_of"] == 3 and r["complete"]]
            fit_rows = [r for r in base if a.fit_from <= r["date"] < a.test_from]
            test_rows = [r for r in base if r["date"] >= a.test_from]
            fit = tennis.fit_serve_levels(fit_rows, [lvl], FORM_GRID)
            cal["form_sd"][tour][surf] = fit["form_sd"]
            cal["fit"][tour][surf] = fit
            cal["validation"][tour][surf] = tennis.validate_totals(test_rows, lvl, fit["form_sd"])
            print(tour, surf, "level", lvl, "form sd", fit["form_sd"], "test", cal["validation"][tour][surf]["mean_games"])
        if tour == "atp":
            slams = [r for r in rows if r["best_of"] == 5 and r["complete"] and r["date"] >= "2022"]
            cal["validation"]["atp_best_of_5"] = tennis.validate_totals(slams, cal["serve_level"]["atp"]["hard"],
                                                                         cal["form_sd"]["atp"]["hard"], by_surface=cal)
        cal["elo"][tour] = tennis.validate_elo(rows, a.elo_test_from)
        print(tour, "elo", cal["elo"][tour]["elo"], "market", cal["elo"][tour]["market"])
    out = d / "calibration.json"
    out.write_text(json.dumps(cal, indent=1) + "\n")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
