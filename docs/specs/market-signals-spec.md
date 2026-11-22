# Market signals: when to buy each tier

Roadmap: before the roadmap (PR #5) · Status: Built Nov 17, 2026; rate-expectations signal and context-only
signals added Nov 2026 (roadmap 2c) · Depends on: none

Instructions for Claude Code. Follow CLAUDE.md, including its Sheet rules (spill ranges, `--dry-run`, the
Signals tab).

## Goal

The model values each company but had no view on when to buy each tier. Add, in the package and on the Google
Sheet: timing signals per tier on a new Signals tab, refreshed by the daily `prices` run; a royalty buy zone; a
producer cost increase; and developer checks (EV per ounce, months of cash). The Model portfolio shows each
holding's relevant signal.

## Scope

- **In:** the Signals tab and `signals` command; PNAV inputs AR:AS and AT:BE; P/NAV U:V; the cost-increase input
  through P/NAV, stress and Holdings downside; Model portfolio W:Y; the `setup-sheet` installer.
- **Out:** advice. Statuses are plain text from a framework, for an investor, with no jargon and no "BUY" commands.

## Design

### Data and computation (`minerval/signals.py`)

- **Yahoo:** daily closes for `[signals] daily` over `daily_range` (5 years), full monthly history for `monthly`,
  latest quotes. **FRED:** `fred_series` (DFII10, real yield) and `fred_rates` (DGS2, DFF), from the graph CSV
  (holidays are "." and skipped) or the API when `FRED_API_KEY` is set. Downloads cached in `cache/signals/`.
- `compute()` is a pure function of the series, the date, the thresholds and the inputs, and returns each value
  and its status with the same rules as the Sheet's formulas. Changes are 12-month unless stated; percentiles use
  month-ends, with the current month at the latest quote.
- **The signals** (`signals.SIGNALS` is the list; thresholds and their reasoning in `[signals.thresholds]`):

| Tier | Signals |
|---|---|
| Physical metal | Gold/silver ratio (and its percentile since 2000); two-year yield's 3-month change (the expected Fed path; also the two-year minus fed funds, context); real yield (context: "peaked and falling" against "rising"); the dollar's 12-month change (context) |
| Physical metal and royalty | SPY drawdown from its 12-month high: "Market pullback" / "Stock-market panic" |
| Royalty | Median independent P/NAV (a Sheet formula over PNAV inputs AJ): buy zone ≤ 1.4, normal to 2.2, rich above; median own-history percentile |
| Producers | Gold, copper and silver against diesel (12-month changes; the changes themselves as info); AISC margin (gold − the industry AISC); GDX, SIL and COPX against their metal (10-year percentile); fund FCF yields for SGDM, SGDJ, COPP, SLVR (weighted from the Holdings tab, excluding `physical_trusts` and `non_operating`) |
| Juniors | Tax-loss window (`tax_loss_window`, Nov 1 – Dec 31); gold, GDX, silver and SIL against their 200-day averages; junior breadth; `junior_timing` (a Sheet formula: window and uptrend); GDXJ and SILJ drawdowns (info) |

- **Context signals** (`context=True`) show "Info" and have no thresholds on the Sheet; `backtest-signals` tests
  their rule with `[signal_backtest.context_thresholds]`.

### Signals tab

- Rows 1–2: title and a note on who writes what. Row 4 headers: A key, B tier, C signal, D unit, E value, F as of,
  G–H thresholds, I status (a formula), J what the framework says, K source. One row per signal, grouped by tier.
- An inputs block below: `industry_aisc` (written by Python from the AISC table), `producer_cost_increase`,
  `energy_share_of_costs` with the `implied_cost_increase` formula, and the developer inputs (`near_cash_share`,
  `runway_short_months`, `runway_ok_months`, `raise_discount`, resource weights).
- Python finds rows by the key in A and writes E:F, except on formula rows (`royalty_pnav_median`,
  `royalty_own_pctile_median`, `junior_timing`, `implied_cost_increase`). Status formulas use `XLOOKUP` on keys,
  never fixed rows. Each run reads G:H and I back and reports any row where the Sheet's status differs from
  Python's. A series that fails to download keeps the Sheet's last value, and the report says so.
- **Commands:** `signals [--dry-run]` writes the tab and `out/signals/` (`report.txt` with every status and what
  changed since the last run, `signals.json`). `prices` runs it at the end (`--no-signals` to skip); a signals
  failure adds a line to the price report and never fails the update.

### Royalty buy zone

- PNAV inputs AR: buy-below price = independent NAV per share (R) × the buy-zone top (Signals G of
  `royalty_pnav_median`). AS: band ("Buy zone", "Normal range", "Rich", or "no independent NAV"), from the same
  cells. P/NAV U:V show them. `pnav.py` writes `royalty_band` and `buy_below_price_usd`.
- Caveat (header note and README): AJ uses the independent model's NAV at that model's own metal prices, a research
  input refreshed by hand.

### Producer cost increase

- A cost increase *c* lowers free cash flow by *k* × max(0, revenue − FCF) × *c*, with *k* the share reaching cash
  flow (0.70): `price_model.cost_change`, `[price_model] cost_increase`, `compute --cost-increase`. FCF-basis rows
  only; it slightly overstates the effect, since taxes don't inflate.
- `stress.py` applies it to FCF, OCF (its smaller cost base), EBITDA (the whole increase, before tax) and the
  breakeven, with a `cost_base_m` helper; `pnav.py` to the cash-flow change.
- Sheet: PNAV inputs H7 reads the Signals input; Z12:AC154 subtract the increase on FCF rows; Holdings downside R
  (cost base, written by `financials`) and K2 subtract it.

### Developer checks

- Research inputs AT:AW (resource amount, unit, category, source and date; `pnav_companies.csv` the record, every
  figure from the company's own latest statement). `financials` writes AX cash and AY 12-month FCF.
- Formulas AZ EV, BA EV per unit, BB EV per gold-equivalent ounce (silver-equivalent at the live gold/silver ratio;
  copper in BA only), BC months of cash, BD cash as a share of market value, BE the developer check ("Short of
  cash" under 12 months, "Watch" under 18, plus "trading near cash"). Roadmap 3 added committed funding.

### Model portfolio and installer

- W: the timing signal for each row's bucket and metal, from `[signals.timing]` (the record); X: EV per
  gold-equivalent ounce; Y: months of cash (developers).
- `setup-sheet [--dry-run]` snapshots every range it touches to `out/layout/`, then installs the Signals tab, PNAV
  inputs H7 and columns, the Z:AC rewrite, P/NAV U:V, Holdings downside R and K2, and Model portfolio W:Y. Each step
  reports "added", "already in place" or "conflict: <cell> holds <x> (skipped)"; a cell is rewritten only when it
  holds exactly the old formula. A second run changes nothing. Formula text comes from `[sheet]` addresses.

## Acceptance criteria

- [x] A1. Percentiles, the tax-loss window (including across the year end), 200-day averages, 12-month changes and
  drawdowns. — `tests/test_signals.py::test_percentile`, `tests/test_signals.py::test_tax_loss_window`,
  `tests/test_signals.py::test_window_across_the_year_end`, `tests/test_signals.py::test_200_day_average`,
  `tests/test_signals.py::test_12_month_change_and_drawdown`
- [x] A2. FRED: holidays skipped, every series downloaded, the API form converted. —
  `tests/test_signals.py::test_parse_fred_skips_holidays`, `tests/test_signals.py::test_every_fred_series_is_downloaded`,
  `tests/test_signals.py::test_fred_api_json_becomes_the_graph_csv`
- [x] A3. Every status at both sides of each threshold; a missing value gives no status. —
  `tests/test_signals.py::test_status_boundaries`, `tests/test_signals.py::test_missing_value_gives_no_status`
- [x] A4. The real yield, rate expectations, junior timing and AISC margin rules; context signals show Info. —
  `tests/test_signals.py::test_real_yield_peaked_and_falling_vs_rising`,
  `tests/test_signals.py::test_rate_expectations_from_the_two_year_yield`, `tests/test_signals.py::test_junior_timing`,
  `tests/test_signals.py::test_aisc_margin_text`,
  `tests/test_signals.py::test_context_signals_show_info_and_have_no_sheet_thresholds`
- [x] A5. Each status formula uses its own row and the same texts as Python. —
  `tests/test_signals.py::test_every_status_formula_uses_its_row_and_texts`
- [x] A6. `compute()` uses the Sheet's thresholds and inputs, handles formula rows and missing series. —
  `tests/test_signals.py::test_compute_ratio_percentile_and_changes`,
  `tests/test_signals.py::test_compute_uses_sheet_thresholds_and_inputs`, `tests/test_signals.py::test_compute_formula_rows`,
  `tests/test_signals.py::test_compute_with_missing_series`
- [x] A7. Fund FCF yields from the Holdings tab; the royalty median from PNAV inputs. —
  `tests/test_signals.py::test_fcf_yield_from_the_holdings_tab`,
  `tests/test_signals.py::test_royalty_median_from_the_pnav_inputs_tab`
- [x] A8. `signals` writes by key, reports drift and changes, writes nothing on a dry run, and runs without the
  tab. — `tests/test_signals.py::test_run_writes_values_by_key_and_reports_drift`,
  `tests/test_signals.py::test_run_dry_run_writes_nothing`, `tests/test_signals.py::test_run_without_the_tab`,
  `tests/test_signals.py::test_changes_since_last_run`,
  `tests/test_signals.py::test_changes_are_measured_against_the_sheet_before_the_write`
- [x] A9. A failed series keeps the Sheet's value without overriding fresh data, and a signals failure never fails
  the price update. — `tests/test_signals.py::test_missing_series_falls_back_to_the_sheet_and_is_not_rewritten`,
  `tests/test_signals.py::test_fallback_never_overrides_fresh_data`,
  `tests/test_signals.py::test_price_update_survives_a_signals_failure`
- [x] A10. A zero cost increase changes nothing, and 10% matches hand-worked figures in stress and P/NAV. —
  `tests/test_stress.py::test_zero_cost_increase_changes_nothing`, `tests/test_stress.py::test_ten_percent_cost_increase`,
  `tests/test_pnav_and_price_model.py::test_cost_change`,
  `tests/test_pnav_and_price_model.py::test_pnav_zero_cost_changes_nothing`,
  `tests/test_pnav_and_price_model.py::test_pnav_ten_percent_cost_increase`
- [x] A11. Royalty bands and developer columns in `pnav.csv`, at their boundaries. —
  `tests/test_pnav_and_price_model.py::test_royalty_band`, `tests/test_pnav_and_price_model.py::test_royalty_columns_in_compute`,
  `tests/test_pnav_and_price_model.py::test_developer_check`,
  `tests/test_pnav_and_price_model.py::test_months_of_cash_and_ev_per_ounce`,
  `tests/test_pnav_and_price_model.py::test_developer_columns_in_compute`
- [x] A12. The installer: a fresh install, nothing on a second run or a dry run, an occupied cell skipped, the
  Z:AC rewrite only over the exact old formula, new signals inserted in their tier, W covering every bucket. —
  `tests/test_layout.py::test_fresh_install`, `tests/test_layout.py::test_second_run_writes_nothing`,
  `tests/test_layout.py::test_dry_run_writes_nothing`, `tests/test_layout.py::test_occupied_cell_skips_the_step`,
  `tests/test_layout.py::test_cash_flow_rewrite_touches_only_the_exact_old_formula`,
  `tests/test_layout.py::test_new_signals_get_rows_inserted_in_their_tier`,
  `tests/test_layout.py::test_timing_formula_covers_every_bucket`
- [x] A13. The resource research columns are well formed (allowed units; a filled amount has a source and date). —
  `tests/test_data_files.py::test_resource_research_columns`
- [x] A14. The Sheet's statuses agree with Python's. — `signals` report, Nov 20, 2026: "Sheet and Python statuses
  agree."
- [x] A15. README has a Signals tab section, `setup-sheet`, the cost-increase input and the developer caveats;
  CLAUDE.md the run order, the changed-signal report and the new spill ranges.

## Decisions

- Thresholds are defaults matching the framework's wording, editable on the Sheet (G:H) with `[signals.thresholds]`
  as the record; changing one changes both (2026-11-17).
- The real yield and the dollar are context only; the two-year yield's 3-month change is the rate signal for
  physical gold (roadmap 2c, Nov 2026).
