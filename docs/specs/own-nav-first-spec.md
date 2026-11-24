# Our NAV first: the Sheet's P/NAV decisions use our valuation where we have one

Roadmap 6c · Status: Built Nov 23, 2026 · Depends on: 6 (valuation by tier)

Instructions for Claude Code. Follow CLAUDE.md; don't restate it here.

## Goal

Our valuation (Rick Rule's method, roadmap 6) takes precedence over an independent NAV (the user, Nov 23, 2026). The
Sheet's P/NAV decisions read the independent NAV typed in PNAV inputs R. These are the royalty buy-below price and
band, a developer's P/NAV after a raise, the Signals royalty median and the screen's royalty measure. This spec
makes them read our NAV per share wherever the valuation produced one, falling back to R (and to the study value in
S for developers) only where it didn't. R stays as the outside reference that the validation check compares against.

## Scope

- **In:**
  - `valuation.csv`'s NAV per share.
  - Two formula columns on PNAV inputs, CU and CV.
  - The four Sheet formulas that read R or AJ for a decision.
  - The Python mirror of the royalty median.
  - The screen's royalty measure.
  - `setup-sheet`'s upgrade of an installed Sheet, and the docs.
- **Out:**
  - R and AJ themselves. R is the independent NAV per share, typed by hand. AJ is the independent P/NAV, C/R, and
    stays the series that Company history records, so the royalties' own-history percentiles compare like with like.
  - The validation check against outside views.
  - `pnav.csv`'s royalty band, buy-below and NAV after a raise. `compute` builds them before `valuation` runs, and only
    its report reads them.

## Design

**Our NAV per share** (base deck) = (NPV + net cash − minority interest) ÷ shares, the figure `valuation`'s check
already computes. It goes in `valuation.csv` as `nav_per_share`. On the Sheet it is (CE + E − CT) × C ÷ D, since
shares = D ÷ C.

| Column | Header | Formula (spill from row 12) |
|---|---|---|
| CU `nav_used` | NAV per share used US$: ours ((CE + E − CT) ÷ shares) where CE has a base-deck NPV, else the independent NAV in R | ours if CE, E, C and D are numbers and C, D > 0; else R; else blank |
| CV `pnav_used` | P/NAV used: price ÷ CU (a NAV at or below zero shows "negative NAV"); developers without one: market cap ÷ (study value S + net cash) | C ÷ CU when CU > 0; else D ÷ (S + E) when S is a number |

**Readers moved to CU and CV** (`setup-sheet` upgrades the exact installed formula and header; a hand-edited one is a
conflict, left alone):

| Where | Was | Now |
|---|---|---|
| PNAV inputs AR, royalty buy-below | R × buy-zone top | CU × buy-zone top |
| PNAV inputs AS, royalty band | on AJ | on CV |
| PNAV inputs BN, NAV per share after a raise | R × shares, else S + net cash | CU × shares, else S + net cash |
| Signals E, `royalty_pnav_median` | median AJ of royalty rows with R | median CV of royalty rows with CU |

The NAV per share after a raise feeds BO (P/NAV after a raise), Model portfolio Z and the screen's developer
measure, so they follow. The Python median (`signals.royalty_pnavs_from_sheet`) reads CV and CU as the Sheet does.
Without the Sheet (`royalty_pnavs_from_derived`), it uses price ÷ `valuation.csv` `nav_per_share` for royalties we
value, and the independent P/NAV for any we don't.

**Screen:** the royalty measure `independent_pnav` becomes `pnav_used`, read from CV, with the same weight and
direction (lower is better).

## Acceptance criteria

- [x] A1. `valuation.csv` gives our base-deck NAV per share, the one the outside-view check uses. —
  `tests/test_valuation.py::test_compute_gives_our_nav_per_share`
- [x] A2. `setup-sheet` installs CU and CV as spill formulas with their headers; CU prefers our NAV and falls back to R,
  and CV falls back to the study value. — `tests/test_layout.py::test_nav_used_prefers_our_valuation`
- [x] A3. AR, AS, BN and the Signals royalty median read CU and CV, and an installed Sheet's exact old formulas and
  headers are upgraded in place. — `tests/test_layout.py::test_installed_nav_readers_are_upgraded_to_the_nav_used`
- [x] A4. Python's royalty median reads CV and CU from the Sheet, and our NAV from `valuation.csv` without it. —
  `tests/test_signals.py::test_royalty_median_uses_our_nav_first`
- [x] A5. The screen's royalty measure is the P/NAV used; superseded by the screen's revision 2, which scores no
  valuation measure (model-portfolio-screen A23). — `tests/test_screen.py::test_valuation_filters_and_measures_are_gone`
- [x] A6. The live Sheet is upgraded: `setup-sheet --dry-run` shown to the user, then `setup-sheet`, and CU, CV and
  the four readers read back without error values. — the `setup-sheet` report (Nov 23, 2026: 11 cells, no conflicts; 113 rows with a NAV used, no error values; the royalty median reads 1.73, "Normal range")
- [x] A7. CLAUDE.md (spill ranges) and the README describe CU and CV. — `grep -n "CU12" CLAUDE.md` and `grep -n
  "NAV per share used" README.md`

## Decisions

- Our valuation takes precedence over an independent value (the user, 2026-11-23). R and AJ stay as the outside
  reference for the validation check and the own-history series, rather than being overwritten.
- Royalties: on Nov 23, 2026 the royalty P/NAV median is 1.89 on our NAVs against 2.31 on the independent ones, so the
  Signals thresholds (1.4, 2.2) keep their meaning. Signal history has a step at the switch date.
