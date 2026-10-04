import csv
import json
import random

import pytest

from betlab import nfl
from betlab.cli import main

NFLVERSE_COLS = ["game_id", "season", "game_type", "week", "gameday", "away_team", "away_score", "home_team",
                 "home_score", "location", "result", "total", "away_rest", "home_rest", "away_moneyline",
                 "home_moneyline", "spread_line", "total_line", "div_game", "roof", "temp", "wind",
                 "away_qb_name", "home_qb_name"]


def _write_games(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=NFLVERSE_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in NFLVERSE_COLS})


def _synthetic_games(n=1500, seed=7, first=2015, seasons=4):
    """Margins piled on 3 and 7 (like the NFL) around half-point spreads."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        f = rng.choice([1, 2.5, 3, 3.5, 6.5, 7, 7.5, 10])
        home_fav = rng.random() < 0.6
        u = rng.random()
        if u < 0.16:
            fm = 3
        elif u < 0.25:
            fm = 7
        else:
            fm = int(round(rng.gauss(f, 13)))
        margin = fm if home_fav else -fm
        if margin == 0:
            margin = 1
        hs, as_ = (24 + margin, 24) if margin > 0 else (24, 24 - margin)
        line = rng.choice([40.5, 44, 44.5, 47.5])
        rows.append({"game_id": f"g{i}", "season": first + i % seasons, "game_type": "REG", "week": 1 + i % 17,
                     "gameday": "2016-10-02", "away_team": "AAA", "home_team": "HHH", "away_score": as_,
                     "home_score": hs, "spread_line": f if home_fav else -f, "total_line": line,
                     "home_moneyline": -150 if home_fav else 130, "away_moneyline": 130 if home_fav else -150,
                     "location": "Home"})
    return rows


def test_load_games_flips_nflverse_spread_sign(tmp_path):
    p = tmp_path / "games.csv"
    _write_games(p, [
        {"game_id": "a", "season": 2025, "week": 1, "home_team": "BAL", "away_team": "TEN", "home_score": 30,
         "away_score": 10, "spread_line": 11.5, "total_line": 41.5, "home_moneyline": -700, "away_moneyline": 500},
        {"game_id": "b", "season": 2025, "week": 1, "home_team": "WAS", "away_team": "IND", "home_score": 17,
         "away_score": 20, "spread_line": -4.5, "total_line": 46.5, "location": "Neutral"},
        {"game_id": "c", "season": 2026, "week": 4, "home_team": "CAR", "away_team": "DET", "spread_line": -3.5},
    ])
    games = nfl.load_games(str(p))
    assert len(games) == 2                                   # unplayed game skipped
    bal, was = games
    assert bal["home_spread"] == -11.5 and bal["margin"] == 20 and bal["total"] == 40
    assert was["home_spread"] == 4.5 and was["neutral"] is True
    assert nfl.favourite_view(bal["home_spread"], bal["margin"]) == (11.5, 20)
    assert nfl.favourite_view(was["home_spread"], was["margin"]) == (4.5, 3)   # IND (away) won by 3
    assert len(nfl.load_games(str(p), completed_only=False)) == 3


def test_fit_weights_finds_key_numbers():
    games = _synthetic_games()
    rows = [{"season": int(g["season"]), "home_spread": -float(g["spread_line"]),
             "margin": g["home_score"] - g["away_score"], "total_line": g["total_line"],
             "total": g["home_score"] + g["away_score"]} for g in games]
    cal = nfl.fit_calibration(rows, 2015)
    sup = list(range(cal["margin"]["support"][0], cal["margin"]["support"][1] + 1))
    w = dict(zip(sup, cal["margin"]["weights"]))
    assert w[3] > 2.0 and w[7] > 1.5 and w[3] > w[5]
    assert all(v == 1.0 for k, v in w.items() if abs(k) > 50)  # rare margins stay plain normal


def test_market_line_is_the_fifty_fifty_point():
    cal = nfl.load_calibration()
    for spread in (-1, -2.5, -3, -3.5, -6.5, -7, -10, 4.5):
        mm = nfl.margin_model(spread, cal)
        c, p, f = mm.spread_probs(spread)
        assert c / (c + f) == pytest.approx(0.5, abs=1e-3)
    c, p, f = nfl.margin_model(-3, cal, p_home_cover=0.56).spread_probs(-3)
    assert c / (c + f) == pytest.approx(0.56, abs=1e-3)
    o, u, pu = nfl.total_dist(44.5, cal).over_under_push(44.5)
    assert o == pytest.approx(0.5, abs=1e-3)


def test_committed_calibration_golden_numbers():
    """2015-2025 NFL closing lines: guard the shipped calibration (update with the doc if refit)."""
    cal = nfl.load_calibration()
    assert cal["seasons"] == [2015, 2025] and cal["n_games"] == 3028
    assert 12.5 <= cal["margin"]["sigma"] <= 14.0 and 12.5 <= cal["total"]["sigma"] <= 14.5
    fav3 = nfl.margin_model(-3, cal)
    hw, tie, aw = nfl.moneyline_probs(fav3)
    assert 0.59 <= hw / (hw + aw) <= 0.62              # 2015-25: -3 favourites won 59.8%
    assert 0.08 <= fav3.spread_probs(-3)[1] <= 0.11    # pushed 10.2%
    assert 0.05 <= nfl.margin_model(-7, cal).spread_probs(-7)[1] <= 0.07   # 6.4%
    assert tie < 0.01                                  # ties ~0.3%
    # half a point off 3 is worth far more than half a point off 4
    off3 = nfl.margin_model(-3, cal).spread_probs(-2.5)[0] - nfl.margin_model(-3, cal).spread_probs(-3)[0]
    off4 = nfl.margin_model(-3, cal).spread_probs(-3.5)[0] - nfl.margin_model(-3, cal).spread_probs(-4)[0]
    assert off3 > 2 * off4


def test_away_favourite_is_the_mirror_image():
    home_fav = nfl.margin_model(-3).dist.pmf
    away_fav = nfl.margin_model(3).dist.pmf
    for k, p in home_fav.items():
        assert away_fav.get(-k, 0.0) == pytest.approx(p)


def test_price_rows_and_offers_are_consistent():
    out = nfl.price(-3, 44.5, alt_spreads=[-2.5, -3.5, -7], alt_totals=[41.5], teaser_points=6,
                    home="NYG", away="ARI")
    for row in out["spread"] + out["moneyline"] + out["alt_spreads"] + out["totals"]:
        assert row["p_win"] + row["p_push"] + row["p_loss"] == pytest.approx(1.0, abs=2e-4)
    alt = {r["selection"]: r for r in out["alt_spreads"]}
    assert alt["NYG -2.5"]["p_win"] > alt["NYG -3.5"]["p_win"] > alt["NYG -7"]["p_win"]
    legs = out["teaser_legs"]["legs"]
    assert legs[0]["selection"].startswith("NYG -3 -> +3") and legs[1]["selection"].startswith("ARI +3 -> +9")
    # an offer at the model's fair price has ~zero EV; a better price has positive EV
    fair = nfl.evaluate_offer(-3, "spread", "home", -2.5, -110)
    fair_price = float(fair["fair_american"])
    assert nfl.evaluate_offer(-3, "spread", "home", -2.5, fair_price)["ev_pct"] == pytest.approx(0, abs=0.6)
    assert nfl.evaluate_offer(-3, "spread", "away", 8.5, -200)["ev_pct"] > \
        nfl.evaluate_offer(-3, "spread", "away", 8.5, -300)["ev_pct"]
    with pytest.raises(ValueError):
        nfl.evaluate_offer(-3, "total", "over", 41.5, -120)          # needs the main total


def test_validate_runs_out_of_sample(tmp_path):
    p = tmp_path / "games.csv"
    _write_games(p, _synthetic_games(n=1200))
    games = nfl.load_games(str(p))
    v = nfl.validate(games, fit_last=2017, test_first=2018)
    assert v["fit"] == [2015, 2017] and v["test"] == [2018, 2018] and v["n_test"] == 300
    assert v["margin_loglik"]["key_weighted"] > v["margin_loglik"]["plain_normal"]
    assert {"moneyline_logloss", "push_rate", "total_loglik"} <= set(v)


def test_nfl_cli_price_and_offers(capsys):
    assert main(["nfl", "price", "--spread", "-3", "--total", "44.5", "--home", "NYG", "--away", "ARI",
                 "--alt", "-2.5", "--teaser", "6", "--offer", "spread:home:-2.5:-130", "total:over:41.5:-150"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["spread"][0]["selection"] == "NYG -3" and len(out["offers"]) == 2
    assert main(["nfl", "price", "--spread", "-3", "--offer", "bad"]) == 1


# ---------------- ratings ----------------
def _season_rows():
    """Two teams, AAA's usual QB 'Ace' hurt in game 5 ('Backup' starts)."""
    rows = []
    for i in range(6):
        d = f"2025-09-{7 + 7 * i:02d}" if 7 + 7 * i <= 30 else f"2025-10-{7 + 7 * i - 30:02d}"
        qb = "Ace" if i != 4 else "Backup"
        rows.append({"game_id": f"g{i}", "date": d, "season": 2025, "game_type": "REG", "home": "AAA", "away": "BBB",
                     "home_score": 24 if i != 4 else 10, "away_score": 17, "home_spread": -3.0, "total_line": 44.5,
                     "home_qb": qb, "away_qb": "Bee", "neutral": False})
    rows.append({**rows[0], "game_id": "next", "date": "2025-10-19", "home_score": None, "away_score": None,
                 "home_qb": "Backup"})
    return rows


