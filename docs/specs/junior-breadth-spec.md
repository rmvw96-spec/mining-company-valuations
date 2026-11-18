# Junior breadth: how much of the junior funds is in an uptrend

Instructions for Claude Code. Roadmap item 2b. Follow CLAUDE.md.

**Status: built** (branch `junior-breadth`). Where the build differs from the plan below:
- Holdings and Yahoo symbols come from the Holdings tab (A, B, C, P) when there's a Sheet (so it works on
  GitHub, where `data/` derived files don't exist), else from `data/derived/holdings_detail.csv`. The list used
  is saved with the prices in `cache/signals/breadth/holdings.json`, so backfills and the backtest use it.
- Prices: 5 years of daily closes (`daily_range`), not 1, so Signal history and the backtest reach back to
  Sep 2022. A holding also has to have traded in the last 10 days to count.
- Silver developers use SGDJ's breadth (there's no junior silver fund in the list); copper developers COPJ's.
- `setup-sheet` didn't add missing signal rows to an existing tab; it now inserts them (built with 2c).
- Coverage on Nov 18, 2026: SGDJ 100%, COPJ 92% (Minsur and Atlas Consolidated have no Yahoo symbol).
- Backtest: Sep 2022 to Oct 2026, every bucket "too few to judge". The thresholds stay provisional.

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
