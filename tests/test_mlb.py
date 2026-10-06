import json
import random
from pathlib import Path

import pytest

from betlab import mlb
from betlab.cli import main
from betlab.fetch import mlb_stats

FIX = Path(__file__).parent / "fixtures"
P = mlb.Params()                       # fixed parameters: tests don't depend on the committed fit


def _draw(pmf, rng):
    u, c = rng.random(), 0.0
    for k, p in enumerate(pmf):
        c += p
        if u < c:
            return k
    return len(pmf) - 1


def _simulate(mua, muh, post, n, seed=7):
    """Brute-force games with the same rules, to check the exact calculation."""
    rng = random.Random(seed)
    m = P.inning_mult
    ah = [mlb.nb_pmf(mua * m[i], P.r) for i in range(9)]
    hh = [mlb.nb_pmf(muh * m[i], P.r) for i in range(9)]
    xa = ah[8] if post else mlb.nb_pmf(P.ghost_mean * mua / P.league_mu, P.ghost_r)
    xh = hh[8] if post else mlb.nb_pmf(P.ghost_mean * muh / P.league_mu, P.ghost_r)
    out = []
    for _ in range(n):
        a = h = 0
        for i in range(8):
            a += _draw(ah[i], rng)
            h += _draw(hh[i], rng)
        a += _draw(ah[8], rng)
        if h <= a:
            k = _draw(hh[8], rng)
            h = a + min(h + k - a, _draw(P.walkoff_cap, rng)) if h + k > a else h + k
            while h == a:
                x, y = _draw(xa, rng), _draw(xh, rng)
                a += x
                h = a + min(h + y - a, _draw(P.walkoff_cap, rng)) if h + y > a else h + y
        out.append((a, h))
    return out


def test_nb_pmf_and_convolution():
    pmf = mlb.nb_pmf(0.5, 0.42)
    assert sum(pmf) == pytest.approx(1.0) and sum(k * p for k, p in enumerate(pmf)) == pytest.approx(0.5, abs=2e-3)
    assert pmf[0] > 0.7                                                    # most half-innings are scoreless
    c = mlb.convolve([0.5, 0.5], [0.5, 0.5])
    assert c == pytest.approx([0.25, 0.5, 0.25])
    assert mlb.nb_logpmf(2, 0.5, 0.42) == pytest.approx(__import__("math").log(pmf[2]))


@pytest.mark.parametrize("post", [False, True])
def test_exact_game_matches_simulation(post):
    gd = mlb.game_dist(0.45, 0.53, P, post)
    sims = _simulate(0.45, 0.53, post, 40000)
    n = len(sims)
    assert sum(gd.joint.values()) == pytest.approx(1.0, abs=1e-9)
    assert gd.p_home() == pytest.approx(sum(h > a for a, h in sims) / n, abs=0.01)
    assert gd.run_line(-1.5)[0] == pytest.approx(sum(h - a >= 2 for a, h in sims) / n, abs=0.01)
    assert gd.over_under(8.5)[0] == pytest.approx(sum(a + h > 8.5 for a, h in sims) / n, abs=0.01)
    assert sum(gd.mean_runs()) == pytest.approx(sum(a + h for a, h in sims) / n, abs=0.06)


def test_game_rules():
    gd = mlb.game_dist(0.5, 0.5, P)
    m = gd.margin_pmf()
    assert m.get(1, 0) > m.get(2, 0) and m[1] > m[-1]                      # walk-offs pile up on +1
    assert 0.07 < gd.p_extra < 0.14 and sum(p for v, p in m.items() if v == 0) == 0
    post = mlb.game_dist(0.5, 0.5, P, postseason=True)
    assert post.p_extra == pytest.approx(gd.p_extra, abs=1e-9)             # regulation is identical
    assert sum(post.mean_runs()) < sum(gd.mean_runs())                     # no automatic runner: fewer extra runs
    f5h, f5a, f5t = gd.f5_result()
    assert f5h + f5a + f5t == pytest.approx(1.0) and 0.12 < f5t < 0.2
    assert 0.4 < gd.nrfi < 0.6


