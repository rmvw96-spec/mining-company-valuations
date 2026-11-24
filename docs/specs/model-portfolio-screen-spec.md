# Model portfolio from a screen

Roadmap 5 and 5b · Status: revision 1 Built Nov 20, 2026; revision 2 In progress · Depends on: 6 for revision 2
([tier-valuation-spec.md](tier-valuation-spec.md))

Instructions for Claude Code. Follow CLAUDE.md, in particular its rule that Model portfolio content (names, weights,
statuses) never goes into the repo, an issue, a log or the step summary.

## Goal

The Model portfolio tab's inputs (holdings and weights A–F, levels S, notes U–V) were typed by hand. The user holds
no miners yet and is building the portfolio from scratch. The screen holds each bucket's **best businesses**, judged
by performance per share at constant metal prices, not by price. Each row gets a **buy signal** when its price is at
good value by its tier's valuation (roadmap 6). A great company that is expensive stays on the list with no buy
signal.

## Scope

- **In:** the screen (universe, buckets, markets, filters, score, selection, weights, the write), the buy signal
  and fair-value status, and `portfolio-file`.
- **Out:** share-price return in the score (it rewards stocks that have already risen; context only); physical
  metal rows (kept as typed); bucket sizes in the repo (private).

## Changes from the build (revision 2)

- **Remove:** the valuation filters (peer norm above the review level; developers' `max_peer_ev_ratio`;
  royalties' `royalty_excluded_bands`) and the valuation score measures (`peer_norm`, `pnav_low`, `breakeven_gap`,
  `addon`, `addon_reliance`, `pnav_after`, `peer_ev_ratio`, `months_of_cash`, `pnav_used`, `own_pctile`).
- **Replace:** the score with the performance measures below; S's peer-norm level (`[portfolio_screen.review]`)
  with the buy multiple; T's status with the buy-signal order; the generated U and V lines.
- **Keep:** markets, the data, size, dilution and developer-cash filters, bucket sizes, limits, selection, weights,
  the write and `portfolio-file`.

## Design

### Privacy and files

- **Committed** (`[portfolio_screen]`): the rules, with the research behind each limit in its comment.
- **Private:** `private/screen.toml` (each bucket's total weight and number of names; neutral example in
  `config/screen.example.toml`) and `private/screen_state.json` (levels the screen wrote).
- **Output:** `out/screen/` (local: `proposal.csv`, `report.txt`, `ranking.csv`), the Sheet, and with `--email` a
  private email. The command never runs on GitHub.
- `config/portfolio.example.csv` is neutral: the four Sprott funds (SGDM, SGDJ, COPP, SLVR) and PHYS, round amounts.

### Universe and buckets

- **Universe:** PNAV inputs rows with a market cap, joined to `data/derived/pnav.csv`. No NPV is needed to be
  ranked; a company without one shows "No NPV" in its status. One row per company (Wheaton is in two funds).
- **Buckets:** `bucket_order` (Physical metal first, then Royalty, then the `[signals.timing]` buckets), mapped by
  `[portfolio_screen.buckets]` from peer group and main metal:

| Bucket | Companies |
|---|---|
| Royalty | Peer group "Royalty/streaming" |
| Gold producers | Senior or intermediate producers, main metal gold |
| Growth: expanding producers | Junior gold producers, or producers whose reserve life or a study shows output rising |
| Copper producers; Silver and polymetallic producers | Producers by main metal |
| Growth: developers | Developers (split by metal in `[signals.timing]`) |

- **Main metal:** the largest revenue share (PNAV inputs J:L) for producers; the resource unit (AU) for developers.
- **Overrides:** `bucket` and `bucket_note` in `pnav_companies.csv` (a classification, not membership).
- Royalty needs no `[signals.timing]` entry: W already shows a royalty company's bands, and an entry would change
  W's formula.

### Markets (`[portfolio_screen.markets]`)

- **Default:** a US listing (exchange or ADR) or a Canadian listing (TSX, TSX-V, CSE). Fidelity's IRA fees (in the
  settings comments; check the schedule yearly) make other markets cost about $50 a trade.
