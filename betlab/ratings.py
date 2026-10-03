"""Kalman point ratings for margins and totals.

Each team has a rating r ~ N(m, v) in points vs an average team on a
neutral court.  A game is observed as

    margin = r_home - r_away + HCA + rest + e,   e ~ N(0, sigma^2)

and the update is a (scalar) Kalman step: the innovation e = actual -
predicted is split between the two teams in proportion to their current
uncertainty.  Ratings drift between games (variance grows by q per day),
regress toward 0 at the start of each season (factor rho), and new teams
start from a prior.  Totals use the same machinery with a league-wide
scoring level L plus per-team "total contributions":

    total = L + t_home + t_away + e_t

Why this model: it is tiny, explainable, has honest predictive variances
(early-season games get wider intervals), and the WNBA preset was tuned
out-of-sample (2014-2025 log-likelihood, tested on 2026).  It is a
*baseline*, not an oracle: on 2026 WNBA its margin RMSE (12.99) trails
DraftKings closing spreads (12.69).  Use it to find stale *openers* and to
anchor props/totals, and judge it by CLV.
"""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Sequence

from .distributions import norm_cdf


@dataclass
class RatingParams:
    hca: float = 1.75
    sigma: float = 12.0
    q: float = 0.05
    v0: float = 12.0
    rho: float = 0.6
    mu_new: float = 0.0
    v_new: float = 20.0
    cap: Optional[float] = 2.5
    sigma_t: float = 15.5
    q_t: float = 0.05
    v0_t: float = 15.0
    rho_t: float = 0.6
    league_total0: Optional[float] = None
    vL_init: float = 400.0
    vL0: float = 5.0
    qL: float = 0.05
    b2b_penalty: float = 2.3
    playoff_hca_extra: float = 0.0
    # Online noise-level adaptation: EWMA (half-life in games) of the implied
    # sigma^2 multiplier.  Lets the model notice variance regime changes
    # (e.g. the 2026 WNBA scoring surge) without peeking at future data.
    # None = off.  On WNBA data it helps totals and slightly hurts margins,
    # so the WNBA preset adapts totals only.
    var_halflife: Optional[float] = None
    var_halflife_total: Optional[float] = None
    var_scale_bounds: tuple = (0.6, 2.5)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Prediction:
    home: str
    away: str
    mu: float            # expected home margin
    sd: float            # predictive SD of margin
    total_mu: float
    total_sd: float
    p_home: float
    home_rest: Optional[int] = None
    away_rest: Optional[int] = None
    notes: List[str] = field(default_factory=list)

    @property
    def fair_home_spread(self) -> float:
        return -self.mu

    @property
    def home_team_total(self) -> float:
        return (self.total_mu + self.mu) / 2.0

    @property
    def away_team_total(self) -> float:
        return (self.total_mu - self.mu) / 2.0

    def as_dict(self) -> dict:
        return {"home": self.home, "away": self.away, "exp_home_margin": round(self.mu, 2),
                "fair_home_spread": round(-self.mu, 2), "margin_sd": round(self.sd, 2),
                "p_home_win": round(self.p_home, 4), "exp_total": round(self.total_mu, 2),
                "total_sd": round(self.total_sd, 2), "home_team_total": round(self.home_team_total, 2),
                "away_team_total": round(self.away_team_total, 2), "home_rest_days": self.home_rest,
                "away_rest_days": self.away_rest, "notes": self.notes}


