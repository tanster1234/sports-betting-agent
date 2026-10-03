"""Game-line pricing from a margin/total model.

A ``MarginModel`` is a discrete distribution of (home score - away score).
Everything — moneyline, spread at any number, alternate spreads, half-point
value, fair line — is read off that one distribution, so pushes and
key numbers are handled consistently.

Default shape is a discretised normal.  For basketball the mass on 0 (a
regulation tie) is re-distributed through an overtime model, because a game
cannot end tied.  For sports with lumpy margins (NFL key numbers) pass an
empirical pmf instead of relying on the normal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .distributions import DiscreteDist, discretized_normal, norm_ppf
from .odds import OddsError, american_to_decimal, devig
from .odds import ev as _ev

# Sport-level defaults.  WNBA values are fitted on 2013-2026 ESPN results and
# 2026 DraftKings closing lines (see .claude/skills/wnba-betting/references/calibration.md).  Other sports
# are published-consensus approximations — recalibrate with your own data
# before trusting them to a tenth of a point.
SPORT_DEFAULTS: Dict[str, dict] = {
    "WNBA": {
        "margin_sigma": 12.5,     # SD of final margin around a sharp closing spread (2026 DK: 12.7)
        "total_sigma": 18.0,      # 2026 DK: 18.7; 2013-2025 seasons ran ~16.5
        "hca": 1.75,              # points; 2021-26 pooled OLS 1.4-1.7, 2013-19 was ~2.9
        "ot_minutes": 5, "reg_minutes": 40,
        "first_half": {"margin_share": 0.60, "margin_sigma_ratio": 0.78, "total_share": 0.50, "total_sigma_ratio": 0.60},
        "first_quarter": {"margin_share": 0.30, "margin_sigma_ratio": 0.55, "total_share": 0.255, "total_sigma_ratio": 0.42},
    },
    "NBA": {
        "margin_sigma": 12.0, "total_sigma": 18.0, "hca": 2.2,
        "ot_minutes": 5, "reg_minutes": 48,
        "first_half": {"margin_share": 0.55, "margin_sigma_ratio": 0.75, "total_share": 0.505, "total_sigma_ratio": 0.62},
        "first_quarter": {"margin_share": 0.28, "margin_sigma_ratio": 0.55, "total_share": 0.255, "total_sigma_ratio": 0.42},
    },
    "NCAAB": {"margin_sigma": 10.5, "total_sigma": 15.0, "hca": 3.0, "ot_minutes": 5, "reg_minutes": 40,
              "first_half": {"margin_share": 0.52, "margin_sigma_ratio": 0.75, "total_share": 0.48, "total_sigma_ratio": 0.62}},
    "WNCAAB": {"margin_sigma": 11.0, "total_sigma": 14.5, "hca": 3.0, "ot_minutes": 5, "reg_minutes": 40},
    "NFL": {"margin_sigma": 13.5, "total_sigma": 10.0, "hca": 1.7, "ot_minutes": None, "reg_minutes": 60,
            "note": "Margins cluster on 3/7/10/14; pass an empirical pmf for key-number pricing."},
    "NCAAF": {"margin_sigma": 15.5, "total_sigma": 13.0, "hca": 2.5, "ot_minutes": None, "reg_minutes": 60},
}


def sport_params(sport: str) -> dict:
    key = sport.upper()
    if key not in SPORT_DEFAULTS:
        raise KeyError(f"no defaults for sport {sport!r}; known: {sorted(SPORT_DEFAULTS)}")
    return SPORT_DEFAULTS[key]


# ---------------------------------------------------------------------------
# Margin model
# ---------------------------------------------------------------------------

def basketball_margin_dist(mu: float, sigma: float, reg_minutes: int = 40, ot_minutes: int = 5) -> DiscreteDist:
    """Discretised normal margin with regulation ties resolved by overtime.

    OT margin ~ discretised N(mu * ot/reg, sigma * sqrt(ot/reg)), conditioned
    on being non-zero (a tied OT just plays another one).
    """
    base = discretized_normal(mu, sigma)
    p_tie = base.prob(0)
    pmf = {k: p for k, p in base.pmf.items() if k != 0}
    if p_tie > 0:
        frac = ot_minutes / reg_minutes
        ot = discretized_normal(mu * frac, max(sigma * math.sqrt(frac), 0.5))
        nz = {k: p for k, p in ot.pmf.items() if k != 0}
        s = sum(nz.values())
        for k, p in nz.items():
            pmf[k] = pmf.get(k, 0.0) + p_tie * p / s
    return DiscreteDist(pmf)


@dataclass
class MarginModel:
    """Distribution of home margin (home - away)."""

    dist: DiscreteDist

    @classmethod
    def normal(cls, mu: float, sigma: float, sport: Optional[str] = None,
               allow_ties: bool = False) -> "MarginModel":
        """``mu``: expected home margin (positive = home favoured).

        For basketball sports (sport given with ot_minutes) ties are resolved
        by an OT model; otherwise a plain discretised normal is used, which
        keeps a small tie probability (``allow_ties``) for sports like the NFL.
        """
        if sport is not None:
            sp = sport_params(sport)
            if sp.get("ot_minutes"):
                return cls(basketball_margin_dist(mu, sigma, sp["reg_minutes"], sp["ot_minutes"]))
        d = discretized_normal(mu, sigma)
        if not allow_ties and sport is None:
            # generic: split the tie mass evenly (approximates sudden-death OT)
            p0 = d.prob(0)
            pmf = {k: p for k, p in d.pmf.items() if k != 0}
            pmf[1] = pmf.get(1, 0.0) + p0 / 2
            pmf[-1] = pmf.get(-1, 0.0) + p0 / 2
            d = DiscreteDist(pmf)
        return cls(d)

    @classmethod
    def from_pmf(cls, pmf: Dict[int, float]) -> "MarginModel":
        return cls(DiscreteDist(pmf))

    @classmethod
    def from_spread(cls, home_spread: float, sigma: float, sport: Optional[str] = None) -> "MarginModel":
        """Market-implied model from a closing spread (home -5.5 => mu = +5.5)."""
        return cls.normal(-float(home_spread), sigma, sport)

    # -- reads ----------------------------------------------------------
    def mean(self) -> float:
        return self.dist.mean()

    def p_home_win(self) -> float:
        over, _, push = self.dist.over_under_push(0)
        return over + push / 2  # residual ties (if any) split

    def p_away_win(self) -> float:
        return 1.0 - self.p_home_win()

    def spread_probs(self, home_line: float) -> Tuple[float, float, float]:
        """(P(home covers), P(push), P(home fails)) for home at ``home_line``.

        Home -5.5 => covers when margin > 5.5.  Home +3 => covers when margin > -3.
        """
        threshold = -float(home_line)
        over, under, push = self.dist.over_under_push(threshold)
        return over, push, under

    def away_spread_probs(self, away_line: float) -> Tuple[float, float, float]:
        cover, push, fail = self.spread_probs(-float(away_line))
        return fail, push, cover

    def fair_home_spread(self) -> float:
        """Half-point home spread closest to 50/50 (negative = home favoured)."""
        return -self.dist.median_line()

    def half_point_value(self, home_line: float) -> dict:
        """Probability gained by moving home's number half a point in its favour."""
        base = self.spread_probs(home_line)
        better = self.spread_probs(home_line + 0.5)
        return {
            "line": home_line,
            "p_cover": base[0], "p_push": base[1],
            "better_line": home_line + 0.5,
            "p_cover_better": better[0], "p_push_better": better[1],
            "delta_win": better[0] - base[0],
            "delta_not_lose": (better[0] + better[1]) - (base[0] + base[1]),
        }


