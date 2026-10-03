"""betlab — deterministic, tested math for sports-betting analysis.

Everything here is pure Python standard library so the skills can call it
from any environment (Claude Code, a laptop, CI) without installing anything.
The skills in ``.claude/skills`` delegate every number to this package instead
of doing odds math "in their head".

Modules
-------
odds          price conversions, vig removal (5 methods), EV, breakeven
kelly         single / push-aware / simultaneous Kelly, staking plans with caps
distributions normal, Poisson, negative-binomial helpers (no scipy)
markets       spread/total/moneyline/alt-line/half pricing from a margin model
props         player-prop distributions with WNBA-calibrated dispersion
parlay        independent and correlated (Gaussian copula) parlay pricing
clv           closing-line value in price, probability and point terms
series        best-of-N playoff series pricing with home/away formats
ratings       Kalman point-rating model for margins and totals
wnba          WNBA presets, team metadata, bundled-data loaders
ledger        append-only, hash-chained bet ledger (place/close/settle/void)
report        performance, CLV significance, calibration, drawdown reports
backtest      walk-forward backtests with no look-ahead
fetch         ESPN + The Odds API clients and offline parsers
"""

__version__ = "1.0.0"
