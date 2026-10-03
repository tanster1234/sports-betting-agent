import pytest

from betlab.markets import (
    MarginModel,
    alt_spread_ladder,
    basketball_margin_dist,
    implied_sigma,
    key_number_report,
    period_lines,
    price_game,
    spread_from_win_prob,
    team_totals_from_lines,
    total_probs,
    win_prob_from_spread,
)
from betlab.odds import ev


def test_pickem_is_fifty_fifty():
    assert MarginModel.normal(0.0, 12.5, "WNBA").p_home_win() == pytest.approx(0.5, abs=1e-9)


def test_basketball_model_has_no_ties():
    d = basketball_margin_dist(1.5, 12.5)
    assert d.prob(0) == 0.0
    assert sum(d.pmf.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("line", [-7.5, -5.5, -3, 0, 2.5, 4])
def test_spread_probs_partition(line):
    mm = MarginModel.normal(5.0, 12.5, "WNBA")
    c, p, f = mm.spread_probs(line)
    assert c + p + f == pytest.approx(1.0)
    if line != int(line):
        assert p == 0.0
    hc, hp, hf = mm.spread_probs(line)
    ac, ap, af = mm.away_spread_probs(-line)
    assert (ac, ap, af) == pytest.approx((hf, hp, hc))


def test_cover_prob_at_fair_line_is_half():
    mm = MarginModel.normal(5.5, 12.5, "WNBA")
    c, p, f = mm.spread_probs(-5.5)
    assert c == pytest.approx(0.5, abs=0.01)
    assert mm.fair_home_spread() == -5.5


def test_win_prob_monotone_in_spread():
    probs = [win_prob_from_spread(s, 12.5) for s in (-12, -6, -1, 0, 3, 9)]
    assert probs == sorted(probs, reverse=True)
    assert win_prob_from_spread(-6.5, 12.5) == pytest.approx(0.70, abs=0.01)


def test_spread_from_win_prob_roundtrip():
    s = spread_from_win_prob(0.70, 12.5)
    assert s == pytest.approx(-6.555, abs=0.01)


def test_implied_sigma_recovers_input():
    mm = MarginModel.normal(6.5, 12.7)
    p = mm.p_home_win()
    assert implied_sigma(-6.5, p) == pytest.approx(12.7, abs=0.2)


def test_half_point_value_on_integer_crossing():
    mm = MarginModel.normal(5.5, 12.5, "WNBA")
    h = mm.half_point_value(-5.5)
    assert h["delta_win"] == pytest.approx(0.0)       # -5 and -5.5 win on the same margins
    assert h["delta_not_lose"] > 0.02                  # but -5 pushes on exactly 5
    assert mm.dist.prob(5) == pytest.approx(h["delta_not_lose"])


def test_totals_and_team_totals():
    o, u, p = total_probs(172.0, 18.0, 172.0)
    assert o == pytest.approx(u, abs=1e-9) and p > 0
    assert team_totals_from_lines(-5.5, 170.5) == (88.0, 82.5)


def test_period_lines_wnba():
    pl = period_lines(-8.0, 172.0, "WNBA", "first_half")
    assert pl["home_spread"] == pytest.approx(-4.8)
    assert pl["total"] == pytest.approx(86.0)
    with pytest.raises(KeyError):
        period_lines(-3, 45, "NFL", "first_half")


def test_price_game_ev_consistent_with_odds_module():
    mm = MarginModel.normal(4.0, 12.5, "WNBA")
    bets = price_game(mm, 170.0, 18.0, "ATL", "NY", home_spread=-3.5, spread_prices=(-110, -110),
                      total_line=168.5, total_prices=(-110, -110), moneyline=(-160, 135))
    assert {b.market for b in bets} == {"moneyline", "spread", "total"}
    for b in bets:
        assert b.ev == pytest.approx(ev(b.p_win, b.price_decimal, b.p_push))
        assert b.market_fair_prob is not None
    sp = [b for b in bets if b.market == "spread"]
    assert sp[0].p_win + sp[1].p_win + sp[0].p_push == pytest.approx(1.0)


def test_alt_ladder_monotone():
    mm = MarginModel.normal(4.0, 12.5, "WNBA")
    ladder = alt_spread_ladder(mm, "ATL", [-10.5, -7.5, -4.5, -1.5, 1.5])
    covers = [r["p_cover"] for r in ladder]
    assert covers == sorted(covers)


def test_key_number_report():
    rows = key_number_report(MarginModel.normal(3.0, 12.5, "WNBA"), range(1, 6))
    assert len(rows) == 5
    assert all(r["p_home_by_k"] > r["p_away_by_k"] for r in rows)


def test_empirical_pmf_supported():
    mm = MarginModel.from_pmf({3: 0.4, -3: 0.3, 7: 0.3})
    assert mm.spread_probs(-3) == pytest.approx((0.3, 0.4, 0.3))
