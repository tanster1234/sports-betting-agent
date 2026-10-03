import pytest

from betlab.clv import clv_from_prices, clv_spread_points, clv_total_points, summarize
from betlab.markets import MarginModel
from betlab.odds import american_to_decimal, devig
from betlab.parlay import (
    correlated_parlay_prob,
    independent_parlay,
    parlay_hold,
    sgp_ev,
    teaser_ev,
    teaser_legs,
)
from betlab.series import (
    FORMATS,
    implied_game_prob_from_series,
    series_from_ratings,
    series_probs,
)


# ---------------- parlays ----------------
def test_independent_parlay():
    r = independent_parlay([0.55, 0.55], [1.909, 1.909])
    assert r["p_all"] == pytest.approx(0.3025)
    assert r["ev"] == pytest.approx(0.3025 * 1.909 ** 2 - 1)


def test_parlay_hold_compounds():
    assert parlay_hold([0.0455, 0.0455]) == pytest.approx(1 - 0.9545 ** 2)
    assert parlay_hold([0.0455] * 4) > 0.16


def test_correlated_parlay_zero_corr_matches_independence():
    r = correlated_parlay_prob([0.6, 0.5], [[1, 0], [0, 1]], n=60000, seed=1)
    assert r["p_all"] == pytest.approx(0.30, abs=4 * r["se"])


def test_positive_correlation_lifts_joint_probability():
    lo = correlated_parlay_prob([0.6, 0.5], [[1, 0.0], [0.0, 1]], n=40000)["p_all"]
    hi = correlated_parlay_prob([0.6, 0.5], [[1, 0.5], [0.5, 1]], n=40000)["p_all"]
    assert hi > lo + 0.03


def test_sgp_ev_has_ci():
    r = sgp_ev([0.6, 0.55], [[1, 0.35], [0.35, 1]], 230, n=30000)
    assert r["ev_ci95"][0] < r["ev"] < r["ev_ci95"][1]


def test_teaser_moves_lines_in_bettors_favour():
    mm = MarginModel.normal(2.5, 13.5)
    legs = teaser_legs([mm, mm], [-2.5, -2.5], 6, [True, False])
    assert legs[0]["home_line_after"] == 3.5
    assert legs[1]["home_line_after"] == -8.5
    base_home = mm.spread_probs(-2.5)[0]
    assert legs[0]["p_win"] > base_home
    r = teaser_ev(legs, -120)
    assert 0 < r["p_all_win"] < 1


# ---------------- CLV ----------------
def test_clv_from_prices_golden():
    r = clv_from_prices(-105, -125, 105)
    p_close = devig([american_to_decimal(-125), american_to_decimal(105)])[0]
    assert r["close_fair_prob"] == pytest.approx(p_close)
    assert r["clv_ev"] == pytest.approx(p_close * american_to_decimal(-105) - 1)
    assert r["clv_ev"] > 0


def test_clv_negative_when_market_moves_away():
    assert clv_from_prices(-125, -105, -115)["clv_ev"] < 0


def test_clv_spread_same_line_equals_price_clv():
    a = clv_spread_points(-3.5, -110, -3.5, -120, 100, 12.5)
    b = clv_from_prices(-110, -120, 100)
    assert a["clv_ev"] == pytest.approx(b["clv_ev"], abs=0.003)


def test_clv_spread_moving_through_numbers_is_positive():
    r = clv_spread_points(-3.5, -110, -5.5, -110, -110, 12.5)
    assert r["points_moved_in_favour"] == 2.0
    assert r["clv_ev"] > 0.05


def test_clv_total_sign_by_side():
    over = clv_total_points(168.5, -110, "over", 170.5, -110, -110, 18.0)
    under = clv_total_points(168.5, -110, "under", 170.5, -110, -110, 18.0)
    assert over["points_moved_in_favour"] == 2.0 and over["clv_ev"] > 0
    assert under["points_moved_in_favour"] == -2.0 and under["clv_ev"] < -0.04


def test_clv_summary_stats():
    s = summarize([0.02, 0.03, -0.01, 0.04, 0.01])
    assert s["n"] == 5 and s["mean"] == pytest.approx(0.018)
    assert s["t"] > 0 and 0 < s["p_value"] < 1


# ---------------- series ----------------
@pytest.mark.parametrize("fmt", sorted(FORMATS))
def test_coin_flip_series_is_half(fmt):
    r = series_probs(0.5, 0.5, fmt)
    assert r["p_higher_seed"] == pytest.approx(0.5)
    assert sum(r["exact"].values()) == pytest.approx(1.0)
    assert sum(r["length"].values()) == pytest.approx(1.0)


def test_best_of_three_closed_form():
    p1, p2, p3 = 0.65, 0.45, 0.65
    r = series_probs(0.65, 0.45, "1-1-1")
    expect = p1 * p2 + p1 * (1 - p2) * p3 + (1 - p1) * p2 * p3
    assert r["p_higher_seed"] == pytest.approx(expect)


def test_series_state_and_per_game_override():
    r = series_probs(0.6, 0.45, "2-2-1", wins_high=2, wins_low=0)
    assert r["p_higher_seed"] > 0.85
    assert set(r["exact"]) <= {"3-0", "3-1", "3-2", "2-3"}
    r2 = series_probs(0.6, 0.45, "2-2-1", per_game=[0.6, 0.6, 0.3, 0.3, 0.6])
    assert r2["p_higher_seed"] < series_probs(0.6, 0.45, "2-2-1")["p_higher_seed"]
    with pytest.raises(ValueError):
        series_probs(0.6, 0.4, "1-1-1", wins_high=2)


def test_series_from_ratings_monotone_and_amplifies():
    ps = [series_from_ratings(d, 1.75, 12.5, "2-2-1-1-1")["p_higher_seed"] for d in (-3, 0, 2, 5)]
    assert ps == sorted(ps)
    r = series_from_ratings(3.0, 1.75, 12.5, "2-2-1-1-1")
    avg_game = (r["p_game_home"] + r["p_game_away"]) / 2
    assert r["p_higher_seed"] > avg_game   # longer series favour the better team


def test_implied_game_prob_roundtrip():
    target = series_probs(0.58, 0.58, "2-2-1-1-1")["p_higher_seed"]
    assert implied_game_prob_from_series(target, "2-2-1-1-1") == pytest.approx(0.58, abs=1e-4)