- **`--all-markets`:** adds the rest, marked `foreign_fee_note`.
- **Canada without a recorded US OTC symbol:** eligible and marked `canada_rep_note` ($32.95, rep-assisted);
  `canada_rep_assisted = false` drops them.
- **Thin OTC ADRs:** out unless `--all-markets` when the median daily dollar volume over 3 months (no-trade days
  count as $0) is below `otc_adr_min_dollar_volume`.
- **Listing columns** in `pnav_companies.csv`: `us_listing`, `canada_listing`, `us_otc_symbol` (with "DTC eligible"
  only where confirmed; never guessed), `listing_source`. A row not researched counts as foreign-only.

### Hard filters (`[portfolio_screen.filters]`)

- **Market:** as above.
- **Data:** financials (Holdings N) within `financials_max_days`; price date (Holdings T) within `price_max_days`.
- **Size:** market cap at least `min_mcap_m` ($300M; producers, royalties) or `min_mcap_developer_m` ($100M; developers).
- **Dilution:** 3-year share change at most `max_share_change_3y_pct` (30%), or 100% for expanding producers (they
  build and merge with shares).
- **History:** at least `min_history_years` (3) of the performance measures, else "too little history", not ranked.
- **Developers:** the developer check isn't "Short of cash".
- **No price, valuation or jurisdiction filter.** Value only drives the buy signal; country risk is in the
  discount rate.

### Score: business performance per share

Per share with each year's share count, **at constant metal prices** (each year re-priced to the base deck with
the valuation's price adjustment), over the last 3 fiscal years with data:

| Bucket | Measures (better = higher unless marked) |
|---|---|
| Producers | Cash flow per share growth (OCF − sustaining; FCF where not recorded, labelled); attributable production per share growth; reserves plus M&I resources per share growth (category weights as roadmap 3); cash margin through the cycle (average and lowest year of cash flow ÷ revenue); 3-year share change (lower); net cash, % of market value; AISC margin at the base deck (roadmap 4a; the breakeven until then) |
| Royalty | OCF per share growth; attributable GEOs sold per share growth; cash margin through the cycle; 3-year share change (lower) |
| Developers | Resource per share growth by category weight; study progress over 3 years (PEA → PFS → FS → permitted → construction; `projects.csv` dates, `study_stage`); exploration and development spending ÷ all spending, and G&A ÷ all spending (lower); risk-adjusted NPV per share across successive studies at a constant deck; 3-year share change (lower) |

- **Computed** in `minerval/performance.py` from Yahoo's annual figures (up to the last four fiscal years, three
  years of change) and the monthly COMEX closes: each year's cash flow + cash_flow_share × revenue × (base ÷ that
  year's average price − 1) by revenue mix, ÷ that year's share count. OCF − sustaining only when sustaining is
  recorded for every year of the window, else FCF for every year, labelled. Growth is the fitted slope over the
  mean size, a year (it works through a change of sign).
- **Developers:** study progress = the stage now (`study_stage`) less the latest study recorded by three years ago
  (none counts as 0); spending = cash used in operations + capital spending, with G&A (SG&A where G&A isn't
  reported) from Yahoo; the NPV per share across studies values each recorded study (superseded ones too) at the
  base deck as of its date, at the rate from the last `valuation`.
- Rank percentiles within the bucket; a measure a company lacks is left out of its average, and the report says how
  many it had.
