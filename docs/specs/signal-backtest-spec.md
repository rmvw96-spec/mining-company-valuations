# Signal backtest, and an industry AISC history

Roadmap 2a · Status: Built Nov 18, 2026 (the Q3 2026 AISC row is pending) · Depends on: 1a
([signal-history-spec.md](signal-history-spec.md)), market signals

Instructions for Claude Code. Follow CLAUDE.md.

## Goal

The Signals tab's thresholds are judgement calls. Test each signal on history: when it said "lean in", did its tier
do better over the following months than when it didn't? The report helps the user decide which signals to trust
and where thresholds sit. **The code reports; it never changes a threshold.** The industry AISC also becomes a dated
record instead of one typed number, so the AISC margin can be tested.

## Scope

- **In:** a dated industry AISC table, month-end signal values from truncated history, forward outcomes per tier,
  and a threshold sweep.
- **Out:** signals with no past inputs (fund FCF yields, the royalty median), reported as skipped; optimising
  thresholds (on one 25-year period that is fitted noise).

## Design

- **Industry AISC** (`data/research/industry_aisc.csv`: `quarter`, `aisc_usd_oz`, `published`, `source`, `note`):
  the World Gold Council's figures **as first published** (what a point-in-time test should use; the revised series
  is only on a chart page), from 2021Q1, with no 2021Q3 or Q4; `note` marks quarters a later report implies were
  revised. Never estimated. `signals.compute()` uses the latest quarter published by its date, and Python writes it
  to the Signals `industry_aisc` input row; the table is the only record (no settings override).
- **Signal values:** at each month-end, `compute()` on series truncated at that date (the shared helper from signal
  history). Series start dates are in `[signals]` (GDX 2006, GDXJ 2009, SIL 2010, SILJ 2012, COPX 2010, DFII10
  2003). Miners-against-metal percentiles count once the ETF has 5 years. Full daily histories are cached in
  `cache/signals/backtest/`.
- **Outcomes** over 3, 6 and 12 months:

| Signal | Outcome |
|---|---|
| Gold/silver ratio | Silver minus gold |
| Real yield, dollar 12-month change | Gold |
| SPY drawdown | Gold, and an equal-weight RGLD, FNV, WPM basket (total return) |
| Metal vs diesel; miners vs metal percentile | Miner ETF minus metal (GDX−gold, SIL−silver, COPX−copper) |
| AISC margin (bucketed by `[signal_backtest] aisc_margin_share`, as its status is text) | GDX minus gold |
| Uptrends, junior timing, junior breadth | GDXJ and SILJ; GDXJ minus GDX |
| Tax-loss window | GDXJ from the window to the end of February |

- **Report**, per signal and status bucket against all months: count, mean and median forward return, hit rate.
  Significance uses non-overlapping windows; a bucket with fewer than 12 independent observations is "too few to
  judge". The sweep (`[signal_backtest.sweep]`) repeats the table at a few thresholds around the current one, to
  show plateaus or knife edges.
- **Command:** `backtest-signals` → `out/backtest-signals/` (`report.txt`, `signals_history.csv`,
  `outcomes.csv`); offline after the first download, `--refresh` to download again.

## Acceptance criteria

- [x] A1. No lookahead: a spike after the date changes nothing. —
  `tests/test_signal_backtest.py::test_no_lookahead_a_spike_after_the_date_changes_nothing`
- [x] A2. The AISC used is the latest published by the date, and the margin is blank before the table starts. —
  `tests/test_signal_backtest.py::test_aisc_used_is_the_latest_published_by_the_date`,
  `tests/test_signal_backtest.py::test_compute_uses_the_dated_aisc_and_leaves_the_margin_blank_before_it`
- [x] A3. Forward returns and differences, the tax-loss window, and the AISC share buckets. —
  `tests/test_signal_backtest.py::test_forward_returns_and_differences`,
  `tests/test_signal_backtest.py::test_tax_loss_returns_from_late_year_to_february`,
  `tests/test_signal_backtest.py::test_aisc_share_buckets`
- [x] A4. Non-overlapping windows, the "too few" flag, and bucket statistics against a baseline. —
  `tests/test_signal_backtest.py::test_non_overlapping_windows_and_the_too_few_flag`,
  `tests/test_signal_backtest.py::test_bucket_stats_with_a_baseline`
- [x] A5. The sweep settings name real thresholds and include the current value. —
  `tests/test_signal_backtest.py::test_sweep_settings_name_real_thresholds`
- [x] A6. The command writes its report offline. —
  `tests/test_signal_backtest.py::test_run_writes_the_report_offline`
- [x] A7. The AISC table is well formed (unique ordered quarters, positive values, a source on every row). —
  `tests/test_data_files.py::test_industry_aisc_table`
- [x] A8. README gives what the backtest answers and its limits; CLAUDE.md says the table is the record.
- [ ] A9. The WGC's Q3 2026 figure is in the table (due early December 2026).
- [ ] A10. (user) The user has read the report; any threshold they change is changed in settings and Signals G:H
  together, and `signals` reports "Sheet and Python statuses agree".

## Decisions

- First-published AISC figures, with the table as the only record (2026-11-18).
- Royalty outcomes use an equal-weight RGLD, FNV, WPM basket rather than GDX (2026-11-18).
