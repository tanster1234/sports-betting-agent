"""Quiet-day pick: the one bet closest to fair, for a day with no value bet.

Opt-in (profile ``quiet_day_pick.enabled``).  Fractional Kelly stakes nothing on a bet without
an edge, so a quiet-day pick is never sized by Kelly.  It gets a small fixed stake
(``stake_pct`` of bankroll) and is labelled entertainment, not value.

Rules:
  * candidates are single bets priced against a sharp fair probability (``p_win``, optional
    ``p_push``); parlays, same-game parlays and teasers are refused, since every leg adds the
    book's margin again;
  * the pick is the candidate with the highest EV, i.e. the lowest expected cost;
  * if that bet already clears the value bar for its market it is a real bet: size it with
    ``betlab stake`` instead;
  * if even the cheapest bet costs more than ``max_cost_pct`` of the stake there is no pick;
  * at most ``max_per_day`` picks a day; log each with tier ``entertainment`` so the record
    that judges skill (ROI, CLV, calibration) leaves it out.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .odds import decimal_to_american, ev, format_american, min_price_for_ev, parse_price
from .profile import min_ev_for
from .report import ENTERTAINMENT as TIER

LABEL = "Entertainment, not value"
NOT_SINGLES = {"parlay", "sgp", "teaser"}
DEFAULTS = {"enabled": False, "stake_pct": 0.01, "max_cost_pct": 0.03, "max_per_day": 1}


def settings(profile: dict) -> dict:
    return {**DEFAULTS, **(profile.get("quiet_day_pick") or {})}


def _fair_american(p_win: float, p_push: float) -> Optional[str]:
    p_loss = 1.0 - p_win - p_push
    if p_win <= 0 or p_loss <= 0:
        return None
    return format_american(decimal_to_american(1.0 + p_loss / p_win))


def _row(c: dict) -> dict:
    d = float(c["decimal"]) if "decimal" in c else parse_price(c["price"])
    p, pp = float(c["p_win"]), float(c.get("p_push", 0.0))
    e = ev(p, d, pp)
    return {**{k: v for k, v in c.items() if k not in ("decimal",)},
            "market": str(c.get("market", "spread")).lower(), "decimal": round(d, 4),
            "price_american": format_american(decimal_to_american(d)), "fair_american": _fair_american(p, pp),
            "ev_pct": round(100 * e, 2), "_ev": e}


def stake_for(profile: dict, bankroll: Optional[float] = None) -> float:
    """Fixed stake: ``stake_pct`` of bankroll to the nearest step, never above the per-bet cap."""
    cfg = settings(profile)
    bank = float(bankroll or profile["bankroll"])
    step = float(profile.get("round_to") or 1.0) or 1.0
    stake = max(float(profile.get("min_stake", 1.0)), round(cfg["stake_pct"] * bank / step) * step)
    cap = math.floor(float(profile["max_bet_pct"]) * bank / step) * step
    return round(min(stake, cap) if cap > 0 else stake, 2)


def picks_today(bets: Iterable[dict], tz: str = "America/New_York", today: Optional[date] = None) -> int:
    """Quiet-day picks already placed today (ledger bets with tier ``entertainment``)."""
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):       # no time-zone database (e.g. bare Windows): use UTC
        zone = timezone.utc
    day = today or datetime.now(zone).date()
    n = 0
    for b in bets:
        if b.get("tier") != TIER or not b.get("placed_at"):
            continue
        t = datetime.fromisoformat(str(b["placed_at"]).replace("Z", "+00:00"))
        if (t.astimezone(zone) if t.tzinfo else t).date() == day:
            n += 1
    return n


def pick(candidates: Sequence[dict], profile: dict, bankroll: Optional[float] = None,
         already_today: int = 0) -> dict:
    """The candidate with the lowest expected cost, sized and labelled as a quiet-day pick."""
    cfg = settings(profile)
    rejected: List[dict] = []
    rows: List[dict] = []
    for c in candidates:
        if str(c.get("market", "")).lower() in NOT_SINGLES:
            rejected.append({"label": c.get("label"), "reason": "parlays add the book's margin on every leg"})
            continue
        rows.append(_row(c))
    rows.sort(key=lambda r: -r["_ev"])
    out: dict = {"enabled": bool(cfg["enabled"]), "label": LABEL, "rejected": rejected}
    if not cfg["enabled"]:
        out["note"] = "Quiet-day picks are off in this profile (quiet_day_pick.enabled)."
    if not rows:
        return {**out, "status": "none", "message": "No single bets to choose from."}
    if already_today >= int(cfg["max_per_day"]):
        return {**out, "status": "done_today",
                "message": f"Already {already_today} quiet-day pick(s) today; the limit is {cfg['max_per_day']}."}
    best = rows[0]
    clean = [{k: v for k, v in r.items() if k != "_ev"} for r in rows]
    if best["_ev"] >= min_ev_for(profile, best["market"]):
        return {**out, "status": "value", "best": clean[0],
                "message": "This clears the value bar for its market, so it is a real bet: size it with "
                           "`betlab stake`, not as a quiet-day pick."}
    if best["_ev"] < -cfg["max_cost_pct"]:
        return {**out, "status": "none", "best": clean[0],
                "message": f"Even the cheapest bet costs {-best['ev_pct']:.1f}% of the stake, more than the "
                           f"{100 * cfg['max_cost_pct']:.0f}% limit: no quiet-day pick today."}
    stake = stake_for(profile, bankroll)
    p, pp = float(best["p_win"]), float(best.get("p_push", 0.0))
    worst = decimal_to_american(min_price_for_ev(p, -cfg["max_cost_pct"], pp))
    chosen = {**clean[0], "stake": stake, "expected_cost": round(max(0.0, -best["_ev"]) * stake, 2),
              "skip_if_worse_than": format_american(worst)}
    if best["_ev"] >= 0:
        cost = f"about break-even by the sharp price ({best['ev_pct']:+.1f}%, below the value bar)"
    else:
        cost = f"costs about {-best['ev_pct']:.1f}% of the stake on average"
    return {**out, "status": "pick", "pick": chosen, "runners_up": clean[1:4], "ledger_tier": TIER,
            "message": f"{LABEL}: {cost}. Log it with --tier {TIER}."}
