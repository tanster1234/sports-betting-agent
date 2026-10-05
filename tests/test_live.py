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
    end_of_2nd = game(status="End of 2nd")              # what ESPN shows first, still in progress
    assert grade_leg(spec, end_of_2nd)["result"] == "won" and grade_leg(spec, end_of_2nd)["state"] == "final"
    assert grade_leg(spec, game(status="0:33 - 2nd"))["result"] is None
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


# ---------------------------------------------------------------------------
# player props (graded from the ESPN game summary)
# ---------------------------------------------------------------------------
from pathlib import Path  # noqa: E402

from betlab.live import grade_player_leg, parse_box, player_name_key  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def nfl_box():
    return parse_box(json.loads((FIX / "espn_nfl_summary_final.json").read_text()))


def prop(player, stat, line, side="over"):
    return {"league": "nfl", "event": "401872965", "market": "player", "player": player, "stat": stat,
            "side": side, "line": line}


def test_player_names_normalise():
    assert player_name_key("Kenneth Walker III") == "kenneth walker"
    assert player_name_key("R.J. Harvey") == player_name_key("RJ Harvey") == "rj harvey"
    assert player_name_key("Amon-Ra St. Brown") == "amon ra st brown"


def test_nfl_final_box_grades_yards_catches_and_touchdowns():
    box = nfl_box()
    assert box["state"] == "post" and box["td_scorers"] == {"jonathan taylor": 2, "treylon burks": 1, "daniel jones": 1}
    td = grade_player_leg(prop("Jonathan Taylor", "anytimeTD", 0.5), box)
    assert td["result"] == "won" and td["score"] == "Jonathan Taylor 2 TD" and td["state"] == "final"
    assert grade_player_leg(prop("Jonathan Taylor", "rushYards", 89.5), box)["result"] == "won"          # 95
    assert grade_player_leg(prop("Jonathan Taylor", "rushYards", 89.5, "under"), box)["result"] == "lost"
    short = grade_player_leg(prop("Jonathan Taylor", "rushYards", 99.5), box)
    assert short["result"] == "lost" and short["detail"] == "finished with 95 rush yds"
    assert grade_player_leg(prop("Tyler Warren", "anytimeTD", 0.5), box)["detail"] == "no touchdown"
    assert grade_player_leg(prop("Daniel Jones", "passYards", 174.5), box)["result"] == "lost"            # 143
    assert grade_player_leg(prop("Laquon Treadwell", "receptions", 4.5), box)["result"] == "won"          # 5
    assert grade_player_leg(prop("Laquon Treadwell", "receptions", 5), box)["result"] == "push"
    assert grade_player_leg(prop("Laquon Treadwell", "anytimeTD", 0.5), box)["result"] == "lost"
    ghost = grade_player_leg(prop("Nobody Here", "recYards", 24.5), box)
    assert ghost["result"] == "lost" and "inactive" in ghost["detail"]


def test_player_leg_before_and_during_a_game():
    pre = grade_player_leg(prop("Bijan Robinson", "rushYards", 59.5), {"state": "pre", "status": "8:15 PM", "players": {},
                                                                     "dnp": set(), "td_scorers": {}})
    assert pre["state"] == "pre" and pre["result"] is None
    js = json.loads((FIX / "espn_wnba_live_summary.json").read_text())
    box = parse_box(js)
    assert box["state"] == "in"
    leg = {"market": "player", "player": "Breanna Stewart", "stat": "points", "side": "over", "line": 15.5}
    live = grade_player_leg(leg, box)
    assert live["state"] == "live" and live["result"] is None and live["now"] == "behind"
    assert live["detail"] == "6 pts, needs 10 more" and live["score"] == "Breanna Stewart 6 pts"
    under = grade_player_leg({**leg, "side": "under"}, box)
    assert under["now"] == "ahead" and under["detail"] == "6 pts, 9.5 to spare" and under["result"] is None
    cleared = grade_player_leg({**leg, "line": 4.5}, box)                     # an over settles once it's cleared
    assert cleared["result"] == "won" and cleared["state"] == "live"
    assert grade_player_leg({**leg, "stat": "threes", "line": 0.5}, box)["detail"] == "0 3PM, needs 1 more"
    js["header"]["competitions"][0]["status"]["type"]["state"] = "post"       # a player who never got in
    dnp = grade_player_leg({**leg, "player": "Anneli Maley", "line": 1.5}, parse_box(js))
    assert dnp["result"] == "void"


