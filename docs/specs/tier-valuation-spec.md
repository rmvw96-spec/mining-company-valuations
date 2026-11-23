# Valuation by tier: EV against a 10-year NPV at three price decks

Roadmap 6 · Status: Built Nov 23, 2026 · Depends on: 3 (developer financing),
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
- **EV / NPV:** EV = market cap − net cash + minority interest (PNAV inputs AZ; minority interest in CT, the
  balance-sheet value from Yahoo, written by `financials`), because the cash flow valued is consolidated; per-share
  prices subtract it again. 1.0 = priced at the deck's value; NPV ≤ 0 reads "negative NPV", never a number.
- **Where computed:** `valuation` (minerval/valuation.py) values every research row offline and writes
  `data/derived/valuation.csv`; `financials` writes its values to the Sheet (they change only with financials, research
  inputs or decks). EV / NPV, the downside test and the FCF yield are Sheet formulas over today's EV, so `prices`
  moves them. Reserve-life P/NAV stays as a context column.
- **Validation report:** `valuation` writes `out/valuation/report.txt`: the decks, what was valued on which basis,
  what wasn't and why, and each NAV more than `check_factor` (2×) away from the independent NAV (PNAV inputs R) or
  the consensus NAV implied by the consensus P/NAV.

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
  decision taken) and has a published study. Its risk-adjusted NPV (Part 3), at the company's share, is added;
  one whose construction is under way is valued from first production (Part 3, step 4).
