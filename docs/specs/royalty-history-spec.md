# Royalties against their own history

Roadmap 4c · Status: Built Nov 20, 2026 · Depends on: 1a ([signal-history-spec.md](signal-history-spec.md))

Instructions for Claude Code. Follow CLAUDE.md.

## Goal

The royalty buy zone compares each company's independent P/NAV with fixed framework bands (buy 1.1–1.4×, normal
1.5–2.2×, rich above 2.2×), and the Signals tab uses the peer median. Some companies always trade above the bands
(Franco-Nevada reads "Rich" almost every day), so the band says little about whether that company is cheap now.
Add a second view: each company against its own past valuation.

## Scope

- **In:** P/OCF against its own 5 years (from day one), P/NAV against its own recorded history (once long enough),
  an own-history band, and a Signals median.
- **Out:** analyst consensus P/NAV snapshots as history (single points: reference only).

## Design

- **Annual operating cash flow** comes from SEC EDGAR XBRL facts (10-K for Royal Gold, 40-F for the others; about
  10 years each, Triple Flag 5), recorded in `data/research/royalty_ocf.csv` by `royalty-ocf`, so the daily run
  makes no EDGAR request. Yahoo's free endpoint has only 4 fiscal years, and 40-F filers' 6-Ks carry no XBRL.
- **P/OCF** (`minerval/royalty_history.py`, `[royalty_history]`) = month-end price of the US listing × shares ÷ the
  latest annual OCF filed by then, so it steps once a year; today's value uses the same basis. Negative years are
  skipped. Ranked in the last `years` (5) of month-ends, with at least `min_months` (36). Label it P/OCF
  everywhere: it tracks P/NAV for royalty companies but isn't the same.
- **P/NAV percentile:** from Company history (`independent_pnav`), blank until `pnav_min_days` (250) recorded days.
- **PNAV inputs:** BY P/OCF, BZ its percentile, CA the P/NAV percentile (written by `signals`, before the Signals
  formulas are read back); CB the band, a formula: "Cheap for itself" at or below the 25th percentile, "Expensive
  for itself" at or above the 75th, else "Normal for itself".
- **Signals:** `royalty_own_pctile_median` (a formula; thresholds 25 and 75).
- **Model portfolio W** (royalty rows): "framework band / own-history band"; `setup-sheet` upgrades the old formula.
- **Known distortions** (README): a fast rise in cash flow and acquisitions paid in shares (Royal Gold after
  Sandstorm) make the latest annual P/OCF read high until the next annual report.

## Acceptance criteria

- [x] A1. Annual rows take the first filing, prefer US$, convert C$, and take shares from the filing. —
  `tests/test_royalty_history.py::test_annual_rows_first_filing_usd_preferred_cad_converted_and_shares_from_the_filing`
- [x] A2. Each month-end uses the annual figure filed by then, negative years skipped, and today counts filings up
  to today only. —
  `tests/test_royalty_history.py::test_pocf_uses_the_annual_figure_filed_by_each_month_end_and_skips_negative_years`,
  `tests/test_royalty_history.py::test_current_month_counts_filings_up_to_today_only`
- [x] A3. The window and its minimum, with today left out of the history. —
  `tests/test_royalty_history.py::test_own_pocf_window_minimum_and_today_left_out_of_the_history`
- [x] A4. Percentile edges and blank cases; the P/NAV percentile needs 250 days. —
  `tests/test_royalty_history.py::test_percentile_edges`, `tests/test_royalty_history.py::test_percentile_blank_cases`,
  `tests/test_royalty_history.py::test_pnav_percentile_needs_the_minimum_days_before_today`
- [x] A5. The band, and its Sheet formula matching the Python rule. — `tests/test_royalty_history.py::test_band`,
  `tests/test_royalty_history.py::test_band_formula_matches_the_python_rule`
- [x] A6. W adds the own band and upgrades the old formula. —
  `tests/test_royalty_history.py::test_timing_formula_adds_the_own_band_and_upgrades_the_old_one`
- [x] A7. The Signals median, its status and formula. — `tests/test_royalty_history.py::test_signal_status`,
  `tests/test_royalty_history.py::test_signal_value_formula_and_compute_median`
- [x] A8. `signals` writes the royalty rows and clears the rest. —
  `tests/test_royalty_history.py::test_update_sheet_writes_royalty_rows_and_clears_the_rest`
- [x] A9. The record file is well formed. — `tests/test_data_files.py::test_royalty_ocf_record`
- [x] A10. README explains the two views of royalty value; CLAUDE.md the columns and the `royalty-ocf` step.

## Decisions

- Python writes BY:CA rather than a Sheet helper range: monthly prices and a few annual figures can't be ranked by
  a formula without a large hidden table (2026-11-20).
