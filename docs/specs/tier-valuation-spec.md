# Valuation by tier: EV against a 10-year NPV at three price decks

Roadmap 6 · Status: In progress (research inputs built Nov 21, 2026) · Depends on: 3 (developer financing),
4b (jurisdiction); 4a improves the pessimistic costs

Instructions for Claude Code. Follow CLAUDE.md, including its Research section for recording filings.

## Goal

The roadmap 5 screen valued producers at today's spot price held flat over the reserve life, from free cash flow
after all capital spending. On Nov 21, 2026 that gave 36 of 97 producers a negative NAV, mostly because a one-off
build was treated as a permanent cost while the production it builds was never counted, and spot had just fallen
about 21% below its 12-month average, so the ranking depended on the week it ran. This spec moves every tier to
Rick Rule's test (as the user summarised it from secondary sources): **enterprise value against the NPV of its assets at pessimistic, base and optimistic decks**,
with spot only as a cross-check. The output (an NPV per deck, a downside test and a buy-below price) is what the
screen's buy signal uses ([model-portfolio-screen-spec.md](model-portfolio-screen-spec.md)).

## Scope

| Rule's test | Here |
|---|---|
| 10-year DCF; EV against NPV; pessimistic, base and optimistic decks, not spot alone | Part 1 |
| Cash flow after sustaining capital; proven pipeline added; FCF yield; cost inflation | Part 2 |
| Developers: study NPV discounted for time and probability; survive a 15–30% capex overrun; capex-to-market cap | Part 3 |
| Royalties: P/NAV and cash-flow multiples at a lower cost of capital | Part 4 |
| Political risk counted once | Discount rate only (Part 1); the screen drops its jurisdiction measures |

