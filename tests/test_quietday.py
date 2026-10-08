import json
from datetime import date

import pytest

from betlab.cli import main
from betlab.ledger import Ledger
from betlab.profile import DEFAULTS, validate
from betlab.quietday import pick, picks_today, stake_for
from betlab.report import performance_report, render_markdown

ON = dict(DEFAULTS, bankroll=185.98, quiet_day_pick={**DEFAULTS["quiet_day_pick"], "enabled": True})

# Oct 8, 2026 (Pinnacle no-vig): Guardians 52.1% at FanDuel -112, White Sox 47.9% at DraftKings -102.
GUARDIANS = {"label": "Guardians ML", "price": -112, "p_win": 0.521, "market": "moneyline", "book": "FanDuel"}
WHITE_SOX = {"label": "White Sox ML", "price": -102, "p_win": 0.479, "market": "moneyline", "book": "DraftKings"}


def test_picks_the_cheapest_single_and_sizes_it_small():
    sgp = {"label": "3-leg SGP", "price": 600, "p_win": 0.14, "market": "sgp"}
    out = pick([WHITE_SOX, GUARDIANS, sgp], ON)
    assert out["status"] == "pick" and out["label"] == "Entertainment, not value"
    p = out["pick"]
    assert p["label"] == "Guardians ML" and p["ev_pct"] == pytest.approx(-1.38, abs=0.01)
    assert p["stake"] == 2.0 and p["expected_cost"] == pytest.approx(0.03, abs=0.005)
    assert p["skip_if_worse_than"] == "-116"           # the price where it would cost 3%
    assert p["fair_american"] == "-109"
    assert [r["label"] for r in out["runners_up"]] == ["White Sox ML"]
    assert out["rejected"][0]["label"] == "3-leg SGP"
    assert "costs about 1.4%" in out["message"] and "--tier entertainment" in out["message"]


def test_a_real_edge_is_not_a_quiet_day_pick():
    value = {"label": "Bucs +9.5", "price": +105, "p_win": 0.52, "market": "spread"}
    out = pick([GUARDIANS, value], ON)
    assert out["status"] == "value" and out["best"]["label"] == "Bucs +9.5"


def test_small_positive_edge_below_the_bar_reads_as_break_even():
    hurkacz = {"label": "Hurkacz ML", "price": 172, "p_win": 0.3748, "market": "moneyline"}
    out = pick([hurkacz], ON)
    assert out["status"] == "pick" and out["pick"]["expected_cost"] == 0
    assert "about break-even" in out["message"]


def test_no_pick_when_even_the_cheapest_costs_too_much():
    dear = {"label": "Over 48.5", "price": -118, "p_win": 0.5, "market": "total"}
    out = pick([dear], ON)
    assert out["status"] == "none" and "3% limit" in out["message"]


def test_one_a_day_and_off_by_default():
    assert pick([GUARDIANS], ON, already_today=1)["status"] == "done_today"
    off = pick([GUARDIANS], dict(DEFAULTS, bankroll=185.98))
    assert off["enabled"] is False and "off in this profile" in off["note"] and off["status"] == "pick"


def test_stake_rounding_and_cap():
    assert stake_for(ON) == 2.0
    assert stake_for(dict(ON, bankroll=50.0)) == 1.0           # min stake
    assert stake_for(dict(ON, bankroll=10000.0)) == 100.0


def test_picks_today_uses_the_local_date():
    bets = [{"tier": "entertainment", "placed_at": "2026-10-09T01:30:00Z"},    # 9:30 PM ET on Oct 8
            {"tier": "entertainment", "placed_at": "2026-10-08T03:00:00Z"},    # 11 PM ET on Oct 7
            {"tier": None, "placed_at": "2026-10-08T20:00:00Z"}]
    assert picks_today(bets, today=date(2026, 10, 8)) == 1


def test_profile_guards():
    with pytest.raises(ValueError):
        validate(dict(DEFAULTS, quiet_day_pick={"stake_pct": 0.05}))
    with pytest.raises(ValueError):
        validate(dict(DEFAULTS, quiet_day_pick={"max_cost_pct": 0.10}))


def test_report_keeps_quiet_day_picks_out_of_the_skill_record(tmp_path):
    L = Ledger(str(tmp_path / "bets.jsonl"))
    a = L.place(sport="MLB", event="CLE @ CHW", market="moneyline", selection="CLE", price=-112, stake=2,
                tier="entertainment", placed_at="2026-10-08T23:00:00Z")
    b = L.place(sport="NFL", event="TB @ DAL", market="spread", selection="TB +9.5", line=9.5, price=105, stake=5,
                placed_at="2026-10-08T23:10:00Z")
    L.settle(a["bet_id"], "loss", settled_at="2026-10-09T03:00:00Z")
    L.settle(b["bet_id"], "win", settled_at="2026-10-09T04:00:00Z")
    rep = performance_report(L.bets(), bankroll_start=185.98)
    assert rep["overall"]["bets"] == 1 and rep["overall"]["pnl"] == pytest.approx(5.25)
    assert rep["entertainment"]["bets"] == 1 and rep["entertainment"]["pnl"] == -2
    assert rep["drawdown"]["max_drawdown"] == 2.0                    # the money still counts
    assert "Quiet-day picks" in render_markdown(rep)


def test_cli_quietday(tmp_path, capsys):
    f = tmp_path / "cands.json"
    f.write_text(json.dumps([GUARDIANS, WHITE_SOX]))
    code = main(["quietday", "--json", str(f), "--bankroll", "185.98", "--ledger", str(tmp_path / "none.jsonl")])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["status"] == "pick" and out["pick"]["label"] == "Guardians ML"
    assert out["pick"]["stake"] == 2.0 and out["bankroll"] == 185.98
