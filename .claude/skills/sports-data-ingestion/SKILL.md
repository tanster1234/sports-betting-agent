---
name: sports-data-ingestion
description: >
  Fetch current, timestamped betting inputs before any analysis: schedules and scores (ESPN API,
  no key), injury reports, opening vs current lines, multi-book odds and player props (The Odds
  API, incl. Pinnacle and Kalshi/Polymarket), best-price line shopping, consensus no-vig prices
  and +EV value scans — with WebSearch/WebFetch fallbacks when APIs are blocked. Use whenever an
  answer depends on today's games, lines, injuries, lineups, weather, starting pitchers or goalies,
  for any sport including WNBA, and whenever the user asks "what are the odds/lines for...".
---

# Sports data ingestion

Bad inputs are the most common reason a "good" bet is bad. Get data in this order, timestamp
everything, and never act on a stale price.

## 1. Schedule, scores, and posted lines (ESPN — free, no key)

```bash
python3 -m betlab fetch espn-scoreboard --league wnba --date 20261004
python3 -m betlab fetch espn-summary --league wnba --event 401918030     # box score + pickcenter
python3 -m betlab fetch espn-injuries --league wnba
```
Leagues: `wnba nba ncaab wncaab nfl ncaaf mlb nhl`. Odds come from ESPN's current provider
(DraftKings in 2026) with **open and close/current** spread, total and moneyline. ESPN's `spread`
is from the **home** team's perspective. The parser also handles the 2024 ESPN BET schema.

## 2. Multi-book odds (The Odds API — needs `ODDS_API_KEY`)

```bash
export ODDS_API_KEY=...        # free tier ~500 credits/month
python3 -m betlab fetch odds --league wnba --regions us us2 --best          # h2h, spreads, totals
python3 -m betlab fetch odds --league wnba --regions us eu us_ex --best     # + Pinnacle + exchanges
python3 -m betlab fetch odds --league wnba --event <id> --markets player_points player_rebounds
python3 -m betlab fetch value --league wnba --min-ev 0.02                   # soft book vs consensus
```
Cost: featured markets = markets × regions per call; event (props) calls = markets returned ×
regions. The `quota` field reports `x-requests-remaining` — check it before looping.
`value` devigs each book's two-way market, builds a sharp-weighted, **leave-one-out** consensus
(Pinnacle ×3, exchanges/low-vig books ×1.5) and lists prices that beat it — the most reliable
model-free +EV source.

## 3. Injuries, lineups, starters

| Sport | Must confirm | Where / when |
|---|---|---|
| WNBA | Out/Questionable list; minutes restrictions; lineups | Official report 5 p.m. local day before (1 p.m. game day on B2B 2nd night); lineups 30 min pre-tip |
| NBA | Same; rest decisions on B2Bs | Official report (5 p.m. local day before, updated); beat writers |
| NFL | QB/OL status | Wed–Fri practice reports; inactives 90 min before kickoff |
| MLB | Starting pitcher, lineup, weather | Probable starters; lineups ~2–4 h before first pitch |
| NHL | Starting goalie | Morning skate / ~1 h before puck drop |
| College | Injuries are thinly reported | Beat writers, school releases |

## 4. When the network is blocked

`betlab fetch` raises a `FetchError` that says so (common in sandboxed cloud sessions). Then:
1. Use WebSearch / WebFetch with the templates below; prefer primary sources (league site, team
   accounts) for injuries and two or more odds pages for lines.
2. Label every number: `ATL -4.5 (-110) · DraftKings via covers.com · 2026-10-04 10:12 ET`.
3. If you can't get a current price, produce fair prices and "bet at X or better" thresholds
   instead of recommendations.
4. Tell the user which hosts failed — they may be able to allow them in their environment.

```
<league> odds today <date>                 <away> vs <home> odds spread total
<team> injury report <date>                <player> status tonight
<league> line movement <team> <date>       <league> opening lines <date>
<player> props <date>                      <pitcher/goalie> starting <date>
<city> weather <game time> wind            <league> referee assignments <date>
```

## 5. Snapshot format (hand this to the analysis)

```
GAME  NY @ ATL · WNBA semis G1 · 2026-10-04 15:00 ET · status pre
LINES (best / book / time)   spread ATL -4.5 -105 FD 10:12 · total 168.5 o-108 FD · ML ATL -185 MGM
OPEN → NOW (DK)              ATL -2.5 → -4.5 · total 166.5 → 168.5 · ML -150 → -190
CONSENSUS NO-VIG             ATL cover 50.6% · over 50.2% · ATL win 64.1%  (5 books, Pinnacle incl.)
INJURIES                     ATL: none · NY: <player> questionable (ankle), 5 PM report
REST / SCHEDULE              ATL 3 days · NY 4 days · no travel back-to-back
NOTES                        lineups due 14:30 ET
```

## Freshness rules

- Lines: re-pull immediately before recommending; > 15 minutes old = stale.
- Injuries: after the official report, and again at lineup release.
- Never mix a morning injury status with an afternoon line (the line may already reflect news
  you haven't seen).
- Prefer the timestamped source when two sources disagree; if they still conflict, PASS.