def test_solve_reproduces_the_market_and_prices_everything():
    p_home, p_over = mlb.market_probs(+120, -140, 8.5, -105, -115)
    gd = mlb.solve(p_home, 8.5, p_over, P)
    o, u, _ = gd.over_under(8.5)
    assert gd.p_home() == pytest.approx(p_home, abs=1e-3) and o / (o + u) == pytest.approx(p_over, abs=1e-3)
    pr = mlb.price(gd, totals=[7.5, 8.5, 9.5], team_totals=[("home", 4.5)], f5_totals=[4.5])
    t = {x["line"]: x for x in pr["totals"]}
    assert t[7.5]["p_over"] > t[8.5]["p_over"] > t[9.5]["p_over"]
    rl = {x["home_line"]: x for x in pr["run_lines"]}
    assert rl[-1.5]["p_home"] < pr["p_home"] < rl[1.5]["p_home"]
    assert pr["f5"]["p_home_lead"] > pr["f5"]["p_away_lead"]
    whole = mlb.solve(0.55, 8.0, 0.5, P)                                   # whole-number total: pushes allowed
    o, u, push = whole.over_under(8.0)
    assert push > 0.06 and o / (o + u) == pytest.approx(0.5, abs=1e-3)


def test_offers():
    gd = mlb.solve(0.56, 8.5, 0.5, P)
    ml = mlb.evaluate_offer(gd, "ml", "home", None, -110)
    assert ml["p_win"] == pytest.approx(gd.p_home(), abs=1e-4)
    rl = mlb.evaluate_offer(gd, "runline", "away", 1.5, -150)
    assert rl["p_win"] == pytest.approx(gd.run_line(-1.5)[1], abs=1e-4)
    f5 = mlb.evaluate_offer(gd, "f5_ml", "home", None, -120)
    assert f5["p_push"] > 0.1                                              # tie after five = push
    tt = mlb.evaluate_offer(gd, "team_total", "home_over", 4.5, -105)
    assert tt["p_win"] == pytest.approx(gd.team_over_under("home", 4.5)[0], abs=1e-4)
    n = mlb.evaluate_offer(gd, "nrfi", "nrfi", None, -120)
    assert n["p_win"] == pytest.approx(gd.nrfi, abs=1e-4)
    with pytest.raises(ValueError):
        mlb.evaluate_offer(gd, "strikeouts", "over", 6.5, -110)


