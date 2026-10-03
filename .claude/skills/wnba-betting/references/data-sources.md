# WNBA data sources

## Built-in commands (preferred — structured, testable)

| Need | Command | Notes |
|---|---|---|
| Schedule, scores, DK open/close lines | `python3 -m betlab fetch espn-scoreboard --league wnba --date 20261004` | no key; `spread` is HOME-perspective |
| One game: lines, box score, series | `python3 -m betlab fetch espn-summary --league wnba --event <id>` | `pickcenter` = DK open + close |
| Injuries (ESPN feed) | `python3 -m betlab fetch espn-injuries --league wnba` | cross-check the official report |
| Multi-book odds | `python3 -m betlab fetch odds --league wnba --regions us us2 us_ex --best` | needs `ODDS_API_KEY`; ~3 credits/call |
| Props for one event | `python3 -m betlab fetch odds --league wnba --event <odds-api-id> --markets player_points player_rebounds` | cost = markets returned × regions |
| +EV vs consensus (no model) | `python3 -m betlab fetch value --league wnba --min-ev 0.02` | leave-one-out consensus |
| Ratings / predictions | `python3 -m betlab wnba ratings` / `wnba predict ...` | bundled data through Oct 1, 2026 |

If a fetch fails with a network/403 error you are probably in a sandbox whose egress policy
blocks the host. Say so, then fall back to WebSearch/WebFetch and label every number with its
source and time.

## Official / primary

- **Injury report:** wnba.com/wnba-injury-report — due 5 p.m. local the day before (1 p.m. game
  day for the 2nd night of a back-to-back); Out / Doubtful / Questionable / Probable / Available.
- **Lineups:** released 30 minutes before tip.
- **stats.wnba.com** (`LeagueID=10`): `leaguegamelog`, `teamgamelogs`, `leaguedashteamstats`
  (`MeasureType=Advanced` for pace/ratings). Needs browser-like headers (`x-nba-stats-origin:
  stats`, `x-nba-stats-token: true`, Origin/Referer wnba.com); cloud IPs often time out; keep
  ≤ ~30 requests/minute.
- Team PR accounts and beat reporters for rest decisions and late scratches.

## Odds

- **The Odds API** — sport key `basketball_wnba`. Featured: `h2h`, `spreads`, `totals`.
  Props (event endpoint): `player_points`, `player_rebounds`, `player_assists`, `player_threes`,
  `player_blocks`, `player_steals`, `player_turnovers`, `player_points_rebounds_assists`,
  `player_points_rebounds`, `player_points_assists`, `player_rebounds_assists`,
  `player_double_double`, `player_first_basket`. Regions: `us` (DK, FD, MGM, BetRivers, Caesars*,
  Fanatics*, BetOnline, LowVig, Bovada), `us2` (theScore Bet, Hard Rock, ...), `us_ex` (Kalshi,
  Polymarket, Novig, ProphetX), `eu` (Pinnacle, delayed). *paid plans. bet365 US and Circa are
  not available. Free tier ≈ 500 credits/month; check `x-requests-remaining`.
- **Sharpest available references:** Pinnacle (sides/totals), prediction-market mids (Kalshi
  `KXWNBAGAME*` series, Polymarket) — an independent study found devigged exchange prices led
  sportsbooks by ~1 point of CLV in 2025–26. No book is reliably sharp on WNBA *props*.
- **Line history pages** (human-readable): Covers, TeamRankings, OddsShark, Action Network.

## Stats and models

- Basketball-Reference WNBA — box scores, advanced stats; **> 20 requests/minute gets you
  blocked for up to a day.**
- Her Hoop Stats — the deepest WNBA advanced stats (subscription).
- sportsdataverse / **wehoop** — R and Python loaders; GitHub data repos `wehoop-wnba-data`
  (parquet: schedules, team/player box, pbp, officials; 2003→) and `wehoop-wnba-raw` (raw ESPN
  JSON incl. `pickcenter` for the current season). This repo's bundled data comes from these.

## WebSearch query templates (when APIs are unavailable)

```
WNBA injury report <Month D, YYYY>
<team> injury update <date>            "<player> status" <team> <opponent>
<away> vs <home> odds <date>           <away> <home> spread total moneyline
WNBA odds today                        WNBA line movement <team> <date>
<player> props <date>                  <player> minutes restriction
WNBA playoffs <round> schedule <year>  <team> starting lineup tonight
```
Always record: source, timestamp, book, and whether the number is an opener or current.

## Freshness rules

| Data | Re-check |
|---|---|
| Lines you will bet | immediately before betting — never act on a price you saw > 15 minutes ago |
| Injury status | after the 5 p.m. local report and again ~30 minutes before tip |
| Lineups / rest | 30 minutes before tip (official release) |
| Ratings | after every completed game day (`wnba ratings --until <date>`) |
