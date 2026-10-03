"""Kelly staking — single, push-aware, simultaneous — plus a capped staking plan.

Why this module exists
----------------------
The reference repo this project grew from sized bets with "confidence tiers"
of 4-5 units at 2% per unit (8-10% of bankroll).  For a +4.8% EV bet at -110
full Kelly is 5.3% of bankroll, so a 5-unit tier bet is ~1.9x full Kelly —
the region where long-run growth turns *negative*.  Here the stake always
comes from (fractional) Kelly first, then caps can only *reduce* it.

Kelly with pushes
-----------------
Maximise G(f) = p_w ln(1 + b f) + p_l ln(1 - f)   (pushes contribute ln 1 = 0)
=> f* = (b p_w - p_l) / (b (p_w + p_l)),  b = decimal - 1.
Without pushes this reduces to the textbook (b p - q) / b.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .odds import OddsError


def kelly_fraction(p_win: float, decimal: float, p_push: float = 0.0) -> float:
    """Full-Kelly fraction of bankroll (0 if the bet is -EV)."""
    p_w, d, p_p = float(p_win), float(decimal), float(p_push)
    if d <= 1:
        raise OddsError(f"decimal odds must be > 1, got {decimal}")
    if not (0 <= p_w <= 1 and 0 <= p_p < 1 and p_w + p_p <= 1 + 1e-12):
        raise OddsError(f"invalid probabilities win={p_win} push={p_push}")
    p_l = max(0.0, 1.0 - p_w - p_p)
    b = d - 1.0
    if p_w + p_l <= 0:
        return 0.0
    f = (b * p_w - p_l) / (b * (p_w + p_l))
    return max(0.0, f)


def growth_rate(f: float, p_win: float, decimal: float, p_push: float = 0.0) -> float:
    """Expected log growth per bet when staking fraction ``f``."""
    p_l = max(0.0, 1.0 - p_win - p_push)
    b = decimal - 1.0
    if f >= 1.0 and p_l > 0:
        return float("-inf")
    return p_win * math.log1p(b * f) + p_l * math.log1p(-f)


def overbet_multiple_where_growth_turns_negative(p_win: float, decimal: float) -> float:
    """Multiple of full Kelly at which expected log growth hits zero (~2 for small edges)."""
    f_star = kelly_fraction(p_win, decimal)
    if f_star <= 0:
        return 0.0
    lo, hi = f_star, 0.999999
    if growth_rate(hi, p_win, decimal) > 0:
        return hi / f_star
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if growth_rate(mid, p_win, decimal) > 0:
            lo = mid
        else:
            hi = mid
    return lo / f_star


# ---------------------------------------------------------------------------
# Simultaneous Kelly for independent bets settled at the same time
# ---------------------------------------------------------------------------

def simultaneous_kelly(bets: Sequence[dict], max_total: float = 1.0, iters: int = 400) -> List[float]:
    """Jointly optimal Kelly fractions for *independent* concurrent bets.

    ``bets``: dicts with keys p_win, decimal, optional p_push.
    Exact expectation over all outcome combinations (2^n or 3^n); limited to
    n <= 10 bets without pushes / n <= 7 with pushes.  Larger slates fall back
    to individual Kelly scaled to ``max_total``.

    Do NOT pass correlated bets (same game spread + ML + total).  Those must be
    combined into one position or capped by game exposure instead.
    """
    n = len(bets)
    if n == 0:
        return []
    singles = [kelly_fraction(b["p_win"], b["decimal"], b.get("p_push", 0.0)) for b in bets]
    has_push = any(b.get("p_push", 0.0) > 0 for b in bets)
    if (has_push and n > 7) or n > 10:
        return _scale_to_cap(singles, max_total)

    outcomes_per_bet = []
    for b in bets:
        p_w = float(b["p_win"])
        p_p = float(b.get("p_push", 0.0))
        p_l = max(0.0, 1.0 - p_w - p_p)
        r_w = float(b["decimal"]) - 1.0
        opts = [(p_w, r_w), (p_l, -1.0)]
        if p_p > 0:
            opts.append((p_p, 0.0))
        outcomes_per_bet.append(opts)
    scenarios = []
    for combo in itertools.product(*outcomes_per_bet):
        prob = 1.0
        rets = []
        for p, r in combo:
            prob *= p
            rets.append(r)
        if prob > 0:
            scenarios.append((prob, rets))

    def objective(f: List[float]) -> float:
        total = 0.0
        for prob, rets in scenarios:
            w = 1.0 + sum(fi * ri for fi, ri in zip(f, rets))
            if w <= 0:
                return float("-inf")
            total += prob * math.log(w)
        return total

    def gradient(f: List[float]) -> List[float]:
        g = [0.0] * n
        for prob, rets in scenarios:
            w = 1.0 + sum(fi * ri for fi, ri in zip(f, rets))
            for i in range(n):
                g[i] += prob * rets[i] / w
        return g

    f = _scale_to_cap([s * 0.5 for s in singles], max_total)
    step = 0.05
    best = objective(f)
    for _ in range(iters):
        g = gradient(f)
        improved = False
        while step > 1e-9:
            cand = [max(0.0, fi + step * gi) for fi, gi in zip(f, g)]
            cand = _scale_to_cap(cand, max_total)
            val = objective(cand)
            if val > best + 1e-15:
                f, best = cand, val
                step *= 1.5
                improved = True
                break
            step *= 0.5
        if not improved:
            break
    return f


def _scale_to_cap(fracs: Sequence[float], cap: float) -> List[float]:
    total = sum(fracs)
    if total <= cap or total == 0:
        return list(fracs)
    k = cap / total
    return [x * k for x in fracs]


# ---------------------------------------------------------------------------
# Staking plan with explicit caps
# ---------------------------------------------------------------------------

@dataclass
class StakeLimits:
    bankroll: float
    kelly_multiplier: float = 0.25        # quarter Kelly by default
    unit_pct: float = 0.01                # 1 unit = 1% of bankroll (display only)
    max_bet_pct: float = 0.03             # hard cap per bet
    max_daily_pct: float = 0.10           # total new exposure per day
    max_game_pct: float = 0.04            # all positions on one game combined
    max_sport_pct: float = 0.08           # concentration cap per sport per day
    min_stake: float = 1.0                # below this, don't bother
    round_to: float = 1.0                 # round stakes to this currency step

    @classmethod
    def from_profile(cls, profile: dict) -> "StakeLimits":
        keys = cls.__dataclass_fields__.keys()
        return cls(**{k: profile[k] for k in keys if k in profile})


@dataclass
class StakeDecision:
    label: str
    full_kelly_pct: float
    target_pct: float
    stake: float
    units: float
    capped_by: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "full_kelly_pct": round(self.full_kelly_pct * 100, 3),
            "target_pct": round(self.target_pct * 100, 3),
            "stake": self.stake,
            "units": self.units,
            "capped_by": self.capped_by,
        }


def stake_plan(candidates: Sequence[dict], limits: StakeLimits,
               already_exposed: Optional[Dict[str, float]] = None) -> List[StakeDecision]:
    """Turn +EV candidates into stakes.

    candidate keys: label, p_win, decimal, optional p_push, game (id string),
    sport, and optional ``kelly_multiplier`` override (e.g. 0.15 for props).

    Order of operations (each step can only reduce the stake):
      1. full Kelly (push-aware) * kelly multiplier
      2. per-bet cap
      3. per-game cap (shared across bets on the same game)
      4. per-sport cap
      5. daily exposure cap
      6. drop if below min_stake; round down to ``round_to``
    ``already_exposed`` carries today's existing exposure:
    {"__day__": x, "game:<id>": y, "sport:<name>": z} as fractions of bankroll.
    """
    exposed = dict(already_exposed or {})
    out: List[StakeDecision] = []
    br = float(limits.bankroll)
    unit = br * limits.unit_pct
    # Size the biggest-edge bets first so caps bind on the marginal ones.
    order = sorted(range(len(candidates)), key=lambda i: -_ev(candidates[i]))
    decisions: Dict[int, StakeDecision] = {}
    for i in order:
        c = candidates[i]
        caps: List[str] = []
        full = kelly_fraction(c["p_win"], c["decimal"], c.get("p_push", 0.0))
        mult = float(c.get("kelly_multiplier", limits.kelly_multiplier))
        target = full * mult
        if target > limits.max_bet_pct:
            target = limits.max_bet_pct
            caps.append("max_bet_pct")
        gkey = f"game:{c.get('game', c.get('label'))}"
        room_game = limits.max_game_pct - exposed.get(gkey, 0.0)
        if target > room_game:
            target = max(0.0, room_game)
            caps.append("max_game_pct")
        skey = f"sport:{c.get('sport', 'any')}"
        room_sport = limits.max_sport_pct - exposed.get(skey, 0.0)
        if target > room_sport:
            target = max(0.0, room_sport)
            caps.append("max_sport_pct")
        room_day = limits.max_daily_pct - exposed.get("__day__", 0.0)
        if target > room_day:
            target = max(0.0, room_day)
            caps.append("max_daily_pct")
        stake = br * target
        step = limits.round_to if limits.round_to > 0 else 0.01
        stake = math.floor(stake / step + 1e-9) * step
        if stake < limits.min_stake:
            if full > 0 and "below_min_stake" not in caps:
                caps.append("below_min_stake")
            stake = 0.0
        pct = stake / br if br else 0.0
        exposed[gkey] = exposed.get(gkey, 0.0) + pct
        exposed[skey] = exposed.get(skey, 0.0) + pct
        exposed["__day__"] = exposed.get("__day__", 0.0) + pct
        decisions[i] = StakeDecision(
            label=str(c.get("label", f"bet{i}")),
            full_kelly_pct=full,
            target_pct=pct,
            stake=round(stake, 2),
            units=round(stake / unit, 2) if unit else 0.0,
            capped_by=caps,
        )
    for i in range(len(candidates)):
        out.append(decisions[i])
    return out


def _ev(c: dict) -> float:
    p_w = float(c["p_win"])
    p_p = float(c.get("p_push", 0.0))
    return p_w * (float(c["decimal"]) - 1.0) - max(0.0, 1.0 - p_w - p_p)


def risk_of_ruin_mc(p_win: float, decimal: float, stake_pct: float, n_bets: int = 1000,
                    ruin_level: float = 0.5, trials: int = 2000, seed: int = 7) -> dict:
    """Monte Carlo: probability the bankroll ever falls below ``ruin_level``.

    Proportional staking (stake_pct of *current* bankroll).  Also returns the
    median ending bankroll multiple and the median max drawdown.
    """
    import random

    rng = random.Random(seed)
    b = decimal - 1.0
    ruined = 0
    endings: List[float] = []
    max_dds: List[float] = []
    for _ in range(trials):
        w = 1.0
        peak = 1.0
        mdd = 0.0
        hit = False
        for _ in range(n_bets):
            stake = w * stake_pct
            w += stake * b if rng.random() < p_win else -stake
            peak = max(peak, w)
            mdd = max(mdd, 1.0 - w / peak)
            if w <= ruin_level:
                hit = True
        ruined += hit
        endings.append(w)
        max_dds.append(mdd)
    endings.sort()
    max_dds.sort()
    return {
        "p_hit_ruin_level": ruined / trials,
        "median_final_multiple": endings[trials // 2],
        "p10_final_multiple": endings[trials // 10],
        "median_max_drawdown": max_dds[trials // 2],
        "p90_max_drawdown": max_dds[(9 * trials) // 10],
    }
