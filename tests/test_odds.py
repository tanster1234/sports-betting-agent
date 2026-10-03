
import pytest

from betlab import odds as O


@pytest.mark.parametrize("american,decimal", [(-110, 1.909091), (100, 2.0), (-100, 2.0), (150, 2.5), (-200, 1.5),
                                              (-150, 1.666667), (250, 3.5), (-1100, 1.090909)])
def test_american_to_decimal_golden(american, decimal):
    assert O.american_to_decimal(american) == pytest.approx(decimal, abs=1e-6)


@pytest.mark.parametrize("decimal", [1.01, 1.5, 1.909, 2.0, 2.5, 7.0, 101.0])
def test_decimal_american_roundtrip(decimal):
    assert O.american_to_decimal(O.decimal_to_american(decimal)) == pytest.approx(decimal, rel=1e-12)


def test_implied_probabilities():
    assert O.american_to_prob(-150) == pytest.approx(0.6)
    assert O.american_to_prob(130) == pytest.approx(100 / 230)
    assert O.american_to_prob(-110) == pytest.approx(110 / 210)
    assert O.prob_to_american(0.6) == pytest.approx(-150)
    assert O.prob_to_american(0.4) == pytest.approx(150)


@pytest.mark.parametrize("bad", [-99, 50, 0, 99.9])
def test_invalid_american(bad):
    with pytest.raises(O.OddsError):
        O.american_to_decimal(bad)


@pytest.mark.parametrize("text,dec", [("-110", 1.909091), ("+150", 2.5), ("150", 2.5), ("2.5", 2.5), ("1.91", 1.91),
                                      ("−120", 1.833333), (-200, 1.5), (3.25, 3.25)])
def test_parse_price(text, dec):
    assert O.parse_price(text) == pytest.approx(dec, abs=1e-6)


@pytest.mark.parametrize("bad", ["", "abc", "+50", "-1.9", "0.9", "1"])
def test_parse_price_rejects(bad):
    with pytest.raises(O.OddsError):
        O.parse_price(bad)


def test_overround_and_hold_standard_market():
    d = O.american_to_decimal(-110)
    assert O.overround([d, d]) == pytest.approx(0.047619, abs=1e-6)
    assert O.hold([d, d]) == pytest.approx(0.045455, abs=1e-6)


@pytest.mark.parametrize("method", O.DEVIG_METHODS)
def test_devig_symmetric_market_is_fifty_fifty(method):
    d = O.american_to_decimal(-110)
    assert O.devig([d, d], method) == pytest.approx([0.5, 0.5], abs=1e-9)


@pytest.mark.parametrize("method", O.DEVIG_METHODS)
@pytest.mark.parametrize("prices", [(-300, 250), (-110, -110), (-1000, 650), (2.1, 3.4, 3.6), (1.5, 4.0, 7.0, 15.0)])
def test_devig_sums_to_one_and_preserves_order(method, prices):
    decs = [O.parse_price(p) for p in prices]
    fair = O.devig(decs, method)
    assert sum(fair) == pytest.approx(1.0, abs=1e-9)
    assert all(0 < p < 1 for p in fair)
    # shorter price -> higher fair probability
    order = sorted(range(len(decs)), key=lambda i: decs[i])
    assert [fair[i] for i in order] == sorted(fair, reverse=True)


def test_devig_multiplicative_golden():
    fair = O.devig_american([-300, 250])
    assert fair[0] == pytest.approx(0.75 / (0.75 + 1 / 3.5), abs=1e-12)


def test_power_and_shin_shift_margin_to_longshot():
    decs = [O.american_to_decimal(-300), O.american_to_decimal(250)]
    mult = O.devig(decs, "multiplicative")[1]
    assert O.devig(decs, "power")[1] < mult
    assert O.devig(decs, "shin")[1] < mult


def test_fair_price_range_brackets_methods():
    decs = [O.american_to_decimal(-300), O.american_to_decimal(250)]
    lo, hi = O.fair_price_range(decs, 1)
    for m in O.DEVIG_METHODS:
        assert lo - 1e-12 <= O.devig(decs, m)[1] <= hi + 1e-12


def test_no_vig_market_is_returned_as_is():
    assert O.devig([2.0, 2.0], "power") == pytest.approx([0.5, 0.5])


def test_ev_golden_values():
    # 57% at -110: EV = .57 * .90909 - .43 = .088182  (reference repo example, correct here)
    assert O.ev_american(0.57, -110) == pytest.approx(0.0881818, abs=1e-6)
    assert O.ev(0.5, 2.0) == pytest.approx(0.0)
    assert O.ev(0.4, 3.0) == pytest.approx(0.2)


def test_ev_with_push():
    # 50% win, 10% push, 40% loss at even money: EV = 0.5 - 0.4 = 0.1
    assert O.ev(0.5, 2.0, 0.1) == pytest.approx(0.1)


def test_ev_rejects_bad_probabilities():
    with pytest.raises(O.OddsError):
        O.ev(0.7, 2.0, 0.4)
    with pytest.raises(O.OddsError):
        O.ev(1.2, 2.0)


def test_prob_edge_vs_ev_differ_by_price():
    # same 2-point probability edge is worth more EV at longer prices
    d1 = O.american_to_decimal(-110)
    d2 = O.american_to_decimal(300)
    e1 = O.ev(1 / d1 + 0.02, d1)
    e2 = O.ev(1 / d2 + 0.02, d2)
    assert e1 == pytest.approx(0.02 * d1)
    assert e2 == pytest.approx(0.02 * d2)
    assert e2 > e1


def test_min_price_for_ev():
    d = O.min_price_for_ev(0.55, 0.02)
    assert O.ev(0.55, d) == pytest.approx(0.02)


def test_min_price_for_ev_with_push():
    # spread on a key number: 50% win, 4% push -> the push refund lowers the price needed
    d = O.min_price_for_ev(0.50, 0.02, push_prob=0.04)
    assert O.ev(0.50, d, 0.04) == pytest.approx(0.02)
    assert d < O.min_price_for_ev(0.50, 0.02)
    with pytest.raises(O.OddsError):
        O.min_price_for_ev(0.7, 0.0, push_prob=0.4)


def test_parlay_decimal():
    assert O.parlay_decimal([2.0, 2.0, 2.0]) == pytest.approx(8.0)


@pytest.mark.parametrize("pm,pk", [(0.6, 0.5), (0.3, 0.45), (0.9, 0.7)])
def test_blend_probs_bounds_and_monotone(pm, pk):
    assert O.blend_probs(pm, pk, 0.0) == pytest.approx(pk)
    assert O.blend_probs(pm, pk, 1.0) == pytest.approx(pm)
    mid = O.blend_probs(pm, pk, 0.5)
    assert min(pm, pk) < mid < max(pm, pk)
    assert O.blend_probs(pm, pk, 0.3) == pytest.approx(1 - O.blend_probs(1 - pm, 1 - pk, 0.3))


def test_blend_rejects_bad_weight():
    with pytest.raises(O.OddsError):
        O.blend_probs(0.5, 0.5, 1.5)


def test_logit_inverse():
    for p in (0.01, 0.3, 0.5, 0.77, 0.99):
        assert O.inv_logit(O.logit(p)) == pytest.approx(p)