- **Out:** explorers and takeover appeal (judgement calls stay with the user); royalties' exploration optionality
  and scale arbitrage (no quantity to research; market cap stays visible for the user's judgement).

## Design

### Part 1: the common method

- **Decks:** `[scenarios]` gets Pessimistic, Base and Optimistic, each with gold, silver and copper set
  independently (no ratio links them), each with a `source` and `as_of` comment. The values are the user's and
  nothing in the design may depend on them. Severe and All-time high stay for the stress test. Spot ("Today") is a
  cross-check column, never the basis of a buy signal or a ranking.
- **Sheet decks:** Metal prices reference H15:K17 becomes Pessimistic / Base / Optimistic / All-time high. Find
  every formula that reads H15:K17 (PNAV inputs, Holdings downside K) before relabelling, and keep `[scenarios]`
  and the cells in step.
- **Discount rate:** 10-year Treasury yield + 3% + the jurisdiction add-on (PNAV inputs P; developers through
  `country_weights` like producers). This is the only place jurisdiction counts.
- **NPV:** cash flow for min(reserve life, `[valuation] horizon_years` = 10) years, no terminal value, at each
  deck. Net cash is not added (EV nets it). Developers keep the study's whole mine life (Part 3).
- **EV / NPV:** EV = market cap + debt − cash (PNAV inputs AZ). 1.0 = priced at the deck's value; NPV ≤ 0 reads
  "negative NPV", never a number.
- **Where computed:** Python writes the NPVs from `financials` (they change only with financials, research inputs
  or decks). EV / NPV and the buy-below price are Sheet formulas over today's EV, so `prices` moves them. Python
  computes the same values in `data/derived/` for tests and the screen. Reserve-life P/NAV stays as a context column.
- **Validation report:** `valuation --check` (or part of `financials --dry-run`) lists each NPV more than 2× away
  from the independent NAV (PNAV inputs R) or the consensus P/NAV (P_NAV I).

### Part 2: producers

- **Cash flow** = operating cash flow (trailing 12 months) − sustaining spending, re-priced from the reporting
  period's average metal prices to each deck by revenue mix (`cash_flow_share` × revenue × the price change).
- **Sustaining spending:** recorded per filing period in `data/research/capex_periods.csv` (as reported, in its
  currency, consolidated basis). `research sustaining --write` builds the trailing 12 months to each company's
  financials date (FY + year to date − prior year to date, or four quarters), converting each part at its
  period-average rate, and writes `sustaining_capex_usd_m` (the total), `capitalized_stripping_usd_m`,
  `sustaining_leases_usd_m`, `sustaining_period_end` and `sustaining_source` to `pnav_companies.csv`. The total
  includes capitalized stripping and sustaining lease payments. Blank where no filing splits sustaining from
  growth: never estimated.
- **Fallback when blank:** free cash flow after all spending, labelled "FCF basis: sustaining not recorded" in the
  screen and the buy signal.
- **Pipeline:** a growth project counts only when it is committed (`projects.csv` `committed` = yes: construction
  decision taken) and has a published study. Its risk-adjusted NPV (Part 3), at the company's share, is added.
- **Cost inflation:** the pessimistic deck runs with costs raised by `[valuation] pessimistic_cost_increase`
  (the existing cost-change function; roadmap 4a's company AISC improves it). Base and optimistic use reported costs.
- **Measures:** EV / NPV at each deck; sustaining FCF yield = base-deck cash flow ÷ EV; downside test: EV ≤
  pessimistic NPV with costs raised.

### Part 3: developers

- **Records:** `data/research/projects.csv`, one row per study (`studies.PROJECT_COLS`: share, study type and
  date, study prices, published NPV and rate, `discounting`, `marginal_tax_rate`, `net_revenue_share`,
  `sensitivity`, capex, `construction_start`, `permits`, `committed`, `superseded`, sources), and
  `data/research/project_cashflows.csv`, one row per study and year (`studies.CASHFLOW_COLS`: pre- and after-tax
  free cash flow, payable metal by metal; year 1 = first construction year).
- **Method** (`minerval/studies.py`, `research studies`):
  1. **Re-price each year:** after-tax cash flow + tax share × net revenue share × Σ payable × (deck − study
     price). Tax share = 1 − the study's marginal tax rate (stated, or derived from its stated terms and noted);
     the average after-tax ÷ pre-tax ratio only when there is none, flagged.
  2. **Discount** at our rate, mid-year or end-year as the study does, over the whole mine life.
  3. **Check:** at the study's own price and rate, the rebuild is within `check_npv` (5%) of the published NPV and
     the re-pricing within `check_sensitivity` (10% of the base NPV) of its sensitivity rows. A study that fails,
     has no cash-flow table, or is superseded by a press release without a new technical report, gets no NPV and
     says why. Years a table aggregates are spread evenly only with the user's approval.
  4. **Time:** discount from today to the construction start: the company's guided `construction_start`, else
     `[valuation.years_to_start]` by stage.
  5. **Probability:** `[valuation.stage_probability]` by stage: construction (`committed`), permitted (`permits` =
     yes after at least a PFS), else the study type.
  6. **Risk-adjusted NPV** = NPV × time discount × probability × attributable share.
  7. **Capex overrun:** the funding gap (roadmap 3) with remaining capex raised by each of `capex_overrun`
     (+15%, +30%), funded by an equity raise at `raise_discount`. The downside test passes when dilution at +30% is
     at most `max_overrun_dilution` (0.33).
  8. **Capex-to-market cap** = remaining capex ÷ market cap.
- **Stage column:** `study_stage` in `pnav_companies.csv` (PEA / PFS / FS / permitted / construction / none),
  filled from the free-text `stage` and checked against the latest study row.
- **Measures:** EV / risk-adjusted NPV at each deck, overrun dilution at +15% and +30%, capex-to-market cap. EV
  per weighted unit (roadmap 3) stays.

### Part 4: royalties

- NPV of operating cash flow over 10 years at each deck (no sustaining spending), at the same discount rate. Their
  lower cost of capital shows in the buy level (Part 5), not the rate.
- Kept: independent P/NAV (AJ), framework band (AS), P/OCF and own-history percentiles (BY:CA). New: EV / NPV at
  each deck and the downside test at the pessimistic deck.

### Part 5: buy level and fair value

`[valuation.buy]`, per tier:

| Tier | Buy when (both) | Above fair value (review) |
|---|---|---|
| Producers | EV ≤ 0.6 × base NPV, and EV ≤ pessimistic NPV with costs raised | EV ≥ 1.0 × base NPV |
| Royalties | EV ≤ 1.0 × base NPV, and EV ≤ pessimistic NPV | EV ≥ 1.5 × base NPV |
| Developers | EV ≤ 0.6 × base risk-adjusted NPV, and the +30% overrun test passes | EV ≥ 1.0 × base risk-adjusted NPV |

- **Buy-below price per share** (US$ and listing currency, a Sheet formula) = (min(buy × base NPV, pessimistic
  NPV) + net cash) ÷ shares. No NPV (negative at base, inputs missing, failed check): no price, and the status
  says why.
- **Basis for the starting values** (into the `[valuation.buy]` comment when built): Rule buys at large discounts
  to his own NPV (about 40% in a Dec 2025 example) and checks the downside first; he cites 15–20× cash flow for
  precious-metals royalties against 5–7× for base-metal producers (Kitco, Feb 2026); Sprott's typical P/NAV by
  stage (Aug 2022): PEA 0.2–0.5×, PFS/FS 0.5–0.7×, construction 0.5–0.8×, production 0.6–1.5×. None is a
  published Rule threshold, and none is fitted to data.

### Sheet

- New PNAV inputs columns after CB, placed by `setup-sheet` (layout in `[sheet.pnav_inputs]`): sustaining spending
  and source; NPV at each deck and its basis (OCF − sustaining / FCF fallback / study); EV / NPV at each deck
  (formulas); downside test; sustaining FCF yield; overrun dilution and capex-to-market cap; buy-below price.
- Company history records each company's daily EV / base NPV.

## Acceptance criteria

Research inputs (built Nov 21, 2026):

- [x] A1. Trailing 12 months = FY + year to date − prior year to date, or a fiscal year ending on the financials
  date. — `tests/test_sustaining.py::test_ttm_from_fiscal_year_and_year_to_date`,
  `tests/test_sustaining.py::test_fiscal_year_ending_on_the_financials_date`
- [x] A2. Built from quarters where no year to date is published. —
  `tests/test_sustaining.py::test_ttm_from_quarters_when_no_year_to_date_is_published`,
  `tests/test_sustaining.py::test_ttm_from_four_quarters_without_a_fiscal_year`
- [x] A3. Stripping is added unless the filing includes it; leases are added and shown; each part is converted
  at its period's rate. — `tests/test_sustaining.py::test_stripping_added_unless_included_and_currency_converted`,
  `tests/test_sustaining.py::test_sustaining_leases_are_added_and_shown`
- [x] A4. An unpublished figure, mixed bases, a missing comparative or no filing leaves the figure unbuilt and
  says why. — `tests/test_sustaining.py::test_unpublished_figure_and_mixed_bases_are_not_built`,
  `tests/test_sustaining.py::test_missing_prior_year_comparative_says_so`,
  `tests/test_sustaining.py::test_no_filing_for_the_date`
- [x] A5. `research sustaining --write` changes only recorded tickers, and the record's columns are fixed. —
  `tests/test_sustaining.py::test_write_companies_fills_only_recorded_tickers`,
  `tests/test_sustaining.py::test_record_file_columns`
- [x] A6. A study rebuild reproduces a published NPV and its sensitivity rows, with tax share = 1 − the marginal
  rate. — `tests/test_studies.py::test_rebuild_matches_the_published_npv_and_sensitivities`,
  `tests/test_studies.py::test_all_metals_sensitivity_rows`
- [x] A7. Without a marginal rate the average share is used and flagged. —
  `tests/test_studies.py::test_without_a_marginal_rate_the_average_share_is_used_and_flagged`
- [x] A8. A study that fails its check, or is superseded, gets no NPV and says why. —
  `tests/test_studies.py::test_a_study_that_does_not_rebuild_is_flagged_and_not_used`,
  `tests/test_studies.py::test_superseded_study_has_no_npv`
- [x] A9. The discount rate takes the add-on from the country table, an override or the hand-set figure. —
  `tests/test_studies.py::test_discount_rate_uses_the_country_table_add_on`
- [x] A10. Stage comes from `committed`, `permits` (after a PFS) or the study type; a guided date beats the
  assumed years; no probability means no risk-adjusted NPV. —
  `tests/test_studies.py::test_stage_and_assumed_time_to_construction`,
  `tests/test_studies.py::test_risk_adjusted_needs_a_construction_date_and_a_stage_probability`
- [x] A11. The study records are well formed (years run 1, 2, 3...; every row sourced). —
  `tests/test_studies.py::test_record_files_are_well_formed`
- [x] A12. Every recorded study with a cash-flow table rebuilds within 5%. — `research studies`, Nov 21, 2026:
  7 of 7 within 1.3%, sensitivity rows within 3.2%; KSM and Diablillos have no table recorded.
- [x] A13. (user) The Step 0 pilot coverage was reviewed and the research items agreed (Nov 21, 2026).

Valuation (to build):

- [ ] A14. `[scenarios]` has Pessimistic, Base and Optimistic, each metal set on its own; changing one metal of one
  deck changes only the NPVs at that deck. — new test
- [ ] A15. Producer NPV covers min(reserve life, 10) years with no terminal value; NPV ≤ 0 shows "negative NPV". —
  new test
- [ ] A16. Producer cash flow is OCF − sustaining re-priced by revenue mix; a blank sustaining figure falls back
  to FCF with its label. — new test
- [ ] A17. The pessimistic deck raises costs by `pessimistic_cost_increase`; base and optimistic don't. — new test
- [ ] A18. A committed project's risk-adjusted NPV is added at the company's share; an uncommitted one isn't. —
  new test
- [ ] A19. Developer overrun dilution at +15% and +30%, its test against 0.33, and capex-to-market cap. — new test
- [ ] A20. `study_stage` holds only the six values and agrees with the latest study row. — new data-file test
- [ ] A21. Royalty NPV of operating cash flow at each deck and its downside test. — new test
- [ ] A22. The buy-below price at each binding condition (the discount, the downside test), and none without an
  NPV. — new test
- [ ] A23. The validation report lists NPVs more than 2× from the independent NAV or consensus P/NAV. — new test
- [ ] A24. `setup-sheet --dry-run` places the new columns after CB, and the user has seen it. — command (user)
- [ ] A25. Every Model portfolio candidate has an NPV at the three decks with its basis shown. —
  `financials --dry-run` report
- [ ] A26. (user) The validation report has been read with the user.
- [ ] A27. README describes the valuation by tier and the decks; the roadmap marks item 6.

## Decisions

All by the user, Nov 21, 2026:

- Scope: everything in Rule's method research can quantify; explorers and takeover appeal stay with the user.
- Jurisdiction counts once, in the discount rate.
- Decks are configurable metal by metal, with no fixed ratio; the design doesn't depend on their values.
- Buy level: a discount to the base-deck NPV plus a downside test at the pessimistic deck. Royalty fair value 1.5×.
- Developers: rebuild the study cash flows at our rate and decks, with the study's own tax share.
- Developer downside test: at most 33% dilution at a 30% capex overrun.
- Production, reserves and sustaining spending are researched from the start (after the Step 0 pilot), with a
  second pass on juniors' MD&As and the FCF fallback where none is split.
- Sustaining spending is an exact trailing 12 months, rebuilt each quarter from a per-period record; capitalized
  stripping and sustaining lease payments count. Southern Copper's "maintenance and replacement" line counts;
  Freeport, Imperial and Trekor stay on the fallback.
- A study superseded by a press release has no NPV until a technical report is filed. Santa Cruz's years 19–24 are
  spread evenly over six years.

## Open questions

1. Stage probabilities (PEA 0.35, PFS 0.50, FS 0.60, permitted 0.75, construction 0.90) and assumed years to
   construction (4 / 3 / 2 / 1 / 0) are proposals in `config/settings.toml`, with their evidence, awaiting the
   user's confirmation.
2. Deck values for Pessimistic, Base and Optimistic, with sources: the user sets them when the decks are built.
   For reference, Rule's own conservative deck was about $3,400 gold (Kitco, Sept 2026, from secondary write-ups).
