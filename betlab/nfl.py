"""NFL pricing from the market line, with real key numbers.

NFL final margins are lumpy: about 15% of games end on exactly 3 points and
9% on 7, then 6, 14, 10 and 4.  A normal curve spreads that mass evenly, so
it misprices exactly the things books sell around the main line: alternate
spreads, teasers through 3 and 7, half-points, and spread <-> moneyline
conversions.  This module fits a *key-number-weighted normal*:

    P(favourite margin = k | spread f)  ∝  φ((k - f) / σ) · w(k)

where σ is the spread of results around the closing line and w(k) is a
per-margin weight fitted by iterative proportional scaling so that, summed
over all games, the model reproduces how often each margin happens.  Totals
use the same form with weights on total points (37, 41, 44, 47, 51 ...).

The fit uses closing lines and results since 2015 (the extra-point rule
change moved margin frequencies) from the nflverse games file
(https://github.com/nflverse/nfldata, ``data/games.csv``).  That file carries
no licence, so it is not redistributed: ``scripts/refresh_nfl_data.py``
downloads it to ``data/nfl/games.csv`` (gitignored) and rebuilds the small
committed table ``data/nfl/calibration.json`` (σ and weights — aggregate
statistics only) that pricing uses at run time.

This prices *derivative* markets from a main line you trust (best: the
sharp consensus).  It does not predict games; an NFL ratings model is a
separate problem and closing NFL spreads are very hard to beat.
"""

from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path
from statistics import NormalDist
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .distributions import DiscreteDist
from .markets import MarginModel
from .odds import american_to_decimal, decimal_to_american, devig

NFLVERSE_GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
MARGIN_SUPPORT = range(-60, 71)        # favourite's margin
TOTAL_SUPPORT = range(0, 126)          # total points
FIT_FIRST_SEASON = 2015                # extra-point rule change


def data_dir() -> Path:
    env = os.environ.get("BETLAB_DATA")
    if env:
        return Path(env) / "nfl"
    return Path(__file__).resolve().parent.parent / "data" / "nfl"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _f(x: str) -> Optional[float]:
    try:
        return float(x) if x not in ("", "NA", None) else None
    except ValueError:
        return None


def load_games(path: Optional[str] = None, completed_only: bool = True) -> List[dict]:
    """nflverse games.csv -> rows in betlab conventions.

    ``home_spread`` is negative when the home team is favoured (nflverse's
    ``spread_line`` has the opposite sign).  ``margin`` = home - away.
    """
    p = Path(path) if path else data_dir() / "games.csv"
    if not p.exists():
        raise FileNotFoundError(f"{p} not found — run `python3 scripts/refresh_nfl_data.py` to download it")
    out = []
    with open(p, newline="") as fh:
        for r in csv.DictReader(fh):
            hs, as_ = _f(r.get("home_score", "")), _f(r.get("away_score", ""))
            if completed_only and (hs is None or as_ is None):
                continue
            sl, tl = _f(r.get("spread_line", "")), _f(r.get("total_line", ""))
            out.append({
                "game_id": r.get("game_id"), "season": int(r["season"]), "week": int(_f(r.get("week", "")) or 0),
                "game_type": r.get("game_type"), "date": r.get("gameday"),
                "home": r.get("home_team"), "away": r.get("away_team"),
                "home_score": hs, "away_score": as_,
                "margin": None if hs is None else hs - as_, "total": None if hs is None else hs + as_,
                "home_spread": None if sl is None else -sl, "total_line": tl,
                "home_ml": _f(r.get("home_moneyline", "")), "away_ml": _f(r.get("away_moneyline", "")),
                "neutral": r.get("location") == "Neutral", "roof": r.get("roof"),
                "wind": _f(r.get("wind", "")), "temp": _f(r.get("temp", "")),
                "home_rest": _f(r.get("home_rest", "")), "away_rest": _f(r.get("away_rest", "")),
                "home_qb": r.get("home_qb_name"), "away_qb": r.get("away_qb_name"),
                "div_game": r.get("div_game") == "1",
            })
    return out