- Production, reserves, resources and GEOs per year are research inputs (filings, with sources; never estimated):
  `data/research/operations.csv`, one row per company, year end, measure (`production`, `resources`, `geo_sold`),
  category (`reserves`, `mi` exclusive of reserves, `inferred`) and metal, in gold ounces at the base deck's prices
  per share (metals outside the deck are left out; royalties' GEOs as published).

### Sizes, limits, selection and weights

- **Sizes:** `private/screen.toml`, written once by `screen --init` from the tab; the user edits it afterwards.
- **Limits** (`[portfolio_screen.limits]`; warnings, not stops): per-name cap `max_name_weight` (6%) or
  `max_name_weight_speculation` (3%); speculation at most `max_speculation` (25%); developers `min_developers`
  (6) to `max_developers` (15) when held; Royalty `royalty_names` (2–4).
- **Selection:** the top N per bucket. A name on the tab stays while it ranks within N + `buffer` and passes the
  filters (`buffer` = 0 while nothing is bought; 2 once holdings are bought); one that fails a filter is dropped
  with the reason.
- **Weights:** each bucket's weight split equally (optional `tilt` by score, default 0), the cap spreading the
  excess; fewer eligible names than N keeps the leftover in the bucket up to the cap and reports the rest as
  unallocated. Physical rows keep their typed weights and the screened weights are scaled so F sums to 1.
- The silver rule in G (PSLV first, from C4) is unaffected: PSLV is a Physical metal row, silver stocks keep E =
  "Silver".

### Buy signal and fair value (revision 2)

- **Levels:** `[valuation.buy]` by tier (tier-valuation spec, Part 5).
- **S:** the row's buy multiple from the rule. A level typed by hand is kept (it differs from
  `private/screen_state.json`); `--rule-review-levels` resets typed levels to the rule.
- **Buy-below price:** AA, after Z (placed by `setup-sheet`), US$ per share at S, a formula over PNAV inputs, so it
  moves with financials and decks: the valuation's own price (CQ) at the rule's multiple; a typed multiple
  re-priced the same way (producers and royalties (min(S × base NPV, pessimistic NPV) + net cash − minority) ÷
  shares; developers the +30% overrun case, spread over the shares after the raise). Every company gets one on
  PNAV inputs (roadmap 6).
- **Check:** `screen`'s report compares T and AA with the same rule in Python, row by row, and names rows whose B
  doesn't look up on PNAV inputs.
