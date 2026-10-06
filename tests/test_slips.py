import json
from pathlib import Path

import pytest

from betlab import postmortem, slips
from betlab.cli import main

FIX = Path(__file__).parent / "fixtures"
SUMMARY = json.loads((FIX / "espn_nfl_atl_no_final.json").read_text())
ROSTERS = {"1": json.loads((FIX / "espn_nfl_roster_atl.json").read_text()),
           "18": json.loads((FIX / "espn_nfl_roster_no.json").read_text())}


def fake_fetch(url):
    if "summary?event=401872979" in url:
        return SUMMARY
    for tid, ros in ROSTERS.items():
        if url.endswith(f"/teams/{tid}/roster"):
            return ros
    raise RuntimeError(f"unexpected url {url}")


def leg(pick, p, **spec):
    return {"pick": pick, "fairProb": p, "spec": {"event": "401872979", "league": "nfl", **spec}}


def player(name, stat, line, p, result=None, side="over"):
    d = leg(f"{name} {line + 0.5:g}+ {stat}", p, market="player", player=name, stat=stat, line=line, side=side)
    if result:
        d["result"] = result
    return d


def monday(results=False):
    """The two real tickets on Falcons @ Saints, Oct 5 2026."""
    r = (lambda x: x) if results else (lambda x: None)
    dk = {"id": "dk", "book": "DraftKings", "tier": "Boosted SGP", "stake": 5, "odds": 653, "eventDate": "2026-10-05",
          "status": "lost" if results else "open",
          "legs": [player("Bijan Robinson", "rushYards", 59.5, 0.824, r("won")),
                   player("Devaughn Vele", "recYards", 24.5, 0.804, r("won")),
                   player("Alvin Kamara", "rushYards", 49.5, 0.307, r("lost"))]}
    fd = {"id": "fd", "book": "FanDuel", "tier": "Boosted SGP", "stake": 10, "odds": 159, "eventDate": "2026-10-05",
          "status": "lost" if results else "open",
          "legs": [player("Michael Penix Jr.", "passYards", 174.5, 0.814, r("won")),
                   player("Alvin Kamara", "rushYards", 19.5, 0.847, r("won")),
                   player("Bijan Robinson", "receptions", 2.5, 0.83, r("lost")),
                   player("Drake London", "receptions", 3.5, 0.875, r("won"))]}
    return dk, fd


def test_measured_football_links_golden_numbers():
    m = slips.football_model()
    lo = m["loadings"]
    assert m["n_player_games"] > 80000 and m["seasons"] == "2021-2025"
    assert 0.25 < lo["rush_yds/RB"]["margin"] < 0.31                 # backs run more when their team is ahead
    assert lo["receptions/RB"]["margin"] < 0                          # ...and catch more when behind
    assert 0.28 < lo["pass_yds/QB"]["total"] < 0.34 and lo["td/RB"]["margin"] > 0.25
    pairs = m["pairs"]
    assert pairs["opponent"]["rush_yds/RB|rush_yds/RB"]["corr"] < -0.12
    assert pairs["teammate"]["pass_yds/QB|rec_yds/WR"]["corr"] > 0.33
    assert pairs["same_player"]["rec_yds/WR|receptions/WR"]["corr"] > 0.75
    assert abs(pairs["same_player"]["receptions/RB|rush_yds/RB"]["corr"]) < 0.05   # RB rushing and catches: unrelated
    assert pairs["teammate"]["td/RB|td/RB"]["beyond_script"] < -0.2                # two backs share the TDs


def test_legs_and_probabilities():
    t = {"id": "x", "legs": [{"pick": "A", "fairProb": 0.6, "spec": {"market": "ml", "side": "home", "event": "1",
                                                                       "league": "nfl"}},
                             {"pick": "B TD", "price": 150, "spec": {"market": "player", "stat": "anytimeTD", "player": "B",
                                                                     "event": "1", "league": "nfl"}},
                             {"pick": "C under", "price": -110, "spec": {"market": "total", "side": "under", "line": 44.5}}]}
    a, b, c = slips.legs_of(t)
    assert (a.p, a.p_source, a.team_side) == (0.6, "fair", "home")
    assert b.p_source == "price" and b.p == pytest.approx(0.4 * 0.90)        # TD props carry a bigger margin
    assert c.sign == -1 and c.p == pytest.approx(110 / 210 * 0.955)