def favourite_view(home_spread: float, margin: float) -> Tuple[float, int]:
    """(favourite's spread magnitude, favourite's margin).  Pick'em uses the home side."""
    f = abs(home_spread)
    fm = -margin if home_spread > 0 else margin
    return f, int(round(fm))


# ---------------------------------------------------------------------------
# Fitting: key-number-weighted normal by iterative proportional scaling
# ---------------------------------------------------------------------------

def _normal_masses(center: float, sigma: float, support: Sequence[int]) -> List[float]:
    nd = NormalDist(center, sigma)
    return [nd.cdf(k + 0.5) - nd.cdf(k - 0.5) for k in support]


def fit_weights(obs: Sequence[Tuple[float, int]], sigma: float, support: Sequence[int],
                iters: int = 60, alpha: float = 2.0, min_count: int = 15,
                bounds: Tuple[float, float] = (0.05, 10.0), always_fit: Sequence[int] = ()) -> List[float]:
    """Weights w(k) so that Σ_games P_model(k) matches the observed count of k.

    ``obs`` is (centre, observed integer).  Values seen fewer than
    ``min_count`` times keep w = 1 (plain normal) so one-off blowouts don't
    become "key numbers"; ``alpha`` (pseudo-count) and ``bounds`` keep the
    rest smooth.  ``always_fit`` values are fitted however rare they are
    (NFL ties: overtime settles nearly all of them, so margin 0 needs a
    weight far below 1).
    """
    support = list(support)
    lo, hi = support[0], support[-1]
    groups = Counter(c for c, _ in obs)
    observed = Counter(min(hi, max(lo, x)) for _, x in obs)
    free = [observed.get(k, 0) >= min_count or k in always_fit for k in support]
    base = {c: _normal_masses(c, sigma, support) for c in groups}
    w = [1.0] * len(support)
    for _ in range(iters):
        expected = [0.0] * len(support)
        for c, n in groups.items():
            b = base[c]
            z = sum(bi * wi for bi, wi in zip(b, w))
            for i, bi in enumerate(b):
                expected[i] += n * bi * w[i] / z
        w = [min(bounds[1], max(bounds[0], w[i] * (observed.get(k, 0) + alpha) / (expected[i] + alpha)))
             if free[i] else 1.0 for i, k in enumerate(support)]
    return w


def log_likelihood(obs: Sequence[Tuple[float, int]], sigma: float, support: Sequence[int],
                   weights: Optional[Sequence[float]] = None) -> float:
    """Average log-probability of the observed values (higher is better)."""
    support = list(support)
    idx = {k: i for i, k in enumerate(support)}
    w = list(weights) if weights is not None else [1.0] * len(support)
    groups: Dict[float, List[int]] = {}
    for c, x in obs:
        groups.setdefault(c, []).append(x)
    ll, n = 0.0, 0
    for c, xs in groups.items():
        b = _normal_masses(c, sigma, support)
        z = sum(bi * wi for bi, wi in zip(b, w))
        for x in xs:
            i = idx.get(min(support[-1], max(support[0], x)))
            ll += math.log(max(1e-12, b[i] * w[i] / z))
            n += 1
    return ll / max(1, n)


def _share(center: float, line: float, sigma: float, weights: Sequence[float], support: Sequence[int]) -> float:
    """P(value > line) / P(value != line) under the weighted model centred at ``center``."""
    over = under = 0.0
    for k, bi, wi in zip(support, _normal_masses(center, sigma, support), weights):
        if k > line:
            over += bi * wi
        elif k < line:
            under += bi * wi
    return over / (over + under) if over + under > 0 else 0.5


