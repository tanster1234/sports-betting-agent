"""WNBA presets, team metadata and bundled-data helpers.

Bundled data (see data/README.md for provenance, all derived from ESPN via
the MIT-licensed sportsdataverse/wehoop project):

* data/wnba/games.csv                 3,318 games, 2013 - 2026 playoffs (to Oct 1, 2026)
* data/wnba/lines_2026_draftkings.csv DraftKings open + close spread/total/ML, 340 games of 2026

Calibrated facts used across the skills (.claude/skills/wnba-betting/references/calibration.md):
* margin SD vs DK close 12.7; totals SD vs close 18.7 (2026)
* modern HCA ~1.75 pts (2021-26 pooled 1.4-1.7; 2013-19 was ~2.9)
* back-to-back penalty ~2.3 +/- 1.0 pts (B2Bs are only 2-5% of team-games)
* 2026 scoring regime: 87.1 ppg, ORtg ~104.8, FT rate +12% (officiating
  emphasis on freedom of movement) — totals models must adapt in-season.
"""

from __future__ import annotations

import csv
import math
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .ratings import KalmanRatings, Prediction, RatingParams, _to_date

# Franchise continuity for ratings carry-over: old ESPN code -> current code.
ALIASES: Dict[str, str] = {"CONN": "CON", "TUL": "DAL", "SA": "LV", "SAN": "LV", "WAS": "WSH", "LAS": "LA",
                           "NYL": "NY", "PHO": "PHX", "GSV": "GS", "LVA": "LV"}

# 2026 alignment (15 teams: East 7, West 8).  ESPN team ids verified 2026.
TEAMS: Dict[str, dict] = {
    "ATL": {"name": "Atlanta Dream", "conf": "East", "tz": "America/New_York", "espn_id": 20},
    "CHI": {"name": "Chicago Sky", "conf": "East", "tz": "America/Chicago", "espn_id": 19},
    "CON": {"name": "Connecticut Sun", "conf": "East", "tz": "America/New_York", "espn_id": 18,
            "note": "Sold; relocates to Houston (Comets) for 2027"},
    "IND": {"name": "Indiana Fever", "conf": "East", "tz": "America/Indiana/Indianapolis", "espn_id": 5},
    "NY": {"name": "New York Liberty", "conf": "East", "tz": "America/New_York", "espn_id": 9},
    "TOR": {"name": "Toronto Tempo", "conf": "East", "tz": "America/Toronto", "espn_id": 131935, "since": 2026},
    "WSH": {"name": "Washington Mystics", "conf": "East", "tz": "America/New_York", "espn_id": 16},
    "DAL": {"name": "Dallas Wings", "conf": "West", "tz": "America/Chicago", "espn_id": 3},
    "GS": {"name": "Golden State Valkyries", "conf": "West", "tz": "America/Los_Angeles", "espn_id": 129689, "since": 2025},
    "LA": {"name": "Los Angeles Sparks", "conf": "West", "tz": "America/Los_Angeles", "espn_id": 6},
    "LV": {"name": "Las Vegas Aces", "conf": "West", "tz": "America/Los_Angeles", "espn_id": 17},
    "MIN": {"name": "Minnesota Lynx", "conf": "West", "tz": "America/Chicago", "espn_id": 8},
    "PHX": {"name": "Phoenix Mercury", "conf": "West", "tz": "America/Phoenix", "espn_id": 11},
    "POR": {"name": "Portland Fire", "conf": "West", "tz": "America/Los_Angeles", "espn_id": 132052, "since": 2026},
    "SEA": {"name": "Seattle Storm", "conf": "West", "tz": "America/Los_Angeles", "espn_id": 14},
}

# Tuned on 2014-2025 (out-of-sample log-likelihood), HCA set from 2021-26.
WNBA_PARAMS = RatingParams(hca=1.75, sigma=12.0, q=0.05, v0=12.0, rho=0.6, mu_new=0.0, v_new=20.0, cap=2.5,
                           sigma_t=15.5, q_t=0.05, v0_t=15.0, rho_t=0.6, vL0=5.0, qL=0.05,
                           b2b_penalty=2.3, playoff_hca_extra=0.0, var_halflife=None, var_halflife_total=100.0)

PLAYOFF_FORMATS = {"first_round": "1-1-1", "semifinals": "2-2-1", "finals": "2-2-1-1-1"}


def data_dir() -> Path:
    env = os.environ.get("BETLAB_DATA")
    if env:
        return Path(env) / "wnba"
    return Path(__file__).resolve().parent.parent / "data" / "wnba"


def canonical(team: str) -> str:
    t = team.strip().upper()
    return ALIASES.get(t, t)


def load_games(path: Optional[str] = None, seasons: Optional[Sequence[int]] = None,
               include_playoffs: bool = True) -> List[dict]:
    p = Path(path) if path else data_dir() / "games.csv"
    out = []
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            r["season"] = int(r["season"])
            if seasons is not None and r["season"] not in seasons:
                continue
            if not include_playoffs and r.get("season_type") == "playoff":
                continue
            r["home_pts"], r["away_pts"] = int(r["home_pts"]), int(r["away_pts"])
            r["neutral"] = int(r.get("neutral") or 0)
            r["home"], r["away"] = canonical(r["home"]), canonical(r["away"])
            out.append(r)
    return out


