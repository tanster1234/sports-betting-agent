# Bet Slip Tracker

A single-page bet tracker published as a claude.ai artifact. It shows each wager as a bet slip
(odds, stake, return, legs with kickoff times and fair chances), settles parlays from leg results,
and summarises net profit, record, return on stake, money in play, expected profit at fair odds,
an estimated balance per sportsbook and a running-total chart.

`bet-slip-tracker.html` is the exact page source that gets published. The publish step wraps it in
the document skeleton (doctype, head, body), so the file starts at `<title>` and has no `<html>`
or `<head>` tags of its own.

## Where the data lives

Bets are stored in the artifact's own database (the `db` runtime capability), not in this repo —
the same rule as the betlab ledger: betting history is personal and never committed. Opened
outside claude.ai the page renders but cannot load or save bets.

| Path | Contents |
|---|---|
| `meta/settings` | `startingBankroll: {DraftKings, FanDuel}` |
| `meta/legTally` | saved leg results `legs: {"<betId>#<leg>": {r, s, d, p}}` plus `won`/`lost`/`push`/`pending` counts; the page merges every leg into it, so deleting a ticket keeps its legs in the count |
| `meta/lessons` | post-mortem summary written by `betlab postmortem`: `legs`, `won`, `expected_wins`, `sd`, `calibration[]` (chance bucket, legs, expected wins ± sd, won), `lessons[]` (`tag`, `lost_legs`, `lesson`), `lost_by_tag`, `calibration_verdict`, `updatedAt` |
| `bets/<id>` | one document per wager (fields below) |

Bet fields: `placedAt`, `eventDate` (YYYY-MM-DD), `sport`, `tier` (free label: Safe, Medium,
Reach…), `book`, `type` (Parlay / Single / Same-game parlay), `stake`, `odds` (American, as
placed), `toReturn` (total return shown on the slip), `boosted`, `quotedOdds` (price before a
boost or line move), `fairProb` (devigged chance from the analysis, 0–1), `status` (`open`, `won`,
`lost`, `push`, `void`, `cashout`), `returned`, `settledAt`, `order`, `notes`, and `legs[]` with
`pick`, `price`, `kickoff` (ISO UTC), `fairProb`, `result` (`pending`, `won`, `lost`, `push`, `void`),
and for live tracking `spec` and `live` (see below); lost legs also get `postmortem: {tags, why, chance}`. Bets also get `liveUpdatedAt` and `needsReturn`.

A parlay settles itself from its legs: any lost leg → lost; every leg won → won at `toReturn`;
a push among otherwise-won legs asks for the amount the book actually paid.

The **Legs** card counts every leg on every ticket (won, lost, push/void, still to play), shows them
as one circle per leg grouped by ticket, the hit rate of decided legs, and how many parlays lost on a
single leg. Each slip also shows its own "2 of 5 legs won" line.

The **What the losses say** card (shown once `meta/lessons` exists) lists the post-mortem lessons
with how many lost legs each covers — red counts are ticket-building mistakes (the same player on
two tickets, legs needing opposite games) — and a calibration table: legs by the chance we gave
them, expected wins ± range, and actual wins. Each lost leg on its slip shows its tags and a short
"why".

## Live tracking

The page cannot reach outside sites, so live scores are written into its database from a Claude
Code session and the page shows them as they arrive (score, clock, and whether each leg is
winning right now). Each tracked leg carries a `spec` naming its ESPN game and market:

```json
{"league": "ncaaf", "event": "401858478", "market": "spread", "period": "game", "team": "WASH", "line": 7.5}
```

`market` is `ml`, `spread` or `total` (`side`: `over`/`under`); `period` is `game` (overtime
included) or `1h`; `team` is the ESPN abbreviation. Player props and touchdowns use `market: "player"`:

```json
{"league": "nfl", "event": "401872979", "market": "player", "player": "Bijan Robinson", "stat": "rushYards", "side": "over", "line": 59.5}
```

`stat` is `passYards`, `passTDs`, `rushYards`, `recYards`, `receptions`, `anytimeTD` (line 0.5), or for
basketball `points`, `rebounds`, `assists`, `threes`; they are graded from the ESPN game summary (box
score and scoring plays). A basketball player listed as not playing grades `void`; an NFL player with no
stats at the final grades `lost` with a note, because ESPN doesn't list inactives in the box score.
Legs keep being graded after their ticket has lost, so every leg ends with a result. Then, during games:

1. Read the bets with ArtifactData `list` (`collection: "bets"`, `out_dir: <dir>`).
2. `python3 -m betlab live --bets <dir>/bets --out <patches>` grades every leg from the ESPN
   scoreboard and writes one patch per bet (`legs[].live`, decided `legs[].result`, the derived
   `status`/`returned`/`settledAt`, `needsReturn`, `liveUpdatedAt`).
3. Write the patches with ArtifactData `batch` (`op: "update"`, `file_path`, `if_version` from step 1).

Repeat every few minutes while games are on. Totals and player overs settle as soon as the line is
passed; other legs settle when their period ends; a parlay with a pushed leg asks for the amount actually paid.
Grading logic lives in `betlab/live.py` (tests: `tests/test_live.py`).

## Publishing and updating

From Claude Code, publish the file with the Artifact tool and `capabilities: {"db": {}}`; pass
the existing artifact URL to update it in place (the database survives republishes). Seed or edit
bets with the ArtifactData tool (`bets` collection), or use the page's own form and buttons.