def median_center(line: float, sigma: float, weights: Sequence[float], support: Sequence[int],
                  p: float = 0.5, span: float = 12.0) -> float:
    """Centre at which the model gives P(over line | no push) = p.

    With key-number weights the centre of the normal is not the 50/50 point
    (mass piled on 3 drags it), so the model is anchored on the market: the
    posted line is where a no-vig price splits, and ``p`` moves off it for a
    juiced price (e.g. -3 at -125/+105 -> p ~ 0.535 for the favourite).
    """
    support = list(support)
    lo, hi = line - span, line + span          # the share rises with the centre
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if _share(mid, line, sigma, weights, support) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _fit_block(obs: Sequence[Tuple[float, int]], support: Sequence[int],
               always_fit: Sequence[int] = ()) -> Tuple[float, List[float]]:
    errs = [x - c for c, x in obs]
    m = sum(errs) / len(errs)
    sigma0 = math.sqrt(sum((e - m) ** 2 for e in errs) / len(errs))
    w = fit_weights(obs, sigma0, support, always_fit=always_fit)
    grid = [round(sigma0 + d / 10, 2) for d in range(-12, 13)]
    best = max(grid, key=lambda s: log_likelihood(obs, s, support, w))
    return best, fit_weights(obs, best, support, always_fit=always_fit)


def _fit_anchored(pairs: Sequence[Tuple[float, int]], support: Sequence[int], rounds: int = 3,
                  always_fit: Sequence[int] = ()) -> Tuple[float, List[float], Dict[float, float]]:
    """Fit σ and weights with each market line re-anchored as the model's 50/50 point."""
    support = list(support)
    lines = sorted({line for line, _ in pairs})
    centers = {line: line for line in lines}
    sigma, w = 0.0, [1.0] * len(support)
    for _ in range(rounds):
        sigma, w = _fit_block([(centers[line], x) for line, x in pairs], support, always_fit)
        centers = {line: median_center(line, sigma, w, support) for line in lines}
    return sigma, w, centers


def margin_obs(games: Iterable[dict]) -> List[Tuple[float, int]]:
    return [favourite_view(g["home_spread"], g["margin"]) for g in games
            if g.get("home_spread") is not None and g.get("margin") is not None]


def total_obs(games: Iterable[dict]) -> List[Tuple[float, int]]:
    return [(g["total_line"], int(round(g["total"]))) for g in games
            if g.get("total_line") is not None and g.get("total") is not None]


def fit_calibration(games: Sequence[dict], first_season: int = FIT_FIRST_SEASON,
                    last_season: Optional[int] = None) -> dict:
    """Fit σ and key weights for margins and totals on completed seasons."""
    use = [g for g in games if g["season"] >= first_season and (last_season is None or g["season"] <= last_season)]
    mo, to = margin_obs(use), total_obs(use)
    ms, mw, mc = _fit_anchored(mo, MARGIN_SUPPORT, always_fit=(0,))
    ts, tw, _ = _fit_anchored(to, TOTAL_SUPPORT)
    seasons = sorted({g["season"] for g in use})
    return {
        "version": 2,
        "source": "nflverse/nfldata games.csv (closing lines and results)",
        "seasons": [seasons[0], seasons[-1]] if seasons else [],
        "n_games": len(mo),
        "anchor": "the market line is the model's 50/50 point (no-vig); see betlab/nfl.py",
        "margin": {"sigma": ms, "support": [MARGIN_SUPPORT[0], MARGIN_SUPPORT[-1]],
                   "weights": [round(x, 5) for x in mw],
                   "centers_at_50pct": {f"{k:g}": round(v, 3) for k, v in mc.items() if k in (0, 1, 2.5, 3, 3.5, 6.5, 7, 7.5, 10, 14)}},
        "total": {"sigma": ts, "support": [TOTAL_SUPPORT[0], TOTAL_SUPPORT[-1]],
                  "weights": [round(x, 5) for x in tw]},
    }


# ---------------------------------------------------------------------------
# Run-time pricing
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def load_calibration(path: Optional[str] = None) -> dict:
    p = Path(path) if path else data_dir() / "calibration.json"
    with open(p) as fh:
        return json.load(fh)