def _write_games(path, rows):
    import csv
    fields = ["season", "season_type", "date", "event_id", "away", "home", "away_score", "home_score", "innings",
              "away_ls", "home_ls", "notes", "provider", "total", "over", "under", "ml_away", "ml_home",
              "rl_line_home", "rl_home", "rl_away", "open_total", "open_ml_away", "open_ml_home"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def test_load_games_and_linescores(tmp_path):
    p = tmp_path / "games.csv"
    base = {"season": 2025, "season_type": "regular", "provider": "ESPN BET", "total": 8.5, "over": -110, "under": -110,
            "ml_away": 120, "ml_home": -140}
    _write_games(p, [
        {**base, "date": "2025-05-02", "event_id": "2", "away": "A", "home": "B", "away_score": 2, "home_score": 3,
         "innings": 9, "away_ls": "0;0;0;1;0;0;1;0;0", "home_ls": "1;0;0;0;2;0;0;0"},            # home skipped the 9th
        {**base, "date": "2025-05-01", "event_id": "1", "away": "A", "home": "B", "away_score": 4, "home_score": 0,
         "innings": 5, "away_ls": "0;0;0;0;4", "home_ls": "0;0;0;0;0"},                       # rain-shortened
        {**base, "date": "2025-05-03", "event_id": "3", "away": "A", "home": "B", "away_score": 1, "home_score": 1,
         "innings": 9, "away_ls": "0;0;0;1;0;0;0;0;0", "home_ls": "0;0;0;0;0;0;0;0;1", "total": "", "ml_home": ""},
    ])
    rows = mlb.load_games(str(p))
    assert [r["event_id"] for r in rows] == ["1", "2"]                       # no odds -> dropped; sorted by date
    assert not mlb.linescore_ok(rows[0]) and mlb.linescore_ok(rows[1])
    assert rows[1]["home_ls"] == [1, 0, 0, 0, 2, 0, 0, 0] and rows[1]["postseason"] is False


def test_fitting_recovers_simulated_parameters():
    rng = random.Random(3)
    truth = mlb.Params(r=0.5, inning_mult=(1.2, 0.9, 1.0, 1.0, 1.0, 1.0, 1.0, 0.95, 0.95))
    rows, mus = [], []
    for _ in range(3000):
        ma, mh = rng.uniform(0.4, 0.6), rng.uniform(0.4, 0.6)
        al = [_draw(mlb.nb_pmf(ma * truth.inning_mult[i], truth.r), rng) for i in range(9)]
        hl = [_draw(mlb.nb_pmf(mh * truth.inning_mult[i], truth.r), rng) for i in range(8)]
        rows.append({"away_ls": al, "home_ls": hl, "postseason": False})
        mus.append((ma, mh))
    fit = mlb.fit_innings(rows, mus, mlb.Params())
    assert fit.r == pytest.approx(0.5, abs=0.06)
    assert fit.inning_mult[0] == pytest.approx(1.2 / (sum(truth.inning_mult) / 9), abs=0.07)
    assert sum(fit.inning_mult) == pytest.approx(9, abs=1e-3)


def test_walkoff_em():
    rng = random.Random(5)
    cap = (0.0, 0.7, 0.1, 0.1, 0.1)
    rows, mus = [], []
    params = mlb.Params()
    while len(rows) < 1500:
        mh = 0.5
        pmf = mlb.nb_pmf(mh * params.inning_mult[8], params.r)
        d = rng.choice([0, 0, 0, 1, 1, 2])
        k = _draw(pmf, rng)
        if k <= d:
            continue
        margin = min(k - d, _draw(cap, rng))
        before = 3                                                         # home runs before its last half
        rows.append({"away_ls": [before + d] + [0] * 8, "home_ls": [before] + [0] * 7 + [d + margin],
                     "away_score": before + d, "home_score": before + d + margin, "postseason": True})
        mus.append((0.5, mh))
    fit = mlb.fit_walkoff(rows, mus, params)
    assert fit.walkoff_cap[1] == pytest.approx(0.7, abs=0.06)


def test_committed_calibration_golden_numbers():
    cal = mlb.load_calibration()
    p = cal["params"]
    assert 0.35 < p["r"] < 0.45 and 0.45 < p["r_first"] < 0.5 and 0.49 < p["league_mu"] < 0.51
    assert sum(p["inning_mult"]) == pytest.approx(9, abs=1e-2) and p["inning_mult"][0] == max(p["inning_mult"])
    trail, tied, lead = p["top9"]
    assert trail < 1 and tied < 1 < lead and p["bottom9"] < 0.9                       # closers in the 9th
    assert 1.1 < p["ghost_mean"] < 1.25 and 0.7 < p["walkoff_cap"][1] < 0.8
    v = cal["validation"]
    assert v["n_games"] == 2446 and cal["fit"]["n_train"] == 7383
    rl = v["run_line_vs_market"]
    assert rl["log_loss_model"] <= rl["log_loss_market"] + 0.001                         # as good as the book's run line
    ll = v["final_score_loglik_per_game"]
    assert ll["model"] > ll["independent_poisson"] + 0.4
    for k, tol in (("total_+1", 0.01), ("total_-1", 0.01), ("total_+2", 0.01), ("total_-2", 0.01), ("f5_tie", 0.01),
                   ("nrfi", 0.01), ("home_-1.5", 0.015), ("away_-1.5", 0.015), ("one_run", 0.025), ("extra_innings", 0.02)):
        m = v["markets"][k]
        assert abs(m["predicted"] - m["actual"]) < tol, k
    assert v["markets"]["one_run"]["predicted"] > v["markets"]["one_run"]["actual"]     # the known lean, documented


def test_stats_api_parsers():
    games = mlb_stats.parse_schedule(json.loads((FIX / "mlb_schedule_20261006.json").read_text()))
    g = games[0]
    assert (g["away"]["abbr"], g["home"]["abbr"], g["postseason"]) == ("LAD", "ATL", True)
    assert g["away"]["probable"]["name"] == "Yoshinobu Yamamoto" and g["series"] == "Series tied 1-1"
    ps = mlb_stats.parse_pitcher_stats(json.loads((FIX / "mlb_pitcher_808967.json").read_text()))
    assert ps["season"]["starts"] == 28 and ps["season"]["k_pct"] == 25.7 and len(ps["last_starts"]) == 3
    bx = mlb_stats.parse_pitchers(json.loads((FIX / "mlb_boxscore_849823.json").read_text()))
    assert bx["home"][0]["starter"] and not bx["home"][1]["starter"] and bx["home"][0]["pitches"] == 90


def test_mlb_cli(capsys):
    assert main(["mlb", "price", "--ml", "+120", "-140", "--total", "8.5", "-105", "-115",
                 "--offer", "runline:home:-1.5:+150:dk", "nrfi:nrfi:0:-115", "team_total:away_over:3.5:-120"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["market_p_home"] == pytest.approx(out["p_home"], abs=1e-3) and len(out["offers"]) == 3
    assert out["offers"][0]["book"] == "dk" and out["postseason"] is False
    assert main(["mlb", "price", "--p-home", "0.6", "--total", "7.5", "--postseason"]) == 0
    assert json.loads(capsys.readouterr().out)["postseason"] is True
    assert main(["mlb", "price", "--ml", "+120", "-140", "--total", "8.5", "--offer", "total:over"]) == 1
    assert "bad --offer" in capsys.readouterr().out
    assert main(["mlb", "price", "--ml", "+120", "-140"]) == 1
    assert "--total" in capsys.readouterr().out
    assert main(["mlb", "validate"]) == 0
    assert "params" in json.loads(capsys.readouterr().out)


def test_scan_row_mapping_uses_each_sides_own_run_line():
    from betlab.cli import _mlb_row_offer
    gd = mlb.solve(0.50, 6.5, 0.5, P, postseason=True)
    away_fav = _mlb_row_offer(gd, {"market": "spreads", "name": "LAD", "point": -1.5, "price": 170}, "ATL", "LAD")
    assert away_fav["p_win"] == pytest.approx(gd.run_line(1.5)[1], abs=1e-4) and away_fav["p_win"] < 0.4
    home_dog = _mlb_row_offer(gd, {"market": "spreads", "name": "ATL", "point": 1.5, "price": -190}, "ATL", "LAD")
    assert home_dog["p_win"] == pytest.approx(1 - away_fav["p_win"], abs=1e-4)
    nrfi = _mlb_row_offer(gd, {"market": "totals_1st_1_innings", "name": "Under", "point": 0.5, "price": -120}, "ATL", "LAD")
    assert nrfi["side"] == "nrfi" and nrfi["p_win"] == pytest.approx(gd.nrfi, abs=1e-4)
    tt = _mlb_row_offer(gd, {"market": "team_totals", "name": "Over", "description": "ATL", "point": 3.5,
                             "price": -105}, "ATL", "LAD")
    assert tt["p_win"] == pytest.approx(gd.team_over_under("home", 3.5)[0], abs=1e-4)


def test_sharp_period_lines_replace_the_model_split():
    from betlab.cli import _mlb_anchor_periods
    gd = mlb.solve(0.495, 6.5, 0.479, P, postseason=True)
    rows = [{"book": "pinnacle", "market": "totals_1st_1_innings", "name": "Over", "point": 0.5, "price": 147},
            {"book": "pinnacle", "market": "totals_1st_1_innings", "name": "Under", "point": 0.5, "price": -174},
            {"book": "pinnacle", "market": "totals_1st_5_innings", "name": "Over", "point": 3.0, "price": -106},
            {"book": "pinnacle", "market": "totals_1st_5_innings", "name": "Under", "point": 3.0, "price": -108},
            {"book": "betonlineag", "market": "h2h_1st_5_innings", "name": "ATL", "point": None, "price": -120},
            {"book": "betonlineag", "market": "h2h_1st_5_innings", "name": "LAD", "point": None, "price": 100}]
    g2, done = _mlb_anchor_periods(gd, rows, "ATL", "LAD")
    assert done == ["first_inning", "f5"]
    assert g2.nrfi == pytest.approx(0.611, abs=0.005) and g2.nrfi > gd.nrfi            # aces: sharper NRFI than the average split
    o, u, _ = g2.f5_over_under(3.0)
    assert o / (o + u) == pytest.approx(0.5 + 0.0, abs=0.01)
    assert g2.joint is gd.joint                                                          # full game untouched
    yrfi = mlb.evaluate_offer(g2, "nrfi", "yrfi", None, 146)
    assert yrfi["ev_pct"] < 0                                                            # FanDuel +146 was not a bet
