"""Best-of-N playoff series pricing.

Formats are written from the HIGHER seed's perspective: 'H' = higher seed at
home.  WNBA 2025+: first round best-of-3 '1-1-1' (H, A, H); semifinals
best-of-5 '2-2-1' (H, H, A, A, H); Finals best-of-7 '2-2-1-1-1'
(H, H, A, A, H, A, H).

Per-game probabilities usually come from a margin model:
p_home_game = P(higher seed wins at home), p_away_game = P(... on the road).
``series_from_ratings`` builds both from a rating difference, HCA and sigma.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .markets import MarginModel

FORMATS: Dict[str, List[str]] = {
    "1-1-1": ["H", "A", "H"],
    "2-1": ["H", "H", "A"],
    "2-2-1": ["H", "H", "A", "A", "H"],
    "2-3-2": ["H", "H", "A", "A", "A", "H", "H"],
    "2-2-1-1-1": ["H", "H", "A", "A", "H", "A", "H"],
    "1": ["H"],   # single game at the higher seed (WNBA rounds 1-2, 2016-2021)
}
WNBA_ROUNDS = {"first_round": "1-1-1", "semifinals": "2-2-1", "finals": "2-2-1-1-1"}


def series_probs(p_home_game: float, p_away_game: float, fmt: str = "2-2-1-1-1",
                 wins_high: int = 0, wins_low: int = 0,
                 per_game: Optional[Sequence[float]] = None) -> dict:
    """Exact series probabilities from the current state.

    ``per_game`` overrides the H/A probabilities game by game (index = game
    number - 1), e.g. to add rest or injury effects to a specific game.
    Returns P(higher seed wins), the distribution of series lengths and the
    exact-result distribution ("4-1", "3-4", ...).
    """
    if fmt not in FORMATS:
        raise KeyError(f"unknown format {fmt!r}; known {sorted(FORMATS)}")
    sched = FORMATS[fmt]
    n = len(sched)
    if n % 2 == 0:
        raise ValueError("series formats must have an odd number of games")
    need = n // 2 + 1
    probs = list(per_game) if per_game is not None else [p_home_game if s == "H" else p_away_game for s in sched]
    if len(probs) != n:
        raise ValueError("per_game must have one probability per possible game")
    if wins_high >= need or wins_low >= need:
        raise ValueError("series already decided")

    results: Dict[str, float] = {}
    # forward DP over (higher-seed wins, lower-seed wins) states
    states = {(wins_high, wins_low): 1.0}
    while states:
        nxt: Dict[tuple, float] = {}
        for (wh, wl), pr in states.items():
            g = wh + wl  # games played -> next game index
            p = probs[g]
            for win, q in ((True, p), (False, 1 - p)):
                a, b = (wh + 1, wl) if win else (wh, wl + 1)
                mass = pr * q
                if a == need or b == need:
                    key = f"{a}-{b}"
                    results[key] = results.get(key, 0.0) + mass
                else:
                    nxt[(a, b)] = nxt.get((a, b), 0.0) + mass
        states = nxt
    p_high = sum(v for k, v in results.items() if int(k.split("-")[0]) == need)
    lengths: Dict[int, float] = {}
    for k, v in results.items():
        a, b = map(int, k.split("-"))
        lengths[a + b] = lengths.get(a + b, 0.0) + v
    return {"format": fmt, "p_higher_seed": p_high, "p_lower_seed": 1 - p_high,
            "exact": dict(sorted(results.items(), key=lambda kv: (-int(kv[0].split('-')[0]), kv[0]))),
            "length": dict(sorted(lengths.items()))}


def series_from_ratings(rating_diff: float, hca: float, sigma: float, fmt: str = "2-2-1-1-1",
                        wins_high: int = 0, wins_low: int = 0, sport: str = "WNBA") -> dict:
    """``rating_diff`` = higher seed rating - lower seed rating (neutral-court points)."""
    p_home = MarginModel.normal(rating_diff + hca, sigma, sport).p_home_win()
    p_away = MarginModel.normal(rating_diff - hca, sigma, sport).p_home_win()
    out = series_probs(p_home, p_away, fmt, wins_high, wins_low)
    out.update({"p_game_home": p_home, "p_game_away": p_away})
    return out


def implied_game_prob_from_series(p_series: float, fmt: str = "2-2-1-1-1", hca_gap: float = 0.0) -> float:
    """Solve for the neutral per-game probability that reproduces a series price.

    ``hca_gap`` shifts home/away game probabilities by +/- that amount.
    Useful to sanity-check a series price against a game moneyline.
    """
    lo, hi = 1e-6, 1 - 1e-6
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        ph = min(max(mid + hca_gap, 1e-6), 1 - 1e-6)
        pa = min(max(mid - hca_gap, 1e-6), 1 - 1e-6)
        if series_probs(ph, pa, fmt)["p_higher_seed"] < p_series:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