def _support(block: dict) -> range:
    lo, hi = block["support"]
    return range(lo, hi + 1)


def _pmf(block: dict, center: float) -> Dict[int, float]:
    support = _support(block)
    raw = [bi * wi for bi, wi in zip(_normal_masses(center, block["sigma"], support), block["weights"])]
    z = sum(raw)
    return {k: v / z for k, v in zip(support, raw) if v > 0}


def _anchored_pmf(block: dict, line: float, p: float) -> Dict[int, float]:
    c = median_center(line, block["sigma"], block["weights"], _support(block), p)
    return _pmf(block, c)


def favourite_pmf(spread_magnitude: float, calibration: Optional[dict] = None, p_cover: float = 0.5) -> Dict[int, float]:
    """Favourite's margin pmf for a favourite of ``spread_magnitude`` whose no-vig cover share is ``p_cover``."""
    cal = calibration or load_calibration()
    return _anchored_pmf(cal["margin"], abs(float(spread_magnitude)), p_cover)


def margin_model(home_spread: float, calibration: Optional[dict] = None, p_home_cover: float = 0.5) -> MarginModel:
    """Home-margin distribution implied by a home spread (home -3 => favourite by 3).

    ``p_home_cover`` is the no-vig chance home covers that spread, ignoring
    pushes (0.5 for a -110/-110 market; devig the two prices otherwise).
    """
    fav_home = home_spread <= 0
    fav = favourite_pmf(home_spread, calibration, p_home_cover if fav_home else 1.0 - p_home_cover)
    if not fav_home:                         # away favoured: home margin = -favourite margin
        return MarginModel.from_pmf({-k: p for k, p in fav.items()})
    return MarginModel.from_pmf(fav)


def total_dist(total_line: float, calibration: Optional[dict] = None, p_over: float = 0.5) -> DiscreteDist:
    cal = calibration or load_calibration()
    return DiscreteDist(_anchored_pmf(cal["total"], float(total_line), p_over))


def _fair_american(p_win: float, p_push: float) -> Optional[str]:
    p_loss = 1.0 - p_win - p_push
    if p_win <= 0 or p_loss <= 0:
        return None
    a = decimal_to_american(1.0 + p_loss / p_win)
    return f"{a:+.0f}" if abs(a) >= 100 else f"{a:+.0f}"


def _row(label: str, p_win: float, p_push: float) -> dict:
    return {"selection": label, "p_win": round(p_win, 4), "p_push": round(p_push, 4),
            "p_loss": round(1 - p_win - p_push, 4), "fair_american": _fair_american(p_win, p_push)}


def moneyline_probs(mm: MarginModel) -> Tuple[float, float, float]:
    """(P(home wins), P(tie), P(away wins)).  NFL ties are rare (~0.3%) and push most moneylines."""
    over, under, push = mm.dist.over_under_push(0)
    return over, push, under


def _fmt_line(x: float) -> str:
    return f"{x:+g}" if x else "PK"


