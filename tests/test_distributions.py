import math

import pytest

from betlab.distributions import (
    DiscreteDist,
    discretized_normal,
    mixture,
    negbin_mean_var,
    norm_cdf,
    poisson,
    poisson_pmf,
)


@pytest.mark.parametrize("mu,sigma", [(0, 12.5), (5.5, 12.5), (-3.2, 8.0), (170.5, 18.0)])
def test_discretized_normal_moments(mu, sigma):
    d = discretized_normal(mu, sigma)
    assert sum(d.pmf.values()) == pytest.approx(1.0)
    assert d.mean() == pytest.approx(mu, abs=0.01)
    assert d.sd() == pytest.approx(math.sqrt(sigma ** 2 + 1 / 12), abs=0.02)  # Sheppard's correction


def test_over_under_push_partition():
    d = discretized_normal(3.0, 10.0)
    for line in (-2.5, 0, 3, 3.5, 10):
        o, u, p = d.over_under_push(line)
        assert o + u + p == pytest.approx(1.0)
        if line != int(line):
            assert p == pytest.approx(0.0)
    assert d.over_under_push(3)[2] > 0


@pytest.mark.parametrize("lam", [0.3, 2.5, 9.0, 27.0])
def test_poisson_moments(lam):
    d = poisson(lam)
    assert d.mean() == pytest.approx(lam, rel=1e-6)
    assert d.var() == pytest.approx(lam, rel=1e-5)
    assert poisson_pmf(2, lam) == pytest.approx(math.exp(-lam) * lam ** 2 / 2)


@pytest.mark.parametrize("mean,var", [(4.0, 6.0), (18.0, 50.0), (1.4, 1.6), (0.7, 0.75)])
def test_negbin_moments(mean, var):
    d = negbin_mean_var(mean, var)
    assert d.mean() == pytest.approx(mean, rel=1e-4)
    assert d.var() == pytest.approx(var, rel=1e-3)


def test_negbin_falls_back_to_poisson():
    d = negbin_mean_var(3.0, 2.0)
    assert d.var() == pytest.approx(3.0, rel=1e-5)


def test_difference_of_poissons_is_skellam_like():
    a, b = poisson(3.1), poisson(2.6)
    diff = a.difference(b)
    assert diff.mean() == pytest.approx(0.5, abs=1e-6)
    assert diff.var() == pytest.approx(5.7, rel=1e-4)
    tot = a.convolve(b)
    assert tot.mean() == pytest.approx(5.7, rel=1e-6)


def test_median_line_is_balanced():
    d = discretized_normal(7.0, 12.0)
    line = d.median_line()
    o, u, _ = d.over_under_push(line)
    assert abs(o - u) < 0.04
    assert line == 6.5 or line == 7.5


def test_mixture_and_shift():
    d = mixture([(0.5, DiscreteDist({0: 1})), (0.5, DiscreteDist({2: 1}))])
    assert d.mean() == pytest.approx(1.0)
    assert d.shift(3).mean() == pytest.approx(4.0)
    assert d.negate().mean() == pytest.approx(-1.0)


def test_quantile():
    d = DiscreteDist({1: 0.2, 2: 0.3, 3: 0.5})
    assert d.quantile(0.1) == 1
    assert d.quantile(0.5) == 2
    assert d.quantile(0.9) == 3


def test_norm_cdf():
    assert norm_cdf(0) == pytest.approx(0.5)
    assert norm_cdf(1.959964) == pytest.approx(0.975, abs=1e-6)