def test_pair_correlations():
    def L(**kw):
        base = dict(ticket="t", index=0, pick="", p=0.5, p_source="fair", price=None, result=None, event="1",
                    league="nfl", market="player", sign=1, home="H", away="A")
        base.update(kw)
        return slips.Leg(**base)
    rb_home = L(player="Home Back", stat="rushYards", position="RB", team_side="home", line=60)
    rb_away = L(player="Away Back", stat="rushYards", position="RB", team_side="away", line=50)
    qb = L(player="Home QB", stat="passYards", position="QB", team_side="home", line=240)
    wr = L(player="Home WR", stat="recYards", position="WR", team_side="home", line=60)
    assert slips.pair_corr(rb_home, rb_away)[0] == pytest.approx(-0.151, abs=0.01)
    assert slips.pair_corr(qb, wr)[0] == pytest.approx(0.373, abs=0.01)
    under = L(player="Home WR", stat="recYards", position="WR", team_side="home", line=60, sign=-1)
    assert slips.pair_corr(qb, under)[0] == pytest.approx(-slips.pair_corr(qb, wr)[0])
    alt = L(player="Home Back", stat="rushYards", position="RB", team_side="home", line=20)
    assert slips.pair_corr(rb_home, alt)[0] == 1.0                           # same stat, different line
    ml_h, ml_a = L(market="ml", team_side="home"), L(market="ml", team_side="away")
    assert slips.pair_corr(ml_h, ml_a)[0] == pytest.approx(-0.95)
    assert slips.pair_corr(ml_h, L(market="total", line=44.5))[0] == 0.0
    assert slips.pair_corr(rb_home, ml_h)[0] == pytest.approx(0.282, abs=0.01)
    assert slips.pair_corr(rb_home, L(event="2", player="X", stat="rushYards"))[0] == 0.0


def test_resolver_fills_teams_and_positions():
    legs = slips.legs_of(monday()[0])
    slips.espn_resolver(fetch=fake_fetch)(legs)
    got = {x.player: (x.team, x.team_side, x.position) for x in legs}
    assert got["Bijan Robinson"] == ("ATL", "away", "RB")
    assert got["Devaughn Vele"] == ("NO", "home", "WR")                      # a Saints receiver, not a Falcon
    assert got["Alvin Kamara"] == ("NO", "home", "RB") and legs[0].home == "NO"


def test_check_flags_mondays_problems():
    dk, fd = monday()
    res = slips.check([dk, fd], resolver=slips.espn_resolver(fetch=fake_fetch), sims=20000)
    t = {x["ticket"]: x for x in res["tickets"]}
    assert t["dk"]["one_story"]["verdict"] == "conflicting"
    clash = [p for p in t["dk"]["one_story"]["pairs"] if p["verdict"] == "pull against each other"]
    assert len(clash) == 1 and "Kamara" in clash[0]["legs"][1] and "Bijan" in clash[0]["legs"][0]
    assert t["fd"]["one_story"]["verdict"] == "one story"                    # Penix passing + London catches
    assert t["dk"]["weakest_leg"].startswith("Alvin Kamara 50+")
    kinds = sorted(e["type"] for e in res["exposure"])
    assert kinds == ["same game", "same player", "same player"]
    kam = next(e for e in res["exposure"] if e["type"] == "same player" and "Kamara" in e["note"])
    assert "same stat at different lines" in kam["note"] and "the DraftKings Boosted SGP" in kam["note"]
    assert any("pull against each other" in n for n in res["notes"]) and res["unresolved_team"] == []
    j = res["joint"]
    assert sum(j["tickets_cashing"].values()) == pytest.approx(1.0, abs=1e-3)
    assert j["profit"]["max_loss"] == -15.0


def test_shared_leg_moves_the_joint_odds():
    one = {"pick": "X TD", "fairProb": 0.4, "spec": {"event": "9", "league": "nfl", "market": "player",
                                                    "player": "X", "stat": "anytimeTD", "side": "over", "line": 0.5}}
    a = {"id": "a", "stake": 1, "odds": 150, "legs": [one]}
    b = {"id": "b", "stake": 1, "odds": 150, "legs": [one]}
    res = slips.check([a, b], sims=20000)
    assert res["exposure"][0]["type"] == "same leg"
    assert res["joint"]["p_none_cash"] == pytest.approx(0.6, abs=0.015)       # not 0.36: one miss sinks both
    assert res["joint"]["p_none_cash_if_independent"] == pytest.approx(0.36, abs=1e-3)