def price(home_spread: float, total_line: Optional[float] = None, alt_spreads: Sequence[float] = (),
          alt_totals: Sequence[float] = (), teaser_points: Optional[float] = None,
          home: str = "HOME", away: str = "AWAY", calibration: Optional[dict] = None,
          p_home_cover: float = 0.5, p_over: float = 0.5) -> dict:
    """Fair probabilities and prices for an NFL game, anchored on the main spread/total.

    ``p_home_cover`` / ``p_over``: the market's no-vig chance at the main
    spread / total ignoring pushes (0.5 for -110/-110; devig juiced prices).
    """
    cal = calibration or load_calibration()
    mm = margin_model(home_spread, cal, p_home_cover)
    out: dict = {"home": home, "away": away, "home_spread": home_spread, "total_line": total_line,
                 "p_home_cover_no_push": p_home_cover, "p_over_no_push": p_over if total_line is not None else None}
    c, p, f = mm.spread_probs(home_spread)
    out["spread"] = [_row(f"{home} {_fmt_line(home_spread)}", c, p), _row(f"{away} {_fmt_line(-home_spread)}", f, p)]
    hw, tie, aw = moneyline_probs(mm)
    out["moneyline"] = [_row(f"{home} ML", hw, tie), _row(f"{away} ML", aw, tie)]
    out["moneyline_no_tie"] = {"p_home": round(hw / (hw + aw), 4), "p_away": round(aw / (hw + aw), 4)}
    alts = []
    for line in sorted(set(float(x) for x in alt_spreads)):
        c, p, f = mm.spread_probs(line)
        alts.append(_row(f"{home} {_fmt_line(line)}", c, p))
        alts.append(_row(f"{away} {_fmt_line(-line)}", f, p))
    if alts:
        out["alt_spreads"] = alts
    # half-points around 3 and 7 from the favourite's side
    fav_home = home_spread <= 0
    fav_name = home if fav_home else away
    hp = []
    for lo_line in (3.5, 3.0, 7.5, 7.0):       # e.g. buying -3.5 down to -3, then -3 down to -2.5
        a = _cover(mm, fav_home, -lo_line)
        b = _cover(mm, fav_home, -lo_line + 0.5)
        hp.append({"favourite": fav_name, "from": -lo_line, "to": -lo_line + 0.5,
                   "win_prob_gain": round(b[0] - a[0], 4),
                   "loss_prob_drop": round((1 - a[0] - a[1]) - (1 - b[0] - b[1]), 4)})
    out["half_points_favourite"] = hp
    if total_line is not None:
        td = total_dist(total_line, cal, p_over)
        tl = [float(total_line)] + [float(x) for x in alt_totals if float(x) != float(total_line)]
        rows = []
        for line in sorted(set(tl)):
            o, u, pu = td.over_under_push(line)
            rows.append(_row(f"Over {line:g}", o, pu))
            rows.append(_row(f"Under {line:g}", u, pu))
        out["totals"] = rows
    if teaser_points:
        legs = []
        for side_home in (True, False):
            name = home if side_home else away
            base = home_spread if side_home else -home_spread
            new = base + teaser_points
            c, p, f = _cover(mm, side_home, new)
            legs.append({"selection": f"{name} {_fmt_line(base)} -> {_fmt_line(new)}", "p_win": round(c, 4),
                         "p_push": round(p, 4), "p_loss": round(f, 4)})
        out["teaser_legs"] = {"points": teaser_points, "legs": legs,
                              "note": "2-team 6-pt at -120 needs ~73.9% per leg; 3-team at +160 ~72.4%"}
    return out


def _cover(mm: MarginModel, side_home: bool, line: float) -> Tuple[float, float, float]:
    """(win, push, loss) for a side at its own line (home -3 => line -3 for home; away +3 => +3)."""
    if side_home:
        return mm.spread_probs(line)
    return mm.away_spread_probs(line)


def evaluate_offer(home_spread: float, market: str, side: str, line: float, american: float,
                   total_line: Optional[float] = None, calibration: Optional[dict] = None,
                   p_home_cover: float = 0.5, p_over: float = 0.5) -> dict:
    """EV of an offered alt spread / alt total / moneyline, priced off the main line."""
    cal = calibration or load_calibration()
    d = american_to_decimal(american)
    if market == "spread":
        mm = margin_model(home_spread, cal, p_home_cover)
        w, p, _ = _cover(mm, side == "home", line)
    elif market == "ml":
        mm = margin_model(home_spread, cal, p_home_cover)
        hw, tie, aw = moneyline_probs(mm)
        w, p = (hw, tie) if side == "home" else (aw, tie)
    elif market == "total":
        if total_line is None:
            raise ValueError("pricing an alt total needs the main total line")
        o, u, pu = total_dist(total_line, cal, p_over).over_under_push(line)
        w, p = (o, pu) if side == "over" else (u, pu)
    else:
        raise ValueError(f"unknown market {market!r} (spread, ml, total)")
    ev = w * (d - 1) - (1 - w - p)
    return {"market": market, "side": side, "line": line, "price": american, "p_win": round(w, 4),
            "p_push": round(p, 4), "fair_american": _fair_american(w, p), "ev_pct": round(100 * ev, 2)}


