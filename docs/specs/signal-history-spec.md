# Signal history: record every run on the Sheet

**Status: built** (branch `signal-history`). Where the build differs from the plan below: the source column is B
(not last), so new signals can be added on the right; the history code creates and manages both tabs itself
rather than `setup-sheet` (they're data tabs with nothing to protect); weekend runs and values kept stale from an
earlier day aren't recorded; daily closes are now cached for five years so the backfill reaches back to 2022.

Instructions for Claude Code. Roadmap item 1a. Follow CLAUDE.md (branch, tests, ruff, ask before `git push`,
Sheet safety, `--dry-run`).

## Goal

Today each run overwrites Signals E:F, so yesterday's readings are gone. Record them, so we can:

- chart each signal over time (gold/silver ratio, royalty median, miner ratios, FCF yields);
- see when a status changed and how long it has held;
- build our own P/NAV history for royalty companies (needed by [royalty-history-spec.md](royalty-history-spec.md))
  and track developers' cash runway between quarterly reports.

The history must live on the **Sheet**, not in `out/`: the scheduled run is on GitHub, where `out/` is thrown
away after each run.

## Design

### New tab: **Signal history** (one row per run date)

- Row 1: headers. Column A `Date` (YYYY-MM-DD, the run date in New York), then one column per signal key in the
  order of `signals.SIGNALS` (value only; the status can be recomputed from the value and thresholds, and
  storing text would bloat the tab). Headers are the keys themselves, so a reordering on the Sheet is caught.
- One row per date. A second run on the same date **replaces** that date's row (intraday then after-close: the
  later run wins). Find the row by date in column A; append when absent.
- New signals added later get a new column at the right; old rows stay blank there.
- Values are written raw (no rounding); number formats as on the Signals tab.

### New tab: **Company history** (long format)

- Columns: `Date`, `Holding` (PNAV inputs B), `Yahoo` (AP), `Metric`, `Value`.
- Metrics, per run:
  - royalty/streaming rows (peer group "Royalty/streaming" with a NAV per share): `independent_pnav` (AJ),
    `price_usd` (C);
  - developer rows (rows with a developer check in BE): `ev_per_aueq_oz` (BB), `months_of_cash` (BC),
    `cash_share` (BD).
- Same-date rows are replaced, as above. Long format keeps the tab narrow as holdings come and go.
- About 40 rows a day, around 10,000 a year: well inside Sheet limits. If it ever passes 100,000 rows,
  archive older years to `Company history YYYY` tabs (not part of this job; note it in CLAUDE.md).

### Code

- `minerval/history.py`:
  - `history_row(rows, today) -> list` from `signals.compute()` output.
  - `company_rows(pnav_cells, today) -> list[list]`.
  - `upsert_by_date(sheet, tab, header, rows, key_cols)`: reads column A (and B:D for the long tab), writes
    replacements in place and appends the rest in one batch. Never touches other rows.
  - `run(sheet, rows, today, dry_run)` called at the end of `signals.run()` when the Signals tab exists.
    A history failure must not fail the signals or price update (same pattern as `prices.run_signals`).
- `setup-sheet` (`layout.py`) gains a step that creates the two tabs with headers (exact mode; skip and report
  if a header differs).
- Settings, `[sheet]`: `signal_history_tab = "Signal history"`, `company_history_tab = "Company history"`.

### Backfill

The market signals (not the FCF yields or company metrics) can be recomputed for past dates from Yahoo and
FRED history. Add `uv run python -m minerval history --backfill 2025-01-01`, which reruns `compute()` with
`today` set to each past weekday on series truncated at that date. Mark backfilled rows in a last column
`Source` = `backfill` (live rows: `live`). The signal backtest ([signal-backtest-spec.md](signal-backtest-spec.md))
reuses the same truncation helper, so build it as a shared function.

## Tests (offline)

- `upsert_by_date`: append on a new date, replace on the same date, leave other rows alone, add a column for a
  new key without disturbing old rows (MemorySheet).
- `company_rows` picks royalty and developer rows exactly as the Signals and Model portfolio formulas do.
- A history write failure leaves the signals report intact, with one line saying the history wasn't written.
- Backfill on synthetic series gives the same values as `compute()` run on the truncated data.

## Docs

- README: what the two tabs hold.
- CLAUDE.md: run-order table (writes Signal history and Company history); what-not-to-touch (don't edit history
  rows by hand; the code finds rows by date).

## Done when

- Two scheduled GitHub runs on consecutive days leave two rows on Signal history and two dates on Company history.
- A manual run on the same day replaces that day's row instead of adding one.
