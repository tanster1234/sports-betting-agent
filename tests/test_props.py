import math

import pytest

from betlab.odds import OddsError, decimal_to_american
from betlab.props import (
    WNBA_DISPERSION,
    PropModel,
    double_double_prob,
    normalize_stat,
    project_from_rate,
    project_mean,
    prop_from_market,
    simulate_player,
    variance_for,
)


@pytest.mark.parametrize("stat", sorted(WNBA_DISPERSION))
def test_dispersion_table_variance(stat):
    a, b = WNBA_DISPERSION[stat]
    assert variance_for(stat, 10.0) == pytest.approx(a * 10 ** b)


@pytest.mark.parametrize("stat,mean", [("points", 18.5), ("rebounds", 7.2), ("assists", 4.4), ("threes", 2.1),
                                       ("pra", 30.0), ("steals", 1.1)])
def test_prop_model_matches_requested_moments(stat, mean):
    pm = PropModel(stat, mean)
    d = pm.dist
    assert d.mean() == pytest.approx(mean, rel=2e-3)
    assert d.var() == pytest.approx(max(pm.var, mean), rel=2e-2)


def test_points_are_overdispersed_assists_near_poisson():
    assert variance_for("points", 18) / 18 > 2.0
    assert 0.9 < variance_for("assists", 4) / 4 < 1.3


def test_aliases():
    assert normalize_stat("PTS") == "points"
    assert normalize_stat("p+r+a") == "pra"
    assert PropModel("3pm", 2.0).stat == "threes"


def test_probs_partition_and_push():
    pm = PropModel("rebounds", 8.0)
    o, u, p = pm.probs(8)
    assert o + u + p == pytest.approx(1.0) and p > 0.05
    o, u, p = pm.probs(8.5)
    assert p == pytest.approx(0.0)


def test_evaluate_ev_and_market_fields():
    out = PropModel("points", 19.4).evaluate(17.5, -115, -105)
    assert out["p_over"] > 0.55
    assert out["ev_over_pct"] > 0 > out["ev_under_pct"]
    assert out["hold_pct"] == pytest.approx(4.71, abs=0.01)


def test_prop_from_market_inverts_model():
    true_mean = 16.3
    pm = PropModel("points", true_mean)
    o, u, _ = pm.probs(15.5)
    # a no-vig two-way price at the model's own probabilities
    over_am = decimal_to_american(1 / o)
    under_am = decimal_to_american(1 / u)
    back = prop_from_market(15.5, over_am, under_am, "points")
    assert back["implied_mean"] == pytest.approx(true_mean, abs=0.05)


def test_project_mean():
    assert project_mean(0.6, 30, pace_factor=1.05, matchup_factor=0.95, usage_factor=1.1) == pytest.approx(0.6 * 30 * 1.05 * 0.95 * 1.1)
    with pytest.raises(OddsError):
        project_mean(-1, 30)


def test_minutes_uncertainty_widens_distribution():
    sure = project_from_rate("points", 0.6, 30)
    unsure = project_from_rate("points", 0.6, 30, minutes_sd=8)
    assert sure.mean == pytest.approx(18.0, rel=1e-3)
    assert unsure.dist.var() > sure.dist.var() * 1.2
    assert unsure.mean == pytest.approx(18.0, rel=0.03)


def test_simulation_marginals_and_correlation():
    sims = simulate_player({"points": 18.0, "threes": 2.2}, n=12000, seed=3)
    pts = [s["points"] for s in sims]
    thr = [s["threes"] for s in sims]
    mp, mt = sum(pts) / len(pts), sum(thr) / len(thr)
    assert mp == pytest.approx(18.0, rel=0.03)
    assert mt == pytest.approx(2.2, rel=0.04)
    cov = sum((a - mp) * (b - mt) for a, b in zip(pts, thr)) / len(pts)
    corr = cov / math.sqrt((sum((a - mp) ** 2 for a in pts) / len(pts)) * (sum((b - mt) ** 2 for b in thr) / len(thr)))
    assert 0.4 < corr < 0.7   # calibrated within-player points-threes corr is 0.62


def test_double_double_monotone():
    lo = double_double_prob(15, 6, 2, n=15000)
    hi = double_double_prob(15, 10, 2, n=15000)
    assert 0 <= lo < hi <= 1
