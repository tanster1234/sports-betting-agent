import json

import pytest

from betlab.ledger import Ledger, LedgerError, infer_side, pnl_for
from betlab.odds import OddsError
from betlab.report import (
    bets_needed,
    bootstrap_roi_ci,
    brier_scores,
    calibration,
    drawdown,
    performance_report,
    render_markdown,
    t_test,
    tilt_check,
)


@pytest.fixture
def ledger(tmp_path):
    return Ledger(str(tmp_path / "bets.jsonl"))


def _place(L, **kw):
    base = dict(sport="WNBA", event="NY @ ATL", market="spread", selection="ATL -3.5", line=-3.5, price=-110, stake=20)
    base.update(kw)
    return L.place(**base)


@pytest.mark.parametrize("result,expected", [("win", 20 * 0.909091), ("loss", -20), ("push", 0), ("void", 0),
                                             ("half_win", 10 * 0.909091), ("half_loss", -10)])
def test_pnl_for(result, expected):
    assert pnl_for(result, 20, 1.909091) == pytest.approx(expected, abs=1e-4)


def test_place_settle_flow(ledger):
    b = _place(ledger, model_prob=0.55)
    assert b["price_decimal"] == pytest.approx(1.909091, abs=1e-6)
    assert b["ev_at_placement"] == pytest.approx(0.55 * 0.909091 - 0.45, abs=1e-5)
    s = ledger.settle(b["bet_id"], "win")
    assert s["pnl"] == pytest.approx(18.18)
    [state] = ledger.bets()
    assert state["status"] == "win" and state["pnl"] == pytest.approx(18.18)


def test_double_settlement_requires_correction(ledger):
    b = _place(ledger)
    ledger.settle(b["bet_id"], "loss")
    with pytest.raises(LedgerError):
        ledger.settle(b["bet_id"], "win")
    ledger.settle(b["bet_id"], "push", correction_reason="stat correction: game graded push")
    [state] = ledger.bets()
    assert state["status"] == "push" and state["pnl"] == 0 and state["corrections"]


def test_validation(ledger):
    with pytest.raises(LedgerError):
        _place(ledger, stake=0)
    with pytest.raises(LedgerError):
        _place(ledger, market="banana")
    with pytest.raises(OddsError):
        _place(ledger, price="+50")
    with pytest.raises(LedgerError):
        _place(ledger, model_prob=1.2)
    _place(ledger, bet_id="fixed1")
    with pytest.raises(LedgerError):
        _place(ledger, bet_id="fixed1")
    with pytest.raises(LedgerError):
        ledger.settle("nope", "win")


def test_hash_chain_detects_edits_and_deletions(ledger):
    a = _place(ledger)
    _place(ledger, selection="NY +3.5", line=3.5)
    ledger.settle(a["bet_id"], "win")
    assert ledger.verify()["ok"]
    lines = ledger.path.read_text().splitlines()
    # deletion
    ledger.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert not ledger.verify()["ok"]
    # edit
    ev = json.loads(lines[1])
    ev["stake"] = 999
    ledger.path.write_text("\n".join([lines[0], json.dumps(ev), lines[2]]) + "\n")
    assert not ledger.verify()["ok"]


def test_close_same_line_clv(ledger):
    b = _place(ledger, price=-105)
    c = ledger.close(b["bet_id"], -125, close_line=-3.5, close_other_price=105)
    assert c["clv_ev"] > 0 and c["clv_prob"] > 0
    assert c["clv_price_only"] == pytest.approx((1 + 100 / 105) / (1 + 100 / 125) - 1, abs=1e-6)


def test_close_moved_spread_and_total_are_signed(ledger):
    sp = _place(ledger, line=-4.5, selection="ATL -4.5")
    c = ledger.close(sp["bet_id"], -110, close_line=-6.5, close_other_price=-110)
    assert c["clv_points"] == 2.0 and c["clv_ev"] > 0
    ov = _place(ledger, market="total", selection="Over 168.5", line=168.5)
    c2 = ledger.close(ov["bet_id"], -110, close_line=166.5, close_other_price=-110)
    assert c2["clv_points"] == -2.0 and c2["clv_ev"] < 0


def test_infer_side():
    assert infer_side("total", "Over 168.5") == "over"
    assert infer_side("prop", "A'ja Wilson under 24.5 points") == "under"
    assert infer_side("spread", "ATL -3.5") is None


