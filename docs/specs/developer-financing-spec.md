# Developers: financing, dilution, and resource quality

Roadmap 3 · Status: Built Nov 18, 2026 · Depends on: market signals (the developer checks, PNAV inputs AX:BE)

Instructions for Claude Code. Follow CLAUDE.md (Sheet safety, the installer pattern in `minerval/layout.py`).

## Goal

The first developer checks had three gaps. The cash runway ignored committed financing (Skeena showed 1.4 months of
cash while building with an arranged project-finance package). There was no view of what a raise would cost
holders. And EV per ounce counted an inferred ounce the same as a reserve ounce. Fix all three.

## Scope

- **In:** committed funding and a funding gap; the expected raise and P/NAV after it; EV per weighted ounce and its
  peer ratio.
- **Out:** developers' corporate costs in the gap (no source gives them consistently, and study capex mostly
  includes owner's costs); estimated figures of any kind (blank where a filing doesn't say).

## Design

- **Research inputs** (PNAV inputs BF:BI and the same columns in `pnav_companies.csv`, each with its source and
  date): `committed_funding_usd_m` (undrawn debt, streams, equity, and construction cash held in escrow, which
  Yahoo's cash leaves out), `remaining_capex_usd_m` (to first production, from the latest study or update),
  `funded_per_company` (a company's own "funded to production" statement, when it publishes no cost-to-complete).
- **Runway:** `months_of_cash` (BC) = (cash + committed funding) ÷ monthly burn; BJ keeps the cash-only figure.
- **Funding gap** = remaining capex − cash − committed funding. `developer_check` (BE): "Fully funded" at a gap
  ≤ 0, "Funding gap $Xm" above, "Funded to production (company says)" from `funded_per_company`, else the runway
  rule.
- **Raise** (gap > 0; equity, the pessimistic case, said in the header): new shares = gap ÷ (price × (1 −
  `raise_discount`)); NAV per share after = (NAV + raise) ÷ (shares + new shares), NAV from PNAV inputs R or S;
  P/NAV after = price ÷ that; dilution = new shares ÷ shares. Formula columns on PNAV inputs, and P/NAV after on
  the Model portfolio (Z); `pnav.compute()` mirrors them and the post-install check compares.
- **Weighted resource** = reserves × 1.0 + M&I excluding reserves × 0.5 + inferred × 0.2 (`resource_weight_*`).
  AT stays the total; a single-category total is weighted as that category, and the split columns (BP:BR) are
  needed only for "Mixed" and "Measured, indicated & inferred" rows. A missing category counts as zero, and the row
  says which. EV per weighted unit sits beside the unweighted one, with each row's ratio to its peer group's median
  (BW).
- **Shared inputs:** `raise_discount` and the resource weights are Signals inputs (`[signals.inputs]`, seeded on
  the Signals tab), so the Sheet and Python read the same values.
- **Installer:** `setup-sheet` adds the columns, and upgrades BC, BE and Model portfolio Y5 in place only where they
  still hold the first formulas and headers.

## Acceptance criteria

- [x] A1. The runway counts committed funding; the gap is computed. —
  `tests/test_pnav_and_price_model.py::test_runway_counts_committed_funding_and_the_gap`
- [x] A2. The developer check's texts at each boundary, including the company's own statement. —
  `tests/test_pnav_and_price_model.py::test_developer_check_with_financing`
- [x] A3. The raise worked example: gap $100M, price $10, discount 15%, 50M shares, NAV $800M → 11.76M new shares,
  NAV per share after $14.57. — `tests/test_pnav_and_price_model.py::test_raise_maths_worked_example`
- [x] A4. Weighted resource with missing categories. — `tests/test_pnav_and_price_model.py::test_weighted_resource`
- [x] A5. The financing columns in `compute()` match the formulas. —
  `tests/test_pnav_and_price_model.py::test_financing_columns_in_compute`
- [x] A6. The research columns are well formed (numbers ≥ 0, a source wherever a number is filled). —
  `tests/test_data_files.py::test_financing_and_split_columns`
- [x] A7. The installer seeds from the research file, upgrades first installs in place, leaves hand-edited formulas
  alone, writes nothing on a second run or a dry run, and skips an occupied cell. —
  `tests/test_layout.py::test_financing_seeds_come_from_the_research_file`,
  `tests/test_layout.py::test_first_install_is_upgraded_in_place`,
  `tests/test_layout.py::test_a_hand_edited_check_formula_is_left_alone`,
  `tests/test_layout.py::test_second_run_writes_nothing`, `tests/test_layout.py::test_dry_run_writes_nothing`,
  `tests/test_layout.py::test_occupied_cell_skips_the_step`
- [x] A8. Skeena's check reflects its arranged financing, and the first set of developers has figures with sources
  (Nov 18, 2026). — `financials` report
- [ ] A9. Every Model portfolio developer has P/NAV after a raise or a "Fully funded" label. Known gaps: FireFly's
  committed funding (not confirmed); Collective Mining's and Viscaria's resource split; Seabridge's gap is KSM's
  whole PFS capex, which a JV partner would largely fund.
- [x] A10. README's developer section and CLAUDE.md's input and spill columns describe it.

## Decisions

- The funding gap leaves out corporate costs, and a company's "funded to production" statement is used rather than
  an estimated cost-to-complete (2026-11-18).
