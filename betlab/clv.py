"""Closing-line value (CLV).

CLV answers "did I get a better price than the efficient market settled
on?"  It converges far faster than win/loss results: ~50 bets of CLV say
more about skill than ~1,000 bets of results.

For a bet at decimal price d_bet and a closing two-way market whose
devigged probability for your side is p_close:

    clv_prob = p_close - 1/d_bet          (probability points)
    clv_ev   = p_close * d_bet - 1         (expected ROI if the close is "true")

For spreads/totals where the *number* moved, compare at the same number by
converting the closing line to a probability at your number with a margin
model (``clv_spread_points``).
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Iterable, Optional

from .markets import MarginModel
from .odds import american_to_decimal, devig

_ND = NormalDist()


def clv_from_prices(bet_american: float, close_side_american: float, close_other_american: float,
                    method: str = "multiplicative") -> dict:
    """CLV of a bet against the devigged closing two-way price."""
    d_bet = american_to_decimal(bet_american)
    p_close = devig([american_to_decimal(close_side_american), american_to_decimal(close_other_american)], method)[0]
    return {
        "bet_decimal": d_bet,
        "close_fair_prob": p_close,
        "close_fair_decimal": 1.0 / p_close,
        "clv_prob": p_close - 1.0 / d_bet,
        "clv_ev": p_close * d_bet - 1.0,
    }


def clv_spread_points(bet_line: float, bet_american: float, close_line: float,
                      close_side_american: float, close_other_american: float,
                      sigma: float, sport: Optional[str] = "WNBA", method: str = "multiplicative") -> dict:
    """CLV for a spread when the number moved (see ``clv_total_points`` for totals).

    1. Devig the closing two-way price at the closing line.
    2. Find the margin mean that reproduces that probability at the closing line.
    3. Re-price *your* line under that market-implied distribution.
    """
    p_close_side = devig([american_to_decimal(close_side_american), american_to_decimal(close_other_american)], method)[0]
    # Solve mu so that P(margin + close_line > 0 | mu) (excluding pushes) = p_close_side
    lo, hi = -60.0, 60.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        c, p, f = MarginModel.normal(mid, sigma, sport).spread_probs(close_line)
        prob = c / (c + f) if (c + f) > 0 else 0.5
        if prob < p_close_side:
            lo = mid
        else:
            hi = mid
    mu = 0.5 * (lo + hi)
    c, p, f = MarginModel.normal(mu, sigma, sport).spread_probs(bet_line)
    d = american_to_decimal(bet_american)
    ev = c * (d - 1.0) - f
    return {"market_mu": mu, "p_cover_at_bet_line": c, "p_push_at_bet_line": p,
            "clv_ev": ev, "points_moved_in_favour": bet_line - close_line}


def summarize(clv_values: Iterable[float]) -> dict:
    """Mean CLV with standard error, t-stat and two-sided p-value (normal approx)."""
    vals = [float(v) for v in clv_values]
    n = len(vals)
    if n == 0:
        return {"n": 0}
    mean = sum(vals) / n
    if n > 1:
        var = sum((v - mean) ** 2 for v in vals) / (n - 1)
        se = math.sqrt(var / n)
    else:
        var, se = 0.0, float("nan")
    t = mean / se if se and se > 0 else float("nan")
    p = 2 * (1 - _ND.cdf(abs(t))) if t == t else float("nan")
    return {"n": n, "mean": mean, "sd": math.sqrt(var), "se": se, "t": t, "p_value": p,
            "share_positive": sum(v > 0 for v in vals) / n}


def clv_total_points(bet_line: float, bet_american: float, side: str, close_line: float,
                     close_over_american: float, close_under_american: float, sigma: float,
                     method: str = "multiplicative") -> dict:
    """CLV for a total when the number moved.

    The devigged closing over probability at the closing line pins down a
    market-implied mean (normal model with ``sigma``); your line is then
    re-priced under that distribution.  ``side`` is "over" or "under".
    """
    from .distributions import discretized_normal, norm_ppf

    side = side.lower()
    if side not in ("over", "under"):
        raise ValueError("side must be 'over' or 'under'")
    p_over_close = devig([american_to_decimal(close_over_american), american_to_decimal(close_under_american)], method)[0]
    mu = close_line + norm_ppf(p_over_close) * sigma
    o, u, p = discretized_normal(mu, sigma).over_under_push(bet_line)
    pw = o if side == "over" else u
    d = american_to_decimal(bet_american)
    moved = (close_line - bet_line) if side == "over" else (bet_line - close_line)
    return {"market_mu": mu, "p_win_at_bet_line": pw, "p_push_at_bet_line": p,
            "clv_ev": pw * (d - 1.0) - (1.0 - pw - p), "points_moved_in_favour": moved}
