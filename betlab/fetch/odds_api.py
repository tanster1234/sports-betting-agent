"""The Odds API (v4) client + consensus no-vig pricing and line shopping.

Set ODDS_API_KEY in the environment (free tier: 500 credits/month).
Featured-market cost = markets x regions per call; event (prop) endpoints
cost unique markets returned x regions.  Remaining quota is reported from
the x-requests-remaining header.

Region "us" covers draftkings, fanduel, betmgm, betrivers, williamhill_us,
fanatics, betonlineag, lowvig, bovada, ...; "us2" espnbet(theScore),
hardrockbet, ...; "us_ex" exchanges / prediction markets (kalshi,
polymarket, novig, prophetx); "eu" includes pinnacle (delayed public odds).

Strategy note: the consensus fair price across several books (weighted
toward sharper ones) is a strong benchmark.  A soft book pricing off that
consensus is the most reliable +EV source for most bettors — no model needed,
just line shopping and fast reaction.
"""

from __future__ import annotations

import os
from collections import defaultdict
from statistics import median
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlencode

from ..odds import american_to_decimal, decimal_to_american, devig
from . import FetchError, fetch_json

BASE = "https://api.the-odds-api.com/v4"
SPORT_KEYS = {
    "wnba": "basketball_wnba", "nba": "basketball_nba", "ncaab": "basketball_ncaab", "wncaab": "basketball_wncaab",
    "nfl": "americanfootball_nfl", "ncaaf": "americanfootball_ncaaf", "mlb": "baseball_mlb", "nhl": "icehockey_nhl",
}
FEATURED = ("h2h", "spreads", "totals")
WNBA_PROP_MARKETS = (
    "player_points", "player_rebounds", "player_assists", "player_threes", "player_blocks", "player_steals",
    "player_turnovers", "player_points_rebounds_assists", "player_points_rebounds", "player_points_assists",
    "player_rebounds_assists", "player_double_double", "player_first_basket",
)
# Books treated as sharper when building a weighted consensus.
SHARP_WEIGHTS = {"pinnacle": 3.0, "circasports": 3.0, "lowvig": 1.5, "betonlineag": 1.5, "kalshi": 1.5,
                 "polymarket": 1.5, "novig": 1.5, "prophetx": 1.2}


def _key() -> str:
    k = os.environ.get("ODDS_API_KEY")
    if not k:
        raise FetchError("ODDS_API_KEY is not set. Get a free key at the-odds-api.com and `export ODDS_API_KEY=...`.")
    return k


def sport_key(sport: str) -> str:
    return SPORT_KEYS.get(sport.lower(), sport)


def odds_url(sport: str, markets: Sequence[str] = FEATURED, regions: Sequence[str] = ("us",),
             api_key: Optional[str] = None, bookmakers: Optional[Sequence[str]] = None,
             odds_format: str = "american") -> str:
    q = {"apiKey": api_key or _key(), "markets": ",".join(markets), "oddsFormat": odds_format, "dateFormat": "iso"}
    if bookmakers:
        q["bookmakers"] = ",".join(bookmakers)
    else:
        q["regions"] = ",".join(regions)
    return f"{BASE}/sports/{sport_key(sport)}/odds?{urlencode(q)}"


def event_odds_url(sport: str, event_id: str, markets: Sequence[str], regions: Sequence[str] = ("us",),
                   api_key: Optional[str] = None, odds_format: str = "american") -> str:
    q = {"apiKey": api_key or _key(), "markets": ",".join(markets), "regions": ",".join(regions),
         "oddsFormat": odds_format, "dateFormat": "iso"}
    return f"{BASE}/sports/{sport_key(sport)}/events/{event_id}/odds?{urlencode(q)}"


def events_url(sport: str, api_key: Optional[str] = None) -> str:
    return f"{BASE}/sports/{sport_key(sport)}/events?{urlencode({'apiKey': api_key or _key()})}"


def normalize(payload) -> List[dict]:
    """Flatten an odds payload (list of events, or a single event) into rows.

    Row: event_id, commence_time, home, away, book, book_title, last_update,
    market, name (team / Over / Under / Yes), description (player for props),
    point, price (American, as returned).
    """
    events = payload if isinstance(payload, list) else [payload]
    rows = []
    for ev in events:
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                for oc in mk.get("outcomes", []):
                    rows.append({
                        "event_id": ev.get("id"), "commence_time": ev.get("commence_time"),
                        "home": ev.get("home_team"), "away": ev.get("away_team"),
                        "book": bk.get("key"), "book_title": bk.get("title"),
                        "last_update": mk.get("last_update") or bk.get("last_update"),
                        "market": mk.get("key"), "name": oc.get("name"), "description": oc.get("description"),
                        "point": oc.get("point"), "price": oc.get("price"),
                    })
    return rows


def _selection_key(r: dict) -> tuple:
    # Group outcomes that are directly comparable (same event, market, player, side and number).
    return (r["event_id"], r["market"], r.get("description"), r["name"], r.get("point"))


