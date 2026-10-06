"""WNBA playoff tracker: what the system would have bet, and how it went.

For every 2026 playoff game in the bundled data, the model is fitted only on games played
before that date, priced at DraftKings' opening line with the profile's market weights and
EV thresholds, and graded against the result and the closing line. Upcoming games are priced
at the current DraftKings line from ESPN (needs network access to site.api.espn.com).

usage: python3 scripts/playoff_tracker.py [--out tracker.json] [--days-ahead 3] [--season 2026]
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from betlab import wnba  # noqa: E402
from betlab.backtest import (  # noqa: E402
    BacktestConfig,
    _clv_vs_close,
    _grade_spread,
    _grade_total,
    _price_fields,
    candidate_bets,
)
from betlab.kelly import kelly_fraction  # noqa: E402
from betlab.profile import load_profile, min_ev_for, model_weight_for  # noqa: E402

MARKETS = ("spread", "total", "moneyline")


def _num(v):
    return None if v in (None, "") else float(v)


def _label(c, home, away):
    if c["market"] == "total":
        return f"{c['side'].title()} {c['line']:g}"
    team = home if c["side"] == "home" else away
    if c["market"] == "spread":
        return f"{team} {c['line']:+g}"
    return f"{team} ML"


def calls_for(pred, prices, prof, home, away):
    """Best side per market, flagged when blended EV clears the profile threshold."""
    weights = {m: model_weight_for(prof, "WNBA", m) for m in MARKETS}
    cfg = BacktestConfig(markets=MARKETS, model_weights=weights)
    cands = candidate_bets(pred, prices, cfg)
    out = []
    for m in MARKETS:
        side = [c for c in cands if c["market"] == m]
        if not side:
            continue
        best = max(side, key=lambda c: c["ev"])
        thr = min_ev_for(prof, m)
        stake = 0.0
        if best["ev"] >= thr:
            f = kelly_fraction(best["p_win"], best["decimal"], best["p_push"]) * prof.get("kelly_multiplier", 0.25)
            stake = min(f, prof.get("max_bet_pct", 0.03))
        out.append({"market": m, "selection": _label(best, home, away), "side": best["side"], "line": best["line"],
                    "home_line": best.get("home_line"), "price": best["price_american"],
                    "p_win": round(best["p_win"], 4), "ev_pct": round(100 * best["ev"], 2),
                    "threshold_pct": round(100 * thr, 1), "bet": best["ev"] >= thr and stake > 0,
                    "stake_pct": round(100 * stake, 2), "_cand": best})
    return out


def settled(games, lines, prof, season):
    rows = []
    po = sorted((l for l in lines if l.get("season_type") == "playoff" and l["date"].startswith(str(season))),
                key=lambda l: (l["date"], l["game_id"]))
    by_id = {str(g["game_id"]): g for g in games}
    for l in po:
        g = by_id[str(l["game_id"])]
        model = wnba.fit_model(games, until=l["date"])   # nothing from this date or later
        pred = wnba.predict(model, g["home"], g["away"], l["date"], playoff=True)
        prices = {k: _num(v) for k, v in _price_fields(l, "open").items()}
        margin, total = int(g["home_pts"]) - int(g["away_pts"]), int(g["home_pts"]) + int(g["away_pts"])
        calls = calls_for(pred, prices, prof, g["home"], g["away"])
        for c in calls:
            best = c.pop("_cand")
            if c["market"] == "spread":
                c["result"] = _grade_spread(margin, best["home_line"], best["side"])
            elif c["market"] == "total":
                c["result"] = _grade_total(total, best["line"], best["side"])
            else:
                c["result"] = "win" if (margin > 0) == (best["side"] == "home") else "loss"
            if c["bet"]:
                clv = _clv_vs_close(best, l, BacktestConfig(price_at="open"))
                c["clv_pct"] = round(100 * clv["clv_ev"], 2) if clv.get("clv_ev") is not None else None
                c["clv_points"] = clv.get("clv_points")
        rows.append({
            "date": l["date"], "game_id": l["game_id"], "home": g["home"], "away": g["away"],
            "score": {"home": int(g["home_pts"]), "away": int(g["away_pts"])},
            "dk_open": {"spread_home": _num(l["spread_home_open"]), "total": _num(l["total_open"]),
                        "ml_home": _num(l["ml_home_open"]), "ml_away": _num(l["ml_away_open"])},
            "dk_close": {"spread_home": _num(l["spread_home_close"]), "total": _num(l["total_close"]),
                         "ml_home": _num(l["ml_home_close"]), "ml_away": _num(l["ml_away_close"])},
            "model": {"home_margin": round(pred.mu, 1), "total": round(pred.total_mu, 1),
                      "p_home": round(pred.p_home, 3)},
            "calls": calls})
    return rows


def series_state(games, home, away, since):
    wins = {home: 0, away: 0}
    for g in games:
        if g.get("season_type") == "playoff" and g["date"] >= since and {g["home"], g["away"]} == {home, away}:
            wins[g["home"] if int(g["home_pts"]) > int(g["away_pts"]) else g["away"]] += 1
    return wins


def upcoming(games, prof, days_ahead):
    from betlab.fetch import FetchError, espn
    model = wnba.fit_model(games)
    out, today = [], date.today()
    for k in range(days_ahead + 1):
        d = today + timedelta(days=k)
        try:
            events = espn.get_scoreboard("wnba", d.strftime("%Y%m%d"))
        except FetchError as e:
            return out, f"live odds unavailable: {e}"
        for ev in events:
            if ev.get("completed") or not ev.get("odds"):
                continue
            o = next((x for x in ev["odds"] if x.get("provider") == "DraftKings"), ev["odds"][0])
            cur = o.get("close") or {}
            if cur.get("spread_home") is None and cur.get("total") is None:
                continue
            home, away = wnba.canonical(ev["home"]["abbr"]), wnba.canonical(ev["away"]["abbr"])
            pred = wnba.predict(model, home, away, d.isoformat(), playoff=True)
            calls = calls_for(pred, cur, prof, home, away)
            for c in calls:
                c.pop("_cand")
            first_meeting = min((g["date"] for g in games if g.get("season_type") == "playoff"
                                 and g["date"] >= "2026-10-03" and {g["home"], g["away"]} == {home, away}),
                                default=d.isoformat())
            out.append({"date": d.isoformat(), "tipoff_utc": ev.get("date"), "home": home, "away": away,
                        "round": (ev.get("notes") or [""])[0], "series": series_state(games, home, away, first_meeting),
                        "dk_open": o.get("open"), "dk_now": cur,
                        "model": {"home_margin": round(pred.mu, 1), "total": round(pred.total_mu, 1),
                                  "p_home": round(pred.p_home, 3)},
                        "calls": calls})
    return out, None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out")
    ap.add_argument("--days-ahead", type=int, default=3)
    ap.add_argument("--season", type=int, default=2026)
    a = ap.parse_args()
    prof = load_profile()
    games, lines = wnba.load_games(), wnba.load_lines()
    done = settled(games, lines, prof, a.season)
    bets = [c for r in done for c in r["calls"] if c["bet"]]
    units = sum((c["stake_pct"] * ((abs(c["price"]) / 100 if c["price"] > 0 else 100 / abs(c["price"])))
                 if c["result"] == "win" else -c["stake_pct"] if c["result"] == "loss" else 0.0) for c in bets)
    clvs = [c["clv_pct"] for c in bets if c.get("clv_pct") is not None]
    nxt, note = upcoming(games, prof, a.days_ahead)
    out = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "data_through": max(g["date"] for g in games),
           "method": "the model is refitted on games before each date (no hindsight), priced at DraftKings' "
                     "opening line with the profile's market weights and minimum edges, and sized at quarter "
                     "Kelly capped at 3%",
           "summary": {"games": len(done), "bets": len(bets),
                       "record": f"{sum(c['result'] == 'win' for c in bets)}-{sum(c['result'] == 'loss' for c in bets)}"
                                 + (f"-{sum(c['result'] == 'push' for c in bets)}" if any(c["result"] == "push" for c in bets) else ""),
                       "profit_pct_bankroll": round(units, 2),
                       "avg_clv_pct": round(sum(clvs) / len(clvs), 2) if clvs else None},
           "settled": done, "upcoming": nxt, "upcoming_note": note}
    text = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(text if not a.out else f"wrote {a.out}: {out['summary']}")


if __name__ == "__main__":
    main()
