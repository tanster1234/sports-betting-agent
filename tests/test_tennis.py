import json

import pytest

from betlab import tennis as T
from betlab.cli import main


def test_hold_and_game_from_points():
    assert T.p_hold(0.6) == pytest.approx(0.7357, abs=1e-4)
    assert T.p_hold(0.5) == pytest.approx(0.5)
    assert T.game_from_points(0.6, 0, 0) == pytest.approx(T.p_hold(0.6))
    assert T.game_from_points(0.6, 3, 3) == pytest.approx(0.36 / (1 - 2 * 0.24))      # deuce
    assert T.game_from_points(0.6, 5, 5) == pytest.approx(T.game_from_points(0.6, 3, 3))
    assert T.game_from_points(0.6, 4, 3) > T.game_from_points(0.6, 3, 3) > T.game_from_points(0.6, 3, 4)


def test_tiebreak_set_and_match_symmetry():
    assert T.tiebreak_win(0.64, 0.64, True) == pytest.approx(0.5)
    assert T.tiebreak_win(0.68, 0.62, True, 10) > T.tiebreak_win(0.68, 0.62, True, 7) > 0.5   # longer favours the better server
    sd = T.set_dist(0.64, 0.64, True)
    assert sum(sd.values()) == pytest.approx(1.0) and set(sd) >= {(6, 0), (7, 6), (6, 7), (7, 5)}
    assert sum(p for (a, b), p in sd.items() if a > b) == pytest.approx(0.5)
    md = T.match_dist(0.64, 0.64, 3)
    assert md.p_a == pytest.approx(0.5) and sum(md.total_games.pmf.values()) == pytest.approx(1.0)
    assert all(v == pytest.approx(0.25) for v in md.set_scores.values())
    assert md.total_games.mean() == pytest.approx(25.68, abs=0.05)
    assert T.match_dist(0.66, 0.62, 5, 10).p_a > T.match_dist(0.66, 0.62, 3).p_a > 0.5


def test_inverse_and_form_mixture_reproduce_the_market():
    pa, pb = T.solve_serve(0.70, 0.64)
    assert (pa + pb) / 2 == pytest.approx(0.64) and T.match_dist(pa, pb).p_a == pytest.approx(0.70, abs=1e-4)
    md = T.mixture_dist(0.70, 0.6441, 0.08)
    assert md.p_a == pytest.approx(0.70, abs=2e-3)
    plain = T.match_dist(*T.solve_serve(0.70, 0.6441))
    assert md.total_games.mean() < plain.total_games.mean()          # form variation -> more lopsided matches


def test_price_and_offers():
    out = T.price(0.60, "atp", "hard", games_lines=[22.5], handicaps_a=[-2.5])
    md = out.pop("_dist")
    tot, hc = out["totals"][0], out["handicaps"][0]
    assert tot["p_over"] + tot["p_under"] + tot["p_push"] == pytest.approx(1.0)
    assert hc["p_cover_a"] + hc["p_cover_b"] + hc["p_push"] == pytest.approx(1.0)
    assert out["p_a"] == pytest.approx(0.60, abs=2e-3) and out["p_hold_a"] > out["p_hold_b"]
    assert sum(out["set_scores"].values()) == pytest.approx(1.0, abs=1e-3)
    fair = T.evaluate_offer(md, "games", "over", 22.5, 100)
    assert fair["ev_pct"] == pytest.approx(100 * (2 * tot["p_over"] - 1), abs=0.05)
    assert T.evaluate_offer(md, "handicap", "b", 2.5, -110)["p_win"] == pytest.approx(hc["p_cover_b"], abs=1e-4)
    assert T.evaluate_offer(md, "sets", "a", "2-0", 150)["p_win"] == pytest.approx(out["set_scores"]["2-0"], abs=1e-3)
    with pytest.raises(ValueError):
        T.evaluate_offer(md, "aces", "over", 5, 100)


