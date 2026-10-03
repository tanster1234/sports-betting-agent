"""Price conversions, vig removal and expected value.

Conventions used everywhere in betlab
-------------------------------------
* ``american``  : -110, +150 ...  (|odds| >= 100)
* ``decimal``   : total return per 1 staked, including the stake (1.909, 2.50)
* ``prob``      : a probability in (0, 1)
* ``EV``        : expected *profit* per 1 unit staked.  EV = p * (d - 1) - (1 - p)
                  = p * d - 1.  "EV%" is EV * 100.
* ``prob edge`` : p - breakeven, where breakeven = 1 / d (the vigged implied
                  probability of the price you are actually getting).

The difference between EV% and probability edge matters: at -110 a 2.0
percentage-point probability edge is +3.8% EV; at +300 it is +8.0% EV.  The
skills always report both, and thresholds are expressed in EV%.
"""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Union

Number = Union[int, float]

DEVIG_METHODS = ("multiplicative", "additive", "power", "shin", "odds_ratio")


class OddsError(ValueError):
    """Raised for impossible prices or probabilities."""


# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------

def american_to_decimal(american: Number) -> float:
    a = float(american)
    if -100 < a < 100:
        raise OddsError(f"American odds must satisfy |odds| >= 100, got {american}")
    return 1.0 + (a / 100.0 if a > 0 else 100.0 / -a)


def decimal_to_american(decimal: Number) -> float:
    d = float(decimal)
    if d <= 1.0:
        raise OddsError(f"Decimal odds must be > 1, got {decimal}")
    return (d - 1.0) * 100.0 if d >= 2.0 else -100.0 / (d - 1.0)


def decimal_to_prob(decimal: Number) -> float:
    d = float(decimal)
    if d <= 1.0:
        raise OddsError(f"Decimal odds must be > 1, got {decimal}")
    return 1.0 / d


def prob_to_decimal(prob: Number) -> float:
    p = float(prob)
    if not 0.0 < p < 1.0:
        raise OddsError(f"Probability must be in (0, 1), got {prob}")
    return 1.0 / p


def american_to_prob(american: Number) -> float:
    """Implied probability of a single price (still contains the vig)."""
    return decimal_to_prob(american_to_decimal(american))


def prob_to_american(prob: Number) -> float:
    return decimal_to_american(prob_to_decimal(prob))


def parse_price(text: Union[str, Number]) -> float:
    """Parse a user-supplied price and return *decimal* odds.

    Accepts American ("-110", "+150", "150", "-100") and decimal ("1.91",
    "2.5").  Anything with |x| >= 100 is treated as American; anything in
    (1, 100) as decimal.  Raises OddsError on ambiguous/invalid input.
    """
    if isinstance(text, (int, float)):
        x = float(text)
        s = str(text)
    else:
        s = str(text).strip().replace("−", "-")  # unicode minus
        if not s:
            raise OddsError("empty price")
        try:
            x = float(s)
        except ValueError as exc:
            raise OddsError(f"cannot parse price {text!r}") from exc
    if abs(x) >= 100:
        return american_to_decimal(x)
    if 1.0 < x < 100:
        if s.startswith("+") or s.startswith("-"):
            raise OddsError(f"{text!r} looks like American odds but |odds| < 100")
        return x
    raise OddsError(f"cannot interpret price {text!r}")


def format_american(american: Number) -> str:
    a = round(float(american))
    return f"+{a}" if a > 0 else str(a)


# ---------------------------------------------------------------------------
# Market margin
# ---------------------------------------------------------------------------

def overround(decimals: Sequence[Number]) -> float:
    """Sum of implied probabilities minus 1 (0.0476 for -110/-110)."""
    return sum(1.0 / float(d) for d in decimals) - 1.0


def hold(decimals: Sequence[Number]) -> float:
    """Theoretical hold: the book's expected margin on balanced action.

    hold = 1 - 1 / sum(implied).  -110/-110 -> 4.55%.
    """
    s = sum(1.0 / float(d) for d in decimals)
    return 1.0 - 1.0 / s


# ---------------------------------------------------------------------------
# Vig removal
# ---------------------------------------------------------------------------

def _bisect(f, lo: float, hi: float, tol: float = 1e-12, maxiter: int = 200) -> float:
    flo = f(lo)
    for _ in range(maxiter):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if abs(fm) < tol or (hi - lo) < tol:
            return mid
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return 0.5 * (lo + hi)