# ---------------------------------------------------------------------------
# Validation (out-of-sample)
# ---------------------------------------------------------------------------

def validate(games: Sequence[dict], fit_last: int, test_first: int, test_last: Optional[int] = None,
             first_season: int = FIT_FIRST_SEASON) -> dict:
    """Fit on [first_season, fit_last], score on [test_first, test_last]."""
    cal = fit_calibration(games, first_season, fit_last)
    test = [g for g in games if g["season"] >= test_first and (test_last is None or g["season"] <= test_last)
            and g.get("home_spread") is not None]
    mo = margin_obs(test)
    msig, tsig = cal["margin"]["sigma"], cal["total"]["sigma"]
    mw, tw = cal["margin"]["weights"], cal["total"]["weights"]
    mcent = {f: median_center(f, msig, mw, MARGIN_SUPPORT) for f in {f for f, _ in mo}}
    out = {"fit": cal["seasons"], "test": [test_first, test_last or max(g["season"] for g in test)],
           "n_test": len(mo)}
    out["margin_loglik"] = {
        "key_weighted": round(log_likelihood([(mcent[f], x) for f, x in mo], msig, MARGIN_SUPPORT, mw), 4),
        "plain_normal": round(log_likelihood(mo, msig, MARGIN_SUPPORT), 4)}
    to = total_obs(test)
    tcent = {t: median_center(t, tsig, tw, TOTAL_SUPPORT) for t in {t for t, _ in to}}
    out["total_loglik"] = {
        "key_weighted": round(log_likelihood([(tcent[t], x) for t, x in to], tsig, TOTAL_SUPPORT, tw), 4),
        "plain_normal": round(log_likelihood(to, tsig, TOTAL_SUPPORT), 4)}
    # pushes at the main key numbers
    pushes = {}
    for key in (3.0, 7.0):
        sub = [fm for f, fm in mo if f == key]
        if sub:
            pred = favourite_pmf(key, cal).get(int(key), 0.0)
            pushes[f"-{key:g}"] = {"n": len(sub), "predicted": round(pred, 4),
                                  "actual": round(sum(1 for x in sub if x == key) / len(sub), 4)}
    out["push_rate"] = pushes
    # moneyline: spread-implied win probability vs the market's own devigged moneyline
    ll_model, ll_mkt, n = 0.0, 0.0, 0
    for g in test:
        if g["home_ml"] is None or g["away_ml"] is None or g["margin"] == 0:
            continue
        try:
            pm = devig([american_to_decimal(g["home_ml"]), american_to_decimal(g["away_ml"])])[0]
        except (ValueError, ZeroDivisionError):
            continue
        hw, tie, aw = moneyline_probs(margin_model(g["home_spread"], cal))
        ph = hw / (hw + aw)
        y = 1 if g["margin"] > 0 else 0
        ll_model += math.log(ph if y else 1 - ph)
        ll_mkt += math.log(pm if y else 1 - pm)
        n += 1
    out["moneyline_logloss"] = {"n": n, "spread_implied": round(-ll_model / max(1, n), 4),
                                "market_moneyline": round(-ll_mkt / max(1, n), 4)}
    # 6-point teaser legs that cross both 3 and 7
    pred, won, legs = 0.0, 0, 0
    for f, fm in mo:
        if 7.5 <= f <= 8.5:                    # favourite teased down to -1.5..-2.5
            line = f - 6
            pred += sum(p for k, p in favourite_pmf(f, cal).items() if k > line)
            won += fm > line
            legs += 1
        elif 1.5 <= f <= 2.5:                  # underdog teased up to +7.5..+8.5
            line = f + 6
            pred += sum(p for k, p in favourite_pmf(f, cal).items() if k < line)
            won += fm < line
            legs += 1
    if legs:
        out["wong_teaser_legs"] = {"n": legs, "predicted": round(pred / legs, 4), "actual": round(won / legs, 4)}
    return out