def total_dist(mu: float, sigma: float) -> DiscreteDist:
    return discretized_normal(mu, sigma)


def total_probs(mu: float, sigma: float, line: float, dist: Optional[DiscreteDist] = None) -> Tuple[float, float, float]:
    """(P(over), P(under), P(push))."""
    d = dist or total_dist(mu, sigma)
    return d.over_under_push(line)


# ---------------------------------------------------------------------------
# Conversions between spread, moneyline and win probability
# ---------------------------------------------------------------------------

def win_prob_from_spread(home_spread: float, sigma: float, sport: Optional[str] = "WNBA") -> float:
    return MarginModel.from_spread(home_spread, sigma, sport).p_home_win()


def spread_from_win_prob(p_home: float, sigma: float) -> float:
    """Approximate home spread implied by a fair win probability (normal model)."""
    if not 0 < p_home < 1:
        raise OddsError("probability must be in (0,1)")
    return -norm_ppf(p_home, 0.0, sigma)


def implied_sigma(home_spread: float, p_home_fair: float) -> float:
    """Margin SD that makes a spread and a fair moneyline probability agree."""
    mu = -float(home_spread)
    z = norm_ppf(p_home_fair)
    if abs(z) < 1e-9:
        raise OddsError("pick'em moneyline: sigma is not identifiable")
    s = mu / z
    if s <= 0:
        raise OddsError("spread and moneyline disagree on the favourite")
    return s


def team_totals_from_lines(home_spread: float, total: float) -> Tuple[float, float]:
    """Implied team totals: home = (total - spread)/2, away = (total + spread)/2."""
    return (float(total) - float(home_spread)) / 2.0, (float(total) + float(home_spread)) / 2.0


