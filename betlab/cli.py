"""Command-line interface: ``python -m betlab <command> ...``

Every command prints JSON (``--format md`` where a report makes sense) so
Claude can read results directly.  Run ``python -m betlab -h`` or
``python -m betlab <command> -h`` for options.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import clv as clv_mod
from . import odds as O
from .kelly import (
    kelly_fraction,
    overbet_multiple_where_growth_turns_negative,
    risk_of_ruin_mc,
    stake_plan,
)
from .markets import (
    MarginModel,
    alt_spread_ladder,
    key_number_report,
    period_lines,
    price_game,
    spread_from_win_prob,
    total_probs,
)
from .profile import load_profile, min_ev_for, model_weight_for, stake_limits, unit_size


def _out(obj, fmt: str = "json") -> None:
    if fmt == "md" and isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, indent=2, default=_default))


def _default(o):
    if hasattr(o, "as_dict"):
        return o.as_dict()
    if isinstance(o, float):
        return round(o, 6)
    return str(o)


def _r(x, n=4):
    return None if x is None else round(float(x), n)


# ---------------------------------------------------------------------------
def cmd_odds(a):
    decs = [O.parse_price(p) for p in a.prices]
    rows = [{"input": p, "decimal": _r(d), "american": O.format_american(O.decimal_to_american(d)),
             "implied_prob": _r(1 / d)} for p, d in zip(a.prices, decs)]
    out = {"prices": rows}
    if len(decs) >= 2:
        out["overround_pct"] = _r(100 * O.overround(decs), 3)
        out["hold_pct"] = _r(100 * O.hold(decs), 3)
        out["fair_probs"] = {m: [_r(p) for p in v] for m, v in O.devig_all_methods(decs).items()}
        out["fair_american"] = [O.format_american(O.prob_to_american(p)) for p in O.devig(decs, a.method)]
        out["method"] = a.method
    return out


def cmd_ev(a):
    d = O.parse_price(a.price)
    p, push = a.prob, a.push
    out = {"price_decimal": _r(d), "price_american": O.format_american(O.decimal_to_american(d)),
           "prob_win": p, "prob_push": push, "breakeven_prob": _r(1 / d),
           "ev_pct": _r(100 * O.ev(p, d, push), 3), "prob_edge_pts": _r(100 * (p - 1 / d), 3),
           "full_kelly_pct": _r(100 * kelly_fraction(p, d, push), 3)}
    fair = 1 + (1 - p - push) / p if p > 0 else None
    out["fair_decimal"] = _r(fair)
    out["fair_american"] = O.format_american(O.decimal_to_american(fair)) if fair and fair > 1 else None
    if a.other is not None:
        fp = O.devig([d, O.parse_price(a.other)], a.method)[0]
        out["market_fair_prob"] = _r(fp)
        if a.model_weight is not None:
            q = p / (1 - push) if push < 1 else p
            pb = O.blend_probs(q, fp, a.model_weight) * (1 - push)
            out["blended_prob"] = _r(pb)
            out["blended_ev_pct"] = _r(100 * O.ev(pb, d, push), 3)
    if a.min_ev is not None:
        # Threshold on the probability actually used for the decision: the blended one when a
        # model weight is given (holding the market's fair probability fixed, i.e. shopping
        # other books), else the raw one.
        base = out.get("blended_prob", p)
        wd = O.min_price_for_ev(base, a.min_ev, push)
        out["worst_acceptable_basis"] = "blended" if "blended_prob" in out else "prob"
        out["worst_acceptable_decimal"] = _r(wd)
        out["worst_acceptable_american"] = O.format_american(O.decimal_to_american(wd))
    return out


def cmd_kelly(a):
    d = O.parse_price(a.price)
    f = kelly_fraction(a.prob, d, a.push)
    out = {"full_kelly_pct": _r(100 * f, 3), "fraction": a.fraction, "stake_pct": _r(100 * f * a.fraction, 3),
           "overbet_multiple_where_growth_turns_negative": _r(overbet_multiple_where_growth_turns_negative(a.prob, d), 3)}
    if a.bankroll:
        out["stake"] = round(a.bankroll * f * a.fraction, 2)
    if a.simulate:
        out["simulation_1000_bets"] = risk_of_ruin_mc(a.prob, d, f * a.fraction)
    return out


def cmd_stake(a):
    prof = load_profile(a.profile)
    if a.bankroll:
        prof["bankroll"] = a.bankroll
    raw = sys.stdin.read() if a.json == "-" else open(a.json).read()
    cands = json.loads(raw)
    for c in cands:
        if "price" in c and "decimal" not in c:
            c["decimal"] = O.parse_price(c["price"])
        if str(c.get("market", "")).lower() == "prop" and "kelly_multiplier" not in c:
            c["kelly_multiplier"] = prof["prop_kelly_multiplier"]
    plan = stake_plan(cands, stake_limits(prof), a.exposed and json.loads(a.exposed))
    return {"bankroll": prof["bankroll"], "unit": unit_size(prof), "profile": prof["_source"],
            "plan": [d.as_dict() for d in plan],
            "total_stake": round(sum(d.stake for d in plan), 2)}


def cmd_price(a):
    if a.kind == "game":
        mm = MarginModel.normal(a.mu, a.sigma, a.sport)
        bets = price_game(mm, a.total_mu, a.total_sigma, a.home, a.away, a.spread,
                          tuple(a.spread_prices) if a.spread_prices else None, a.total_line,
                          tuple(a.total_prices) if a.total_prices else None, tuple(a.ml) if a.ml else None, a.method)
        return {"p_home_win": _r(mm.p_home_win()), "fair_home_spread": mm.fair_home_spread(),
                "bets": [b.as_dict() for b in bets]}
    if a.kind == "convert":
        mm = MarginModel.from_spread(a.spread, a.sigma, a.sport)
        p = mm.p_home_win()
        return {"home_spread": a.spread, "sigma": a.sigma, "p_home_win": _r(p),
                "fair_ml_home": O.format_american(O.prob_to_american(p)), "fair_ml_away": O.format_american(O.prob_to_american(1 - p))}
    if a.kind == "spread-from-prob":
        return {"p_home": a.prob, "sigma": a.sigma, "home_spread": _r(spread_from_win_prob(a.prob, a.sigma), 2)}
    if a.kind == "period":
        return period_lines(a.spread, a.total_line, a.sport, a.period)
    if a.kind == "alt":
        mm = MarginModel.normal(a.mu, a.sigma, a.sport)
        return alt_spread_ladder(mm, a.home, a.lines)
    if a.kind == "keys":
        return key_number_report(MarginModel.normal(a.mu, a.sigma, a.sport))
    if a.kind in ("mlb", "nhl"):
        from .lowscoring import mlb_game, nhl_game
        if a.kind == "mlb":
            res = mlb_game(a.home_rate, a.away_rate, a.var_ratio or 2.0, total_line=a.total_line)
        else:
            res = nhl_game(a.home_rate, a.away_rate, a.var_ratio or 1.0, empty_net_shift=a.empty_net,
                           total_line=a.total_line)
        out = {k: _r(v) if isinstance(v, float) else v for k, v in res.items()}
        if a.ml:
            dh, da = (O.american_to_decimal(x) for x in a.ml)
            out["ev_home_ml_pct"] = _r(100 * O.ev(res["p_home_win"], dh), 3)
            out["ev_away_ml_pct"] = _r(100 * O.ev(res["p_away_win"], da), 3)
            out["market_fair_ml"] = [_r(x) for x in O.devig([dh, da], a.method)]
        if a.total_prices and a.total_line is not None:
            do, du = (O.american_to_decimal(x) for x in a.total_prices)
            out["ev_over_pct"] = _r(100 * O.ev(res["p_over"], do, res["p_push"]), 3)
            out["ev_under_pct"] = _r(100 * O.ev(res["p_under"], du, res["p_push"]), 3)
        return out
    if a.kind == "total":
        o, u, p = total_probs(a.total_mu, a.total_sigma, a.total_line)
        out = {"p_over": _r(o), "p_under": _r(u), "p_push": _r(p)}
        if a.total_prices:
            do, du = (O.american_to_decimal(x) for x in a.total_prices)
            out.update({"ev_over_pct": _r(100 * O.ev(o, do, p), 3), "ev_under_pct": _r(100 * O.ev(u, du, p), 3),
                        "market_fair": [_r(x) for x in O.devig([do, du], a.method)]})
        return out
    raise SystemExit(f"unknown price kind {a.kind}")


def cmd_prop(a):
    from .props import (
        PropModel,
        double_double_prob,
        project_from_rate,
        prop_from_market,
    )
    if a.kind == "implied":
        return prop_from_market(a.line, a.over, a.under, a.stat)
    if a.kind == "dd":
        return {"p_double_double": _r(double_double_prob(a.points, a.rebounds, a.assists))}
    if a.rate is not None:
        m = project_from_rate(a.stat, a.rate, a.minutes, a.minutes_sd, a.pace, a.matchup, a.usage)
        o, u, p = m.probs(a.line) if a.line is not None else (None, None, None)
        out = {"stat": m.stat, "mean": _r(m.mean, 3), "fair_line": m.fair_line()}
        if a.line is not None:
            out.update({"line": a.line, "p_over": _r(o), "p_under": _r(u), "p_push": _r(p)})
            if a.over is not None:
                out["ev_over_pct"] = _r(100 * O.ev(o, O.american_to_decimal(a.over), p), 3)
            if a.under is not None:
                out["ev_under_pct"] = _r(100 * O.ev(u, O.american_to_decimal(a.under), p), 3)
        return out
    pm = PropModel(a.stat, a.mean)
    if a.line is None:
        return {"stat": pm.stat, "mean": a.mean, "sd": _r(pm.var ** 0.5, 3), "fair_line": pm.fair_line(),
                "ladder": pm.ladder([pm.fair_line() + k for k in (-3, -2, -1, 0, 1, 2, 3)])}
    return pm.evaluate(a.line, a.over, a.under)


def cmd_parlay(a):
    from .parlay import correlated_parlay_prob, independent_parlay, parlay_hold, sgp_ev
    decs = [O.parse_price(p) for p in a.prices] if a.prices else None
    out = {}
    if decs:
        out["independent"] = independent_parlay(a.probs, decs)
    if a.corr:
        corr = json.loads(a.corr)
        if a.offered:
            out["correlated"] = sgp_ev(a.probs, corr, a.offered, n=a.sims)
        else:
            out["correlated"] = correlated_parlay_prob(a.probs, corr, n=a.sims)
    if a.leg_hold:
        out["parlay_hold_pct"] = _r(100 * parlay_hold([a.leg_hold] * len(a.probs)), 3)
    return out


def cmd_series(a):
    from .series import series_from_ratings, series_probs
    if a.rating_diff is not None:
        return series_from_ratings(a.rating_diff, a.hca, a.sigma, a.format, a.wins_high, a.wins_low, a.sport)
    return series_probs(a.p_home, a.p_away, a.format, a.wins_high, a.wins_low)


def cmd_clv(a):
    if a.line is not None and a.close_line is not None and a.line != a.close_line:
        return clv_mod.clv_spread_points(a.line, O.decimal_to_american(O.parse_price(a.bet)), a.close_line,
                                         O.decimal_to_american(O.parse_price(a.close)),
                                         O.decimal_to_american(O.parse_price(a.close_other)), a.sigma, a.sport)
    return clv_mod.clv_from_prices(O.decimal_to_american(O.parse_price(a.bet)), O.decimal_to_american(O.parse_price(a.close)),
                                   O.decimal_to_american(O.parse_price(a.close_other)))


def _ledger(a):
    from .ledger import Ledger
    prof = load_profile(getattr(a, "profile", None))
    return Ledger(a.ledger or prof["ledger_path"]), prof


def cmd_ledger(a):
    L, prof = _ledger(a)
    if a.action == "add":
        units = a.units if a.units is not None else round(a.stake / unit_size(prof), 2)
        return L.place(sport=a.sport, event=a.event, market=a.market, selection=a.selection, price=a.price,
                       stake=a.stake, book=a.book, line=a.line, model_prob=a.model_prob, model_push_prob=a.model_push_prob,
                       market_prob=a.market_prob, event_date=a.event_date, tier=a.tier, units=units,
                       tags=a.tags, notes=a.notes)
    if a.action == "close":
        return L.close(a.bet_id, a.close_price, a.close_line, a.close_other)
    if a.action == "settle":
        return L.settle(a.bet_id, a.result, a.correction)
    if a.action == "void":
        return L.void(a.bet_id, a.reason)
    if a.action == "note":
        return L.note(a.bet_id, a.text)
    if a.action == "verify":
        return L.verify()
    return L.bets(a.status)


def cmd_report(a):
    from .report import performance_report, render_markdown
    L, prof = _ledger(a)
    rep = performance_report(L.bets(), bankroll_start=a.bankroll or prof["bankroll"])
    dd = rep["drawdown"].get("current_drawdown_pct")
    if dd is not None and dd >= 100 * prof["stop_loss_drawdown_pct"]:
        rep["stop_loss"] = f"Drawdown {dd}% >= stop-loss {100 * prof['stop_loss_drawdown_pct']}%: pause 48h and review."
    return render_markdown(rep) if a.format == "md" else rep


def cmd_wnba(a):
    from . import wnba
    model = wnba.fit_model(until=a.until)
    if a.action == "ratings":
        return {"as_of": a.until or "all bundled data", "league_total": _r(model.league_total(), 2),
                "ratings": model.ratings_table(a.season)}
    if a.action == "calibrate":
        return wnba.season_summary(wnba.load_games())
    if a.action == "series":
        from .series import series_probs
        fmt = wnba.PLAYOFF_FORMATS[a.round]
        ph = wnba.predict(model, a.high, a.low, a.date, playoff=True).p_home
        pa = 1 - wnba.predict(model, a.low, a.high, a.date, playoff=True).p_home
        out = series_probs(ph, pa, fmt, a.wins_high, a.wins_low)
        out.update({"higher_seed": a.high, "lower_seed": a.low, "p_game_at_high": _r(ph), "p_game_at_low": _r(pa)})
        return out
    pred = wnba.predict(model, a.home, a.away, a.date, playoff=a.playoff, neutral=a.neutral,
                        extra_home_adj=a.adj, extra_total_adj=a.total_adj)
    out = {"prediction": pred.as_dict()}
    if a.action == "price":
        prof = load_profile(a.profile)
        mm = MarginModel.normal(pred.mu, pred.sd, "WNBA")
        priced = price_game(mm, pred.total_mu, pred.total_sd, wnba.canonical(a.home), wnba.canonical(a.away),
                            a.spread, tuple(a.spread_prices) if a.spread_prices else None, a.total_line,
                            tuple(a.total_prices) if a.total_prices else None, tuple(a.ml) if a.ml else None,
                            prof["devig_method"])
        rows = []
        for b in priced:
            row = b.as_dict()
            w = a.model_weight if a.model_weight is not None else model_weight_for(prof, "WNBA", b.market)
            if b.market_fair_prob is not None:
                q = b.p_win / (1 - b.p_push) if b.p_push < 1 else b.p_win
                pb = O.blend_probs(q, b.market_fair_prob, w) * (1 - b.p_push)
                row["model_weight"] = w
                row["blended_p_win"] = _r(pb)
                row["blended_ev_pct"] = _r(100 * O.ev(pb, b.price_decimal, b.p_push), 3)
                thr = min_ev_for(prof, b.market)
                row["min_ev_pct"] = 100 * thr
                row["qualifies"] = row["blended_ev_pct"] >= 100 * thr
            rows.append(row)
        out["bets"] = rows
    return out


def cmd_backtest(a):
    from . import wnba
    from .backtest import BacktestConfig, run_backtest, sweep
    from .ratings import KalmanRatings
    games, lines = wnba.load_games(), wnba.load_lines()
    fac = lambda: KalmanRatings(wnba.WNBA_PARAMS, aliases=wnba.ALIASES)  # noqa: E731
    mw = json.loads(a.model_weights) if a.model_weights else None
    cfg = BacktestConfig(markets=tuple(a.markets), price_at=a.price_at, min_ev=a.min_ev, start=a.start, end=a.end,
                         model_weight=a.model_weight, model_weights=mw, kelly_multiplier=a.kelly,
                         include_playoffs=not a.no_playoffs, min_disagreement=a.min_disagreement)
    if a.sweep:
        field, vals = a.sweep.split("=")
        conv = (lambda v: None if v == "none" else float(v))
        return {"sweep": sweep(games, lines, fac, cfg, field, [conv(v) for v in vals.split(",")]),
                "warning": "The best row of a sweep is optimistically biased. Judge configs by CLV and re-test forward."}
    res = run_backtest(games, lines, fac, cfg)
    if a.bets_out:
        with open(a.bets_out, "w") as f:
            json.dump(res.bets, f, indent=1)
    return {"config": res.config, "summary": res.summary}


def cmd_fetch(a):
    if a.source.startswith("espn"):
        from .fetch import espn
        if a.source == "espn-scoreboard":
            return espn.get_scoreboard(a.league, a.date)
        if a.source == "espn-summary":
            return espn.get_summary(a.league, a.event)
        return espn.get_injuries(a.league)
    from .fetch import odds_api
    if a.source == "odds":
        if a.event:
            res = odds_api.get_event_odds(a.league, a.event, a.markets or odds_api.WNBA_PROP_MARKETS[:4], a.regions)
        else:
            res = odds_api.get_odds(a.league, a.markets or odds_api.FEATURED, a.regions)
        if a.best:
            res["best"] = odds_api.best_lines(res["rows"])
        return res
    if a.source == "value":
        res = odds_api.get_odds(a.league, a.markets or odds_api.FEATURED, a.regions)
        return {"quota": res["quota"], "value": odds_api.value_scan(res["rows"], a.min_ev)}
    raise SystemExit(f"unknown source {a.source}")


def cmd_live(a):
    """Grade tracker bets from live ESPN scores; optionally write one patch file per bet."""
    import datetime as _dt
    import os

    from . import live
    from .fetch import espn

    bets = {}
    if os.path.isdir(a.bets):
        for fn in sorted(os.listdir(a.bets)):
            if fn.endswith(".json"):
                with open(os.path.join(a.bets, fn)) as f:
                    bets[fn[:-5]] = json.load(f)
    else:
        with open(a.bets) as f:
            raw = json.load(f)
        bets = raw if isinstance(raw, dict) else {b["id"]: b for b in raw}
    boards = sorted({(lg["spec"].get("league", "ncaaf"), lg["spec"].get("date") or b.get("eventDate"))
                     for b in bets.values() for lg in b.get("legs") or [] if lg.get("spec")})
    games, errors = {}, []
    for league, date in boards:
        url = espn.scoreboard_url(league, date) + ("&groups=80&limit=300" if league == "ncaaf" else "")
        try:
            js, _ = espn.fetch_json(url)
        except Exception as exc:  # keep grading the boards that did load
            errors.append(f"{league} {date}: {exc}")
            continue
        for g in espn.parse_scoreboard(js):
            games[str(g["event_id"])] = g
    # player-prop legs are graded from each game's summary (box score + scoring plays); fetch only
    # games that still have an undecided player leg and have started
    boxes = {}
    want = sorted({(lg["spec"].get("league", "ncaaf"), str(lg["spec"]["event"]))
                   for b in bets.values() for lg in b.get("legs") or []
                   if (lg.get("spec") or {}).get("market") == "player" and (lg.get("result") or "pending") == "pending"})
    for league, ev in want:
        g = games.get(ev)
        if g is not None and g.get("state") == "pre":
            boxes[ev] = {"state": "pre", "status": g.get("status") or "", "players": {}, "dnp": set(), "td_scorers": {}}
            continue
        try:
            js, _ = espn.fetch_json(espn.summary_url(league, ev))
        except Exception as exc:  # keep grading everything else
            errors.append(f"{league} summary {ev}: {exc}")
            continue
        boxes[ev] = live.parse_box(js)
    now = a.now or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"fetched_at": now, "games": len(games), "errors": errors, "bets": []}
    for doc_id, bet in bets.items():
        patch = live.apply_live(bet, games, now, boxes)
        if patch is None:
            continue
        changed = patch.pop("changed")
        legs = [f"{lg.get('pick')}: {(lg.get('live') or {}).get('state', '?')}"
                f"{' · ' + lg['live']['detail'] if (lg.get('live') or {}).get('detail') else ''}"
                f" [{lg.get('result') or 'pending'}]" for lg in patch["legs"]]
        out["bets"].append({"doc_id": doc_id, "changed": changed, "status": patch.get("status", bet.get("status")),
                            "decided": sum(1 for lg in patch["legs"] if (lg.get("result") or "pending") != "pending"),
                            "legs": legs})
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            with open(os.path.join(a.out, f"{doc_id}.json"), "w") as f:
                json.dump(patch, f, indent=1)
    return out


def cmd_nfl(a):
    """NFL pricing off a market line: key-number margins, alt lines, teasers, offers."""
    from . import nfl
    if a.action in ("ratings", "predict", "backtest"):
        games = nfl.load_games(a.games, completed_only=False)
        qb = nfl.NFL_QB_ADJ if a.qb_adj is None else a.qb_adj
        if a.action == "backtest":
            first, last = a.test_seasons
            played = [g for g in games if g["home_score"] is not None]
            return nfl.ratings_backtest(played, range(first, last + 1), qb_adj=qb)
        import datetime as _dt
        day = a.date or _dt.date.today().isoformat()
        model, rows = nfl.fit_ratings(games, until=day, qb_adj=qb)
        if a.action == "ratings":
            return {"as_of": day, "ratings": model.ratings_table(a.season)}
        team = a.home if a.home not in (None, "HOME") else None
        todays = [r for r in rows if r["date"] == day and (team is None or team in (r["home"], r["away"]))]
        if not todays:
            raise ValueError(f"no NFL games on {day} in the schedule file (use --date YYYY-MM-DD)")
        return {"as_of": day, "note": "model lines lose to closing lines in backtests; use for news and early numbers",
                "games": [nfl.predict_game(model, r) for r in todays]}
    if a.action in ("validate", "fit"):
        games = nfl.load_games(a.games)
        if a.action == "fit":
            cal = nfl.fit_calibration(games, a.first, a.fit_last)
            return {**{k: v for k, v in cal.items() if k not in ("margin", "total")},
                    "margin_sigma": cal["margin"]["sigma"], "total_sigma": cal["total"]["sigma"]}
        return nfl.validate(games, a.fit_last, a.test_first, a.test_last, a.first)
    if a.spread is None:
        raise ValueError("nfl price needs --spread (home spread, e.g. -3 when home is favoured)")
    out = nfl.price(a.spread, a.total, a.alt, a.alt_totals, a.teaser, a.home, a.away)
    offers = []
    for o in a.offer:
        try:
            market, side, line, price = o.split(":")
        except ValueError:
            raise ValueError(f"bad --offer {o!r}; use market:side:line:price, e.g. spread:home:-2.5:-130") from None
        offers.append(nfl.evaluate_offer(a.spread, market, side, float(line), float(price), a.total))
    if offers:
        out["offers"] = offers
    return out


def cmd_liveread(a):
    """In-game read for WNBA/NBA: play-by-play facts, a fair live price, and live offers checked."""
    from . import liveread as lr
    if a.action == "validate":
        from . import wnba
        from .ratings import KalmanRatings
        rows = lr.halftime_rows(wnba.load_games(), wnba.load_lines(),
                                lambda: KalmanRatings(wnba.WNBA_PARAMS, aliases=wnba.ALIASES))
        return lr.validate_halftime([r for r in rows if r["season"] >= a.since])
    if a.summary:
        with open(a.summary) as f:
            js = json.load(f)
    else:
        if not a.event:
            raise ValueError("liveread needs --event ESPN_EVENT_ID (or --summary FILE)")
        from .fetch import espn
        js, _ = espn.fetch_json(espn.summary_url(a.league, a.event))
    game = lr.parse_game(js, a.league.upper())
    offers = []
    for o in a.offer:
        parts = o.split(":")
        if len(parts) not in (4, 5):
            raise ValueError(f"bad --offer {o!r}; use market:side:line:price[:book], e.g. ml:home:0:-120:dk")
        market, side, line, price = parts[:4]
        offers.append({"market": market, "side": side, "line": None if market == "ml" else float(line),
                       "price": float(price), "book": parts[4] if len(parts) == 5 else None})
    sharp = {}
    for s in a.sharp:
        parts = s.split(":")
        try:
            if parts[0] == "ml" and len(parts) == 3:
                sharp["ml"] = {"first": float(parts[1]), "second": float(parts[2])}
            elif parts[0] in ("spread", "total") and len(parts) == 4:
                sharp[parts[0]] = {"line": float(parts[1]), "first": float(parts[2]), "second": float(parts[3])}
            else:
                raise ValueError
        except ValueError:
            raise ValueError(f"bad --sharp {s!r}; use ml:HOME:AWAY, spread:HOME_LINE:HOME:AWAY or "
                             "total:LINE:OVER:UNDER") from None
    return lr.live_read(game, a.pre_spread, a.pre_total, offers, sharp or None, a.min_ev)


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="betlab", description="Deterministic betting math. All output is JSON.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("odds", help="convert prices; with 2+ prices: hold and fair probabilities (all devig methods)")
    s.add_argument("prices", nargs="+")
    s.add_argument("--method", default="multiplicative", choices=O.DEVIG_METHODS)
    s.set_defaults(fn=cmd_odds)

    s = sub.add_parser("ev", help="EV / edge / Kelly for one price given your probability")
    s.add_argument("--prob", type=float, required=True, help="your P(win)")
    s.add_argument("--price", required=True)
    s.add_argument("--push", type=float, default=0.0)
    s.add_argument("--other", help="price of the other side (enables market fair prob)")
    s.add_argument("--model-weight", type=float, help="blend your prob with the market (needs --other)")
    s.add_argument("--min-ev", type=float, help="report the worst price that still clears this EV")
    s.add_argument("--method", default="multiplicative", choices=O.DEVIG_METHODS)
    s.set_defaults(fn=cmd_ev)

    s = sub.add_parser("kelly", help="Kelly fraction, stake and optional simulation")
    s.add_argument("--prob", type=float, required=True)
    s.add_argument("--price", required=True)
    s.add_argument("--push", type=float, default=0.0)
    s.add_argument("--fraction", type=float, default=0.25)
    s.add_argument("--bankroll", type=float)
    s.add_argument("--simulate", action="store_true")
    s.set_defaults(fn=cmd_kelly)

    s = sub.add_parser("stake", help="staking plan with caps for a JSON list of candidates")
    s.add_argument("--json", required=True, help="file or - for stdin: [{label,p_win,price|decimal,p_push?,game,sport,market}]")
    s.add_argument("--profile")
    s.add_argument("--bankroll", type=float)
    s.add_argument("--exposed", help='JSON of existing exposure, e.g. {"__day__":0.03}')
    s.set_defaults(fn=cmd_stake)

    s = sub.add_parser("price", help="price game lines from a margin/total model")
    s.add_argument("kind", choices=["game", "convert", "spread-from-prob", "period", "alt", "keys", "total", "mlb", "nhl"])
    s.add_argument("--sport", default="WNBA")
    s.add_argument("--mu", type=float, help="expected home margin")
    s.add_argument("--sigma", type=float, default=12.5)
    s.add_argument("--total-mu", type=float)
    s.add_argument("--total-sigma", type=float, default=18.0)
    s.add_argument("--home", default="HOME")
    s.add_argument("--away", default="AWAY")
    s.add_argument("--spread", type=float, help="home spread, e.g. -5.5")
    s.add_argument("--spread-prices", nargs=2, type=float, metavar=("HOME", "AWAY"))
    s.add_argument("--total-line", type=float)
    s.add_argument("--total-prices", nargs=2, type=float, metavar=("OVER", "UNDER"))
    s.add_argument("--ml", nargs=2, type=float, metavar=("HOME", "AWAY"))
    s.add_argument("--prob", type=float)
    s.add_argument("--period", default="first_half", choices=["first_half", "first_quarter"])
    s.add_argument("--lines", nargs="+", type=float)
    s.add_argument("--home-rate", type=float, help="mlb/nhl: expected runs/goals for home")
    s.add_argument("--away-rate", type=float, help="mlb/nhl: expected runs/goals for away")
    s.add_argument("--var-ratio", type=float, help="mlb/nhl: variance/mean of team scoring (MLB ~2, NHL ~1)")
    s.add_argument("--empty-net", type=float, default=0.0, help="nhl: share of 1-goal wins turned into 2-goal wins")
    s.add_argument("--method", default="multiplicative", choices=O.DEVIG_METHODS)
    s.set_defaults(fn=cmd_price)

    s = sub.add_parser("prop", help="player prop pricing (WNBA-calibrated dispersion)")
    s.add_argument("kind", nargs="?", default="price", choices=["price", "implied", "dd"])
    s.add_argument("--stat", default="points")
    s.add_argument("--mean", type=float)
    s.add_argument("--line", type=float)
    s.add_argument("--over", type=float)
    s.add_argument("--under", type=float)
    s.add_argument("--rate", type=float, help="per-minute rate (alternative to --mean)")
    s.add_argument("--minutes", type=float)
    s.add_argument("--minutes-sd", type=float, default=0.0)
    s.add_argument("--pace", type=float, default=1.0)
    s.add_argument("--matchup", type=float, default=1.0)
    s.add_argument("--usage", type=float, default=1.0)
    s.add_argument("--points", type=float)
    s.add_argument("--rebounds", type=float)
    s.add_argument("--assists", type=float)
    s.set_defaults(fn=cmd_prop)

    s = sub.add_parser("parlay", help="independent / correlated parlay pricing")
    s.add_argument("--probs", nargs="+", type=float, required=True)
    s.add_argument("--prices", nargs="+")
    s.add_argument("--corr", help="JSON correlation matrix for a same-game parlay")
    s.add_argument("--offered", type=float, help="offered American price for the whole SGP")
    s.add_argument("--sims", type=int, default=200000)
    s.add_argument("--leg-hold", type=float, help="per-leg hold, e.g. 0.045, to show compounded parlay hold")
    s.set_defaults(fn=cmd_parlay)

    s = sub.add_parser("series", help="best-of-N playoff series pricing")
    s.add_argument("--format", default="2-2-1-1-1")
    s.add_argument("--p-home", type=float)
    s.add_argument("--p-away", type=float)
    s.add_argument("--rating-diff", type=float)
    s.add_argument("--hca", type=float, default=1.75)
    s.add_argument("--sigma", type=float, default=12.5)
    s.add_argument("--wins-high", type=int, default=0)
    s.add_argument("--wins-low", type=int, default=0)
    s.add_argument("--sport", default="WNBA")
    s.set_defaults(fn=cmd_series)

    s = sub.add_parser("clv", help="closing line value of a bet")
    s.add_argument("--bet", required=True)
    s.add_argument("--close", required=True, help="closing price of your side")
    s.add_argument("--close-other", required=True, help="closing price of the other side")
    s.add_argument("--line", type=float)
    s.add_argument("--close-line", type=float)
    s.add_argument("--sigma", type=float, default=12.5)
    s.add_argument("--sport", default="WNBA")
    s.set_defaults(fn=cmd_clv)

    s = sub.add_parser("ledger", help="append-only bet ledger")
    s.add_argument("action", choices=["add", "close", "settle", "void", "note", "list", "verify"])
    s.add_argument("--ledger")
    s.add_argument("--profile")
    s.add_argument("--bet-id")
    s.add_argument("--sport")
    s.add_argument("--event")
    s.add_argument("--event-date")
    s.add_argument("--market")
    s.add_argument("--selection")
    s.add_argument("--line", type=float)
    s.add_argument("--price")
    s.add_argument("--stake", type=float)
    s.add_argument("--units", type=float)
    s.add_argument("--book")
    s.add_argument("--model-prob", type=float)
    s.add_argument("--model-push-prob", type=float)
    s.add_argument("--market-prob", type=float)
    s.add_argument("--tier")
    s.add_argument("--tags", nargs="*")
    s.add_argument("--notes")
    s.add_argument("--close-price")
    s.add_argument("--close-line", type=float)
    s.add_argument("--close-other")
    s.add_argument("--result")
    s.add_argument("--correction")
    s.add_argument("--reason")
    s.add_argument("--text")
    s.add_argument("--status", choices=["open", "settled"])
    s.set_defaults(fn=cmd_ledger)

    s = sub.add_parser("report", help="performance review from the ledger")
    s.add_argument("--ledger")
    s.add_argument("--profile")
    s.add_argument("--bankroll", type=float)
    s.add_argument("--format", default="json", choices=["json", "md"])
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("wnba", help="WNBA ratings / predictions / pricing from bundled data")
    s.add_argument("action", choices=["ratings", "predict", "price", "calibrate", "series"])
    s.add_argument("--until", help="fit only on games before this date (YYYY-MM-DD)")
    s.add_argument("--season", type=int)
    s.add_argument("--home")
    s.add_argument("--away")
    s.add_argument("--date")
    s.add_argument("--playoff", action="store_true")
    s.add_argument("--neutral", action="store_true")
    s.add_argument("--adj", type=float, default=0.0, help="manual home-margin adjustment in points (injuries etc.)")
    s.add_argument("--total-adj", type=float, default=0.0)
    s.add_argument("--spread", type=float)
    s.add_argument("--spread-prices", nargs=2, type=float)
    s.add_argument("--total-line", type=float)
    s.add_argument("--total-prices", nargs=2, type=float)
    s.add_argument("--ml", nargs=2, type=float)
    s.add_argument("--model-weight", type=float)
    s.add_argument("--profile")
    s.add_argument("--high")
    s.add_argument("--low")
    s.add_argument("--round", default="semifinals", choices=["first_round", "semifinals", "finals"])
    s.add_argument("--wins-high", type=int, default=0)
    s.add_argument("--wins-low", type=int, default=0)
    s.set_defaults(fn=cmd_wnba)

    s = sub.add_parser("backtest", help="walk-forward WNBA 2026 backtest vs DraftKings open/close")
    s.add_argument("--markets", nargs="+", default=["spread", "total", "moneyline"])
    s.add_argument("--price-at", default="open", choices=["open", "close"])
    s.add_argument("--min-ev", type=float, default=0.02)
    s.add_argument("--model-weight", type=float)
    s.add_argument("--model-weights", help='per-market JSON, e.g. {"total":0.35,"spread":0.15}')
    s.add_argument("--min-disagreement", type=float, default=0.0)
    s.add_argument("--kelly", type=float, default=0.25)
    s.add_argument("--start", default="2026-05-01")
    s.add_argument("--end")
    s.add_argument("--no-playoffs", action="store_true")
    s.add_argument("--sweep", help="field=v1,v2,... e.g. min_ev=0.02,0.04,0.06 (use 'none' for None)")
    s.add_argument("--bets-out")
    s.set_defaults(fn=cmd_backtest)

    s = sub.add_parser("fetch", help="live data: ESPN (no key) / The Odds API (ODDS_API_KEY)")
    s.add_argument("source", choices=["espn-scoreboard", "espn-summary", "espn-injuries", "odds", "value"])
    s.add_argument("--league", default="wnba")
    s.add_argument("--date", help="YYYYMMDD or YYYY-MM-DD")
    s.add_argument("--event")
    s.add_argument("--markets", nargs="+")
    s.add_argument("--regions", nargs="+", default=["us"])
    s.add_argument("--best", action="store_true")
    s.add_argument("--min-ev", type=float, default=0.02)
    s.set_defaults(fn=cmd_fetch)

    s = sub.add_parser("nfl", help="NFL prices from the market line: key numbers, alt lines, teasers")
    s.add_argument("action", choices=["price", "validate", "fit", "ratings", "predict", "backtest"])
    s.add_argument("--spread", type=float, help="home spread (negative = home favoured), e.g. -3")
    s.add_argument("--total", type=float, help="main total")
    s.add_argument("--home", default="HOME")
    s.add_argument("--away", default="AWAY")
    s.add_argument("--alt", type=float, nargs="+", default=[], help="alternate HOME spreads to price")
    s.add_argument("--alt-totals", type=float, nargs="+", default=[])
    s.add_argument("--teaser", type=float, help="teaser points, e.g. 6")
    s.add_argument("--offer", nargs="+", default=[],
                   help="offered prices to check, market:side:line:price, e.g. spread:home:-2.5:-130 "
                        "spread:away:8.5:-300 total:over:41.5:-120 ml:away:0:150")
    s.add_argument("--games", help="nflverse games.csv (validate/fit); default data/nfl/games.csv")
    s.add_argument("--first", type=int, default=2015)
    s.add_argument("--fit-last", type=int, default=2023)
    s.add_argument("--test-first", type=int, default=2024)
    s.add_argument("--test-last", type=int)
    s.add_argument("--date", help="ratings/predict: as of this date, YYYY-MM-DD (default today)")
    s.add_argument("--season", type=int, help="ratings: only teams' current-season rows")
    s.add_argument("--qb-adj", type=float, help="points for a start by someone other than the usual QB (default 3)")
    s.add_argument("--test-seasons", type=int, nargs=2, default=[2021, 2025], metavar=("FIRST", "LAST"))
    s.set_defaults(fn=cmd_nfl)

    s = sub.add_parser("live", help="grade bet-tracker legs from live ESPN scores")
    s.add_argument("--bets", required=True, help="directory of <doc_id>.json bets, or a JSON list/dict of bets")
    s.add_argument("--out", help="write one patch file per bet here (for the tracker database)")
    s.add_argument("--now", help="timestamp to stamp updates with (ISO, UTC); default now")
    s.set_defaults(fn=cmd_live)

    s = sub.add_parser("liveread", help="in-game read (WNBA/NBA): play-by-play facts, fair live price, offers")
    s.add_argument("action", nargs="?", default="read", choices=["read", "validate"])
    s.add_argument("--league", default="wnba", choices=["wnba", "nba"])
    s.add_argument("--event", help="ESPN event id (from fetch espn-scoreboard)")
    s.add_argument("--summary", help="saved ESPN summary JSON instead of fetching")
    s.add_argument("--pre-spread", type=float, help="pregame home spread (default: closing line in the ESPN summary)")
    s.add_argument("--pre-total", type=float, help="pregame total (default: closing total in the ESPN summary)")
    s.add_argument("--offer", nargs="+", default=[],
                   help="live book prices, market:side:line:price[:book], e.g. ml:home:0:-120:dk "
                        "spread:away:1.5:-120:fd total:over:178.5:-115:dk")
    s.add_argument("--sharp", nargs="+", default=[],
                   help="sharp live two-way prices to devig: ml:HOME:AWAY spread:HOME_LINE:HOME:AWAY total:LINE:OVER:UNDER")
    s.add_argument("--min-ev", type=float, default=0.03, help="EV vs the sharp price needed to qualify (live: 3%%)")
    s.add_argument("--since", type=int, default=2023, help="validate: first season with halftime scores")
    s.set_defaults(fn=cmd_liveread)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        res = args.fn(args)
    except Exception as exc:  # surface a clean error for the agent to read
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, indent=2))
        return 1
    _out(res, getattr(args, "format", "json"))
    return 0
