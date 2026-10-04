import json
from pathlib import Path

import pytest

from betlab import liveread as lr
from betlab.cli import main

FIX = Path(__file__).parent / "fixtures" / "espn_wnba_live_summary.json"


def play(period, clock, away, home, text="", team=None):
    return {"period": period, "clock": clock, "elapsed_s": (period - 1) * 600 + 600 - lr.clock_seconds(clock),
            "home": home, "away": away, "team": team, "text": text}


def test_clock_and_time_left():
    assert lr.clock_seconds("8:13") == 493 and lr.clock_seconds("45.2") == 45.2 and lr.clock_seconds(None) == 0
    half = lr.time_left(3, 600, "WNBA")
    assert half["seconds_left"] == 1200 and half["frac_left"] == 0.5 and not half["in_ot"]
    assert lr.time_left(2, 360, "NBA")["seconds_left"] == 2 * 720 + 360
    ot = lr.time_left(5, 120, "WNBA")
    assert ot["in_ot"] and ot["seconds_left"] == 120
    with pytest.raises(ValueError):
        lr.time_left(1, 600, "NFL")


def test_parse_real_espn_live_summary():
    g = lr.parse_game(json.loads(FIX.read_text()), "WNBA")
    assert (g["home"], g["away"], g["state"], g["status"]) == ("ATL", "NY", "in", "3:44 - 2nd")
    assert g["score"] == {"home": 32, "away": 36} and g["period"] == 2 and len(g["plays"]) == 144
    assert lr.pregame_line(g) == {"home_spread": -4.5, "total": 172.5, "source": "DraftKings"}
    stewart = next(p for p in g["players"] if p["name"] == "Breanna Stewart")
    assert stewart["team"] == "NY" and stewart["starter"] and stewart["fouls"] == 0
    assert g["teams"]["NY"]["ft"] == (9, 9) and g["teams"]["ATL"]["three"] == (5, 10)
    facts = lr.game_facts(g)
    assert facts["runs"]["lead_changes"] == 14 and facts["runs"]["largest_lead"] == {"ATL": 2, "NY": 6}
    assert [p["name"] for p in facts["foul_trouble"]] == ["Jordin Canada"]
    assert all(len(v) == 5 for v in facts["on_floor"].values())
    assert facts["shooting"]["ATL"]["three_pts_vs_typical"] == 4.8


def test_runs_lead_changes_and_window():
    plays = [play(1, "9:30", 0, 2), play(1, "9:00", 3, 2), play(1, "8:00", 5, 2), play(1, "7:00", 7, 2),
             play(1, "6:00", 9, 2), play(1, "5:00", 9, 4), play(1, "4:00", 9, 9), play(1, "3:00", 9, 9, "foul")]
    r = lr.scoring_runs(plays, "ATL", "NY", min_run=7, window_s=200)
    assert r["runs"] == [{"team": "NY", "points": 9, "from": "1|9:00"},
                         {"team": "ATL", "points": 7, "from": "1|5:00", "ongoing": True}]
    assert r["current_run"] == {"team": "ATL", "points": 7, "from": "1|5:00"}
    assert r["lead_changes"] == 1 and r["ties"] == 1 and r["largest_lead"] == {"ATL": 2, "NY": 7}
    assert r["last_window"]["points"] == {"ATL": 7, "NY": 2}          # plays from 6:20 on


def test_foul_trouble_thresholds():
    ps = [{"team": "A", "name": "x", "fouls": 2, "starter": True, "minutes": 6},
          {"team": "A", "name": "y", "fouls": 6, "starter": False, "minutes": 20},
          {"team": "B", "name": "z", "fouls": 2, "starter": True, "minutes": 9, "dnp": False}]
    assert {p["name"] for p in lr.foul_trouble(ps, 1)} == {"x", "y", "z"}           # 2 fouls in Q1
    q2 = lr.foul_trouble(ps, 2)
    assert [p["name"] for p in q2] == ["y"] and q2[0]["fouled_out"]


def test_on_floor_tracks_substitutions():
    players = [{"team": "A", "name": n, "starter": True} for n in "abcde"] + [{"team": "A", "name": "f", "starter": False}]
    plays = [{"text": "f enters the game for c", "team": None}, {"text": "c enters the game for a", "team": None}]
    assert lr.on_floor(players, plays) == {"A": ["b", "c", "d", "e", "f"]}


