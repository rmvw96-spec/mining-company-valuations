# Jurisdiction risk from a country table

Instructions for Claude Code. Roadmap item 4b. Follow CLAUDE.md.

**Status: built** (branch `jurisdiction-snapshots`). Where the build differs from the plan below:
- The add-on comes from the Policy Perception Index (Table 2), not the Investment Attractiveness Index: the IAI is
  60% geology, and the discount-rate add-on prices policy risk. A first build used IAI quartiles (0/1/2/4) and was
  dropped: near-ties a place apart got a point or two apart, and the average add-on rose from 0.97 to 1.45. Now:
  the average of the last three years' scores (the survey is noisy year to year), 0 at 90 and above, 3 at 0, in
  steps of 0.25. That keeps the average near the hand-set level and moves few companies by a point or more.
  Each row has a `rule`: `score` (built from a private scores file; the survey is copyright, so only the
  rounded add-ons are committed), `fixed`, `top` or `median`.
- Fraser ranks provinces and states, not Canada, the US, Australia or Argentina as a whole. A weight on one of
  those countries without a region (`Canada:0.4`) uses the median add-on of its ranked regions.
- `country_weights` is filled where the location is clear (one country, or shares already recorded in
  `countries`) and, for nine larger multi-country companies, from their 2025 production (or gross profit) by
  mine, each with `country_weights_source`.
- Places outside the 2025 ranking: Mauritania, Turkey, Suriname, the Dominican Republic, Senegal, Zimbabwe and
  California are scored from the 2024 survey's Table 2 (their 2023 and 2024 scores, the ones inside the three-year
  window; the scores-file row carries its own `source` and `as_of`). Nicaragua (US sanctions on its gold sector)
  takes the top add-on; Cambodia, Thailand and Azerbaijan (in neither survey) keep the hand-set add-on of the one
  company operating only there; Bulgaria (dropped from the 2024 survey for too few responses), Greece, Poland,
  Honduras and North Macedonia (in neither survey) take the median scored add-on, provisionally. Argentine
  provinces neither survey ranks (Jujuy, Salta) are weighted as `Argentina`, the median of the ranked provinces;
  US energy royalties and South Dakota as `United States`. Developers don't use the add-on (they're valued on their
  study NPV), so they have no weights.
- Weights for the remaining multi-country companies (Nov 2026): from each company's latest annual figures by mine
  or segment (production, gold-equivalent production, revenue or EBITDA, whichever the company publishes), with the
  source in `country_weights_source`. Where 2025 output misrepresents the business (Barrick: Loulo-Gounkoto
  suspended and two mines sold; Endeavour Silver: two new mines part-year), the latest guidance by mine is used
  instead, and the source says so. Royalty companies are weighted by revenue or GEOs by asset, named assets only.
  Three stay manual, with the reason in `country_weights_source`: Royal Gold (about half its revenue unnamed by
  property), Harmony and Central Asia Metals (no split published).
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
