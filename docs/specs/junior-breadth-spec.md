# Junior breadth: how much of the junior funds is in an uptrend

Roadmap 2b · Status: Built Nov 18, 2026 · Depends on: 1a (Signal history), market signals

Instructions for Claude Code. Follow CLAUDE.md.

## Goal

The junior timing signal waits for gold and GDX to be above their 200-day averages, but an index can turn up on a
few large names while most juniors keep falling. Confirm it with breadth: **the share of SGDJ and of COPJ, by fund
weight, in holdings trading above their own 200-day average.**

## Scope

- **In:** two signals from the funds' own holdings and their Yahoo symbols (no new data source).
- **Out:** GDXJ's holdings; past fund holdings (not available, so history uses today's list).

## Design

- **Holdings:** from the Holdings tab (A, B, C, P) when there is a Sheet (so it runs on GitHub), else
  `data/derived/holdings_detail.csv`. The list is saved with the prices in `cache/signals/breadth/holdings.json`.
- **Prices:** 5 years of daily closes per holding (`daily_range`, `yahoo.pmap` pacing), cached in
  `cache/signals/breadth/`.
- **Signals** (tier "Juniors", kind `high_low`): `breadth_sgdj` and `breadth_copj` = Σ weight of holdings above
  their 200-day average ÷ Σ weight of holdings with 200 days of data that traded in the last 10 days. Symbols
  that fail, are short or stale are left out of both sides; the report gives the covered weight.
- **Thresholds** `[0.6, 0.3]` (provisional; settings comment): "Broad uptrend" at 60%+, "Narrow: most juniors
  still falling" under 30%, "Mixed" between.
- **Model portfolio W:** "Growth: developers" adds `breadth_sgdj`; copper developers (`Growth: developers|Copper`)
  `breadth_copj`; silver developers use SGDJ's (there's no junior silver fund).
- **Sheet:** `setup-sheet` inserts the two rows (it inserts any missing signal row by key).
- **History and backtest:** computed with today's holdings, so survivorship bias applies and the backtest report
  says so; Signal history reaches back to Sep 2022.

## Acceptance criteria

- [x] A1. Breadth weights holdings and reports coverage. — `tests/test_breadth.py::test_weights_and_coverage`
- [x] A2. Missing, short and stale series are left out of both sides. —
  `tests/test_breadth.py::test_missing_short_and_stale_series_leave_both_sides`
- [x] A3. Statuses at the thresholds. — `tests/test_breadth.py::test_compute_statuses_and_thresholds`
- [x] A4. Backfills truncate the series to each date. — `tests/test_breadth.py::test_truncate_cuts_the_breadth_series`
- [x] A5. Holdings come from the Sheet when there is one, and the list is kept with the closes. —
  `tests/test_breadth.py::test_holdings_from_the_sheet`,
  `tests/test_breadth.py::test_fetch_keeps_the_list_and_the_closes`
- [x] A6. Each fund's covered company weight is at least 90%. — `signals` report, Nov 18, 2026: SGDJ 100%, COPJ
  92% (Minsur and Atlas Consolidated have no Yahoo symbol).
- [x] A7. Backtested Sep 2022 to Oct 2026: every bucket "too few to judge", so the thresholds stay provisional. —
  `backtest-signals`

## Decisions

- Thresholds stay provisional until the backtest has enough observations (2026-11-18).