def load_lines(path: Optional[str] = None) -> List[dict]:
    p = Path(path) if path else data_dir() / "lines_2026_draftkings.csv"
    out = []
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            for k, v in list(r.items()):
                if k in ("game_id", "date", "season_type", "home", "away", "book"):
                    continue
                r[k] = float(v) if v not in ("", None) else None
            r["home"], r["away"] = canonical(r["home"]), canonical(r["away"])
            out.append(r)
    return out


def fit_model(games: Optional[Iterable[dict]] = None, until: Optional[str] = None,
              params: Optional[RatingParams] = None) -> KalmanRatings:
    """Fit the WNBA rating model on games strictly before ``until`` (ISO date)."""
    gs = list(games) if games is not None else load_games()
    if until:
        cut = _to_date(until)
        gs = [g for g in gs if _to_date(g["date"]) < cut]
    return KalmanRatings(params or WNBA_PARAMS, aliases=ALIASES).fit(gs)


def predict(model: KalmanRatings, home: str, away: str, game_date: str, playoff: bool = False,
            neutral: bool = False, **kw) -> Prediction:
    return model.predict(canonical(home), canonical(away), game_date, season=_to_date(game_date).year,
                         playoff=playoff, neutral=neutral, **kw)


# ---------------------------------------------------------------------------
# Calibration helpers (stdlib re-implementation of .claude/skills/wnba-betting/references/calibration.md)
# ---------------------------------------------------------------------------

def _solve(A: List[List[float]], b: List[float]) -> List[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            raise ValueError("singular system")
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                if f:
                    for k in range(c, n + 1):
                        M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def fit_hca_ols(games: Sequence[dict]) -> dict:
    """OLS: margin = HCA * home_flag + r_home - r_away, sum(r) = 0.

    Returns HCA, its standard error and the residual SD for one season (or
    any set of games where team strengths are roughly constant).
    """
    teams = sorted({g["home"] for g in games} | {g["away"] for g in games})
    idx = {t: i for i, t in enumerate(teams)}
    k = len(teams)
    # Parameters: r_0..r_{k-2} (r_{k-1} = -sum), hca  => k unknowns
    def row(g):
        x = [0.0] * k
        for t, s in ((g["home"], 1.0), (g["away"], -1.0)):
            i = idx[t]
            if i < k - 1:
                x[i] += s
            else:
                for j in range(k - 1):
                    x[j] -= s
        x[k - 1] = 0.0 if int(g.get("neutral", 0) or 0) else 1.0
        return x
    X = [row(g) for g in games]
    y = [float(g["home_pts"]) - float(g["away_pts"]) for g in games]
    XtX = [[sum(X[r][i] * X[r][j] for r in range(len(X))) for j in range(k)] for i in range(k)]
    Xty = [sum(X[r][i] * y[r] for r in range(len(X))) for i in range(k)]
    beta = _solve(XtX, Xty)
    resid = [y[r] - sum(X[r][j] * beta[j] for j in range(k)) for r in range(len(X))]
    dof = max(1, len(X) - k)
    s2 = sum(e * e for e in resid) / dof
    # variance of hca = s2 * (XtX^-1)[k-1][k-1]
    e_last = [0.0] * k
    e_last[k - 1] = 1.0
    inv_col = _solve(XtX, e_last)
    return {"hca": beta[k - 1], "hca_se": math.sqrt(s2 * inv_col[k - 1]), "resid_sd": math.sqrt(s2), "n": len(X), "teams": k}


def season_summary(games: Sequence[dict]) -> List[dict]:
    by: Dict[int, List[dict]] = {}
    for g in games:
        if g.get("season_type", "regular") != "regular":
            continue
        by.setdefault(int(g["season"]), []).append(g)
    out = []
    for s, gs in sorted(by.items()):
        tot = [g["home_pts"] + g["away_pts"] for g in gs]
        mar = [g["home_pts"] - g["away_pts"] for g in gs if not int(g.get("neutral", 0) or 0)]
        n = len(tot)
        mt = sum(tot) / n
        sd_t = math.sqrt(sum((t - mt) ** 2 for t in tot) / (n - 1))
        ot = sum(int(g.get("periods") or 4) > 4 for g in gs) / n
        poss = [float(g["poss"]) for g in gs if g.get("poss") not in (None, "")]
        row = {"season": s, "games": n, "avg_total": round(mt, 1), "total_sd": round(sd_t, 1),
               "home_margin": round(sum(mar) / len(mar), 2) if mar else None,
               "home_win_pct": round(sum(m > 0 for m in mar) / len(mar), 3) if mar else None,
               "ot_rate": round(ot, 3)}
        if poss:
            row["ortg"] = round(100 * sum(tot) / (2 * sum(poss)), 1)
        try:
            h = fit_hca_ols(gs)
            row["hca_ols"], row["hca_se"], row["resid_sd"] = round(h["hca"], 2), round(h["hca_se"], 2), round(h["resid_sd"], 2)
        except ValueError:
            pass
        out.append(row)
    return out