def _pair_key(r: dict) -> tuple:
    # Two-way market identity: spreads pair (+x, -x); totals/props pair over/under at same point.
    pt = r.get("point")
    if r["market"].startswith("spreads") or r["market"].startswith("alternate_spreads"):
        pt = abs(pt) if pt is not None else None
    return (r["event_id"], r["market"], r.get("description"), pt, r["book"])


def best_lines(rows: Iterable[dict]) -> List[dict]:
    """Best available price for every distinct selection across books."""
    best: Dict[tuple, dict] = {}
    for r in rows:
        if r.get("price") is None:
            continue
        k = _selection_key(r)
        d = american_to_decimal(r["price"])
        if k not in best or d > best[k]["decimal"]:
            best[k] = {**r, "decimal": d}
    return sorted(best.values(), key=lambda r: (r["event_id"], r["market"], str(r.get("description")), str(r["name"])))


def book_fair_probs(rows: Iterable[dict], method: str = "multiplicative") -> List[dict]:
    """Devig each book's own two-way markets.  Rows without a complete pair are skipped."""
    pairs: Dict[tuple, List[dict]] = defaultdict(list)
    for r in rows:
        if r.get("price") is not None:
            pairs[_pair_key(r)].append(r)
    out = []
    for rs in pairs.values():
        if len(rs) != 2:
            continue
        fair = devig([american_to_decimal(rs[0]["price"]), american_to_decimal(rs[1]["price"])], method)
        for r, p in zip(rs, fair):
            out.append({**r, "fair_prob": p})
    return out


def consensus(rows: Iterable[dict], method: str = "multiplicative", weights: Optional[Dict[str, float]] = None,
              exclude_books: Sequence[str] = ()) -> Dict[tuple, dict]:
    """Weighted consensus fair probability per selection (books devigged individually)."""
    w = {**SHARP_WEIGHTS, **(weights or {})}
    acc: Dict[tuple, List[tuple]] = defaultdict(list)
    for r in book_fair_probs(rows, method):
        if r["book"] in exclude_books:
            continue
        acc[_selection_key(r)].append((r["fair_prob"], w.get(r["book"], 1.0), r["book"]))
    out = {}
    for k, vals in acc.items():
        tw = sum(x[1] for x in vals)
        p = sum(x[0] * x[1] for x in vals) / tw
        out[k] = {"fair_prob": p, "books": [x[2] for x in vals], "n_books": len(vals),
                  "median_prob": median(x[0] for x in vals)}
    return out


def value_scan(rows: Sequence[dict], min_ev: float = 0.02, min_books: int = 3, method: str = "multiplicative",
               weights: Optional[Dict[str, float]] = None) -> List[dict]:
    """Prices that beat the leave-one-out consensus fair price by ``min_ev``.

    Leave-one-out: a book's own price is excluded from the consensus it is
    judged against, so a single stale book cannot validate itself.
    """
    rows = [r for r in rows if r.get("price") is not None]
    books = sorted({r["book"] for r in rows})
    found = []
    for b in books:
        cons = consensus([r for r in rows if r["book"] != b], method, weights)
        for r in rows:
            if r["book"] != b:
                continue
            c = cons.get(_selection_key(r))
            if not c or c["n_books"] < min_books:
                continue
            d = american_to_decimal(r["price"])
            ev = c["fair_prob"] * d - 1.0
            if ev >= min_ev:
                found.append({**r, "decimal": round(d, 4), "consensus_fair_prob": round(c["fair_prob"], 4),
                              "consensus_books": c["n_books"], "ev_pct": round(100 * ev, 2),
                              "fair_american": round(decimal_to_american(1 / c["fair_prob"]))})
    return sorted(found, key=lambda r: -r["ev_pct"])


def active_sports(group: Optional[str] = None, api_key: Optional[str] = None) -> List[dict]:
    """In-season sports (free endpoint: costs no credits), optionally one group such as 'Tennis'."""
    js, _ = fetch_json(f"{BASE}/sports/?" + urlencode({"apiKey": api_key or _key()}))
    return [s for s in js if group is None or s.get("group", "").lower() == group.lower()]


def get_odds(sport: str, markets: Sequence[str] = FEATURED, regions: Sequence[str] = ("us",),
             bookmakers: Optional[Sequence[str]] = None) -> dict:
    js, hdrs = fetch_json(odds_url(sport, markets, regions, bookmakers=bookmakers))
    return {"rows": normalize(js), "quota": {k: hdrs.get(k) for k in ("x-requests-remaining", "x-requests-used", "x-requests-last")}}


def get_event_odds(sport: str, event_id: str, markets: Sequence[str] = WNBA_PROP_MARKETS[:4],
                   regions: Sequence[str] = ("us",)) -> dict:
    js, hdrs = fetch_json(event_odds_url(sport, event_id, markets, regions))
    return {"rows": normalize(js), "quota": {k: hdrs.get(k) for k in ("x-requests-remaining", "x-requests-used", "x-requests-last")}}
