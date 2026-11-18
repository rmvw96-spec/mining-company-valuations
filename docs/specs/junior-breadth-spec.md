# Junior breadth: how much of the junior funds is in an uptrend

Instructions for Claude Code. Roadmap item 2b. Follow CLAUDE.md.

## Goal

The junior timing signal waits for gold and GDX to be above their 200-day averages. An index can turn up on a
few large names while most juniors keep falling. Add a breadth confirmation: **the share of SGDJ and of COPJ, by
fund weight, in holdings trading above their own 200-day average.**

We already hold both funds' holdings (`data/holdings.csv`) and their Yahoo symbols, so no new data source is
needed. GDXJ's holdings aren't needed.

## Design

- `signals.fetch()` also downloads ~1 year of daily closes for each company in SGDJ and COPJ (about 140
  symbols; use `yahoo.pmap` with the existing pacing). Cache in `cache/signals/breadth/`. Symbols that fail are
  left out of both numerator and denominator; report the covered weight.
- New signals (tier "Juniors"):
  - `breadth_sgdj`: Σ weight of holdings above their 200-day average ÷ Σ weight of holdings with 200 days of data.
  - `breadth_copj`: the same for COPJ.
  - kind `high_low` with thresholds, as a starting point, `[0.6, 0.3]`: "Broad uptrend" at 60%+, "Narrow:
    most juniors still falling" under 30%, "Mixed" between. Comment the thresholds as provisional until the
    backtest has looked at them.
- `junior_timing` stays as it is (it's a formula on the Sheet). The Model portfolio timing column for
  "Growth: developers" adds `breadth_sgdj` (or `breadth_copj` for copper rows: needs the "Bucket|Metal" key form
  already supported in `[signals.timing]`).
- Signals tab: two new rows via `setup-sheet` (the installer already adds missing signal rows by key; check it
  does, and add that if not).

## Backtest

Historical breadth needs past holdings, which we don't have. Approximate it with today's holdings (survivorship
bias: today's holdings are the survivors) and say so in the backtest report. Live values start accumulating in
Signal history from the day this lands.

## Tests (offline)

- Breadth on synthetic series: weights, the 200-day minimum, missing symbols excluded from both sides.
- Status boundaries, and the matching Sheet formula (the existing status/formula tests cover new keys
  automatically; check they do).

## Done when

Two new rows on the Signals tab, written daily on GitHub, with coverage of at least 90% of each fund's
company weight (report it).
