"""Walk-forward backtesting with no look-ahead.

Rules enforced by the engine (these are the ways backtests usually lie):

1. Predictions for date D use only games completed before D.  All of a
   date's games are priced first; the model learns from them only after.
2. You bet the price you could actually have gotten (``price_at='open'`` or
   ``'close'``), including the vig — never the devigged line.
3. Pushes are graded as pushes from the actual final score.
4. Staking compounds on the running bankroll with caps, like real life.
5. Every run reports how many configurations were tried so you can discount
   for multiple testing; the summary includes a bootstrap CI, not just ROI.

The bundled data lets you run a genuine 2026 WNBA test: the model is fit on
2013-2025, then walks through 340 2026 games against DraftKings openers or
closers.  Betting into *closing* lines is the hardest possible test — a
model with no information edge should lose about the vig there.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from .clv import clv_spread_points, clv_total_points
from .distributions import discretized_normal
from .kelly import kelly_fraction
from .markets import MarginModel
from .odds import american_to_decimal, blend_probs, devig
from .ratings import KalmanRatings, _to_date
from .report import bootstrap_roi_ci, t_test


@dataclass
class BacktestConfig:
    markets: Sequence[str] = ("spread", "total", "moneyline")
    price_at: str = "open"                 # "open" or "close"
    min_ev: float = 0.03                   # minimum EV (fraction) to bet
    min_disagreement: float = 0.0          # optional: |model - market line| in points (spread/total)
    max_disagreement: Optional[float] = None  # skip huge disagreements (usually news the model lacks)
    kelly_multiplier: float = 0.25
    max_bet_pct: float = 0.03
    bankroll: float = 1000.0
    flat_stake_pct: Optional[float] = None  # if set, ignore Kelly and stake this % of starting bankroll
    sport: str = "WNBA"
    start: Optional[str] = None
    end: Optional[str] = None
    include_playoffs: bool = True
    clv_margin_sigma: float = 12.5
    clv_total_sigma: float = 18.0
    # Shrink model probabilities toward the devigged market price at bet time
    # (logit blend).  None = trust the raw model (almost always overconfident).
    model_weight: Optional[float] = None
    model_weights: Optional[Dict[str, float]] = None   # per-market override


@dataclass
class BacktestResult:
    config: dict
    bets: List[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"config": self.config, "summary": self.summary, "bets": self.bets}


def _price_fields(line_row: dict, price_at: str) -> dict:
    s = price_at
    return {
        "spread_home": line_row.get(f"spread_home_{s}"),
        "spread_price_home": line_row.get(f"spread_price_home_{s}"),
        "spread_price_away": line_row.get(f"spread_price_away_{s}"),
        "total": line_row.get(f"total_{s}"),
        "over_price": line_row.get(f"over_price_{s}"),
        "under_price": line_row.get(f"under_price_{s}"),
        "ml_home": line_row.get(f"ml_home_{s}"),
        "ml_away": line_row.get(f"ml_away_{s}"),
    }


def _grade_spread(margin: int, home_line: float, side: str) -> str:
    adj = margin + home_line if side == "home" else -(margin + home_line)
    return "win" if adj > 0 else ("loss" if adj < 0 else "push")


def _grade_total(total: int, line: float, side: str) -> str:
    diff = total - line if side == "over" else line - total
    return "win" if diff > 0 else ("loss" if diff < 0 else "push")


def _weight(cfg: "BacktestConfig", market: str) -> Optional[float]:
    if cfg.model_weights and market in cfg.model_weights:
        return cfg.model_weights[market]
    return cfg.model_weight


def _blend_two_way(p_side: float, p_push: float, price_side: float, price_other: float, w: Optional[float]) -> float:
    """Blend the win share (ex-push) with the devigged market, keep the model push prob."""
    if w is None:
        return p_side
    q_model = p_side / (1.0 - p_push) if p_push < 1 else 0.5
    q_mkt = devig([american_to_decimal(price_side), american_to_decimal(price_other)])[0]
    return blend_probs(q_model, q_mkt, w) * (1.0 - p_push)


def candidate_bets(pred, prices: dict, cfg: BacktestConfig) -> List[dict]:
    """All sides of all requested markets with (optionally market-blended) probabilities and EV."""
    out: List[dict] = []
    mm = MarginModel.normal(pred.mu, pred.sd, cfg.sport)
    if "spread" in cfg.markets and prices["spread_home"] is not None:
        line = prices["spread_home"]
        c, p, f = mm.spread_probs(line)
        dis = pred.mu - (-line)
        w = _weight(cfg, "spread")
        ph, pa = prices["spread_price_home"], prices["spread_price_away"]
        c, f = _blend_two_way(c, p, ph, pa, w), _blend_two_way(f, p, pa, ph, w)
        for side, pw, price in (("home", c, ph), ("away", f, pa)):
            d = american_to_decimal(price)
            out.append({"market": "spread", "side": side, "line": line if side == "home" else -line, "home_line": line,
                        "price_american": price, "decimal": d, "p_win": pw, "p_push": p,
                        "ev": pw * (d - 1) - (1 - pw - p), "disagreement": dis if side == "home" else -dis})
    if "total" in cfg.markets and prices["total"] is not None:
        line = prices["total"]
        td = discretized_normal(pred.total_mu, pred.total_sd)
        o, u, p = td.over_under_push(line)
        dis = pred.total_mu - line
        w = _weight(cfg, "total")
        po, pu = prices["over_price"], prices["under_price"]
        o, u = _blend_two_way(o, p, po, pu, w), _blend_two_way(u, p, pu, po, w)
        for side, pw, price in (("over", o, po), ("under", u, pu)):
            d = american_to_decimal(price)
            out.append({"market": "total", "side": side, "line": line, "price_american": price, "decimal": d,
                        "p_win": pw, "p_push": p, "ev": pw * (d - 1) - (1 - pw - p),
                        "disagreement": dis if side == "over" else -dis})
    if "moneyline" in cfg.markets and prices["ml_home"] is not None:
        ph = mm.p_home_win()
        w = _weight(cfg, "moneyline")
        if w is not None:
            ph = blend_probs(ph, devig([american_to_decimal(prices["ml_home"]), american_to_decimal(prices["ml_away"])])[0], w)
        for side, pw, price in (("home", ph, prices["ml_home"]), ("away", 1 - ph, prices["ml_away"])):
            d = american_to_decimal(price)
            out.append({"market": "moneyline", "side": side, "line": None, "price_american": price, "decimal": d,
                        "p_win": pw, "p_push": 0.0, "ev": pw * (d - 1) - (1 - pw), "disagreement": None})
    return out


def run_backtest(games: Sequence[dict], lines: Sequence[dict], model_factory: Callable[[], KalmanRatings],
                 cfg: Optional[BacktestConfig] = None, configs_tried: int = 1) -> BacktestResult:
    cfg = cfg or BacktestConfig()
    by_id = {str(g["game_id"]): g for g in games}
    start = _to_date(cfg.start) if cfg.start else min(_to_date(l["date"]) for l in lines)
    end = _to_date(cfg.end) if cfg.end else max(_to_date(l["date"]) for l in lines)
    model = model_factory()
    hist = sorted(games, key=lambda g: (_to_date(g["date"]), str(g["game_id"])))
    idx = 0
    # learn from everything before the first test date
    while idx < len(hist) and _to_date(hist[idx]["date"]) < start:
        model.update(hist[idx])
        idx += 1
    test_lines = [l for l in lines if start <= _to_date(l["date"]) <= end
                  and (cfg.include_playoffs or l.get("season_type") != "playoff")]
    dates = sorted({_to_date(l["date"]) for l in test_lines})
    bankroll = cfg.bankroll
    bets: List[dict] = []
    for d in dates:
        while idx < len(hist) and _to_date(hist[idx]["date"]) < d:
            model.update(hist[idx])
            idx += 1
        todays = [l for l in test_lines if _to_date(l["date"]) == d]
        day_bets = []
        for l in todays:
            g = by_id.get(str(l["game_id"]))
            if g is None:
                continue
            pred = model.predict(g["home"], g["away"], d, season=int(g["season"]),
                                 neutral=bool(int(g.get("neutral", 0) or 0)),
                                 playoff=g.get("season_type") == "playoff")
            prices = _price_fields(l, cfg.price_at)
            cands = candidate_bets(pred, prices, cfg)
            for mkt in cfg.markets:
                side_c = [c for c in cands if c["market"] == mkt]
                if not side_c:
                    continue
                best = max(side_c, key=lambda c: c["ev"])
                if best["ev"] < cfg.min_ev:
                    continue
                if best["disagreement"] is not None:
                    if best["disagreement"] < cfg.min_disagreement:
                        continue
                    if cfg.max_disagreement is not None and best["disagreement"] > cfg.max_disagreement:
                        continue
                if cfg.flat_stake_pct:
                    stake = cfg.bankroll * cfg.flat_stake_pct
                else:
                    f = kelly_fraction(best["p_win"], best["decimal"], best["p_push"]) * cfg.kelly_multiplier
                    stake = bankroll * min(f, cfg.max_bet_pct)
                if stake <= 0:
                    continue
                margin = int(g["home_pts"]) - int(g["away_pts"])
                total = int(g["home_pts"]) + int(g["away_pts"])
                if mkt == "spread":
                    res = _grade_spread(margin, best["home_line"], best["side"])
                elif mkt == "total":
                    res = _grade_total(total, best["line"], best["side"])
                else:
                    won = (margin > 0) == (best["side"] == "home")
                    res = "win" if won else "loss"
                pnl = stake * (best["decimal"] - 1) if res == "win" else (-stake if res == "loss" else 0.0)
                bet = {"date": d.isoformat(), "game_id": l["game_id"], "matchup": f"{g['away']} @ {g['home']}",
                       "market": mkt, "side": best["side"], "line": best["line"], "price_american": best["price_american"],
                       "p_win": round(best["p_win"], 4), "p_push": round(best["p_push"], 4), "ev": round(best["ev"], 4),
                       "model_mu": round(pred.mu, 2), "model_total": round(pred.total_mu, 2),
                       "stake": round(stake, 2), "result": res, "pnl": round(pnl, 2)}
                if cfg.price_at == "open":
                    bet.update(_clv_vs_close(best, l, cfg))
                day_bets.append(bet)
        for b in day_bets:
            bankroll += b["pnl"]
            b["bankroll_after"] = round(bankroll, 2)
        bets.extend(day_bets)
    return BacktestResult(config={**asdict(cfg), "configs_tried": configs_tried}, bets=bets,
                          summary=summarize_bets(bets, cfg.bankroll, configs_tried))


def _clv_vs_close(best: dict, l: dict, cfg: BacktestConfig) -> dict:
    try:
        if best["market"] == "moneyline":
            ch, ca = american_to_decimal(l["ml_home_close"]), american_to_decimal(l["ml_away_close"])
            p_home = devig([ch, ca])[0]
            p = p_home if best["side"] == "home" else 1 - p_home
            return {"clv_ev": round(p * best["decimal"] - 1, 4)}
        if best["market"] == "spread":
            close_home = l["spread_home_close"]
            if best["side"] == "home":
                r = clv_spread_points(best["line"], best["price_american"], close_home, l["spread_price_home_close"],
                                      l["spread_price_away_close"], cfg.clv_margin_sigma, cfg.sport)
            else:
                r = clv_spread_points(best["line"], best["price_american"], -close_home, l["spread_price_away_close"],
                                      l["spread_price_home_close"], cfg.clv_margin_sigma, cfg.sport)
            return {"clv_ev": round(r["clv_ev"], 4), "clv_points": round(r["points_moved_in_favour"], 2)}
        if best["market"] == "total":
            r = clv_total_points(best["line"], best["price_american"], best["side"], l["total_close"],
                                 l["over_price_close"], l["under_price_close"], cfg.clv_total_sigma)
            return {"clv_ev": round(r["clv_ev"], 4), "clv_points": round(r["points_moved_in_favour"], 2)}
    except (TypeError, KeyError, ValueError):
        return {}
    return {}


def summarize_bets(bets: Sequence[dict], bankroll0: float, configs_tried: int = 1) -> dict:
    out: dict = {"configs_tried": configs_tried}
    if not bets:
        out["note"] = "no bets met the criteria"
        return out
    def block(rows):
        st = sum(b["stake"] for b in rows)
        pnl = sum(b["pnl"] for b in rows)
        w = sum(b["result"] == "win" for b in rows)
        l_ = sum(b["result"] == "loss" for b in rows)
        p = sum(b["result"] == "push" for b in rows)
        d = {"bets": len(rows), "record": f"{w}-{l_}-{p}", "staked": round(st, 2), "pnl": round(pnl, 2),
             "roi_pct": round(100 * pnl / st, 2) if st else None,
             "avg_ev_at_bet_pct": round(100 * sum(b["ev"] for b in rows) / len(rows), 2)}
        clv = [b["clv_ev"] for b in rows if b.get("clv_ev") is not None]
        if clv:
            tt = t_test(clv)
            d["avg_clv_pct"] = round(100 * tt["mean"], 2) if "mean" in tt else None
            d["clv_t"] = round(tt.get("t", float("nan")), 2) if len(clv) > 1 else None
        lo, hi = bootstrap_roi_ci([{"stake": b["stake"], "pnl": b["pnl"]} for b in rows])
        d["roi_ci95_pct"] = [round(100 * lo, 2), round(100 * hi, 2)] if lo is not None else None
        return d
    out["overall"] = block(bets)
    out["by_market"] = {m: block([b for b in bets if b["market"] == m]) for m in sorted({b["market"] for b in bets})}
    eq, peak, mdd = bankroll0, bankroll0, 0.0
    for b in bets:
        eq += b["pnl"]
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak if peak else 0)
    out["final_bankroll"] = round(eq, 2)
    out["max_drawdown_pct"] = round(100 * mdd, 2)
    if configs_tried > 1:
        out["multiple_testing_note"] = (f"{configs_tried} configurations were tried; the best one is biased upward. "
                                        "Require the CI to clear zero by a wide margin, or re-test on a new season.")
    return out


def sweep(games, lines, model_factory, base: BacktestConfig, field_name: str, values: Iterable) -> List[dict]:
    vals = list(values)
    rows = []
    for v in vals:
        cfg = BacktestConfig(**{**asdict(base), field_name: v})
        res = run_backtest(games, lines, model_factory, cfg, configs_tried=len(vals))
        rows.append({field_name: v, **{k: res.summary.get("overall", {}).get(k) for k in ("bets", "record", "roi_pct", "roi_ci95_pct", "avg_clv_pct", "clv_t")}})
    return rows
