# Jurisdiction risk from a country table

Instructions for Claude Code. Roadmap item 4b. Follow CLAUDE.md.

**Status: built** (branch `jurisdiction-snapshots`). Where the build differs from the plan below:
- The table stores the IAI rank (`iai_rank`, `iai_ranked`) and the code maps it to the quartile add-on, so a
  change to `[jurisdiction] quartile_addons` needs no edit to the table. `addon_pct_points` is filled only for
  places the survey doesn't rank, with the reason in `basis`.
- Fraser ranks provinces and states, not Canada, the US, Australia or Argentina as a whole. A weight on one of
  those countries without a region (`Canada:0.4`) uses the median add-on of its ranked regions.
- `country_weights` is filled where the location is clear (one country, or shares already recorded in
  `countries`), with `country_weights_source`. Other multi-country companies keep the hand-set add-on (basis
  `manual`) until their annual reports are read: a roadmap small item. Developers don't use the add-on (they're
  valued on their study NPV), so they have no weights.
- The override is `addon_override` with `addon_override_note`.
- The sensitivity is PNAV inputs BX (and P/NAV W): today's P/NAV with the add-on raised by `[pnav]
  sensitivity_points` (2).
- Built with the `snapshots` command (roadmap small item) in the same PR.

## Goal

The P/NAV discount rate is the 10-year Treasury yield + 3% + a **jurisdiction add-on** typed in per company
(`addon_pct_points` in `data/research/pnav_companies.csv`, PNAV inputs P). The add-ons are hand-set, so similar
risks get different numbers, and a company with mines in three countries gets one number someone picked.

Make the add-on come from a **country table**, weighted by where each company's value is, with the hand-set
figure kept as an override.

## Part 1: country table (the record)

- New file `data/research/country_risk.csv`: `country`, `region` (optional, e.g. a province or state where it
  differs a lot: Sinaloa vs Sonora, Quebec vs British Columbia), `addon_pct_points`, `basis`, `source`, `as_of`.
- Basis: start from a published, dated index and map it to add-on bands, so the numbers are explainable. The
  Fraser Institute Annual Survey of Mining Companies (Investment Attractiveness Index, by province and state) is
  the usual one for mining; check the latest edition and its terms. Mapping (in settings.toml, commented):
  top quartile 0, second 1, third 2, bottom 4 percentage points, plus explicit entries for countries the survey
  rates poorly or doesn't cover (sanctions, active conflict).
- The user reviews the table before it's used: the PR shows the old and new add-on for every company.

## Part 2: company weights by country

- New column in `pnav_companies.csv`: `country_weights`, e.g. `Canada:0.6;Mexico:0.4`, by share of production
  (producers) or of NAV (developers) from the latest annual report. The existing `countries` column stays as a
  description.
- Company add-on = Σ weight × country add-on. If `country_weights` is blank, use the existing hand-set
  `addon_pct_points` and say so in a new `addon_basis` column (`table` or `manual`).
- Keep a `addon_override` column: when filled, it wins, with a note saying why (e.g. a specific permit dispute).

## Part 3: where it's used

- `pnav.inputs()` computes the add-on; PNAV inputs P is written by a new step in `financials` (only rows with
  `addon_basis = table`; manual rows keep the Sheet value, which stays the working copy).
- Sensitivity view: a P/NAV at add-on +2 points for each company, so the user sees which valuations depend
  most on the risk premium (one more P_NAV column via the installer).

## Tests (offline)

- Weighted add-on, the fallback and the override.
- `country_weights` parsing and validation (weights sum to 1 ± 0.01; every country is in the table).
- Data-file validation for `country_risk.csv` (unique country/region; a source on every row).

## Docs

README (how the discount rate is built), CLAUDE.md (the table is the record; P is written for table rows).

## Done when

Every company on the Model portfolio has a table-based add-on or a stated reason for a manual one, and the user
has reviewed the old-vs-new table in the PR.
