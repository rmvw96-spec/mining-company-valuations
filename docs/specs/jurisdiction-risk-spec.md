# Jurisdiction risk from a country table

Roadmap 4b · Status: Built Nov 18–19, 2026 (developers' weights added Nov 21) · Depends on: none

Instructions for Claude Code. Follow CLAUDE.md, including its steps for a new Fraser survey.

## Goal

The discount rate is the 10-year Treasury yield + 3% + a jurisdiction add-on that was typed in per company
(`addon_pct_points`, PNAV inputs P), so similar risks got different numbers and a company with mines in three
countries got one number someone picked. Build the add-on from a dated country table, weighted by where each
company's value is, with the hand-set figure kept as a fallback and an override.

## Scope

- **In:** the country table, company weights by country, the add-on written to PNAV inputs P, and a sensitivity
  column.
- **Out:** the Fraser survey itself in the repo (copyright: only the rounded add-ons are committed; the scores stay
  in `private/`).

## Design

- **Country table** (`data/research/country_risk.csv`, the record: `country`, `region`, `rule`,
  `addon_pct_points`, `few_responses`, `basis`, `source`, `as_of`), built by
  `jurisdiction --build private/fraser-<year>-scores.csv --source ... --as-of ...`:
  - `score` rows: the Fraser Institute **Policy Perception Index** (Table 2), averaged over the last `years` (3)
    surveys where scored (one survey is noisy), on a straight line from 0 points at `floor_score` (90) and above to
    `top_addon` (3) at 0, in steps of 0.25 (`[jurisdiction]`). Only these rows are rewritten by a build.
  - A place missing from the latest survey but scored in the one before keeps that score, with its own source.
  - `fixed` (a hand-set figure with its reason), `top` (sanctions, e.g. Nicaragua) and `median` (provisional: the
    median scored add-on) rows for places no survey ranks. Each row's `basis` says why.
  - Fraser ranks provinces and states, not Canada, the US, Australia or Argentina as a whole: a weight on one of
    those without a region uses the median of its ranked regions.
- **Company weights:** `country_weights` in `pnav_companies.csv` (`Canada:0.6;Mexico:0.4`, summing to 1 within
  `weight_tolerance`), with `country_weights_source`: production by mine from the latest annual report (or revenue,
  EBITDA or gross profit, whichever is published; latest guidance where the year misrepresents the business);
  royalty companies by revenue or GEOs from named assets; developers by project location (they need the add-on
  for their study discount rate, roadmap 6). Left blank, with the reason, where no split is published.
- **Company add-on** = Σ weight × country add-on. `addon_override` (with `addon_override_note`) wins; blank weights
  keep the hand-set `addon_pct_points` (`addon_basis` = `table` or `manual`).
- **Where used:** `pnav.inputs()`; `financials` writes PNAV inputs P for table rows only (manual rows keep the
  Sheet's value). `jurisdiction` writes `out/jurisdiction/comparison.csv`, old against new, for the user.
- **Sensitivity:** PNAV inputs BX (and P/NAV W) = today's P/NAV with the add-on raised by
  `[pnav] sensitivity_points` (2).

## Acceptance criteria

- [x] A1. A score maps to its add-on, and the average uses the latest years and skips blanks. —
  `tests/test_jurisdiction.py::test_addon_from_score`,
  `tests/test_jurisdiction.py::test_average_score_uses_the_latest_years_and_skips_blanks`
- [x] A2. The table's rules and the region median. — `tests/test_jurisdiction.py::test_table_rules_and_region_median`
- [x] A3. A build rewrites only scored rows. — `tests/test_jurisdiction.py::test_build_table_rewrites_scored_rows_only`
- [x] A4. Weights are parsed and checked (sum to 1, every country in the table). —
  `tests/test_jurisdiction.py::test_parse_and_check_weights`
- [x] A5. The weighted add-on, the override and the manual fallback, and the comparison file. —
  `tests/test_jurisdiction.py::test_company_addon`, `tests/test_jurisdiction.py::test_apply_and_comparison`,
  `tests/test_jurisdiction.py::test_missing_table_means_every_addon_stays_manual`
- [x] A6. The table and the weights are well formed (unique place, a source on every row). —
  `tests/test_data_files.py::test_country_risk_table`, `tests/test_data_files.py::test_country_weights`
- [x] A7. README explains the discount rate; CLAUDE.md says the table is the record and how to add a new survey.
- [ ] A8. (user) The user has reviewed `out/jurisdiction/comparison.csv`, including the developers' add-ons added
  Nov 21, before `financials` writes them to the Sheet.

## Decisions

- The Policy Perception Index rather than the Investment Attractiveness Index, since the IAI is 60% geology and
  the add-on prices policy risk; a straight line rather than quartile bands, which put near-ties a point or two
  apart and raised the average add-on from 0.97 to 1.45 (2026-11-18).
- Country risk counts once, in the discount rate (the user, 2026-11-21).