def test_opposite_sides_and_cli(capsys):
    t = [{"id": "a", "stake": 2, "odds": -110, "legs": [{"pick": "Home ML", "fairProb": 0.5, "spec": {
              "event": "5", "league": "nfl", "market": "ml", "side": "home"}}]},
         {"id": "b", "stake": 2, "odds": -110, "legs": [{"pick": "Away ML", "fairProb": 0.5, "spec": {
              "event": "5", "league": "nfl", "market": "ml", "side": "away"}}]}]
    assert main(["slips", "check", "--tickets", json.dumps(t), "--offline", "--sims", "4000"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert any(e["type"] == "opposite sides" for e in out["exposure"]) and out["proposed"] == ["a", "b"]
    assert out["joint"]["p_all_cash"] < 0.05
    assert main(["slips", "check", "--offline"]) == 1
    assert "nothing to check" in capsys.readouterr().out
    assert main(["parlay", "--probs", "0.5", "0.6"]) == 0                     # chance without prices
    assert json.loads(capsys.readouterr().out)["independent"]["fair_american"] == "+233"


def test_box_score_splits_completions_and_attempts():
    from betlab.live import parse_box
    penix = parse_box(SUMMARY)["players"]["michael penix"]
    assert penix[("passing", "completions")] == 15 and penix[("passing", "passingAttempts")] == 20


def test_postmortem_of_monday_night():
    dk, fd = monday(results=True)
    res = postmortem.review([dk, fd], fetch=fake_fetch)
    rec = {r["pick"]: r for r in res["records"]}
    kam = rec["Alvin Kamara 50+ rushYards"]
    assert kam["result"] == "lost" and kam["chance"] == "long shot"
    for tag in ("expected loss", "game script", "only miss", "same player twice", "conflict"):
        assert tag in kam["tags"], tag
    assert "ATL beat the spread by 22.5" in kam["why"] and "7 carries" in kam["why"]
    assert kam["facts"]["beat_spread_home"] == -22.5 and kam["facts"]["carries"] == 7
    bij = rec["Bijan Robinson 3+ receptions"]
    assert {"upset", "volume", "only miss", "same player twice"} <= set(bij["tags"]) and "Only 2 targets" in bij["why"]
    assert rec["Bijan Robinson 60+ rushYards"]["facts"].get("helped_by_script")
    s = res["summary"]
    assert s["legs"] == 7 and s["won"] == 5 and s["calibration_verdict"].startswith("too few")
    assert [x["tag"] for x in s["lessons"]][:2] == ["same player twice", "conflict"]
    assert s["tickets"] == 2 and s["tickets_cashed"] == 0


def test_postmortem_shared_loss_and_near_miss():
    leg_ = {"pick": "Olave TD", "fairProb": 0.45, "result": "lost",
            "spec": {"event": "401872979", "league": "nfl", "market": "player", "player": "Chris Olave",
                     "stat": "anytimeTD", "side": "over", "line": 0.5}}
    rec_ = player("Chris Olave", "receptions", 8.5, 0.55, "lost")             # 8 catches: one short
    a = {"id": "a", "book": "DK", "tier": "Reach", "eventDate": "2026-10-05", "status": "lost", "legs": [leg_, rec_]}
    b = {"id": "b", "book": "DK", "tier": "Big", "eventDate": "2026-10-05", "status": "lost", "legs": [leg_]}
    res = postmortem.review([a, b], fetch=fake_fetch)
    recs = [r for r in res["records"] if r["pick"] == "Olave TD"]
    assert len(recs) == 2 and all("shared" in r["tags"] for r in recs)
    assert "TDs went elsewhere" in recs[0]["tags"] and "Devaughn Vele" in recs[0]["why"]
    olave = next(r for r in res["records"] if r["pick"].startswith("Chris Olave"))
    assert "near miss" in olave["tags"] and olave["facts"]["missed_by"] == 0.5
