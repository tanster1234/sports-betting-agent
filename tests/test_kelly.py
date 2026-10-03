import pytest

from betlab.kelly import (
    StakeLimits,
    growth_rate,
    kelly_fraction,
    overbet_multiple_where_growth_turns_negative,
    risk_of_ruin_mc,
    simultaneous_kelly,
    stake_plan,
)
from betlab.odds import american_to_decimal


def test_kelly_golden():
    # (b p - q) / b with p=.57 at -110  ->  9.70% (reference repo's docs got this one right)
    assert kelly_fraction(0.57, american_to_decimal(-110)) == pytest.approx(0.0970, abs=1e-4)


def test_kelly_zero_when_negative_ev():
    assert kelly_fraction(0.5, american_to_decimal(-110)) == 0.0
    assert kelly_fraction(0.3, 3.0) == 0.0


def test_reference_repo_formula_bug_is_not_reproduced():
    """magicjordan33 used Kelly = edge*d/(d-1) with edge vs the *vig-free* prob (50%).

    For p=.57 at -110 that gives (0.07*1.909)/0.909 = 14.7% — 1.5x the true Kelly.
    """
    d = american_to_decimal(-110)
    buggy = (0.57 - 0.50) * d / (d - 1)
    assert buggy == pytest.approx(0.147, abs=1e-3)
    assert kelly_fraction(0.57, d) < buggy / 1.4


@pytest.mark.parametrize("p_w,p_p,d", [(0.5, 0.06, 2.0), (0.48, 0.05, 2.1), (0.55, 0.0, 1.909), (0.3, 0.0, 4.0)])
def test_push_aware_kelly_maximises_growth(p_w, p_p, d):
    f = kelly_fraction(p_w, d, p_p)
    grid = [i / 10000 for i in range(0, 5000)]
    best = max(grid, key=lambda x: growth_rate(x, p_w, d, p_p))
    assert f == pytest.approx(best, abs=2e-4)


def test_overbetting_twice_kelly_kills_growth():
    m = overbet_multiple_where_growth_turns_negative(0.55, 1.909)
    assert 1.9 < m < 2.1
    f = kelly_fraction(0.55, 1.909)
    assert growth_rate(2.2 * f, 0.55, 1.909) < 0 < growth_rate(f, 0.55, 1.909)


def test_reference_tier_sizing_exceeds_full_kelly():
    """A 4-unit (8% of bankroll) 'Tier A' bet at +4.8% EV, -110 is >1.5x full Kelly."""
    d = american_to_decimal(-110)
    p = (1.048) / d  # EV 4.8%
    assert 0.08 / kelly_fraction(p, d) > 1.5


def test_simultaneous_kelly_close_to_individual_for_small_edges():
    bets = [dict(p_win=0.54, decimal=1.909), dict(p_win=0.55, decimal=1.909), dict(p_win=0.36, decimal=3.2)]
    joint = simultaneous_kelly(bets)
    singles = [kelly_fraction(b["p_win"], b["decimal"]) for b in bets]
    for j, s in zip(joint, singles):
        assert j == pytest.approx(s, rel=0.15)
        assert j <= s + 1e-6


def test_simultaneous_kelly_respects_cap():
    bets = [dict(p_win=0.65, decimal=2.0)] * 4
    joint = simultaneous_kelly(bets, max_total=0.2)
    assert sum(joint) <= 0.2 + 1e-9


def test_simultaneous_kelly_with_push_and_fallback():
    bets = [dict(p_win=0.5, p_push=0.05, decimal=2.0)] * 3
    assert all(f > 0 for f in simultaneous_kelly(bets))
    many = [dict(p_win=0.55, decimal=1.909)] * 12   # > 10 bets -> scaled singles
    out = simultaneous_kelly(many, max_total=0.3)
    assert sum(out) == pytest.approx(0.3)


def _cands():
    return [dict(label="a", p_win=0.56, decimal=1.909, game="g1", sport="WNBA"),
            dict(label="b", p_win=0.58, decimal=1.909, game="g1", sport="WNBA"),
            dict(label="c", p_win=0.60, decimal=1.909, game="g2", sport="WNBA")]


def test_stake_plan_never_exceeds_caps():
    lim = StakeLimits(bankroll=1000, max_bet_pct=0.03, max_game_pct=0.04, max_daily_pct=0.05, max_sport_pct=0.08)
    plan = stake_plan(_cands(), lim)
    by = {d.label: d for d in plan}
    assert all(d.stake <= 30 for d in plan)
    assert by["a"].stake + by["b"].stake <= 40 + 1e-9
    assert sum(d.stake for d in plan) <= 50 + 1e-9
    assert any("max_daily_pct" in d.capped_by or "max_game_pct" in d.capped_by for d in plan)


def test_stake_plan_prioritises_best_ev_and_respects_existing_exposure():
    lim = StakeLimits(bankroll=1000, max_daily_pct=0.10)
    plan = stake_plan(_cands(), lim, already_exposed={"__day__": 0.09})
    assert sum(d.stake for d in plan) <= 10 + 1e-9
    by = {d.label: d for d in plan}
    assert by["c"].stake >= by["a"].stake   # c has the biggest edge


def test_stake_plan_fractional_kelly_and_units():
    lim = StakeLimits(bankroll=2000, kelly_multiplier=0.25, unit_pct=0.01, round_to=1)
    d = stake_plan([dict(label="x", p_win=0.55, decimal=1.909, game="g", sport="WNBA")], lim)[0]
    full = kelly_fraction(0.55, 1.909)
    assert d.stake == pytest.approx(int(2000 * full * 0.25))
    assert d.units == pytest.approx(d.stake / 20)


def test_stake_plan_drops_tiny_and_negative_bets():
    lim = StakeLimits(bankroll=100, min_stake=5)
    plan = stake_plan([dict(label="neg", p_win=0.45, decimal=1.909, game="g"),
                       dict(label="tiny", p_win=0.53, decimal=1.909, game="h")], lim)
    assert all(d.stake == 0 for d in plan)


def test_risk_of_ruin_deterministic_and_sane():
    a = risk_of_ruin_mc(0.55, 1.909, 0.0137, n_bets=300, trials=300)
    b = risk_of_ruin_mc(0.55, 1.909, 0.0137, n_bets=300, trials=300)
    assert a == b
    reckless = risk_of_ruin_mc(0.55, 1.909, 0.25, n_bets=300, trials=300)
    assert reckless["p_hit_ruin_level"] > a["p_hit_ruin_level"]
