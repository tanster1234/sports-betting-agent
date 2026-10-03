"""Append-only, hash-chained bet ledger (JSONL).

Design borrowed from the "transactions audit trail" idea in sklls/betting-app-skill,
adapted for a single bettor:

* Every action is an *event* appended to a JSONL file: place, close, settle,
  void, note.  Nothing is edited in place; current bet state is a replay.
* Each event stores the SHA-256 of the previous event (``prev``) and of
  itself (``hash``), so ``verify()`` detects hand edits or truncation.
* Settling twice is refused unless the new event is marked as a correction
  with a reason — the same "no double payout" guarantee a wallet needs.
* Prices are parsed once (American or decimal) and both forms are stored, so
  reports never re-derive odds from strings.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .odds import decimal_to_american, devig, parse_price

TOTAL_LIKE = {"total", "team_total", "period_total"}
SPREAD_LIKE = {"spread", "period_spread"}


def infer_side(market: str, selection: str) -> Optional[str]:
    """'over'/'under' for totals and props when the selection text says so."""
    s = selection.strip().lower()
    if s.startswith(("over", "o ")) or s.endswith(" over") or " over " in f" {s} ":
        return "over"
    if s.startswith(("under", "u ")) or s.endswith(" under") or " under " in f" {s} ":
        return "under"
    return None

MARKETS = {"spread", "total", "moneyline", "team_total", "prop", "future", "parlay", "sgp", "teaser",
           "period_spread", "period_total", "period_moneyline", "series", "other"}
RESULTS = {"win", "loss", "push", "void", "half_win", "half_loss"}


class LedgerError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _digest(event: dict) -> str:
    body = {k: v for k, v in event.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def pnl_for(result: str, stake: float, decimal: float) -> float:
    if result == "win":
        return stake * (decimal - 1.0)
    if result == "loss":
        return -stake
    if result in ("push", "void"):
        return 0.0
    if result == "half_win":
        return stake * (decimal - 1.0) / 2.0
    if result == "half_loss":
        return -stake / 2.0
    raise LedgerError(f"unknown result {result!r}; use one of {sorted(RESULTS)}")


class Ledger:
    def __init__(self, path: str):
        self.path = Path(path)

    # ------------------------------------------------------------------
    def events(self) -> List[dict]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path) as f:
            for n, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise LedgerError(f"{self.path}:{n}: corrupt JSON ({exc})") from exc
        return out

    def _append(self, event: dict) -> dict:
        evs = self.events()
        event = dict(event)
        event.setdefault("ts", _now())
        event["prev"] = evs[-1]["hash"] if evs else None
        event["hash"] = _digest(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return event

    def verify(self) -> dict:
        prev = None
        for i, ev in enumerate(self.events()):
            if ev.get("prev") != prev:
                return {"ok": False, "index": i, "error": "broken chain (event removed or reordered)"}
            if _digest(ev) != ev.get("hash"):
                return {"ok": False, "index": i, "error": "hash mismatch (event edited)"}
            prev = ev["hash"]
        return {"ok": True, "events": len(self.events())}

    # ------------------------------------------------------------------
    def place(self, *, sport: str, event: str, market: str, selection: str, price, stake: float,
              book: Optional[str] = None, line: Optional[float] = None, model_prob: Optional[float] = None,
              model_push_prob: Optional[float] = None, market_prob: Optional[float] = None,
              event_date: Optional[str] = None, tier: Optional[str] = None, units: Optional[float] = None,
              tags: Optional[List[str]] = None, notes: Optional[str] = None, bet_id: Optional[str] = None,
              placed_at: Optional[str] = None, side: Optional[str] = None) -> dict:
        market = market.lower()
        if market not in MARKETS:
            raise LedgerError(f"market must be one of {sorted(MARKETS)}")
        stake = float(stake)
        if stake <= 0:
            raise LedgerError("stake must be > 0")
        d = parse_price(price)
        for name, p in (("model_prob", model_prob), ("market_prob", market_prob)):
            if p is not None and not 0 < float(p) < 1:
                raise LedgerError(f"{name} must be in (0,1)")
        bid = bet_id or uuid.uuid4().hex[:8]
        if bid in self._state():
            raise LedgerError(f"bet id {bid} already exists")
        ev = {
            "type": "place", "bet_id": bid, "sport": sport.upper(), "event": event, "market": market,
            "selection": selection, "side": (side or infer_side(market, selection)),
            "line": None if line is None else float(line), "book": book,
            "price_decimal": round(d, 6), "price_american": round(decimal_to_american(d), 2),
            "stake": round(stake, 2), "units": None if units is None else float(units),
            "model_prob": None if model_prob is None else float(model_prob),
            "model_push_prob": None if model_push_prob is None else float(model_push_prob),
            "market_prob": None if market_prob is None else float(market_prob),
            "event_date": event_date, "tier": tier, "tags": tags or [], "notes": notes,
            "placed_at": placed_at or _now(),
        }
        if model_prob is not None:
            pp = float(model_push_prob or 0.0)
            ev["ev_at_placement"] = round(float(model_prob) * (d - 1.0) - max(0.0, 1 - float(model_prob) - pp), 6)
        return self._append(ev)

    def close(self, bet_id: str, close_price, close_line: Optional[float] = None,
              close_other_price=None, devig_method: str = "multiplicative") -> dict:
        st = self._require(bet_id)
        if st.get("status") == "void":
            raise LedgerError("cannot record a close for a voided bet")
        dc = parse_price(close_price)
        ev = {"type": "close", "bet_id": bet_id, "close_decimal": round(dc, 6),
              "close_american": round(decimal_to_american(dc), 2),
              "close_line": None if close_line is None else float(close_line)}
        d_bet = st["price_decimal"]
        same_number = close_line is None or st.get("line") is None or float(close_line) == float(st["line"])
        if close_other_price is not None:
            do = parse_price(close_other_price)
            p_close = devig([dc, do], devig_method)[0]
            ev["close_other_decimal"] = round(do, 6)
            ev["close_fair_prob"] = round(p_close, 6)
            if same_number:
                ev["clv_ev"] = round(p_close * d_bet - 1.0, 6)
                ev["clv_prob"] = round(p_close - 1.0 / d_bet, 6)
        if same_number:
            ev["clv_price_only"] = round(d_bet / dc - 1.0, 6)
        else:
            ev.update(self._moved_line_clv(st, dc, close_line, close_other_price, devig_method))
        return self._append(ev)

    @staticmethod
    def _moved_line_clv(st: dict, dc: float, close_line: float, close_other_price, devig_method: str) -> dict:
        """Points CLV with the right sign, plus model-based CLV EV when possible."""
        from .clv import clv_spread_points, clv_total_points
        from .markets import SPORT_DEFAULTS

        line, market, side = float(st["line"]), st["market"], st.get("side")
        out: dict = {}
        sp = SPORT_DEFAULTS.get(str(st.get("sport", "")).upper(), {})
        if market in TOTAL_LIKE or side in ("over", "under"):
            if side in ("over", "under"):
                out["clv_points"] = round((close_line - line) if side == "over" else (line - close_line), 3)
                if close_other_price is not None and market in TOTAL_LIKE and sp.get("total_sigma"):
                    do = parse_price(close_other_price)
                    over_p, under_p = (dc, do) if side == "over" else (do, dc)
                    r = clv_total_points(line, st["price_american"], side, close_line,
                                         decimal_to_american(over_p), decimal_to_american(under_p),
                                         sp["total_sigma"], devig_method)
                    out["clv_ev"] = round(r["clv_ev"], 6)
            else:
                out["line_moved"] = round(line - close_line, 3)
                out["warning"] = "side unknown (selection should start with Over/Under); points CLV not signed"
        elif market in SPREAD_LIKE:
            out["clv_points"] = round(line - close_line, 3)   # bigger handicap for you = better
            if close_other_price is not None and sp.get("margin_sigma"):
                r = clv_spread_points(line, st["price_american"], close_line, decimal_to_american(dc),
                                      decimal_to_american(parse_price(close_other_price)), sp["margin_sigma"],
                                      str(st.get("sport")).upper() if sp.get("ot_minutes") else None, devig_method)
                out["clv_ev"] = round(r["clv_ev"], 6)
        else:
            out["line_moved"] = round(line - close_line, 3)
        return out

    def settle(self, bet_id: str, result: str, correction_reason: Optional[str] = None,
               settled_at: Optional[str] = None) -> dict:
        result = result.lower()
        if result not in RESULTS:
            raise LedgerError(f"result must be one of {sorted(RESULTS)}")
        st = self._require(bet_id)
        if st.get("status") in RESULTS and not correction_reason:
            raise LedgerError(f"bet {bet_id} already settled as {st['status']}; pass correction_reason to re-grade")
        pnl = pnl_for(result, st["stake"], st["price_decimal"])
        ev = {"type": "settle", "bet_id": bet_id, "result": result, "pnl": round(pnl, 2),
              "settled_at": settled_at or _now()}
        if correction_reason:
            ev["correction"] = correction_reason
        return self._append(ev)

    def void(self, bet_id: str, reason: str) -> dict:
        """Void a bet (postponed game, palpable error): stake refunded, pnl 0."""
        st = self._require(bet_id)
        ev = {"type": "settle", "bet_id": bet_id, "result": "void", "pnl": 0.0,
              "settled_at": _now(), "reason": reason}
        if st.get("status") in RESULTS:
            ev["correction"] = f"voided after settlement: {reason}"
        return self._append(ev)

    def note(self, bet_id: str, text: str) -> dict:
        self._require(bet_id)
        return self._append({"type": "note", "bet_id": bet_id, "text": text})

    # ------------------------------------------------------------------
    def _state(self) -> Dict[str, dict]:
        bets: Dict[str, dict] = {}
        for ev in self.events():
            t, bid = ev.get("type"), ev.get("bet_id")
            if t == "place":
                b = {k: v for k, v in ev.items() if k not in ("type", "prev", "hash", "ts")}
                b["status"] = "open"
                b["pnl"] = None
                b["notes_log"] = []
                bets[bid] = b
            elif bid in bets:
                b = bets[bid]
                if t == "close":
                    for k, v in ev.items():
                        if k not in ("type", "bet_id", "prev", "hash", "ts"):
                            b[k] = v
                elif t == "settle":
                    b["status"] = ev["result"]
                    b["pnl"] = ev["pnl"]
                    b["settled_at"] = ev.get("settled_at")
                    if ev.get("correction"):
                        b.setdefault("corrections", []).append(ev["correction"])
                elif t == "note":
                    b["notes_log"].append(ev.get("text"))
        return bets

    def _require(self, bet_id: str) -> dict:
        st = self._state()
        if bet_id not in st:
            raise LedgerError(f"no bet with id {bet_id}")
        return st[bet_id]

    def bets(self, status: Optional[str] = None) -> List[dict]:
        rows = list(self._state().values())
        if status == "open":
            rows = [b for b in rows if b["status"] == "open"]
        elif status == "settled":
            rows = [b for b in rows if b["status"] in RESULTS]
        return rows