def _to_date(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


class _Team:
    __slots__ = ("m", "v", "t", "vt", "season", "last", "games")

    def __init__(self, m, v, t, vt, season, last):
        self.m, self.v, self.t, self.vt = m, v, t, vt
        self.season, self.last, self.games = season, last, 0


class KalmanRatings:
    def __init__(self, params: Optional[RatingParams] = None, aliases: Optional[Dict[str, str]] = None):
        self.p = params or RatingParams()
        self.aliases = dict(aliases or {})
        self.teams: Dict[str, _Team] = {}
        self.L: Optional[float] = None
        self.vL: float = self.p.vL_init
        self.L_season: Optional[int] = None
        self.L_last: Optional[date] = None
        self.scale_m: float = 1.0
        self.scale_t: float = 1.0
        self.history: List[dict] = []

    # ------------------------------------------------------------------
    def _name(self, t: str) -> str:
        return self.aliases.get(t, t)

    def _state(self, team: str, season: int, d: date, mutate: bool):
        """Team state as of date d (drift / season rollover applied).

        ``games`` counts games played in the *current* season.
        """
        p = self.p
        st = self.teams.get(team)
        if st is None:
            m, v, t, vt, s_, last, n = p.mu_new, p.v_new, 0.0, p.v0_t, season, None, 0
        elif st.season != season:
            m, v = p.rho * st.m, p.v0
            t, vt = p.rho_t * st.t, p.v0_t
            s_, last, n = season, None, 0
        else:
            days = max(0, (d - st.last).days) if st.last else 0
            m, v = st.m, st.v + p.q * days
            t, vt = st.t, st.vt + p.q_t * days
            s_, last, n = season, st.last, st.games
        if mutate:
            if st is None:
                st = _Team(m, v, t, vt, s_, last)
                self.teams[team] = st
            else:
                st.m, st.v, st.t, st.vt, st.season, st.last = m, v, t, vt, s_, last
            st.games = n
            return st
        copy = _Team(m, v, t, vt, s_, last)
        copy.games = n
        return copy

    def _league(self, season: int, d: date, mutate: bool):
        p = self.p
        if self.L is None:
            L = p.league_total0 if p.league_total0 is not None else None
            vL = p.vL_init
        else:
            L, vL = self.L, self.vL
            if self.L_season is not None and season != self.L_season:
                vL += p.vL0
            if self.L_last is not None:
                vL += p.qL * max(0, (d - self.L_last).days)
        if mutate:
            self.L, self.vL, self.L_season, self.L_last = L, vL, season, d
        return L, vL

    @staticmethod
    def _rest(st: _Team, d: date) -> Optional[int]:
        if st.last is None:
            return None
        return (d - st.last).days - 1

    # ------------------------------------------------------------------
    def predict(self, home: str, away: str, game_date, season: Optional[int] = None,
                neutral: bool = False, playoff: bool = False,
                home_rest: Optional[int] = None, away_rest: Optional[int] = None,
                extra_home_adj: float = 0.0, extra_total_adj: float = 0.0) -> Prediction:
        """Pre-game prediction without changing any state.

        ``extra_home_adj``: your manual adjustment in points (e.g. -4.0 if the
        home team's star is out and the ratings don't know yet).
        ``extra_total_adj``: points added to the expected total.
        """
        d = _to_date(game_date)
        season = season if season is not None else d.year
        h, a = self._name(home), self._name(away)
        sh = self._state(h, season, d, mutate=False)
        sa = self._state(a, season, d, mutate=False)
        L, vL = self._league(season, d, mutate=False)
        return self._predict_from(h, a, sh, sa, L, vL, d, neutral, playoff, home_rest, away_rest,
                                  extra_home_adj, extra_total_adj)

    def _predict_from(self, h, a, sh, sa, L, vL, d, neutral, playoff, home_rest, away_rest,
                      extra_home_adj=0.0, extra_total_adj=0.0) -> Prediction:
        p = self.p
        notes: List[str] = []
        hr = home_rest if home_rest is not None else self._rest(sh, d)
        ar = away_rest if away_rest is not None else self._rest(sa, d)
        hca = 0.0 if neutral else p.hca + (p.playoff_hca_extra if playoff else 0.0)
        rest_adj = 0.0
        if hr == 0:
            rest_adj -= p.b2b_penalty
            notes.append(f"{h} on a back-to-back (-{p.b2b_penalty})")
        if ar == 0:
            rest_adj += p.b2b_penalty
            notes.append(f"{a} on a back-to-back (+{p.b2b_penalty} to {h})")
        mu = sh.m - sa.m + hca + rest_adj + extra_home_adj
        S = sh.v + sa.v + p.sigma ** 2 * self.scale_m
        if L is None:
            L = 160.0
            notes.append("no league scoring history; total uses 160 placeholder")
        muT = L + sh.t + sa.t + extra_total_adj
        ST = vL + sh.vt + sa.vt + p.sigma_t ** 2 * self.scale_t
        sd = math.sqrt(S)
        p_home = norm_cdf(mu / sd)
        if sh.games < 5 or sa.games < 5:
            notes.append("early-season / new team: wide uncertainty")
        return Prediction(h, a, mu, sd, muT, math.sqrt(ST), p_home, hr, ar, notes)

    # ------------------------------------------------------------------
    def update(self, game: dict) -> dict:
        """Process one completed game: record the pre-game prediction, then learn."""
        p = self.p
        d = _to_date(game["date"])
        season = int(game.get("season") or d.year)
        h, a = self._name(game["home"]), self._name(game["away"])
        neutral = bool(int(game.get("neutral", 0) or 0))
        playoff = str(game.get("season_type", "regular")).lower().startswith("p") or bool(game.get("playoff", False))
        sh = self._state(h, season, d, mutate=True)
        sa = self._state(a, season, d, mutate=True)
        hp, ap = float(game["home_pts"]), float(game["away_pts"])
        if self.L is None and p.league_total0 is None:
            self.L, self.vL = hp + ap, p.vL_init
            self.L_season, self.L_last = season, d
        L, vL = self._league(season, d, mutate=True)
        pred = self._predict_from(h, a, sh, sa, L, vL, d, neutral, playoff, None, None)
        margin, total = hp - ap, hp + ap
        rec = {"game_id": game.get("game_id"), "date": d.isoformat(), "season": season, "home": h, "away": a,
               "pred_margin": pred.mu, "pred_sd": pred.sd, "pred_total": pred.total_mu, "pred_total_sd": pred.total_sd,
               "p_home": pred.p_home, "margin": margin, "total": total, "playoff": playoff}
        self.history.append(rec)
        # noise-level adaptation (uses raw innovations, before any capping)
        lo, hi = p.var_scale_bounds
        if p.var_halflife:
            alpha = 1.0 - 0.5 ** (1.0 / p.var_halflife)
            imp_m = ((margin - pred.mu) ** 2 - sh.v - sa.v) / p.sigma ** 2
            self.scale_m = min(hi, max(lo, (1 - alpha) * self.scale_m + alpha * imp_m))
        if p.var_halflife_total:
            alpha_t = 1.0 - 0.5 ** (1.0 / p.var_halflife_total)
            imp_t = ((total - pred.total_mu) ** 2 - self.vL - sh.vt - sa.vt) / p.sigma_t ** 2
            self.scale_t = min(hi, max(lo, (1 - alpha_t) * self.scale_t + alpha_t * imp_t))
        # margin update
        S = pred.sd ** 2
        e = margin - pred.mu
        if p.cap:
            lim = p.cap * math.sqrt(S)
            e = max(-lim, min(lim, e))
        kh, ka = sh.v / S, sa.v / S
        sh.m += kh * e
        sa.m -= ka * e
        sh.v -= sh.v * kh
        sa.v -= sa.v * ka
        # totals update
        ST = pred.total_sd ** 2
        eT = total - pred.total_mu
        if p.cap:
            limT = p.cap * math.sqrt(ST)
            eT = max(-limT, min(limT, eT))
        kL, kth, kta = self.vL / ST, sh.vt / ST, sa.vt / ST
        self.L += kL * eT
        sh.t += kth * eT
        sa.t += kta * eT
        self.vL -= self.vL * kL
        sh.vt -= sh.vt * kth
        sa.vt -= sa.vt * kta
        sh.last = sa.last = d
        sh.games += 1
        sa.games += 1
        return rec

    def fit(self, games: Iterable[dict]) -> "KalmanRatings":
        for g in sorted(games, key=lambda g: (_to_date(g["date"]), str(g.get("game_id", "")))):
            self.update(g)
        return self

    # ------------------------------------------------------------------
    def ratings_table(self, season: Optional[int] = None) -> List[dict]:
        rows = []
        for name, st in self.teams.items():
            if season is not None and st.season != season:
                continue
            rows.append({"team": name, "rating": round(st.m, 2), "rating_sd": round(math.sqrt(st.v), 2),
                         "total_contrib": round(st.t, 2), "season": st.season, "games": st.games,
                         "last_game": st.last.isoformat() if st.last else None})
        rows.sort(key=lambda r: -r["rating"])
        return rows

    def league_total(self) -> Optional[float]:
        return self.L

    def evaluate(self, seasons: Optional[Sequence[int]] = None) -> dict:
        """Out-of-sample accuracy of the recorded pre-game predictions."""
        rows = [r for r in self.history if seasons is None or r["season"] in seasons]
        n = len(rows)
        if n == 0:
            return {"n": 0}
        se = sum((r["margin"] - r["pred_margin"]) ** 2 for r in rows) / n
        seT = sum((r["total"] - r["pred_total"]) ** 2 for r in rows) / n
        ll = sum(-0.5 * math.log(2 * math.pi * r["pred_sd"] ** 2) - (r["margin"] - r["pred_margin"]) ** 2 / (2 * r["pred_sd"] ** 2) for r in rows) / n
        brier = sum((r["p_home"] - (1.0 if r["margin"] > 0 else 0.0)) ** 2 for r in rows) / n
        return {"n": n, "margin_rmse": math.sqrt(se), "total_rmse": math.sqrt(seT), "margin_loglik": ll, "brier": brier}


def read_games_csv(path: str) -> List[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))