def test_live_price_basic_invariants():
    tip = lr.live_price(-4.5, 172.5, 0, 0, 1, 600)
    assert 0.6 < tip["p_home_win"] < 0.68 and abs(tip["exp_final_total"] - 172.5) < 1.5
    # halftime, pick'em, home up 10: the fitted shape keeps less of the lead than plain time scaling
    half = lr.live_price(0, 170, 50, 40, 3, 600)
    assert half["at_halftime_shape"] and half["p_home_win"] < half["naive_p_home_win"]
    assert 8.0 < half["exp_final_margin"] < 9.0                     # 10 - 0.15 * 10
    assert abs(half["exp_final_total"] - (90 + 85 - 0.1 + 0.106 * 5)) < 0.6
    late = lr.live_price(-4.5, 172.5, 80, 77, 4, 0)
    assert late["p_home_win"] > 0.999
    tied = lr.live_price(0, 172.5, 80, 80, 4, 0)
    assert tied["p_overtime"] > 0.99 and abs(tied["p_home_win"] - 0.5) < 0.01
    m = tied["_margin"]
    c, p, f = m.spread_probs(-1.5)
    assert abs(c + p + f - 1) < 1e-9
    ot = lr.live_price(-2, 172.5, 85, 83, 5, 60)
    assert not ot["at_halftime_shape"] and ot["p_home_win"] > 0.7


def test_offers_against_sharp_and_model():
    g = lr.parse_game(json.loads(FIX.read_text()), "WNBA")
    good = lr.live_read(g, offers=[{"market": "ml", "side": "away", "price": 110}],
                        sharp={"ml": {"first": -105, "second": -115}})
    o = good["offers"][0]
    assert o["sharp_p"] > 0.5 and o["ev_vs_sharp_pct"] > 3 and abs(o["model_minus_sharp"]) <= 0.06 and o["qualifies"]
    bad = lr.live_read(g, offers=[{"market": "ml", "side": "away", "price": 110}],
                       sharp={"ml": {"first": -250, "second": 200}})
    assert not bad["offers"][0]["qualifies"] and any("market knows" in n for n in bad["notes"])
    other_line = lr.live_read(g, offers=[{"market": "spread", "side": "away", "line": 2.5, "price": -110}],
                              sharp={"spread": {"line": -1.5, "first": -110, "second": -110}})
    assert other_line["offers"][0]["sharp_p"] is None and "ev_vs_sharp_pct" not in other_line["offers"][0]
    no_sharp = lr.live_read(g, offers=[{"market": "total", "side": "under", "line": 178.5, "price": -110}])
    assert no_sharp["offers"][0]["qualifies"] is False and no_sharp["offers"][0]["p_win"] > 0.6


def test_notes_are_plain_language():
    g = lr.parse_game(json.loads(FIX.read_text()), "WNBA")
    notes = lr.live_read(g)["notes"]
    assert any("Jordin Canada" in n for n in notes)
    assert any(n.startswith("ATL shooting hot") for n in notes)
    assert any(n.startswith("Fair: NY wins") for n in notes)


def test_halftime_validation_golden_numbers():
    from betlab import wnba
    from betlab.ratings import KalmanRatings
    rows = lr.halftime_rows(wnba.load_games(), wnba.load_lines(), lambda: KalmanRatings(wnba.WNBA_PARAMS, aliases=wnba.ALIASES))
    v = lr.validate_halftime(rows)
    assert (v["n_train"], v["n_test"]) == (835, 340)
    pooled = v["fit_pooled"]
    for k in ("mu_share", "reversion", "half_sd", "total_offset", "pace_carry", "half_total_sd"):
        assert pooled[k] == pytest.approx(lr.LIVE_PARAMS["WNBA"][k], abs=0.006), k     # constants match the fit
    assert all(-0.25 < b < -0.09 for b in v["reversion_by_season"].values())           # same sign every season
    t = v["test_win_prob"]
    assert t["fitted"]["log_loss"] < t["naive_time_scaling"]["log_loss"] < t["pregame_only"]["log_loss"]
    mid = next(b for b in v["calibration_by_halftime_lead"] if b["halftime_lead"] == "6-10")
    assert mid["n"] == 338 and abs(mid["leader_won"] - mid["fitted"]) < 0.01 and mid["naive"] - mid["leader_won"] > 0.03
    rm = v["test_2h_total_rmse"]
    assert rm["first_half_pace"] > rm["pregame_half"] + 2                               # pace-chasing is worse


def test_liveread_cli(capsys):
    assert main(["liveread", "--summary", str(FIX), "--offer", "ml:away:0:110:dk", "--sharp", "ml:-105:-115"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["game"] == "NY @ ATL" and out["price"]["fitted"] and out["offers"][0]["book"] == "dk"
    assert main(["liveread", "--summary", str(FIX), "--league", "nba"]) == 0
    nba = json.loads(capsys.readouterr().out)
    assert not nba["price"]["fitted"] and any("borrowed from the WNBA fit" in n for n in nba["notes"])
    assert main(["liveread", "--summary", str(FIX), "--offer", "ml:home"]) == 1
    assert "bad --offer" in capsys.readouterr().out
    assert main(["liveread"]) == 1
