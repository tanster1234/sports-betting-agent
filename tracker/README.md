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
| `bets/<id>` | one document per wager (fields below) |

Bet fields: `placedAt`, `eventDate` (YYYY-MM-DD), `sport`, `tier` (free label: Safe, Medium,
Reach…), `book`, `type` (Parlay / Single / Same-game parlay), `stake`, `odds` (American, as
placed), `toReturn` (total return shown on the slip), `boosted`, `quotedOdds` (price before a
boost or line move), `fairProb` (devigged chance from the analysis, 0–1), `status` (`open`, `won`,
`lost`, `push`, `void`, `cashout`), `returned`, `settledAt`, `order`, `notes`, and `legs[]` with
`pick`, `price`, `kickoff` (ISO UTC), `fairProb`, `result` (`pending`, `won`, `lost`, `push`).

A parlay settles itself from its legs: any lost leg → lost; every leg won → won at `toReturn`;
a push among otherwise-won legs asks for the amount the book actually paid.

## Publishing and updating

From Claude Code, publish the file with the Artifact tool and `capabilities: {"db": {}}`; pass
the existing artifact URL to update it in place (the database survives republishes). Seed or edit
bets with the ArtifactData tool (`bets` collection), or use the page's own form and buttons.