def devig(decimals: Sequence[Number], method: str = "multiplicative") -> List[float]:
    """Return fair probabilities for a complete market (all outcomes listed).

    Methods
    -------
    multiplicative  p_i = pi_i / sum(pi).  Standard for two-way markets.
    additive        p_i = pi_i - (sum - 1)/n.  Removes vig equally; can break
                    for longshots (clipped then renormalised).
    power           p_i = pi_i ** k with k chosen so sum = 1.  Puts more of
                    the margin on longshots (favourite-longshot bias).
    shin            Shin (1993) insider-trading model; similar to power.
                    Good default for futures and 3+-way markets.
    odds_ratio      fair odds-ratio scaled by a constant (Cheung 2015).

    For a -110/-110 market every method returns 50/50.  They diverge for
    lopsided prices; when they disagree by more than your edge, you do not
    have an edge.
    """
    if method not in DEVIG_METHODS:
        raise OddsError(f"unknown devig method {method!r}; choose from {DEVIG_METHODS}")
    if len(decimals) < 2:
        raise OddsError("need at least two outcomes to remove vig")
    pis = [1.0 / float(d) for d in decimals]
    for d in decimals:
        if float(d) <= 1.0:
            raise OddsError(f"decimal odds must be > 1, got {d}")
    s = sum(pis)
    n = len(pis)
    if s <= 1.0:
        # No vig (or an arbitrage) — multiplicative normalisation is the only
        # sensible choice and is exact when s == 1.
        return [p / s for p in pis]

    if method == "multiplicative":
        return [p / s for p in pis]

    if method == "additive":
        out = [p - (s - 1.0) / n for p in pis]
        if min(out) <= 0:
            out = [max(p, 1e-9) for p in out]
        t = sum(out)
        return [p / t for p in out]

    if method == "power":
        k = _bisect(lambda k: sum(p ** k for p in pis) - 1.0, 1.0, 50.0)
        out = [p ** k for p in pis]
        t = sum(out)
        return [p / t for p in out]

    if method == "shin":
        def probs(z: float) -> List[float]:
            return [(math.sqrt(z * z + 4.0 * (1.0 - z) * p * p / s) - z) / (2.0 * (1.0 - z)) for p in pis]

        z = _bisect(lambda z: sum(probs(z)) - 1.0, 0.0, 0.999)
        out = probs(z)
        t = sum(out)
        return [p / t for p in out]

    # odds_ratio
    def probs_or(c: float) -> List[float]:
        return [p / (c * (1.0 - p) + p) for p in pis]

    c = _bisect(lambda c: sum(probs_or(c)) - 1.0, 1.0, 100.0)
    out = probs_or(c)
    t = sum(out)
    return [p / t for p in out]


def devig_american(americans: Sequence[Number], method: str = "multiplicative") -> List[float]:
    return devig([american_to_decimal(a) for a in americans], method)


def devig_all_methods(decimals: Sequence[Number]) -> dict:
    """Fair probabilities under every method — use the spread as model risk."""
    return {m: devig(decimals, m) for m in DEVIG_METHODS}


def fair_price_range(decimals: Sequence[Number], index: int = 0) -> tuple:
    """(min, max) fair probability of outcome ``index`` across devig methods."""
    vals = [devig(decimals, m)[index] for m in DEVIG_METHODS]
    return min(vals), max(vals)


# ---------------------------------------------------------------------------
# Expected value
# ---------------------------------------------------------------------------

def breakeven_prob(decimal: Number) -> float:
    """Win probability needed to break even at this price (no pushes)."""
    return 1.0 / float(decimal)


def ev(prob: Number, decimal: Number, push_prob: Number = 0.0) -> float:
    """Expected profit per 1 staked.

    ``prob`` is P(win), ``push_prob`` is P(stake returned).  P(loss) is the
    remainder.  EV = p_win * (d - 1) - p_loss.
    """
    p, d, pp = float(prob), float(decimal), float(push_prob)
    if not (0 <= p <= 1 and 0 <= pp <= 1 and p + pp <= 1 + 1e-12):
        raise OddsError(f"invalid probabilities win={prob} push={push_prob}")
    if d <= 1:
        raise OddsError(f"decimal odds must be > 1, got {decimal}")
    p_loss = max(0.0, 1.0 - p - pp)
    return p * (d - 1.0) - p_loss


def ev_american(prob: Number, american: Number, push_prob: Number = 0.0) -> float:
    return ev(prob, american_to_decimal(american), push_prob)


def prob_edge(prob: Number, decimal: Number) -> float:
    """Probability points above breakeven (no pushes)."""
    return float(prob) - breakeven_prob(decimal)


def min_price_for_ev(prob: Number, min_ev: Number = 0.0) -> float:
    """Worst decimal price you can accept and still have EV >= min_ev.

    d >= (1 + min_ev) / p.  Useful as a "don't bet below" number.
    """
    p = float(prob)
    if not 0 < p < 1:
        raise OddsError(f"probability must be in (0,1), got {prob}")
    return (1.0 + float(min_ev)) / p


def no_vig_line(decimals: Sequence[Number], method: str = "multiplicative") -> List[float]:
    """Fair decimal prices for every outcome."""
    return [1.0 / p for p in devig(decimals, method)]


def parlay_decimal(decimals: Iterable[Number]) -> float:
    out = 1.0
    for d in decimals:
        if float(d) <= 1:
            raise OddsError(f"decimal odds must be > 1, got {d}")
        out *= float(d)
    return out


# ---------------------------------------------------------------------------
# Model / market blending
# ---------------------------------------------------------------------------

def logit(p: float) -> float:
    p = min(max(float(p), 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def inv_logit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def blend_probs(p_model: float, p_market: float, model_weight: float) -> float:
    """Shrink a model probability toward the devigged market in logit space.

    p = inv_logit(w * logit(p_model) + (1 - w) * logit(p_market)).

    Why: when a results-only model disagrees with a sharp market, the market
    is usually right.  Backtests on 2026 WNBA show raw model EVs of 10-30%
    per bet against DraftKings — impossible numbers — while realised CLV was
    a few percent at best.  Blending converts "model says +20%" into an
    honest estimate.  Typical weights: 0.1-0.25 vs sharp closing lines,
    0.3-0.5 vs openers or soft markets where the model has shown CLV.
    """
    w = float(model_weight)
    if not 0.0 <= w <= 1.0:
        raise OddsError("model_weight must be in [0, 1]")
    return inv_logit(w * logit(p_model) + (1 - w) * logit(p_market))
