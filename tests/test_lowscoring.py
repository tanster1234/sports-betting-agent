import pytest

from betlab.lowscoring import mlb_game, nhl_game


def test_mlb_partition_and_complements():
    r = mlb_game(4.6, 4.2, total_line=8.5)
    assert r["p_home_win"] + r["p_away_win"] == pytest.approx(1.0)
    assert r["p_home_minus_1_5"] + r["p_away_plus_1_5"] == pytest.approx(1.0)
    assert r["p_away_minus_1_5"] + r["p_home_plus_1_5"] == pytest.approx(1.0)
    assert r["p_over"] + r["p_under"] + r["p_push"] == pytest.approx(1.0)
    assert 0.06 < r["p_extras"] < 0.14
    assert r["p_home_minus_1_5"] < r["p_home_win"]


def test_mlb_monotone_in_runs():
    lo = mlb_game(4.0, 4.5)["p_home_win"]
    hi = mlb_game(5.0, 4.5)["p_home_win"]
    assert lo < 0.5 < hi


def test_mlb_even_teams_home_edge_only_from_extras():
    r = mlb_game(4.5, 4.5, p_home_extras=0.5)
    assert r["p_home_win"] == pytest.approx(0.5, abs=1e-9)


def test_nhl_ot_rules():
    r = nhl_game(3.0, 3.0, p_home_ot=0.5, total_line=6.5)
    assert r["p_home_win"] == pytest.approx(0.5, abs=1e-9)
    assert r["p_ot"] + r["p_home_regulation_win"] + r["p_away_regulation_win"] == pytest.approx(1.0)
    # OT wins are by exactly one goal, so -1.5 never includes them
    assert r["p_home_minus_1_5"] < r["p_home_regulation_win"]
    assert r["p_over"] + r["p_under"] + r["p_push"] == pytest.approx(1.0)


def test_nhl_empty_net_shift_raises_puckline_and_total():
    base = nhl_game(3.3, 2.8)
    en = nhl_game(3.3, 2.8, empty_net_shift=0.25)
    assert en["p_home_minus_1_5"] > base["p_home_minus_1_5"]
    assert en["exp_total"] > base["exp_total"]
    assert en["p_home_win"] == pytest.approx(base["p_home_win"])   # winner unchanged


def test_nhl_overdispersion_flag():
    assert nhl_game(3.0, 2.7, var_ratio=1.3)["p_ot"] < nhl_game(3.0, 2.7, var_ratio=1.0)["p_ot"]