def test_live_states():
    assert T.parse_score("6-4 3-2") == ([(6, 4)], (3, 2))
    assert T.parse_score("7-6(4) 6-7(5) 2-1") == ([(7, 6), (6, 7)], (2, 1))
    near = T.live_state(0.64, 0.64, "6-0 5-0", "40-0", "a")
    assert near["p_a"] > 0.999 and near["p_win_current_game_a"] > 0.97
    tb = T.live_state(0.64, 0.64, "6-4 6-6", "5-4", "b")
    assert 0.5 < tb["p_win_current_game_a"] < 1 and tb["p_a"] == pytest.approx(tb["p_win_current_game_a"] + (1 - tb["p_win_current_game_a"]) * 0.5, abs=1e-3)
    with pytest.raises(ValueError):
        T.live_state(0.64, 0.64, "6-4 6-4", "0-0", "a")
    lv = T.live_price(0.60, "atp", "hard", score="6-4 2-3", points="15-40", server="a")
    assert 0.5 < lv["p_a"] < 0.8 and lv["games_played"] == 15 and lv["_total"].over_under_push(17.5)[0] == pytest.approx(1.0)


def test_tournament_format_and_names():
    assert T.tournament_format("tennis_atp_shanghai_masters") == {"surface": "hard", "best_of": 3, "final_tb": 7, "grand_slam": False}
    assert T.tournament_format("tennis_atp_wimbledon")["best_of"] == 5
    w = T.tournament_format("tennis_wta_french_open", "wta")
    assert w["surface"] == "clay" and w["best_of"] == 3 and w["final_tb"] == 10
    assert T.name_key("Sinner J.") == T.name_key("Jannik Sinner") == "sinner j"
    assert T.name_key("Auger-Aliassime F.") == T.name_key("Felix Auger Aliassime")
    assert T.name_key("Zhang Zh.") == T.name_key("Zhizhen Zhang")
    assert T.name_key("De Minaur A.") == T.name_key("Alex De Minaur")


def test_completed_matches_and_loaders(tmp_path):
    assert T.completed([(6, 4), (6, 3)], 3) == 1 and T.completed([(4, 6), (7, 6), (3, 6)], 3) == 2
    assert T.completed([(6, 4), (2, 1)], 3) is None and T.completed([(6, 4)], 3) is None       # retirements
    f = tmp_path / "atp_odds.csv"
    f.write_text("Tournament,Date,Series,Court,Surface,Round,Best of,Player_1,Player_2,Winner,Rank_1,Rank_2,Pts_1,Pts_2,Odd_1,Odd_2,Score\n"
                 "Wimbledon,2025-07-01,Grand Slam,Outdoor,Grass,1st Round,5,Sinner J.,Nardi L.,Sinner J.,1,90,10000,600,1.02,15.0,6-4 6-3 6-0\n"
                 "Eastbourne,2025-06-25,ATP250,Outdoor,Grass,2nd Round,3,Fritz T.,Lehecka J.,Lehecka J.,4,30,5000,1500,1.5,2.6,6-7 4-1\n"
                 "Bad,-1,ATP250,Outdoor,Hard,1st Round,3,X Y.,Z W.,X Y.,1,2,1,1,-,-,6-1 6-1\n")
    rows = T.load_matches("atp", str(f))
    assert [r["date"] for r in rows] == ["2025-06-25", "2025-07-01"]
    assert rows[0]["winner"] == 2 and rows[0]["complete"] is False and rows[1]["complete"] is True
    assert T.market_prob(rows[1]) == pytest.approx((1 / 1.02) / (1 / 1.02 + 1 / 15.0))
    assert T.final_tb_for(rows[1]) == 10 and T.final_tb_for(rows[0]) == 7
    sk = tmp_path / "sk"
    sk.mkdir()
    (sk / "atp_matches_2026.csv").write_text(
        "tourney_name,surface,tourney_level,tourney_date,match_num,winner_name,loser_name,score,best_of,round,"
        "w_svpt,w_1stWon,w_2ndWon,l_svpt,l_1stWon,l_2ndWon\n"
        "Roland Garros,Clay,G,20260525,1,Jannik Sinner,Carlos Alcaraz,6-4 6-7(5) 6-3 6-4,5,F,100,50,15,110,45,20\n"
        "Challenger X,Clay,C,20260525,1,A B,C D,6-1 6-1,3,R32,50,30,5,50,20,5\n")
    srows = T.load_sackmann("atp", [2026], str(sk))
    assert len(srows) == 1 and srows[0]["date"] == "2026-05-25" and srows[0]["complete"]
    assert T.serve_rates(srows)["clay"] == {"rate": round((65 + 65) / 210, 4), "serve_points": 210}


