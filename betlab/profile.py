"""Bettor profile: bankroll, risk limits, thresholds and preferences.

Lookup order: explicit path -> $BETLAB_PROFILE -> config/profile.json ->
config/profile.example.json -> built-in defaults.  Values are merged over
DEFAULTS so a profile only needs the keys it changes.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Optional

from .kelly import StakeLimits

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "bankroll": 1000.0,
    "unit_pct": 0.01,
    "kelly_multiplier": 0.25,
    "prop_kelly_multiplier": 0.15,
    "max_bet_pct": 0.03,
    "max_daily_pct": 0.10,
    "max_game_pct": 0.04,
    "max_sport_pct": 0.08,
    "min_stake": 1.0,
    "round_to": 1.0,
    # Minimum EV (fraction of stake) after blending with the market, by market type.
    "min_ev": {"spread": 0.02, "total": 0.02, "moneyline": 0.025, "team_total": 0.03, "period": 0.03,
               "prop": 0.04, "parlay": 0.08, "sgp": 0.10, "future": 0.06, "series": 0.03},
    # Weight on the model when blending with the devigged market (logit space).
    "model_weight": {
        "default": {"spread": 0.15, "total": 0.2, "moneyline": 0.15, "prop": 0.5},
        "WNBA": {"spread": 0.15, "total": 0.35, "moneyline": 0.15, "prop": 0.5},
        # NFL ratings vs closing lines, 2021-25 walk-forward: best blend weight 0 (see betlab/nfl.py)
        "NFL": {"spread": 0.0, "total": 0.0, "moneyline": 0.0, "prop": 0.5},
    },
    "devig_method": "multiplicative",
    "stop_loss_drawdown_pct": 0.20,
    "daily_stop_loss_pct": 0.05,
    "books": ["DraftKings", "FanDuel", "BetMGM", "Caesars", "Fanatics", "theScore Bet"],
    "state": None,
    "sports": ["WNBA", "NBA", "NFL", "MLB", "NHL", "NCAAF", "NCAAB"],
    "timezone": "America/New_York",
    "ledger_path": "data/ledger/bets.jsonl",
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def profile_path(path: Optional[str] = None) -> Optional[Path]:
    for cand in (path, os.environ.get("BETLAB_PROFILE"), ROOT / "config" / "profile.json",
                 ROOT / "config" / "profile.example.json"):
        if cand and Path(cand).exists():
            return Path(cand)
    return None


def load_profile(path: Optional[str] = None) -> dict:
    p = profile_path(path)
    prof = DEFAULTS
    if p is not None:
        with open(p) as f:
            prof = _merge(DEFAULTS, json.load(f))
        prof["_source"] = str(p)
    else:
        prof = copy.deepcopy(DEFAULTS)
        prof["_source"] = "built-in defaults"
    validate(prof)
    return prof


def validate(p: dict) -> None:
    if float(p["bankroll"]) <= 0:
        raise ValueError("bankroll must be > 0")
    for k in ("unit_pct", "kelly_multiplier", "max_bet_pct", "max_daily_pct", "max_game_pct", "max_sport_pct"):
        v = float(p[k])
        if not 0 < v <= 1:
            raise ValueError(f"{k} must be in (0, 1], got {v}")
    if float(p["kelly_multiplier"]) > 0.5:
        raise ValueError("kelly_multiplier above 0.5 is not allowed: model error makes >half-Kelly a bankroll risk")
    if float(p["max_bet_pct"]) > 0.05:
        raise ValueError("max_bet_pct above 5% of bankroll per bet is not allowed")


def unit_size(p: dict) -> float:
    return round(float(p["bankroll"]) * float(p["unit_pct"]), 2)


def stake_limits(p: dict) -> StakeLimits:
    return StakeLimits.from_profile(p)


def min_ev_for(p: dict, market: str) -> float:
    m = market.lower()
    table = p.get("min_ev", {})
    if m in table:
        return float(table[m])
    if m.startswith("period"):
        return float(table.get("period", 0.03))
    return float(table.get("spread", 0.02))


def model_weight_for(p: dict, sport: str, market: str) -> float:
    mw = p.get("model_weight", {})
    sp = mw.get(sport.upper(), {})
    if market in sp:
        return float(sp[market])
    return float(mw.get("default", {}).get(market, 0.2))