def test_settled_ticket_keeps_grading_its_other_legs():
    bet = {"stake": 10, "toReturn": 48.1, "status": "lost", "returned": 0, "settledAt": "2026-10-04T20:13:36Z",
           "legs": [{"pick": "Texans ML", "result": "lost"},
                    {"pick": "Taylor 90+ rush yds", "result": "pending", "spec": prop("Jonathan Taylor", "rushYards", 89.5)},
                    {"pick": "Taylor anytime TD", "result": "pending", "spec": prop("Jonathan Taylor", "anytimeTD", 0.5)}]}
    patch = apply_live(bet, {}, "2026-10-05T22:00:00Z", {"401872965": nfl_box()})
    assert [lg["result"] for lg in patch["legs"]] == ["lost", "won", "won"]
    assert patch["status"] == "lost" and patch["settledAt"] == "2026-10-04T20:13:36Z" and patch["changed"]
    void = {**bet, "status": "open", "legs": [{"pick": "a", "result": "won"}, {"pick": "b", "result": "void"}]}
    assert derive_status(void, void["legs"])["needsReturn"] is True


def test_live_cli_fetches_summaries_only_for_open_player_legs(tmp_path, monkeypatch, capsys):
    from betlab.fetch import espn
    summary = json.loads((FIX / "espn_nfl_summary_final.json").read_text())
    board = {"events": [
        {"id": "401872965", "shortName": "IND VS WSH", "status": {"period": 4, "displayClock": "0:00",
         "type": {"state": "post", "completed": True, "shortDetail": "Final", "name": "STATUS_FINAL"}},
         "competitions": [{"competitors": [
             {"homeAway": "home", "score": "13", "team": {"abbreviation": "WSH"}, "linescores": []},
             {"homeAway": "away", "score": "30", "team": {"abbreviation": "IND"}, "linescores": []}]}]},
        {"id": "401872979", "shortName": "ATL @ NO", "status": {"period": 0, "displayClock": "0:00",
         "type": {"state": "pre", "completed": False, "shortDetail": "10/5 - 8:15 PM EDT", "name": "STATUS_SCHEDULED"}},
         "competitions": [{"competitors": [
             {"homeAway": "home", "score": "0", "team": {"abbreviation": "NO"}},
             {"homeAway": "away", "score": "0", "team": {"abbreviation": "ATL"}}]}]}]}
    calls = []

    def fake(url):
        calls.append(url)
        return (summary if "summary" in url else board), {}
    monkeypatch.setattr(espn, "fetch_json", fake)
    bets = tmp_path / "bets"
    bets.mkdir()
    (bets / "old.json").write_text(json.dumps({"eventDate": "2026-10-04", "stake": 2.5, "toReturn": 42.67, "status": "lost",
        "legs": [{"pick": "Taylor TD", "result": "pending", "spec": prop("Jonathan Taylor", "anytimeTD", 0.5)},
                 {"pick": "Burks TD", "result": "won", "spec": prop("Treylon Burks", "anytimeTD", 0.5)},
                 {"pick": "Allen TD", "result": "lost"}]}))
    (bets / "tonight.json").write_text(json.dumps({"eventDate": "2026-10-05", "stake": 5, "toReturn": 37.65, "status": "open",
        "legs": [{"pick": "Bijan 60+", "result": "pending",
                  "spec": {**prop("Bijan Robinson", "rushYards", 59.5), "event": "401872979"}}]}))
    assert main(["live", "--bets", str(bets), "--now", "2026-10-05T22:00:00Z"]) == 0
    out = {b["doc_id"]: b for b in json.loads(capsys.readouterr().out)["bets"]}
    assert out["old"]["status"] == "lost" and out["old"]["decided"] == 3 and "[won]" in out["old"]["legs"][0]
    assert out["tonight"]["status"] == "open" and out["tonight"]["decided"] == 0
    assert sum("summary" in c for c in calls) == 1                     # the game that hasn't started isn't fetched