def test_elo_moves_ratings_and_validation_shape():
    elo = T.Elo()
    assert elo.prob("A B.", "C D.", "hard") == pytest.approx(0.5)
    for _ in range(5):
        elo.update("A B.", "C D.", True, "hard", 3, "2025-01-01")
    assert elo.prob("A B.", "C D.", "hard") > 0.6 and elo.prob("A B.", "C D.", "hard", 5) > elo.prob("A B.", "C D.", "hard", 3)
    rows = [{"date": f"2025-0{1 + i % 9}-01", "p1": "A B.", "p2": "C D.", "winner": 1, "surface": "hard", "best_of": 3,
             "odd1": 1.5, "odd2": 2.6} for i in range(20)]
    v = T.validate_elo(rows, "2025-05-01")
    assert v["n"] > 0 and set(v["blends"]) >= {"0.0", "1.0"} and v["blends"]["0.0"] == v["market"]


def test_committed_calibration_golden_numbers():
    cal = T.load_calibration()
    lv, sd = cal["serve_level"], cal["form_sd"]
    assert 0.63 < lv["atp"]["hard"] < 0.66 and lv["atp"]["clay"] < lv["atp"]["hard"] < lv["atp"]["grass"]
    assert 0.55 < lv["wta"]["hard"] < 0.59 and lv["wta"]["clay"] < lv["wta"]["hard"] < lv["wta"]["grass"]
    assert all(0.04 <= sd[t][s] <= 0.12 for t in ("atp", "wta") for s in ("hard", "clay", "grass"))
    for t in ("atp", "wta"):
        for s in ("hard", "clay", "grass"):
            v = cal["validation"][t][s]
            assert abs(v["mean_games"]["actual"] - v["mean_games"]["model"]) < 0.4             # held-out 2024+
            assert v["loglik_per_match"]["model"] > v["loglik_per_match"]["no_form"]
        e = cal["elo"][t]
        assert e["market"]["log_loss"] < e["elo"]["log_loss"]                                   # the market wins
        assert e["blends"]["0.0"]["log_loss"] <= min(b["log_loss"] for b in e["blends"].values())
    bo5 = cal["validation"]["atp_best_of_5"]
    assert abs(bo5["mean_games"]["actual"] - bo5["mean_games"]["model"]) < 0.5


def test_tennis_cli(capsys):
    assert main(["tennis", "price", "--ml", "-165", "140", "--games", "22.5", "--offer", "games:over:22.5:-110", "ml:b:0:150"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["p_source"] == "devigged --ml" and len(out["offers"]) == 2 and out["totals"][0]["line"] == 22.5
    assert main(["tennis", "live", "--p", "0.6", "--score", "6-4 2-3", "--points", "15-40", "--server", "a",
                 "--games", "25.5", "--offer", "ml:a:0:-150"]) == 0
    live = json.loads(capsys.readouterr().out)
    assert live["sets"] == "1-0" and live["offers"][0]["market"] == "ml"
    assert main(["tennis", "price", "--p", "0.6", "--offer", "games:over"]) == 1
    assert "bad --offer" in capsys.readouterr().out
    assert main(["tennis", "price"]) == 1
    assert "--ml" in capsys.readouterr().out
    assert main(["tennis", "validate"]) == 0
    assert "serve_level" in json.loads(capsys.readouterr().out)
