# Signal history: record every run on the Sheet

Roadmap 1a · Status: Built Nov 18, 2026 · Depends on: market signals

Instructions for Claude Code. Follow CLAUDE.md.

## Goal

Each run overwrites Signals E:F, so yesterday's readings are lost. Record them on the Sheet (the scheduled run is on
GitHub, where `out/` is thrown away), so each signal can be charted, a status change dated, and royalty P/NAV and
developers' cash runway tracked between reports (used by [royalty-history-spec.md](royalty-history-spec.md) and the
alerts).

## Scope

- **In:** a Signal history tab (wide, one row per date), a Company history tab (long), and a backfill of the market
  signals.
- **Out:** backfilling FCF yields or company metrics (no past inputs); archiving old years (note in CLAUDE.md if the
  tab passes 100,000 rows).

## Design

- **Signal history:** A `Date` (run date in New York), B `Source` (`live` or `backfill`), then one column per signal
  key, found by its header, so new keys go on the right and columns can be reordered. Values only (statuses are
  recomputed from values and thresholds), written raw.
- **Company history:** `Date`, `Holding` (PNAV inputs B), `Yahoo` (AP), `Metric`, `Value`. Royalty rows record
  `independent_pnav` (AJ) and `price_usd` (C); developer rows (a developer check in BE) `ev_per_aueq_oz` (BB),
  `months_of_cash` (BC) and `cash_share` (BD). About 40 rows a day.
- **Writing** (`minerval/history.py`, at the end of `signals.run()`): find rows by date; a second run on the same
  date replaces that date's rows, a new date appends, and other rows are never touched. Company history refuses to
  write before a later recorded date. Weekend runs and values kept stale from an earlier day aren't recorded. The
  code creates and grows both tabs itself (data tabs with nothing to protect). A history failure never fails the
  signals or price update.
- **Backfill:** `history --backfill <date>` reruns `compute()` for each past weekday on series truncated at that
  date (a shared helper the signal backtest also uses), inserts older dates in order and never replaces a live
  row. Daily closes are cached for five years, so it reaches back to 2022.
- **Settings:** `[sheet]` `signal_history_tab`, `company_history_tab`.

## Acceptance criteria

- [x] A1. The first write creates the tab with headers and formats. —
  `tests/test_history.py::test_first_write_creates_the_tab_with_headers_and_formats`
- [x] A2. The same date replaces and a new date appends. —
  `tests/test_history.py::test_same_date_replaces_and_a_new_date_appends`
- [x] A3. Columns are found by key and new keys go on the right; a moved header stops the write. —
  `tests/test_history.py::test_columns_are_found_by_key_and_new_keys_go_on_the_right`,
  `tests/test_history.py::test_a_moved_header_stops_the_write`
- [x] A4. Backfill inserts older dates in order, never replaces live rows, and matches `compute()` on truncated
  data. — `tests/test_history.py::test_backfill_inserts_older_dates_in_order_and_never_replaces_live_rows`,
  `tests/test_history.py::test_truncate_hides_later_data`,
  `tests/test_history.py::test_backfill_matches_compute_on_the_truncated_data`,
  `tests/test_history.py::test_backfill_command_writes_rows`
- [x] A5. `--dry-run` writes nothing; the tab grows in chunks. — `tests/test_history.py::test_dry_run_writes_nothing`,
  `tests/test_history.py::test_the_tab_grows_in_chunks`
- [x] A6. Company history picks royalty and developer rows, replaces the same date, and refuses to write before a
  later date. — `tests/test_history.py::test_company_rows_pick_royalties_and_developers`,
  `tests/test_history.py::test_company_history_appends_then_replaces_the_same_date`,
  `tests/test_history.py::test_company_history_refuses_to_write_before_a_later_date`
- [x] A7. A `signals` run records history, skips weekends, and survives a history failure. —
  `tests/test_history.py::test_signals_run_records_history`, `tests/test_history.py::test_weekends_are_not_recorded`,
  `tests/test_history.py::test_a_history_failure_never_fails_the_signals_run`
- [x] A8. Values and cleared cells are written as the Sheet expects. —
  `tests/test_history.py::test_values_and_clear_cells`
- [x] A9. README says what the two tabs hold; CLAUDE.md lists them in the run order and says not to edit them by
  hand.
