---
name: responsible-gambling
description: >
  Recognize and respond to problem-gambling warning signs during any betting conversation —
  chasing losses ("I need to win it back"), betting rent/bill money or borrowed money, escalating
  stakes, hiding bets, betting to escape stress, distress or anger after a bad beat, wanting to
  stop but not being able to — with a calm, supportive response, practical limits, and current
  US help resources (1-800-MY-RESET, 1-800-522-4700, text 800GAM, state lines, self-exclusion).
  Use whenever these signs appear, even mid-analysis, and when users ask about limits, cooling
  off, self-exclusion or getting help.
---

# Responsible gambling

Analysis skills in this repo exist to make betting *more disciplined*, never to push anyone to
bet more. When the conversation shows harm, the person matters more than the pick.

## Warning signs (any one is enough to pause the analysis)

- Chasing: "I have to win back today's losses", raising stakes after losses, "one more bet".
- Money stress: betting money needed for rent, bills, food; borrowing or using credit to bet.
- Loss of control: wanting to stop and not being able to; betting longer or more than planned.
- Secrecy or conflict: hiding bets from family, lying about losses.
- Mood: betting to escape anxiety/depression; anger, panic or despair after losses.
- Tilt in the data: `python3 -m betlab report` → `tilt.flag` true (stakes after losing days
  ≥ 1.25× stakes after winning days), stop-loss breached, rapidly rising bet frequency.

## How to respond

1. **Pause the picks.** Don't provide new bets, parlays or "safer" plays to someone who is
   chasing or distressed — a recommendation in that moment reinforces the chase.
2. **Be direct and kind.** Acknowledge the feeling without judgement ("Losing days like this are
   rough, and wanting to get it back is a very normal reaction"). Say plainly that chasing is the
   pattern that turns bad days into bad months, and that the math doesn't change because of
   yesterday.
3. **Offer concrete options**: stop for today; set a deposit/loss/time limit in the sportsbook
   app; take a cool-off (24 h – 30 days); self-exclusion; talk to someone.
4. **Share resources** (below) when signs are more than a single frustrated comment.
5. **If there is any mention of self-harm or crisis**, prioritise safety: in the US call or text
   **988** (Suicide & Crisis Lifeline), or local emergency services.
6. Resume analysis only if the user wants to *and* it isn't feeding a chase — and then with the
   normal stop-loss and staking rules, never "catch-up" stakes.

## Resources (United States, as of 2026)

| Resource | Contact |
|---|---|
| National Problem Gambling Helpline (NCPG) | **1-800-MY-RESET** (1-800-697-3738) · 1-800-522-4700 still active · text **800GAM** · chat at ncpgambling.org/chat |
| 1-800-GAMBLER | operated by the Council on Compulsive Gambling of New Jersey (NJ and other states still list it) |
| New York | 877-8-HOPENY or text HOPENY (467369) |
| Massachusetts | (800) 327-5050 · gamblinghelplinema.org |
| Connecticut | 888-789-7777 · ccpg.org |
| Maryland | mdgamblinghelp.org |
| Gamblers Anonymous | gamblersanonymous.org (meetings) |
| Crisis / suicidal thoughts | call or text **988** |

Practical tools: in-app deposit, wager and time limits; cool-off periods; state self-exclusion
programs (run by each state's gaming regulator — search "<state> sports betting
self-exclusion"); blocking software (e.g. Gamban, BetBlocker); bank gambling-transaction blocks
offered by many card issuers.

Legal age for sports betting is 21 in most US states (18 in a few jurisdictions, e.g. DC, KY,
NH, WY). Never help someone underage bet or evade limits or exclusions.

## Footer for betting outputs

Every bet card ends with:
`21+. Bet only what you can afford to lose. Gambling problem? Call 1-800-MY-RESET (1-800-697-3738)
or 1-800-522-4700, or text 800GAM.`
