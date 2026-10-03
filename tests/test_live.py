import json

from betlab.cli import main
from betlab.live import apply_live, derive_status, grade_leg


def game(state="in", period=2, status="7:49 - 2nd", away=("ORST", [14, 7]), home=("CSU", [7, 7]), name=None):
    def team(abbr, lines):
        return {"abbr": abbr, "score": float(sum(lines)), "linescores": [float(x) for x in lines]}
    return {"event_id": "1", "name": name or f"{away[0]} @ {home[0]}", "state": state, "completed": state == "post",
            "status": status, "status_name": "STATUS_IN_PROGRESS" if state == "in" else None, "period": period,
            "away": team(*away), "home": team(*home)}


def test_moneyline_live_then_final():
    g = game()
    live = grade_leg({"market": "ml", "team": "ORST"}, g)
    assert live["state"] == "live" and live["result"] is None
    assert live["now"] == "ahead" and live["detail"] == "leading by 7"
    assert live["score"] == "ORST 21 – CSU 14"
    final = grade_leg({"market": "ml", "team": "CSU"}, game(state="post", period=4, status="Final",
                                                            away=("ORST", [14, 7, 0, 3]), home=("CSU", [7, 7, 0, 3])))
    assert final["state"] == "final" and final["result"] == "lost" and final["now"] == "behind"


def test_spread_cover_and_push():
    g = game(state="post", period=4, status="Final", away=("WASH", [7, 3, 7, 7]), home=("USC", [7, 10, 7, 7]))
    assert grade_leg({"market": "spread", "team": "WASH", "line": 7.5}, g)["result"] == "won"      # lost by 7
    assert grade_leg({"market": "spread", "team": "USC", "line": -7.5}, g)["result"] == "lost"
    push = grade_leg({"market": "spread", "team": "USC", "line": -7}, g)
    assert push["result"] == "push" and push["detail"] == "exactly on the number"


def test_first_half_spread_settles_at_halftime_and_ignores_later_quarters():
    spec = {"market": "spread", "period": "1h", "team": "ORST", "line": -3.5}
    live = grade_leg(spec, game())
    assert live["state"] == "live" and live["result"] is None and live["detail"] == "covering by 3.5"
    half = game(status="Halftime")
    half["status_name"] = "STATUS_HALFTIME"
    assert grade_leg(spec, half)["result"] == "won"
    third = game(period=3, status="2:00 - 3rd", away=("ORST", [14, 7, 0]), home=("CSU", [7, 7, 21]))
    res = grade_leg(spec, third)
    assert res["result"] == "won" and res["score"] == "1H ORST 21 – CSU 14"


def test_totals_settle_early_once_passed():
    under = {"market": "total", "period": "1h", "side": "under", "line": 26.5}
    g = game(period=2, away=("GASO", [7, 7]), home=("CCU", [7, 3]))
    live = grade_leg(under, g)
    assert live["result"] is None and live["detail"] == "24 points, 2.5 to spare" and live["now"] == "ahead"
    g2 = game(period=2, away=("GASO", [7, 14]), home=("CCU", [7, 3]))
    assert grade_leg(under, g2)["result"] == "lost"                                   # already over at 31
    assert grade_leg({**under, "side": "over"}, g2)["result"] == "won"
    final = game(state="post", period=4, status="Final", away=("GASO", [7, 7, 0, 0]), home=("CCU", [7, 3, 0, 0]))
    assert grade_leg({**under, "side": "over"}, final)["result"] == "lost"
    exact = game(period=2, away=("GASO", [10]), home=("CCU", [10]))
    assert grade_leg({"market": "total", "side": "over", "line": 20}, exact)["detail"] == "20 points, right on 20"


def test_pregame_has_no_result():
    g = game(state="pre", period=0, status="10/3 - 7:30 PM EDT", away=("MIA", []), home=("CLEM", []))
    out = grade_leg({"market": "ml", "team": "MIA"}, g)
    assert out["state"] == "pre" and out["result"] is None and out["score"] == "MIA @ CLEM"


def test_derive_status_matches_tracker_rules():
    bet = {"stake": 10, "toReturn": 20.9, "status": "open"}
    assert derive_status(bet, [{"result": "won"}, {"result": "lost"}])["status"] == "lost"
    assert derive_status(bet, [{"result": "won"}, {"result": "won"}]) == {"status": "won", "returned": 20.9, "needsReturn": False}
    assert derive_status(bet, [{"result": "won"}, {"result": "push"}])["needsReturn"] is True
    assert derive_status(bet, [{"result": "won"}, {"result": "pending"}])["status"] == "open"
    assert derive_status({**bet, "status": "cashout"}, [{"result": "lost"}]) == {}


def test_apply_live_patch_and_change_detection():
    bet = {"stake": 6, "toReturn": 29.88, "status": "open", "legs": [
        {"pick": "ORST 1H -3.5", "result": "pending", "spec": {"event": "1", "market": "spread", "period": "1h", "team": "ORST", "line": -3.5}},
        {"pick": "Untracked leg", "result": "pending"}]}
    half = game(status="Halftime")
    half["status_name"] = "STATUS_HALFTIME"
    patch = apply_live(bet, {"1": half}, "2026-10-03T23:40:00Z")
    assert patch["changed"] is True and patch["status"] == "open"
    assert patch["legs"][0]["result"] == "won" and patch["legs"][0]["live"]["updatedAt"] == "2026-10-03T23:40:00Z"
    assert "live" not in patch["legs"][1]
    again = apply_live({**bet, "legs": patch["legs"]}, {"1": half}, "2026-10-03T23:50:00Z")
    assert again["changed"] is False                      # only the timestamp moved
    assert apply_live({"legs": [{"pick": "x"}]}, {}, "t") is None


def test_live_cli_with_stubbed_scoreboard(tmp_path, monkeypatch, capsys):
    from betlab.fetch import espn
    bet = {"eventDate": "2026-10-03", "stake": 10, "toReturn": 20.9, "status": "open",
           "legs": [{"pick": "ORST ML", "result": "pending",
                     "spec": {"league": "ncaaf", "event": "401860899", "market": "ml", "team": "ORST"}}]}
    (tmp_path / "bets").mkdir()
    (tmp_path / "bets" / "b1.json").write_text(json.dumps(bet))
    final = game(state="post", period=4, status="Final", away=("ORST", [14, 7, 7, 7]), home=("CSU", [7, 7, 0, 0]))
    raw = {"events": [{"id": "401860899", "shortName": "ORST @ CSU", "status": {"period": 4, "displayClock": "0:00",
           "type": {"state": "post", "completed": True, "shortDetail": "Final", "name": "STATUS_FINAL"}},
           "competitions": [{"competitors": [
               {"homeAway": side, "score": str(int(final[side]["score"])), "team": {"abbreviation": final[side]["abbr"]},
                "linescores": [{"value": v} for v in final[side]["linescores"]]} for side in ("home", "away")]}]}]}
    calls = []
    monkeypatch.setattr(espn, "fetch_json", lambda url: (calls.append(url), (raw, {}))[1])
    assert main(["live", "--bets", str(tmp_path / "bets"), "--out", str(tmp_path / "patch"), "--now", "2026-10-04T03:00:00Z"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "groups=80" in calls[0] and "dates=20261003" in calls[0]
    assert out["bets"][0]["status"] == "won" and out["bets"][0]["decided"] == 1
    patch = json.loads((tmp_path / "patch" / "b1.json").read_text())
    assert patch["status"] == "won" and patch["returned"] == 20.9 and patch["settledAt"] == "2026-10-04T03:00:00Z"
    assert "changed" not in patch