def test_rating_rows_flag_a_backup_qb_and_handicap_him():
    rows = nfl.rating_rows(_season_rows(), qb_adj=3.0, lookback=4)
    by_id = {r["game_id"]: r for r in rows}
    assert by_id["g3"]["home_qb"]["change"] is False and by_id["g3"]["extra_home_adj"] == 0.0
    assert by_id["g4"]["home_qb"] == {"usual": "Ace", "starter": "Backup", "change": True}
    assert by_id["g4"]["extra_home_adj"] == -3.0                  # home side handicapped
    assert by_id["next"]["extra_home_adj"] == -3.0                 # projected backup for an unplayed game
    assert by_id["g0"]["home_qb"]["usual"] is None                 # not enough history yet


def test_backup_loss_is_not_fully_charged_to_the_team():
    games = _season_rows()[:-1]
    with_adj, _ = nfl.fit_ratings(games, qb_adj=3.0)
    without, _ = nfl.fit_ratings(games, qb_adj=0.0)
    r_with = {t["team"]: t["rating"] for t in with_adj.ratings_table()}
    r_without = {t["team"]: t["rating"] for t in without.ratings_table()}
    assert r_with["AAA"] > r_without["AAA"]                        # the backup's loss counted less


def test_predict_and_backtest_outputs():
    games = _season_rows()
    model, rows = nfl.fit_ratings(games, until="2025-10-19")
    pred = nfl.predict_game(model, [r for r in rows if r["game_id"] == "next"][0])
    assert pred["qb_adjustment"] == -3.0 and "Backup" in pred["notes"][0]
    assert pred["model_minus_market"] == pytest.approx(pred["model_home_spread"] + 3.0, abs=0.06)
    bt = nfl.ratings_backtest([g for g in games if g["home_score"] is not None], test_seasons=[2025])
    assert bt["n"] == 6 and 0.0 <= bt["best_blend_weight_on_model"] <= 1.0
    assert set(bt["ats_when_disagreeing"]) == {">=1", ">=2", ">=3"}


def test_nfl_cli_predict_and_ratings(tmp_path, capsys):
    p = tmp_path / "games.csv"
    rows = []
    for g in _season_rows():
        rows.append({"game_id": g["game_id"], "season": g["season"], "game_type": "REG", "week": 1,
                     "gameday": g["date"], "home_team": g["home"], "away_team": g["away"],
                     "home_score": "" if g["home_score"] is None else g["home_score"],
                     "away_score": "" if g["away_score"] is None else g["away_score"],
                     "spread_line": 3.0, "total_line": 44.5, "home_qb_name": g["home_qb"],
                     "away_qb_name": g["away_qb"], "location": "Home"})
    _write_games(p, rows)
    assert main(["nfl", "predict", "--games", str(p), "--date", "2025-10-19"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["games"][0]["home"] == "AAA" and out["games"][0]["qb_adjustment"] == -3.0
    assert main(["nfl", "ratings", "--games", str(p), "--date", "2025-10-19"]) == 0
    assert {r["team"] for r in json.loads(capsys.readouterr().out)["ratings"]} == {"AAA", "BBB"}
    assert main(["nfl", "predict", "--games", str(p), "--date", "2025-12-25"]) == 1
