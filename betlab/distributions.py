"""Small, dependency-free probability toolkit.

``DiscreteDist`` is the workhorse: an integer-valued pmf with helpers for
over/under/push probabilities at any line (half-point or integer).  Margins,
totals, goals, runs and player stats are all represented this way so every
pricing function shares the same push handling.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Dict, Iterable, Optional, Tuple

_STD = NormalDist()


def norm_cdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    return NormalDist(mu, sigma).cdf(x)


def norm_ppf(p: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    return NormalDist(mu, sigma).inv_cdf(p)


def norm_pdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    return NormalDist(mu, sigma).pdf(x)


class DiscreteDist:
    """Integer-valued distribution stored as {value: probability}."""

    __slots__ = ("pmf",)

    def __init__(self, pmf: Dict[int, float], normalize: bool = True):
        clean = {int(k): float(v) for k, v in pmf.items() if v > 0}
        if not clean:
            raise ValueError("empty distribution")
        if normalize:
            s = sum(clean.values())
            clean = {k: v / s for k, v in clean.items()}
        self.pmf = dict(sorted(clean.items()))

    # -- moments ---------------------------------------------------------
    def mean(self) -> float:
        return sum(k * p for k, p in self.pmf.items())

    def var(self) -> float:
        m = self.mean()
        return sum((k - m) ** 2 * p for k, p in self.pmf.items())

    def sd(self) -> float:
        return math.sqrt(self.var())

    # -- probabilities ---------------------------------------------------
    def prob(self, k: int) -> float:
        return self.pmf.get(int(k), 0.0)

    def cdf(self, x: float) -> float:
        """P(X <= x)."""
        return sum(p for k, p in self.pmf.items() if k <= x)

    def sf(self, x: float) -> float:
        """P(X > x)."""
        return sum(p for k, p in self.pmf.items() if k > x)

    def over_under_push(self, line: float) -> Tuple[float, float, float]:
        """(P(X > line), P(X < line), P(X == line)); push only on integer lines."""
        over = sum(p for k, p in self.pmf.items() if k > line)
        under = sum(p for k, p in self.pmf.items() if k < line)
        push = 1.0 - over - under
        return over, under, max(0.0, push)

    def quantile(self, q: float) -> int:
        acc = 0.0
        for k, p in self.pmf.items():
            acc += p
            if acc >= q - 1e-12:
                return k
        return max(self.pmf)

    def median_line(self) -> float:
        """Half-point line closest to a 50/50 split (the 'fair' line)."""
        best, best_gap = None, 2.0
        lo, hi = min(self.pmf), max(self.pmf)
        k = lo - 0.5
        while k <= hi + 0.5:
            o, u, _ = self.over_under_push(k)
            if abs(o - u) < best_gap:
                best, best_gap = k, abs(o - u)
            k += 1.0
        return best

    # -- algebra ---------------------------------------------------------
    def convolve(self, other: "DiscreteDist") -> "DiscreteDist":
        """Distribution of X + Y for independent X, Y."""
        out: Dict[int, float] = {}
        for a, pa in self.pmf.items():
            for b, pb in other.pmf.items():
                out[a + b] = out.get(a + b, 0.0) + pa * pb
        return DiscreteDist(out)

    def difference(self, other: "DiscreteDist") -> "DiscreteDist":
        """Distribution of X - Y for independent X, Y."""
        out: Dict[int, float] = {}
        for a, pa in self.pmf.items():
            for b, pb in other.pmf.items():
                out[a - b] = out.get(a - b, 0.0) + pa * pb
        return DiscreteDist(out)

    def shift(self, c: int) -> "DiscreteDist":
        return DiscreteDist({k + int(c): p for k, p in self.pmf.items()}, normalize=False)

    def negate(self) -> "DiscreteDist":
        return DiscreteDist({-k: p for k, p in self.pmf.items()}, normalize=False)

    def trimmed(self, eps: float = 1e-12) -> "DiscreteDist":
        return DiscreteDist({k: p for k, p in self.pmf.items() if p > eps})

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DiscreteDist(mean={self.mean():.3f}, sd={self.sd():.3f}, support={min(self.pmf)}..{max(self.pmf)})"


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------

def discretized_normal(mu: float, sigma: float, width: float = 8.0) -> DiscreteDist:
    """Integer pmf with continuity correction: P(k) = Phi(k+.5) - Phi(k-.5)."""
    if sigma <= 0:
        raise ValueError("sigma must be > 0")
    nd = NormalDist(mu, sigma)
    lo = int(math.floor(mu - width * sigma))
    hi = int(math.ceil(mu + width * sigma))
    pmf = {}
    prev = nd.cdf(lo - 0.5)
    for k in range(lo, hi + 1):
        cur = nd.cdf(k + 0.5)
        pmf[k] = cur - prev
        prev = cur
    return DiscreteDist(pmf)


def poisson_pmf(k: int, lam: float) -> float:
    if k < 0:
        return 0.0
    if lam == 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(k * math.log(lam) - lam - math.lgamma(k + 1))


def poisson(lam: float, tail: float = 1e-12) -> DiscreteDist:
    if lam < 0:
        raise ValueError("lambda must be >= 0")
    pmf = {}
    k, acc = 0, 0.0
    upper = int(lam + 12 * math.sqrt(lam + 1) + 20)
    while k <= upper:
        p = poisson_pmf(k, lam)
        pmf[k] = p
        acc += p
        if acc > 1 - tail and k > lam:
            break
        k += 1
    return DiscreteDist(pmf)


def negbin_mean_var(mean: float, var: float, tail: float = 1e-12) -> DiscreteDist:
    """Negative binomial parameterised by mean and variance (var > mean).

    r = mean^2 / (var - mean), p = r / (r + mean).  Falls back to Poisson when
    var <= mean (no over-dispersion).
    """
    if mean < 0:
        raise ValueError("mean must be >= 0")
    if mean == 0:
        return DiscreteDist({0: 1.0})
    if var <= mean * (1 + 1e-9):
        return poisson(mean, tail)
    r = mean * mean / (var - mean)
    p = r / (r + mean)
    pmf = {}
    k, acc = 0, 0.0
    log_p, log_q = math.log(p), math.log1p(-p)
    upper = int(mean + 15 * math.sqrt(var) + 30)
    while k <= upper:
        lp = math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * log_p + k * log_q
        pk = math.exp(lp)
        pmf[k] = pk
        acc += pk
        if acc > 1 - tail and k > mean:
            break
        k += 1
    return DiscreteDist(pmf)


def mixture(components: Iterable[Tuple[float, DiscreteDist]]) -> DiscreteDist:
    """Weighted mixture of discrete distributions."""
    out: Dict[int, float] = {}
    for w, d in components:
        for k, p in d.pmf.items():
            out[k] = out.get(k, 0.0) + w * p
    return DiscreteDist(out)


def gauss_hermite_normal_nodes(mu: float, sigma: float, n: int = 15,
                               lower: Optional[float] = None) -> list:
    """Quadrature-like (value, weight) nodes for a (truncated) normal via
    equal-probability slices — robust and dependency-free."""
    nd = NormalDist(mu, sigma)
    lo_p = nd.cdf(lower) if lower is not None else 0.0
    nodes = []
    for i in range(n):
        q = lo_p + (1 - lo_p) * (i + 0.5) / n
        nodes.append((nd.inv_cdf(min(max(q, 1e-12), 1 - 1e-12)), 1.0 / n))
    return nodes