def test_void(ledger):
    b = _place(ledger)
    ledger.void(b["bet_id"], "game postponed")
    [st] = ledger.bets()
    assert st["status"] == "void" and st["pnl"] == 0


# ---------------- reports ----------------
def _bets(n_win, n_loss, stake=10.0, dec=1.909091, clv=None, prob=None, day="2026-07-0"):
    rows = []
    for i in range(n_win + n_loss):
        win = i < n_win
        rows.append({"status": "win" if win else "loss", "stake": stake, "price_decimal": dec,
                     "pnl": stake * (dec - 1) if win else -stake, "sport": "WNBA", "market": "total",
                     "book": "DK", "tier": None, "clv_ev": clv, "model_prob": prob,
                     "placed_at": f"2026-07-{1 + i % 28:02d}T12:00:00", "settled_at": f"2026-07-{1 + i % 28:02d}T23:00:00",
                     "event_date": f"2026-07-{1 + i % 28:02d}"})
    return rows


def test_report_core_numbers():
    rows = _bets(60, 40)
    rep = performance_report(rows, bankroll_start=1000)
    o = rep["overall"]
    assert (o["wins"], o["losses"]) == (60, 40)
    assert o["roi_pct"] == pytest.approx(100 * (60 * 9.09091 - 400) / 1000, abs=0.01)
    lo, hi = o["roi_ci95_pct"]
    assert lo < o["roi_pct"] < hi
    assert "verdict" in rep and rep["by_market"]["total"]["bets"] == 100
    md = render_markdown(rep)
    assert "Performance review" in md and "Verdict" in md


def test_verdict_small_sample():
    assert "Too few" in performance_report(_bets(10, 5))["verdict"]


def test_verdict_uses_clv():
    rows = _bets(50, 50)
    for i, b in enumerate(rows):
        b["clv_ev"] = 0.03 + (0.01 if i % 2 else -0.01)
    assert "Positive, statistically significant CLV" in performance_report(rows)["verdict"]
    for i, b in enumerate(rows):
        b["clv_ev"] = -0.03 + (0.01 if i % 2 else -0.01)
    assert "Negative, significant CLV" in performance_report(rows)["verdict"]


def test_calibration_and_brier_skill():
    rows = _bets(55, 45, prob=0.55)
    for b in rows:
        b["close_fair_prob"] = 0.5
    cal = calibration(rows)
    assert cal and cal[0]["n"] == 100 and cal[0]["actual"] == pytest.approx(0.55)
    br = brier_scores(rows)
    assert br["brier_model"] == pytest.approx(0.2475, abs=1e-4)
    assert br["brier_market"] == pytest.approx(0.25)
    assert br["brier_skill_vs_market"] > 0


def test_drawdown_and_streak():
    rows = _bets(0, 5) + _bets(3, 0)
    for i, b in enumerate(rows):
        b["settled_at"] = f"2026-08-{i + 1:02d}"
    dd = drawdown(rows, bankroll_start=100)
    assert dd["max_drawdown"] == pytest.approx(50.0)
    assert dd["longest_losing_streak"] == 5
    assert dd["max_drawdown_pct"] == pytest.approx(50.0)


def test_tilt_detector_flags_chasing():
    rows = []
    for d in range(1, 21):
        lost_prev = d % 2 == 0
        rows.append({"status": "loss" if d % 2 else "win", "stake": 50.0 if lost_prev else 10.0, "pnl": -10.0 if d % 2 else 9.0,
                     "price_decimal": 1.9, "placed_at": f"2026-06-{d:02d}T10:00:00"})
    t = tilt_check(rows)
    assert t["flag"] is True and t["ratio"] > 2


def test_bets_needed():
    assert bets_needed(0.03) == pytest.approx((1.96 * 0.95 / 0.03) ** 2, rel=0.01)
    assert bets_needed(-0.01) > 10 ** 8


def test_t_test_and_bootstrap():
    t = t_test([0.1, -0.1, 0.2, 0.0])
    assert t["n"] == 4 and t["mean"] == pytest.approx(0.05)
    lo, hi = bootstrap_roi_ci([{"stake": 1, "pnl": x} for x in (1, -1, 1, -1, 1)])
    assert lo <= 0.2 <= hi
