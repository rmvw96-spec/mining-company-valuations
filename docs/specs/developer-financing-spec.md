# Developers: financing, dilution, and resource quality

Instructions for Claude Code. Roadmap item 3. Follow CLAUDE.md (Sheet safety and the installer pattern in
`minerval/layout.py`; never write into spill ranges).

## Goal

The developer checks added in PR #5 (PNAV inputs AX:BE, Model portfolio X:Y) are a good first cut, with two gaps
the Q3 refresh made visible:

1. **Cash runway ignores committed financing.** Skeena shows 1.4 months of cash ($59M against $507M a year of
   spending), but it is building with a project-finance package. The check says "Short of cash: financing likely"
   for a company whose financing is already arranged. Column BE's header already warns about this.
2. **No view of what a raise would cost existing holders.** For a developer that does need money, the question
   is how much NAV per share is left after the raise.
3. **EV per ounce treats all ounces alike.** An inferred ounce in Mexico and a reserve ounce in Nevada count the
   same.

## Part 1: committed financing

- New research columns in `data/research/pnav_companies.csv` and PNAV inputs (inputs, next free columns after BE;
  confirm on the Sheet): `undrawn_facilities_usd_m` (committed but undrawn debt, streams and equity), `facilities_source`
  (document and date), `remaining_capex_usd_m` (to first production; from the latest study or company update).
- `months_of_cash` becomes: (cash + undrawn facilities) ÷ monthly burn. Keep the old figure as `months_of_cash_only`
  so both are visible.
- New funding check: **funding gap** = remaining capex + 12 months of corporate costs − cash − undrawn facilities.
  `developer_check` uses the gap when remaining capex is filled in: "Fully funded" (gap ≤ 0), "Funding gap $Xm"
  otherwise; falls back to the runway rule when it isn't.
- Fill these for the developers on the Model portfolio first (read the list from the Sheet; don't write it into
  the repo, which is public), then the rest of the developer rows, each with a source. Blank where unknown: never estimate.

## Part 2: expected raise and NAV after it

For rows with a funding gap > 0:

- **Raise** = the gap, assumed raised in equity at a discount to today's price (`[developers] raise_discount`,
  default 0.15; a comment saying it's the typical bought-deal discount and the user can change it).
- **New shares** = raise ÷ (price × (1 − discount)).
- **NAV per share after** = (NAV + raise) ÷ (shares + new shares), where NAV is the independent model NAV or study
  value already on PNAV inputs (R or S). **P/NAV after** = price ÷ NAV per share after.
- **Dilution** = new shares ÷ shares.
- Show these on PNAV inputs (formula columns, spilled like AZ:BE, created by `setup-sheet`) and add P/NAV after
  to the Model portfolio developer rows (a new spill column after Y).
- Python mirrors the formulas in `pnav.compute()`; the post-install check compares them, as today.

Equity is the pessimistic case (debt and streams dilute less). Say so in the column header.

## Part 3: EV per ounce by resource category

- Today AT:AW hold one resource figure and its category. Allow the split: `resource_mi` and `resource_inferred`
  (both in the unit in AU), plus `reserves` where published. Keep AT as the total for compatibility, or replace
  it; decide in the PR and migrate the 29 filled rows from their sources.
- **Weighted ounces** = reserves × 1.0 + M&I (excluding reserves) × 0.5 + inferred × 0.2 (weights in
  `[developers] resource_weights`, commented as conventional rules of thumb).
- New column: EV per weighted gold-equivalent ounce. Keep the unweighted one.
- Peer comparison: median EV per weighted oz within the peer group (AL), and each row's ratio to it.

## Tests (offline)

- Runway with and without facilities; funding gap and the new check texts at the boundaries.
- Raise maths on a worked example (gap $100M, price $10, discount 15%, 50M shares, NAV $800M → new shares
  11.76M, NAV/share after $14.57).
- Weighted ounces with missing categories (missing counts as zero, and the row says which are missing).
- Data-file validation for the new columns (numbers ≥ 0, a source wherever a number is filled).
- Installer: dry run on a MemorySheet, idempotent rerun, refuses to overwrite a non-empty target.

## Docs

README (developer section), CLAUDE.md (new input and spill columns; what-not-to-touch).

## Done when

Skeena's check reflects its arranged financing, every Model portfolio developer has P/NAV after a raise or a
"Fully funded" label, and the sources are in the CSV.
