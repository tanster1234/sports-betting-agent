import json

import pytest

from betlab import wnba
from betlab.backtest import (
    BacktestConfig,
    _grade_spread,
    _grade_total,
    run_backtest,
    summarize_bets,
)
from betlab.cli import main
from betlab.fetch import FetchError, espn, odds_api
from betlab.profile import (
    DEFAULTS,
    load_profile,
    min_ev_for,
    model_weight_for,
    validate,
)
from betlab.ratings import KalmanRatings


# ---------------- backtest ----------------
def test_grading():
    assert _grade_spread(5, -4.5, "home") == "win"
    assert _grade_spread(4, -4.0, "home") == "push"
    assert _grade_spread(3, -4.5, "away") == "win"
    assert _grade_total(170, 168.5, "over") == "win"
    assert _grade_total(168, 168.0, "under") == "push"


class SpyModel(KalmanRatings):
    """Records the latest game date learned before each prediction."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.max_seen = None
        self.violations = []

    def update(self, game):
        self.max_seen = max(self.max_seen or game["date"], game["date"])
        return super().update(game)

    def predict(self, home, away, game_date, **kw):
        d = str(game_date)[:10]
        if self.max_seen is not None and self.max_seen >= d:
            self.violations.append((d, self.max_seen))
        return super().predict(home, away, game_date, **kw)


def test_backtest_has_no_lookahead(wnba_games, wnba_lines):
    holder = {}

    def factory():
        holder["m"] = SpyModel(wnba.WNBA_PARAMS, aliases=wnba.ALIASES)
        return holder["m"]

    run_backtest(wnba_games, wnba_lines, factory, BacktestConfig(start="2026-06-01", end="2026-06-30", min_ev=0.0))
    assert holder["m"].violations == []


def test_backtest_accounting_is_consistent(wnba_games, wnba_lines):
    fac = lambda: KalmanRatings(wnba.WNBA_PARAMS, aliases=wnba.ALIASES)  # noqa: E731
    cfg = BacktestConfig(markets=("total",), price_at="open", min_ev=0.02, model_weight=0.35, start="2026-05-01")
    r = run_backtest(wnba_games, wnba_lines, fac, cfg)
    s = r.summary
    assert s["final_bankroll"] == pytest.approx(cfg.bankroll + sum(b["pnl"] for b in r.bets), abs=0.05)
    assert s["overall"]["bets"] == len(r.bets)
    assert all(b["stake"] <= b.get("bankroll_after", 1e9) + abs(b["pnl"]) + 1e-6 for b in r.bets)
    # deterministic
    r2 = run_backtest(wnba_games, wnba_lines, fac, cfg)
    assert [b["pnl"] for b in r.bets] == [b["pnl"] for b in r2.bets]


def test_documented_totals_clv_finding_still_holds(wnba_games, wnba_lines):
    """Regression guard for .claude/skills/wnba-betting/references/calibration.md: 2026 totals vs DK openers had positive CLV."""
    fac = lambda: KalmanRatings(wnba.WNBA_PARAMS, aliases=wnba.ALIASES)  # noqa: E731
    cfg = BacktestConfig(markets=("total",), price_at="open", min_ev=0.02, model_weight=0.35, start="2026-05-01")
    o = run_backtest(wnba_games, wnba_lines, fac, cfg).summary["overall"]
    assert o["bets"] >= 40
    assert o["avg_clv_pct"] > 2.0 and o["clv_t"] > 2.0


def test_summarize_empty():
    assert "note" in summarize_bets([], 1000)


# ---------------- ESPN parsers ----------------
def test_parse_real_summary(fixture_json):
    s = espn.parse_summary(fixture_json("espn_summary_2026.json"))
    assert s["home"]["abbr"] == "SEA" and s["away"]["abbr"] == "GS"
    assert s["home"]["score"] == 80 and s["away"]["score"] == 91
    o = s["odds"][0]
    assert o["provider"] == "DraftKings"
    assert o["home_spread"] == 5.5          # ESPN 'spread' is from the HOME team's perspective
    assert o["close"]["spread_home"] == 5.5 and o["open"]["spread_home"] == 4.5
    assert o["close"]["ml_home"] == 195 and o["close"]["ml_away"] == -238
    assert o["open"]["total"] == 154.5 and o["close"]["total"] == 157.5
    assert o["close"]["over_price"] == -105 and o["close"]["under_price"] == -115
    assert any(p["points"] is not None for p in s["players"])


def test_parse_scoreboard_both_schemas(fixture_json):
    games = espn.parse_scoreboard(fixture_json("espn_scoreboard.json"))
    assert len(games) == 2
    g26, g24 = games
    assert g26["home"]["abbr"] == "ATL" and g26["state"] == "pre"
    o = g26["odds"][0]
    assert o["close"]["ml_home"] == -160 and o["open"]["ml_away"] == 126
    assert o["close"]["spread_home"] == -3.5 and o["close"]["spread_price_away"] == -108
    assert o["close"]["total"] == 168.5 and o["open"]["total"] == 166.5
    assert "Semifinals - Game 1" in g26["notes"]
    o24 = g24["odds"][0]
    assert o24["provider"] == "ESPN BET"
    assert o24["close"]["ml_home"] == 105 and o24["close"]["ml_away"] == -125
    assert o24["open"]["ml_home"] == 110
    assert o24["open"]["total"] == 165.5 and o24["close"]["over_price"] == -115
    assert g24["completed"] is True and g24["home"]["score"] == 92


def test_parse_injuries_recovers_ids(fixture_json):
    inj = espn.parse_injuries(fixture_json("espn_injuries.json"))
    assert len(inj) == 2
    assert inj[0]["player"] == "A'ja Wilson" and inj[0]["status"] == "Day-To-Day"
    assert inj[1]["player_id"] == "4433403"


def test_espn_urls():
    assert espn.scoreboard_url("wnba", "2026-10-04").endswith("/basketball/wnba/scoreboard?dates=20261004")
    assert "mens-college-basketball" in espn.summary_url("ncaab", "1")
    with pytest.raises(KeyError):
        espn.injuries_url("cricket")


# ---------------- The Odds API ----------------
def test_odds_api_normalize_best_and_value(fixture_json):
    rows = odds_api.normalize(fixture_json("odds_api_wnba.json"))
    assert len(rows) == 4 * 6
    best = odds_api.best_lines(rows)
    ny_ml = [r for r in best if r["market"] == "h2h" and r["name"] == "New York Liberty"][0]
    assert ny_ml["book"] == "betmgm" and ny_ml["price"] == 155
    fair = odds_api.book_fair_probs(rows)
    assert len(fair) == len(rows)          # every outcome has its pair
    value = odds_api.value_scan(rows, min_ev=0.02)
    assert [(v["book"], v["name"]) for v in value] == [("betmgm", "New York Liberty")]
    assert 3.0 < value[0]["ev_pct"] < 5.5


def test_odds_api_urls(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "abc")
    u = odds_api.odds_url("wnba", ("h2h", "spreads"), ("us", "us_ex"))
    assert "/sports/basketball_wnba/odds?" in u and "markets=h2h%2Cspreads" in u and "regions=us%2Cus_ex" in u
    e = odds_api.event_odds_url("wnba", "evt", ("player_points",))
    assert "/events/evt/odds?" in e
    monkeypatch.delenv("ODDS_API_KEY")
    with pytest.raises(FetchError):
        odds_api.odds_url("wnba")


# ---------------- profile ----------------
def test_profile_defaults_and_guards(tmp_path):
    p = load_profile()
    assert p["kelly_multiplier"] <= 0.5 and p["bankroll"] > 0
    assert min_ev_for(p, "prop") > min_ev_for(p, "spread")
    assert model_weight_for(p, "WNBA", "total") == 0.35
    assert model_weight_for(p, "NBA", "total") == DEFAULTS["model_weight"]["default"]["total"]
    bad = dict(DEFAULTS, kelly_multiplier=1.0)
    with pytest.raises(ValueError):
        validate(bad)
    with pytest.raises(ValueError):
        validate(dict(DEFAULTS, max_bet_pct=0.10))
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"bankroll": 5000, "min_ev": {"prop": 0.05}}))
    q = load_profile(str(f))
    assert q["bankroll"] == 5000 and q["min_ev"]["prop"] == 0.05 and q["min_ev"]["spread"] == 0.02


# ---------------- CLI ----------------
def run_cli(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip().startswith(("{", "[")) else out)


def test_cli_odds_ev_kelly(capsys):
    code, out = run_cli(capsys, "odds", "-110", "-110")
    assert code == 0 and out["hold_pct"] == pytest.approx(4.545, abs=1e-3)
    code, out = run_cli(capsys, "ev", "--prob", "0.56", "--price", "-110", "--other", "-110", "--model-weight", "0.35")
    assert out["ev_pct"] == pytest.approx(6.909, abs=1e-3) and out["blended_ev_pct"] < 0
    code, out = run_cli(capsys, "kelly", "--prob", "0.55", "--price", "-110", "--bankroll", "2000")
    assert out["stake"] == pytest.approx(27.5)


def test_cli_wnba_price_and_series(capsys):
    code, out = run_cli(capsys, "wnba", "price", "--home", "ATL", "--away", "NY", "--date", "2026-10-04", "--playoff",
                        "--spread", "-3.5", "--spread-prices", "-112", "-108", "--total-line", "168.5",
                        "--total-prices", "-110", "-110", "--ml", "-160", "134")
    assert code == 0 and len(out["bets"]) == 6
    assert all("blended_ev_pct" in b for b in out["bets"])
    code, out = run_cli(capsys, "wnba", "series", "--high", "ATL", "--low", "NY", "--round", "semifinals", "--date", "2026-10-04")
    assert 0.5 < out["p_higher_seed"] < 0.9


def test_cli_ledger_and_report(capsys, tmp_path):
    L = str(tmp_path / "l.jsonl")
    code, b = run_cli(capsys, "ledger", "add", "--ledger", L, "--sport", "WNBA", "--event", "NY @ ATL", "--market", "total",
                      "--selection", "Over 168.5", "--line", "168.5", "--price", "-110", "--stake", "20", "--model-prob", "0.54")
    assert code == 0 and b["side"] == "over"
    code, _ = run_cli(capsys, "ledger", "settle", "--ledger", L, "--bet-id", b["bet_id"], "--result", "win")
    code, rep = run_cli(capsys, "report", "--ledger", L)
    assert rep["overall"]["wins"] == 1
    code, md = run_cli(capsys, "report", "--ledger", L, "--format", "md")
    assert "Performance review" in md


def test_cli_errors_are_json(capsys):
    code, out = run_cli(capsys, "ev", "--prob", "0.5", "--price", "+50")
    assert code == 1 and out["error"] == "OddsError"