# ---------------------------------------------------------------------------
# Team ratings (power ratings with a QB-change adjustment)
# ---------------------------------------------------------------------------

# Relocations: nflverse keeps historical codes.
NFL_ALIASES = {"OAK": "LV", "SD": "LAC", "STL": "LA"}

# Tuned on 2012-2019 (margin log-likelihood; home edge checked on 2016-19), tested
# walk-forward on 2021-2025 against closing lines: RMSE 13.10 vs 12.66 for the
# closing spread, best blend weight on the model 0 — see ``ratings_backtest``.
NFL_RATING_PARAMS = dict(hca=1.75, sigma=13.0, q=0.02, v0=20.0, rho=0.6, mu_new=0.0, v_new=40.0, cap=2.5,
                         sigma_t=13.0, q_t=0.02, v0_t=12.0, rho_t=0.6, vL_init=400.0, vL0=4.0, qL=0.02,
                         b2b_penalty=0.0)
NFL_QB_ADJ = 3.0          # points a team loses when someone other than its usual starter starts


def rating_params(**overrides):
    from .ratings import RatingParams
    return RatingParams(**{**NFL_RATING_PARAMS, **overrides})


def rating_rows(games: Sequence[dict], qb_adj: float = NFL_QB_ADJ, lookback: int = 4,
                min_history: int = 3) -> List[dict]:
    """Games -> ratings-engine rows, flagging starts by someone other than the usual QB.

    A team's usual starter is the QB with the most starts in its previous
    ``lookback`` games (across seasons).  When the listed starter differs —
    an injury, a benching — that team is handicapped by ``qb_adj`` points in
    the prediction and the ratings learn from the result net of it.  nflverse
    lists projected starters for upcoming games, so this applies before
    kickoff too (check the real starter on game day).
    """
    from collections import defaultdict, deque
    hist: Dict[str, deque] = defaultdict(lambda: deque(maxlen=lookback))
    rows = []
    for g in sorted(games, key=lambda g: (g["date"] or "", g["game_id"] or "")):
        home, away = NFL_ALIASES.get(g["home"], g["home"]), NFL_ALIASES.get(g["away"], g["away"])
        flags = {}
        for team, qb in ((home, g.get("home_qb")), (away, g.get("away_qb"))):
            h = hist[team]
            usual = Counter(h).most_common(1)[0][0] if len(h) >= min_history else None
            flags[team] = {"usual": usual, "starter": qb, "change": bool(usual and qb and qb != usual)}
        adj = (-qb_adj if flags[home]["change"] else 0.0) + (qb_adj if flags[away]["change"] else 0.0)
        rows.append({
            "game_id": g["game_id"], "date": g["date"], "season": g["season"], "home": home, "away": away,
            "home_pts": g["home_score"], "away_pts": g["away_score"], "neutral": int(bool(g.get("neutral"))),
            "season_type": "regular" if g.get("game_type") in (None, "", "REG") else "playoff",
            "extra_home_adj": adj, "home_qb": flags[home], "away_qb": flags[away],
            "home_spread": g.get("home_spread"), "total_line": g.get("total_line"),
        })
        if g.get("home_score") is not None:          # only played games teach "usual starter"
            if g.get("home_qb"):
                hist[home].append(g["home_qb"])
            if g.get("away_qb"):
                hist[away].append(g["away_qb"])
    return rows


def fit_ratings(games: Sequence[dict], until: Optional[str] = None, qb_adj: float = NFL_QB_ADJ, **overrides):
    """Fit the ratings on completed games before ``until`` (YYYY-MM-DD).  Returns (model, rows)."""
    from .ratings import KalmanRatings
    rows = rating_rows(games, qb_adj)
    played = [r for r in rows if r["home_pts"] is not None and (until is None or r["date"] < until)]
    model = KalmanRatings(rating_params(**overrides)).fit(played)
    return model, rows