- **T (formula), in order:** "No NPV: <why>"; "Fails downside test"; "Buy: below US$<price>" (with the price in
  the listing's currency); "Above fair value: review"; "Hold". Physical metal rows (no S) stay blank.
- **Alerts:** a change in T is emailed privately by `prices` (`alerts.notify_portfolio`).
- **Review on performance:** a row whose score falls below its bucket's cut is listed by the next `screen` run.

### The command

`python -m minerval screen` reads PNAV inputs, P/NAV, Holdings, Holdings downside and the Model portfolio.

- **Default (dry run):** writes `out/screen/`: each bucket's ranked eligible companies with score and measures
  (`ranking.csv` has each measure's percentile), exclusions with the filter, limit warnings, and the proposal against
  the tab (added, kept, dropped with why, weight changes). Shown to the user before any write.
- **`--init`:** writes `private/screen.toml` from the tab (never overwrites).
- **`--write`:** Model portfolio rows 6–31, Physical metal rows first, then buckets in `bucket_order`:
  - A–F: bucket, holding (the P/NAV tab's name exactly), where it trades (from the listing columns), Sprott ticker
    (Holdings downside L; a kept holding keeps its tab ticker), main metal, weight. S as above.
  - U: a generated line starting "Screen:", from the measures; V: for a new row, "Screen: review above fair value,
    or if it fails a filter". Text the user typed (not starting "Screen:") is kept.
  - More than 26 rows stops the write (rows can't be added below 31). Leftover rows are cleared. G–R, T and W–Z are
    never written.
  - Before: save A6:V31 with formulas to `out/screen/backup-<time>.json`; stop if any B isn't on the P/NAV tab or any
    D isn't on Holdings downside L. After: read back H, K and T and report lookups that failed.
  - Then runs `portfolio-file`. `--email` sends the summary of changes privately.

### `portfolio-file`

Reads Model portfolio A–F, B3 and C4 and writes `private/portfolio.csv` for `backtest` and `project` (keeping the
old file as `private/portfolio.<date>.csv`): key = D, label = B, group = A, metal = E, amount_usd = F × (B3 + C4),
already_held = "yes" only for the PSLV silver covered by C4, yahoo from Holdings P (`physical_symbols` for the
trusts), `toronto_listing_in_cad` for .TO/.V symbols quoted in CAD, `first_month` carried over. The report gives
the row count, never names or amounts.

## Acceptance criteria

Revision 1 (built Nov 20, 2026):

- [x] A1. Companies map to buckets, Royalty included; the override wins; a developer's metal is its resource
  unit. — `tests/test_screen.py::test_bucket_mapping`, `tests/test_screen.py::test_bucket_override_wins`,
  `tests/test_screen.py::test_developer_metal_from_the_resource_unit`
- [x] A2. US and Canadian names pass by default; foreign-only names need `--all-markets`; Canada rep-assisted is
  kept or dropped by the setting; "where it trades" reads from the listing columns. —
  `tests/test_screen.py::test_markets_and_where`, `tests/test_screen.py::test_all_markets_lets_foreign_names_in`
- [x] A3. Thin OTC ADRs are left out unless `--all-markets`, with no-trade days at $0. —
  `tests/test_screen.py::test_thin_otc_adrs_are_left_out_unless_all_markets`,
  `tests/test_screen.py::test_dollar_volume_counts_missing_days_as_zero`
- [x] A4. Each hard filter fails at its edge and passes inside it, with expanding producers' own dilution limit
  and the developer filters. — `tests/test_screen.py::test_each_filter`, `tests/test_screen.py::test_filter_edges_pass`,
  `tests/test_screen.py::test_a_good_company_passes`,
  `tests/test_screen.py::test_expanding_producers_have_their_own_dilution_limit`,
  `tests/test_screen.py::test_developer_filters`
- [x] A5. There is no jurisdiction filter. — `tests/test_screen.py::test_no_jurisdiction_filter_unless_configured`
- [x] A6. Rank percentiles; a missing measure is left out of the average. — `tests/test_screen.py::test_rank_pct`,
  `tests/test_screen.py::test_score_averages_the_measures_each_company_has`
- [x] A7. A held name at rank N + buffer stays and one below is replaced. —
  `tests/test_screen.py::test_select_with_the_turnover_buffer`
- [x] A8. Weights: equal split, tilt, the cap and unallocated weight. —
  `tests/test_screen.py::test_weights_equal_cap_and_unallocated`
- [x] A9. The plan keeps physical rows and typed U and V, scales weights so F sums to 1, and reports drops. —
  `tests/test_screen.py::test_plan_keeps_physical_scales_weights_and_keeps_typed_levels`
- [x] A10. A typed S is kept, a screen-written S follows the rule, and `--rule-review-levels` resets typed ones. —
  `tests/test_screen.py::test_a_level_written_by_the_screen_follows_the_rule_and_rule_levels_resets_typed_ones`
- [x] A11. Warnings for more than 26 rows, speculation, developer count and too few eligible names. —
  `tests/test_screen.py::test_plan_warnings`
- [x] A12. The write touches only A–F, S and U–V, clears leftover rows, and stops past 26 rows. —
  `tests/test_screen.py::test_write_rows_touches_only_the_inputs_and_clears_the_rest`
- [x] A13. `portfolio-file` rows and columns match what the backtest reads. —
  `tests/test_screen.py::test_portfolio_rows`,
  `tests/test_screen.py::test_portfolio_file_columns_match_what_the_backtest_reads`
- [x] A14. `--init` sizes the buckets from the tab and doesn't overwrite. —
  `tests/test_screen.py::test_init_sizes_from_the_tab`
- [x] A15. `ranking.csv` shows each measure's percentile, pick and exclusion. —
  `tests/test_screen.py::test_ranking_table_shows_each_measures_rank`
- [x] A16. Settings, listing columns and the neutral example portfolio are well formed. —
  `tests/test_data_files.py::test_screen_settings`, `tests/test_data_files.py::test_listing_columns`,
  `tests/test_data_files.py::test_example_portfolio_is_neutral`
- [x] A17. (user) The user reviewed the first dry-run report and ranking (Nov 21, 2026).
- [x] A18. The write stops when a B or D wouldn't look up. —
  `tests/test_screen.py::test_write_stops_when_a_name_or_ticker_wouldnt_look_up`
- [ ] A19. (user) `screen --write` has filled the tab with no lookup failures, and `backtest` runs on the
  `private/portfolio.csv` it wrote. — commands

Revision 2 (to build):

- [x] A20. A year's cash flow and production are re-priced to the base deck and taken per share with that year's
  share count. — `tests/test_performance.py::test_each_year_is_repriced_to_the_base_deck_per_share_with_that_years_shares`,
  `tests/test_performance.py::test_production_is_valued_at_the_base_deck_and_taken_per_share`
- [x] A21. Each performance measure, the FCF-basis label and "too little history". —
  `tests/test_performance.py::test_measures_for_a_producer_and_a_royalty`,
  `tests/test_performance.py::test_research_measures_by_tier`,
  `tests/test_performance.py::test_study_progress_counts_the_stages_moved_in_three_years`,
  `tests/test_performance.py::test_spending_shares_for_a_developer`,
  `tests/test_performance.py::test_npv_per_share_across_studies`,
  `tests/test_performance.py::test_add_fills_the_universe_by_ticker`,
  `tests/test_screen.py::test_performance_measures_by_bucket`,
  `tests/test_screen.py::test_aisc_margin_is_the_base_decks_margin_over_the_breakeven`,
  `tests/test_screen.py::test_the_why_text_labels_the_fcf_basis`, `tests/test_screen.py::test_too_little_history`
- [x] A22. Selection ignores price: an expensive company with the best score is selected, with no buy status. —
  `tests/test_screen.py::test_selection_ignores_price`
- [x] A23. The valuation filters and valuation score measures are gone from code and settings. —
  `tests/test_screen.py::test_valuation_filters_and_measures_are_gone`,
  `tests/test_screen.py::test_no_filter_on_price_or_valuation`
- [x] A24. T's status at each edge (no NPV, downside test, buy, above fair value, hold) and the buy-below price at
  each binding condition; a typed S is kept. — `tests/test_screen.py::test_status_at_each_edge`,
  `tests/test_screen.py::test_buy_below_at_each_binding_condition`,
  `tests/test_screen.py::test_a_typed_level_is_kept_and_sets_the_status`,
  `tests/test_layout.py::test_portfolio_status_and_buy_below_columns`,
  `tests/test_screen.py::test_sheet_statuses_are_checked_against_python` (Nov 24, 2026: 22 rows on the Sheet agree)
- [x] A25. `setup-sheet --dry-run` places the buy-below column after Z, and the user has seen it. — command (user;
  seen and installed Nov 24, 2026, with S reset to the rule's multiples)
- [ ] A26. Annual production, reserves plus M&I resources, and royalty GEOs for 2022–2025 are recorded with
  sources for every screened company that publishes them. — data-file test
- [ ] A27. (user) The user has set the score weighting.
- [x] A28. README and CLAUDE.md describe revision 2; the roadmap marks 5b. — `grep -n "revision 2" README.md CLAUDE.md`

## Decisions

- Royalty bucket; sizes default to the tab's split with Royalty funded from Gold producers; a typed level is kept;
  a neutral example portfolio; US and Canadian markets by default, with an option for the rest (the user,
  2026-11-20).
- Skip thinly traded OTC ADRs; no jurisdiction filter (country risk counts once, in the discount rate); turnover
  buffer 0 until holdings are bought (the user, 2026-11-21).
- Select on business performance per share at constant metal prices, with no price test; value drives a buy signal
  per row, on the Sheet and by private email (the user, 2026-11-21).
- Production and reserves are researched from the start; reserves plus M&I resources, since juniors publish
  resources more often than reserves (the user, 2026-11-21).
- Developers' measures: everything Rule states that can be quantified (the user, 2026-11-21).

## Open questions

1. **Weighting** of the performance measures, after the valuation work is settled. The likely shape: equal weights
   across themes (growth per share, margins, balance sheet and dilution), not across measures, and not tuned to the
   backtest.
2. **Period:** 3 fiscal years today (Yahoo carries 4 annual years for 220 of 237 companies); longer needs research
   from filings.