- **Cost inflation:** the pessimistic deck runs with costs raised by `[valuation] pessimistic_cost_increase`
  (the existing cost-change function; roadmap 4a's company AISC improves it). Base and optimistic use reported costs.
- **Measures:** EV / NPV at each deck; sustaining FCF yield = base-deck cash flow ÷ EV; downside test: EV ≤
  pessimistic NPV with costs raised.

### Part 3: developers

- **Records:** `data/research/projects.csv`, one row per study (`studies.PROJECT_COLS`: share, study type and
  date, study prices, published NPV and rate, `discounting`, `marginal_tax_rate`, `net_revenue_share`,
  `sensitivity`, initial capex, remaining capex to completion (as the company states it, once construction is
  under way), `construction_start`, `first_production`, `permits`, `committed`, `superseded`, sources), and
  `data/research/project_cashflows.csv`, one row per study and year (`studies.CASHFLOW_COLS`: pre- and after-tax
  free cash flow, payable metal by metal; year 1 = first construction year).
- **Method** (`minerval/studies.py`, `research studies`):
  1. **Re-price each year:** after-tax cash flow + tax share × net revenue share × Σ payable × (deck − study
     price). Tax share = 1 − the study's marginal tax rate (stated, or derived from its stated terms and noted);
     the average after-tax ÷ pre-tax ratio only when there is none, flagged.
  2. **Discount** at our rate, mid-year, end-year or from the start of year 1 (`start-year`) as the study does,
     over the whole mine life.
  3. **Check:** at the study's own price and rate, the rebuild is within `check_npv` (5%) of the published NPV and
     the re-pricing within `check_sensitivity` (10% of the base NPV) of its sensitivity rows. A study that fails,
     has no cash-flow table, or is superseded by a press release without a new technical report, gets no NPV and
     says why. Years a table aggregates are spread evenly only with the user's approval.
  4. **Time:** discount from today to the construction start: the company's guided `construction_start`, else
     `[valuation.years_to_start]` by stage. Once a committed project's construction start has passed, the study's
     years from its first production year (payable metal and a positive after-tax cash flow: a commissioning year
     still carrying construction capex counts as construction) are used instead, discounted from today to the guided
     `first_production`, and the remaining capex to completion is subtracted: the capex already spent is out of the
     company's cash and isn't counted again. Without a guided first production date or a stated remaining capex the
     project isn't valued, and the report says which is missing.
  5. **Probability:** `[valuation.stage_probability]` by stage: construction (`committed`), permitted (`permits` =
     yes after at least a PFS), else the study type.
  6. **Risk-adjusted NPV** = NPV × time discount × probability × attributable share; under construction,
     (NPV from first production × time discount × probability − remaining capex) × attributable share.
  7. **Financing and overrun (Rule's financing-adjusted test):** the funding gap (roadmap 3: remaining capex −
     cash − committed funding) at the study's capex and at each of `capex_overrun` (+15%, +30%) is financed with
     `equity_share` (0.35) in equity at `raise_discount` (15%), the rest debt. Dilution at each overrun is shown for
     information, with a note when the +30% raise more than doubles the share count (`dilution_note_above`); it is
     priced into the buy-below price (Part 5) rather than tested against a limit.
  8. **Capex-to-market cap** = remaining capex ÷ market cap.
- **Stage column:** `study_stage` in `pnav_companies.csv` (PEA / PFS / FS / permitted / construction / none),
  filled from the free-text `stage` and checked against the latest study row.
- **Measures:** EV / risk-adjusted NPV at each deck, overrun dilution at +15% and +30%, capex-to-market cap. EV
  per weighted unit (roadmap 3) stays.

### Part 4: royalties

- NPV = operating cash flow at each deck as a perpetuity at the same discount rate, with no growth (no sustaining
  spending; new deals and discoveries are the upside). At a rate near 9% the buy level (1.0×) is about 11× cash
  flow and fair value (1.5×) about 16-17×, against the 15-20× Rule cites for precious-metals royalties.
- Kept: independent P/NAV (AJ), framework band (AS), P/OCF and own-history percentiles (BY:CA). New: EV / NPV at
  each deck and the downside test at the pessimistic deck.

### Part 5: buy level and fair value

`[valuation.buy]`, per tier:

| Tier | Buy when (both) | Above fair value (review) |
|---|---|---|
| Producers | EV ≤ 0.6 × base NPV, and EV ≤ pessimistic NPV with costs raised | EV ≥ 1.0 × base NPV |
| Royalties | EV ≤ 1.0 × base NPV, and EV ≤ pessimistic NPV | EV ≥ 1.5 × base NPV |
| Developers | Price ≤ (0.6 × base risk-adjusted NPV − the +30% overrun's extra capex + net cash + equity raised) ÷ (shares + new shares) | Price ≥ the same at the study's capex with 1.0 × NPV |

- **Buy-below price per share** (US$) = (min(buy × base NPV, pessimistic NPV) + net cash) ÷ shares, written by
  `financials`: it doesn't depend on today's price, only on the NPVs, net cash and the share count. No NPV (negative at base, inputs missing, failed check): no price, and the status
  says why.
- The evidence for the starting values is in the `[valuation.buy]` comment in `config/settings.toml`.

### Sheet

- PNAV inputs CC:CS, placed by `setup-sheet` (layout in `[sheet.pnav_inputs]`). Written by `financials`: CC the
  basis, CD:CF the NPV at each deck, CG the base-deck cash flow, CM:CO the overrun dilutions and test, CQ:CR the
  buy-below and fair-value prices, CS why there's none. Formulas: CH:CJ EV / NPV at each deck, CK the downside test,
  CL the sustaining FCF yield, CP capex-to-market cap.
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
  `tests/test_studies.py::test_all_metals_sensitivity_rows`,
  `tests/test_studies.py::test_start_year_discounting_leaves_year_one_undiscounted`
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

- [x] A14. Decks are read metal by metal and an incomplete deck is refused; changing one metal of one deck changes
  only the NPVs at that deck. — `tests/test_valuation.py::test_decks_are_read_metal_by_metal_and_must_be_complete`,
  `tests/test_valuation.py::test_changing_one_metal_of_one_deck_changes_only_that_decks_npv`,
  `tests/test_valuation.py::test_the_settings_name_the_decks_consistently`
- [x] A15. Producer NPV covers min(reserve life, 10) years with no terminal value; NPV ≤ 0 shows "negative NPV";
  no reserve life or cash flow means no NPV, with the reason. —
  `tests/test_valuation.py::test_npv_covers_the_shorter_of_reserve_life_and_horizon_with_no_terminal_value`,
  `tests/test_valuation.py::test_a_negative_npv_is_text_not_a_ratio`,
  `tests/test_valuation.py::test_no_reserve_life_or_cash_flow_means_no_npv_and_says_why`
- [x] A16. Producer cash flow is OCF − sustaining re-priced by revenue mix; a blank sustaining figure falls back
  to FCF with its label. — `tests/test_valuation.py::test_cash_flow_is_ocf_less_sustaining_repriced_by_revenue_mix`,
  `tests/test_valuation.py::test_a_blank_sustaining_figure_falls_back_to_fcf_with_its_label`,
  `tests/test_valuation.py::test_measures_ev_to_npv_fcf_yield_and_the_downside_test`
- [x] A17. The pessimistic deck raises costs by `pessimistic_cost_increase`; base and optimistic don't. —
  `tests/test_valuation.py::test_only_the_pessimistic_deck_raises_costs`
- [x] A18. A committed project's risk-adjusted NPV is added at the company's share; an uncommitted or superseded
  one isn't, and one that can't be valued is named. —
  `tests/test_valuation.py::test_a_committed_projects_risk_adjusted_npv_is_added_and_an_uncommitted_one_isnt`,
  `tests/test_valuation.py::test_a_committed_project_that_cant_be_valued_is_left_out_and_named`
- [x] A19. Developer financing at the study's capex and at +15% and +30% overruns with 35% equity, its dilution and
  doubling note, and capex-to-market cap. —
  `tests/test_valuation.py::test_overrun_financing_uses_rules_equity_share_and_notes_a_doubling`,
  `tests/test_valuation.py::test_no_remaining_capex_means_the_dilution_cant_be_priced`
- [x] A20. `study_stage` holds only the six values and agrees with the latest study row. —
  `tests/test_data_files.py::test_study_stage_holds_the_six_values_and_agrees_with_the_latest_study`
- [x] A21. Royalty NPV is a perpetuity of operating cash flow at each deck, with its downside test. —
  `tests/test_valuation.py::test_royalty_npv_is_a_perpetuity_of_operating_cash_flow_at_each_deck_with_no_cost_increase`
- [x] A22. The buy-below price at each binding condition (the discount, the downside test, developers' financing
  at a +30% overrun), and none without an NPV. — `tests/test_valuation.py::test_buy_below_price_at_each_binding_condition`,
  `tests/test_valuation.py::test_developers_buy_below_prices_in_the_dilution_of_a_30pct_overrun`,
  `tests/test_valuation.py::test_no_npv_means_no_buy_below_price_and_says_why`,
  `tests/test_valuation.py::test_the_settings_set_a_buy_level_below_fair_value_for_every_tier`
- [x] A23. The validation check flags an NAV more than 2× from the independent NAV or the consensus P/NAV. —
  `tests/test_valuation.py::test_validation_flags_npvs_more_than_twice_away_from_the_outside_views`
- [x] A24. `setup-sheet --dry-run` places the new columns after CB, and the user has seen it. — command (user):
  the dry run (23 cells, no conflicts) approved and installed Nov 22, 2026; read back with no error values
- [x] A25. The screen's report counts the candidates with an NPV at all three decks and a basis, and names the
  rest. — `tests/test_screen.py::test_report_names_candidates_without_an_npv_at_every_deck`
- [x] A26. (user) The validation report has been read with the user. — read Nov 23, 2026: coverage by tier, the
  9 flags (10-year horizon, growth not recorded, the fallback); the gaps are now tracked by roadmap 6b
- [x] A27. README describes the valuation by tier and the decks (its "Valuation by tier" section); the roadmap's
  status table tracks item 6.
- [ ] A28. (user) `[scenarios]` holds the user's Pessimistic, Base and Optimistic decks, each with a source and date,
  and `[valuation] pessimistic_cost_increase` is set.
- [x] A29. EV includes minority interest and per-share prices subtract it, in `valuation` and in the Sheet's AZ
  (CT written by `financials`; an installed EV formula is upgraded in place). —
  `tests/test_valuation.py::test_ev_adds_minority_interest_because_cash_flow_is_consolidated`,
  `tests/test_valuation.py::test_per_share_figures_subtract_minority_interest`,
  `tests/test_layout.py::test_ev_adds_minority_interest`,
  `tests/test_layout.py::test_installed_ev_is_upgraded_to_add_minority_interest`,
  `tests/test_financials.py::test_financials_writes_the_new_columns_once_set_up`
- [x] A30. A committed project whose construction is under way is valued from its first production year, at the
  guided first production date, less the stated remaining capex; without either it isn't valued, and says why. —
  `tests/test_studies.py::test_production_years_start_at_the_first_year_with_payable_metal`,
  `tests/test_studies.py::test_a_commissioning_year_still_carrying_construction_capex_isnt_a_production_year`,
  `tests/test_studies.py::test_a_project_under_construction_is_valued_from_first_production`,
  `tests/test_studies.py::test_under_construction_needs_first_production_and_remaining_capex`
- [ ] A31. (data) Every Model portfolio candidate has an NPV at the three decks with its basis shown: 43 of 46 on
  Nov 23, 2026; open: Koryx (PFS due early Jan 2027), KSM (its table aggregates years), Diablillos (DFS on SEDAR+
  only). — the `screen` report's Valuation line

## Decisions

All by the user, Nov 21, 2026:

- Scope: everything in Rule's method research can quantify; explorers and takeover appeal stay with the user.
- Jurisdiction counts once, in the discount rate.
- Decks are configurable metal by metal, with no fixed ratio; the design doesn't depend on their values.
- Buy level: a discount to the base-deck NPV plus a downside test at the pessimistic deck. Royalty fair value 1.5×.
- Developers: rebuild the study cash flows at our rate and decks, with the study's own tax share.
- Developers: Rule's financing-adjusted per-share test (35% equity, 15% discount, the +30% overrun's cost and
  dilution priced into the buy-below), replacing the 33% dilution limit set Nov 21 (the user, 2026-11-22; from Rule
  Investment Newsletter #22, Nov 11, 2026).
- Royalties: a perpetuity of base-deck operating cash flow, replacing 10 years (the user, 2026-11-22).
- Production, reserves and sustaining spending are researched from the start (after the Step 0 pilot), with a
  second pass on juniors' MD&As and the FCF fallback where none is split.
- Sustaining spending is an exact trailing 12 months, rebuilt each quarter from a per-period record; capitalized
  stripping and sustaining lease payments count. Southern Copper's "maintenance and replacement" line counts;
  Freeport, Imperial and Trekor stay on the fallback.
- A study superseded by a press release has no NPV until a technical report is filed. Santa Cruz's years 19–24 are
  spread evenly over six years.
- Stage probabilities PEA 0.35, PFS 0.50, FS 0.60, permitted 0.75, construction 0.90, and assumed years to
  construction 4 / 3 / 2 / 1 / 0, as researched (evidence in `config/settings.toml`) (the user, 2026-11-22).
- A committed project already under construction (Skouries, Oko West) is valued from first production, at the
  guided date, less the remaining capex the company states, rather than re-pricing the whole study from today or
  leaving it out until production (the user, 2026-11-22).
- `study_stage` (Nov 23, 2026): KSM stays PFS as recorded (its permits have no source), Marimaca is FS (an
  environmental approval isn't the full set of key permits), PDI Gold is FS (Bankan DFS June 2025; exploitation
  permit and investment decision pending); A25 split into the report check and a data follow-up (A31).
- Oko West stays unvalued until the combined Oko West / Oko-Ghanie FS (mid-2027): its gold price grid can't come
  from its own cash-flow table, so the re-pricing check fails (the user, 2026-11-22).

## Open questions

1. Deck values for Pessimistic, Base and Optimistic, with sources: the user sets them when the decks are built.
   For reference, Rule's own conservative deck was about $3,400 gold (Kitco, Sept 2026, from secondary write-ups).
2. When a committed project's production enters the trailing operating cash flow, it must leave the pipeline (or
   be counted twice). Proposed: drop it once a full year of production is in the trailing 12 months, by
   `first_production` against the company's financials date; until then the partial year is counted twice.