def predict_game(model, row: dict) -> dict:
    """Model line for one game row (from ``rating_rows``), including its QB adjustment."""
    pr = model.predict(row["home"], row["away"], row["date"], season=row["season"],
                       neutral=bool(row["neutral"]), extra_home_adj=row["extra_home_adj"])
    out = {"home": row["home"], "away": row["away"], "date": row["date"],
           "model_home_spread": round(-pr.mu, 1), "model_total": round(pr.total_mu, 1),
           "p_home_win": round(pr.p_home, 3), "qb_adjustment": row["extra_home_adj"],
           "market_home_spread": row.get("home_spread"), "market_total": row.get("total_line")}
    for side in ("home", "away"):
        q = row[f"{side}_qb"]
        if q["change"]:
            out.setdefault("notes", []).append(
                f"{row[side]}: listed starter {q['starter']}, usual {q['usual']} (-{abs(row['extra_home_adj']) if row['extra_home_adj'] else 0:g} applied; verify the starter on game day)")
    if row.get("home_spread") is not None:
        out["model_minus_market"] = round(out["model_home_spread"] - row["home_spread"], 1)
    return out


def ratings_backtest(games: Sequence[dict], test_seasons: Sequence[int], qb_adj: float = NFL_QB_ADJ,
                     edges: Sequence[float] = (1.0, 2.0, 3.0), **overrides) -> dict:
    """Walk-forward check of the ratings against closing lines (no look-ahead).

    Every prediction is made before the game from earlier results only.
    Reports margin RMSE for the model and for the closing spread, the
    log-likelihood-optimal weight on the model when blended with the market,
    and how often the model's side covered the closing spread when it
    disagreed by at least each ``edge`` (pushes excluded).
    """
    from .ratings import KalmanRatings
    rows = [r for r in rating_rows(games, qb_adj) if r["home_pts"] is not None]
    model = KalmanRatings(rating_params(**overrides)).fit(rows)
    test = [(h, r) for h, r in zip(model.history, rows) if r["season"] in set(test_seasons)
            and r.get("home_spread") is not None]
    n = len(test)
    if not n:
        return {"n": 0}
    se_model = sum((h["margin"] - h["pred_margin"]) ** 2 for h, _ in test) / n
    se_mkt = sum((h["margin"] + r["home_spread"]) ** 2 for h, r in test) / n
    sd = 13.0

    def ll(w: float) -> float:
        tot = 0.0
        for h, r in test:
            mu = w * h["pred_margin"] + (1 - w) * (-r["home_spread"])
            tot += -0.5 * ((h["margin"] - mu) / sd) ** 2
        return tot / n

    weights = [i / 20 for i in range(0, 21)]
    best_w = max(weights, key=ll)
    ats = {}
    for edge in edges:
        won = lost = 0
        for h, r in test:
            diff = h["pred_margin"] - (-r["home_spread"])     # + => model likes home vs the line
            if abs(diff) < edge:
                continue
            res = h["margin"] + r["home_spread"]              # home cover margin
            if res == 0:
                continue
            if (diff > 0) == (res > 0):
                won += 1
            else:
                lost += 1
        tot = won + lost
        ats[f">={edge:g}"] = {"bets": tot, "win_rate": round(won / tot, 4) if tot else None,
                              "breakeven_at_-110": 0.5238}
    return {"n": n, "seasons": sorted(set(test_seasons)),
            "margin_rmse_model": round(math.sqrt(se_model), 3), "margin_rmse_closing_spread": round(math.sqrt(se_mkt), 3),
            "best_blend_weight_on_model": best_w, "ats_when_disagreeing": ats,
            "qb_adj": qb_adj, "params": {**NFL_RATING_PARAMS, **overrides}}
