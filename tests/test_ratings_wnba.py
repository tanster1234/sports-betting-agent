import math
import random
from datetime import date, timedelta

import pytest

from betlab import wnba
from betlab.ratings import KalmanRatings, RatingParams


def synthetic_league(seed=1, teams=10, seasons=(2030, 2031), games_per_team=40, hca=2.0, sigma=11.0):
    rng = random.Random(seed)
    names = [f"T{i}" for i in range(teams)]
    strength = {t: rng.gauss(0, 5) for t in names}
    games = []
    gid = 0
    for s in seasons:
        d = date(s, 5, 10)
        for _ in range(games_per_team * teams // 2):
            h, a = rng.sample(names, 2)
            margin = strength[h] - strength[a] + hca + rng.gauss(0, sigma)
            tot = 160 + rng.gauss(0, 15)
            hp = round((tot + margin) / 2)
            ap = round((tot - margin) / 2)
            if hp == ap:
                hp += 1
            games.append({"game_id": str(gid), "season": s, "date": d.isoformat(), "home": h, "away": a,
                          "home_pts": hp, "away_pts": ap, "neutral": 0})
            gid += 1
            if gid % 5 == 0:
                d += timedelta(days=1)
    return games, strength


def test_ratings_recover_true_strengths():
    games, strength = synthetic_league()
    m = KalmanRatings(RatingParams(hca=2.0, sigma=11.0)).fit(games)
    table = {r["team"]: r["rating"] for r in m.ratings_table()}
    xs = [strength[t] for t in table]
    ys = [table[t] for t in table]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    corr = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(
        sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    assert corr > 0.9


def test_predict_does_not_mutate_state():
    games, _ = synthetic_league(teams=6, seasons=(2030,), games_per_team=10)
    m = KalmanRatings().fit(games)
    before = m.ratings_table()
    p1 = m.predict("T1", "T2", "2030-09-01").as_dict()
    p2 = m.predict("T1", "T2", "2030-09-01").as_dict()
    assert p1 == p2
    assert m.ratings_table() == before


def test_variance_grows_with_rest_and_new_season_regresses():
    games, _ = synthetic_league(teams=6, seasons=(2030,), games_per_team=20)
    p = RatingParams(rho=0.5)
    m = KalmanRatings(p).fit(games)
    last = max(g["date"] for g in games)
    soon = m.predict("T1", "T2", last).sd
    later = m.predict("T1", "T2", "2030-12-31").sd
    assert later > soon
    nxt = m.predict("T1", "T3", "2031-05-15", season=2031)
    cur = m.predict("T1", "T3", last, season=2030)
    assert abs(nxt.mu - p.hca) < abs(cur.mu - p.hca) + 1e-9   # ratings shrink toward 0


def test_back_to_back_penalty_applied():
    m = KalmanRatings(RatingParams(b2b_penalty=2.3))
    base = m.predict("A", "B", "2030-06-01", home_rest=2, away_rest=2)
    tired_home = m.predict("A", "B", "2030-06-01", home_rest=0, away_rest=2)
    assert base.mu - tired_home.mu == pytest.approx(2.3)
    assert any("back-to-back" in n for n in tired_home.notes)


def test_manual_adjustments():
    m = KalmanRatings()
    p = m.predict("A", "B", "2030-06-01", extra_home_adj=-4.0, extra_total_adj=3.0)
    q = m.predict("A", "B", "2030-06-01")
    assert p.mu == pytest.approx(q.mu - 4.0)
    assert p.total_mu == pytest.approx(q.total_mu + 3.0)
    assert p.home_team_total + p.away_team_total == pytest.approx(p.total_mu)


# ---------------- bundled WNBA data ----------------
def test_bundled_data_shapes(wnba_games, wnba_lines, calib_games, calib_lines):
    assert len(calib_games) == 3318 and len(calib_lines) == 340    # the documented snapshot
    assert len(wnba_games) >= 3318 and len(wnba_lines) >= 340      # refreshes only append
    assert {g["season"] for g in wnba_games} == set(range(2013, 2027))
    teams_2026 = {g["home"] for g in wnba_games if g["season"] == 2026}
    assert teams_2026 == set(wnba.TEAMS)
    assert "CONN" not in {g["home"] for g in wnba_games}


def test_lines_match_game_results(wnba_games, wnba_lines):
    by = {g["game_id"]: g for g in wnba_games}
    for l in wnba_lines:
        g = by[l["game_id"]]
        assert (g["home"], g["away"]) == (l["home"], l["away"])
        assert int(l["home_pts"]) == g["home_pts"] and int(l["away_pts"]) == g["away_pts"]
        assert abs(l["spread_price_home_close"]) >= 100 and abs(l["over_price_open"]) >= 100


def test_fit_until_has_no_lookahead(wnba_games):
    a = wnba.fit_model(wnba_games, until="2026-07-01")
    b = wnba.fit_model([g for g in wnba_games if g["date"] < "2026-07-01"])
    pa = wnba.predict(a, "LV", "NY", "2026-07-01").as_dict()
    pb = wnba.predict(b, "LV", "NY", "2026-07-01").as_dict()
    assert pa == pb


def test_model_accuracy_regression(wnba_model):
    """Golden numbers from .claude/skills/wnba-betting/references/calibration.md — fail loudly if the model drifts."""
    ev26 = wnba_model.evaluate([2026])
    assert ev26["n"] == 340
    assert 12.7 < ev26["margin_rmse"] < 13.2       # DK closing spread RMSE was 12.69
    assert 18.5 < ev26["total_rmse"] < 19.4        # DK closing total RMSE was 18.69
    train = wnba_model.evaluate(range(2014, 2026))
    assert 12.2 < train["margin_rmse"] < 12.6


def test_2026_playoff_teams_rate_highest(wnba_model):
    table = [r["team"] for r in wnba_model.ratings_table(2026)]
    playoff = {"MIN", "GS", "LV", "ATL", "WSH", "IND", "DAL", "NY"}
    assert set(table[:8]) == playoff


def test_season_summary_matches_calibration_doc(calib_games):
    rows = {r["season"]: r for r in wnba.season_summary(calib_games)}
    assert rows[2026]["avg_total"] == pytest.approx(174.1, abs=0.05)
    assert rows[2026]["hca_ols"] == pytest.approx(1.80, abs=0.01)
    assert rows[2025]["avg_total"] == pytest.approx(163.3, abs=0.05)
    assert rows[2026]["ortg"] == pytest.approx(104.8, abs=0.1)


def test_fit_hca_ols_recovers_synthetic_hca():
    games, _ = synthetic_league(teams=8, seasons=(2030,), games_per_team=60, hca=3.0, sigma=8.0, seed=4)
    # OLS assumes constant strengths, which holds in the generator
    r = wnba.fit_hca_ols(games)
    assert r["hca"] == pytest.approx(3.0, abs=3 * r["hca_se"])
    assert r["resid_sd"] == pytest.approx(8.0, abs=1.0)


def test_canonical_aliases():
    assert wnba.canonical("conn") == "CON"
    assert wnba.canonical("SA") == "LV"
    assert wnba.canonical("TUL") == "DAL"