def period_lines(home_spread: float, total: float, sport: str = "WNBA", period: str = "first_half") -> dict:
    """Derive fair period lines (1H/1Q) from full-game lines using calibrated shares."""
    sp = sport_params(sport)
    if period not in sp:
        raise KeyError(f"no {period} calibration for {sport}")
    f = sp[period]
    mu = -float(home_spread)
    return {
        "period": period,
        "home_spread": round(-mu * f["margin_share"], 2),
        "margin_sigma": round(sp["margin_sigma"] * f["margin_sigma_ratio"], 2),
        "total": round(float(total) * f["total_share"], 2),
        "total_sigma": round(sp["total_sigma"] * f["total_sigma_ratio"], 2),
    }


# ---------------------------------------------------------------------------
# Evaluating offered prices against a model
# ---------------------------------------------------------------------------

@dataclass
class PricedBet:
    market: str
    selection: str
    line: Optional[float]
    price_decimal: float
    p_win: float
    p_push: float
    ev: float                 # expected profit per 1 staked
    fair_decimal: float       # price at which EV = 0 (push-aware)
    market_fair_prob: Optional[float] = None   # devigged book probability, if a two-way price was given

    def as_dict(self) -> dict:
        return {
            "market": self.market, "selection": self.selection, "line": self.line,
            "price_decimal": round(self.price_decimal, 4), "p_win": round(self.p_win, 4),
            "p_push": round(self.p_push, 4), "ev_pct": round(self.ev * 100, 2),
            "fair_decimal": round(self.fair_decimal, 4),
            "market_fair_prob": None if self.market_fair_prob is None else round(self.market_fair_prob, 4),
        }


def _fair_decimal(p_win: float, p_push: float) -> float:
    p_loss = max(1e-12, 1.0 - p_win - p_push)
    if p_win <= 0:
        return float("inf")
    return 1.0 + p_loss / p_win


def price_two_way(market: str, labels: Sequence[str], lines: Sequence[Optional[float]],
                  americans: Sequence[float], probs: Sequence[Tuple[float, float]],
                  devig_method: str = "multiplicative") -> List[PricedBet]:
    """Price both sides of a two-way market.

    ``probs``: [(p_win, p_push) for each side] from *your* model.
    The book's devigged probability is attached for comparison.
    """
    decs = [american_to_decimal(a) for a in americans]
    fair = devig(decs, devig_method)
    out = []
    for lab, line, d, (pw, pp), mf in zip(labels, lines, decs, probs, fair):
        out.append(PricedBet(market, lab, line, d, pw, pp, _ev(pw, d, pp), _fair_decimal(pw, pp), mf))
    return out


def price_game(model_margin: MarginModel, total_mu: Optional[float], total_sigma: Optional[float],
               home: str, away: str, home_spread: Optional[float] = None,
               spread_prices: Optional[Tuple[float, float]] = None, total_line: Optional[float] = None,
               total_prices: Optional[Tuple[float, float]] = None,
               moneyline: Optional[Tuple[float, float]] = None,
               devig_method: str = "multiplicative") -> List[PricedBet]:
    """Price every offered side of a game.  Prices are American (home, away) / (over, under)."""
    out: List[PricedBet] = []
    if moneyline:
        ph = model_margin.p_home_win()
        out += price_two_way("moneyline", [home, away], [None, None], moneyline, [(ph, 0.0), (1 - ph, 0.0)], devig_method)
    if home_spread is not None and spread_prices:
        hc, hp, hf = model_margin.spread_probs(home_spread)
        out += price_two_way("spread", [f"{home} {home_spread:+g}", f"{away} {-home_spread:+g}"],
                             [home_spread, -home_spread], spread_prices, [(hc, hp), (hf, hp)], devig_method)
    if total_line is not None and total_prices and total_mu is not None and total_sigma is not None:
        o, u, p = total_probs(total_mu, total_sigma, total_line)
        out += price_two_way("total", [f"Over {total_line:g}", f"Under {total_line:g}"],
                             [total_line, total_line], total_prices, [(o, p), (u, p)], devig_method)
    return out


def alt_spread_ladder(model_margin: MarginModel, home: str, lines: Iterable[float]) -> List[dict]:
    """Fair prices for a ladder of alternate home spreads."""
    rows = []
    for ln in lines:
        c, p, f = model_margin.spread_probs(ln)
        fair = _fair_decimal(c, p)
        rows.append({"selection": f"{home} {ln:+g}", "p_cover": round(c, 4), "p_push": round(p, 4),
                     "fair_decimal": round(fair, 4),
                     "fair_american": round((fair - 1) * 100) if fair >= 2 else round(-100 / (fair - 1))})
    return rows


def key_number_report(model_margin: MarginModel, numbers: Iterable[int] = range(1, 16)) -> List[dict]:
    """P(final margin == k) for home-win margins (k) and away-win margins (-k)."""
    return [{"margin": k, "p_home_by_k": round(model_margin.dist.prob(k), 4),
             "p_away_by_k": round(model_margin.dist.prob(-k), 4)} for k in numbers]
