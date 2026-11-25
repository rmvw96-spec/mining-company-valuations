# To-do

The open work as of Nov 25, 2026, after PR #31. The [roadmap](roadmap.md) status table shows what each item's spec
has built; this list says what's left and where to start.

- **Links** go to files in the repo.
- **Paths in `code`** are local files on the working machine. They're ignored by git, so they aren't on GitHub.
- **Holding names, weights and statuses** never go here (CLAUDE.md, ground rules). Anything about the Model
  portfolio's own rows is in the local note `private/session-2026-11/NOTES.md`.

## Next, in order

### 1. Score weighting (roadmap 5b, A27; the user decides)

- **Today:** the 13 performance measures are weighted equally (1.0 each).
- **The problem:** `explore_dev_share` and `ga_share` are complements, so together they count double for developers.
- **The likely shape (the spec):** equal weights across themes, not across measures. The themes are growth per
  share, margins, and balance sheet and dilution. The weights aren't tuned to the backtest.
- **Next step:**
  1. Claude drafts the theme weights in the settings, with the reasoning in the settings comment.
  2. The user approves them.
  3. Tick A27 and update the 5b row of the roadmap.
- **Sources:**
  - [settings, `[portfolio_screen.score]`](../config/settings.toml#L478)
  - [the screen spec's open question 1](specs/model-portfolio-screen-spec.md#open-questions) and
    [A27](specs/model-portfolio-screen-spec.md#acceptance-criteria)
  - [minerval/performance.py](../minerval/performance.py), which computes the measures

### 2. Production, reserves and royalty GEOs, 2022–2025 (roadmap 5b, A26; research, large)

- **Today:** [data/research/operations.csv](../data/research/operations.csv) has only its header row. Until it's
  filled, the production, reserves, resource and GEO growth measures are left out of every score.
- **What to record:** one row per company, year end, measure and metal, from the filings, with a source for each
  figure. Never estimate.
  - Measures: `production`, `resources` and `geo_sold`.
  - Resource categories: `reserves`, `mi` (excluding reserves) and `inferred`.
  - Units: oz, koz, Moz, lb, Mlb, Blb, t or kt. The code converts them to gold ounces at the base deck and
    divides by each year's share count.
  - Format: the spec's Design section, "Production, reserves, resources and GEOs per year"
    ([screen spec](specs/model-portfolio-screen-spec.md#design)), and `OPERATIONS_COLS` in
    [minerval/performance.py](../minerval/performance.py).
- **Which companies:** every screened company that publishes the figures. The candidates by bucket are in the last
  `screen` run's `out/screen/ranking.csv` (local). Suggested order:
  1. Royalty: few companies, and each annual report has a GEO table.
  2. Producers.
  3. Developers: resources only.
- **Where the figures are** ([CLAUDE.md, Research](../CLAUDE.md#research-company-filings)):
  - Production: the MD&A highlights table, which often covers three years.
  - Reserves and resources: the year-end reserve release or the AIF. Check attributable against 100%.
  - GEOs: the royalty companies' annual reports and MD&As.
- **Already downloaded:**
  - [data/research/sources.csv](../data/research/sources.csv) logs every document read so far.
  - `cache/research/` holds the documents fetched by `research fetch`.
  - `private/session-2026-11/scratchpad/` holds the Nov 21–25 downloads by company folder (MD&As, annual reports,
    ASX quarterlies, technical reports).
- **Helpers (local):**
  - `private/session-2026-11/scratchpad/tools/`:
    - `asx.py`: ASX announcement lists and PDFs.
    - `inv.py`: Investegate, for London.
    - `secgrep.py` and `pgrep.py`: grep EDGAR rows.
    - `add_capex.py`: the pattern for appending rows by column name.
  - The project skill `.claude/skills/sustaining-research-batch/SKILL.md`: the batch loop and tie-out checks.
- **Proof:** A26 names a data-file test. Write it with the first batch: every row well formed, with a source and a
  known unit, measure and category.

### 3. `refresh`, for the developers' G&A

- **Why:** `cache/fundamentals.json` (Nov 22) has none of the G&A series the developer spending shares read
  (`annualGeneralAndAdministrativeExpense`, `annualSellingGeneralAndAdministration`). Until a `refresh`, those two
  measures are blank.
- **Run:** `refresh`, then `valuation`, then `financials --dry-run` and `financials`, in the
  [run order](../CLAUDE.md#commands-and-run-order).

### 4. First `screen --write` (roadmap 5, A19; the user runs it)

- **Before it:**
  - Items 1–3.
  - Fix the one Model portfolio name in column B that PNAV inputs doesn't have. The last lines of `screen`'s report
    name it, and so does the local note. The write stops while a name doesn't look up (A18).
- **Then:**
  1. `screen`, and show the user `out/screen/report.txt`.
  2. `screen --write`, with `--email` for the private summary.
  3. `backtest` on the `private/portfolio.csv` the write produces.
- **Sources:** [screen spec A19](specs/model-portfolio-screen-spec.md#acceptance-criteria) and the
  [run order](../CLAUDE.md#commands-and-run-order).

### 5. Producer costs (roadmap 4a; not started, 0 of 8)

- **What it does:** replaces the cost base inferred from revenue minus cash flow with reported AISC, and turns the
  diesel signal into a cost increase for each company from its energy exposure.
- **Independent of the screen.** Its result would inform `pessimistic_cost_increase` (below).
- **Open question:** the default energy shares by mine type, and their source.
- **Spec:** [producer-costs-spec.md](specs/producer-costs-spec.md).

## Decisions for the user (no deadline)

| Decision | Where | Note |
|---|---|---|
| Base deck: keep it or lower it | [settings `[scenarios]`](../config/settings.toml#L38), [tier spec A28](specs/tier-valuation-spec.md#acceptance-criteria) | Base (gold 4,550, silver 64.875, copper 6.49) sits above Dec 2027 COMEX futures (3,820 / 45.22 / 5.89, Nov 20–23, 2026). |
| Set `[valuation] pessimistic_cost_increase` | [settings `[valuation]`](../config/settings.toml#L350), [tier spec A28](specs/tier-valuation-spec.md#acceptance-criteria) | Not set, so the pessimistic deck uses reported costs, and `valuation`'s report says so. |
| When a committed project leaves the pipeline | [tier spec open question 2](specs/tier-valuation-spec.md#open-questions) | Proposed: once a full year of its production is in the trailing 12 months. |
| KSM's aggregated years | [coverage.csv](../data/research/coverage.csv) (SA, study) | Spread Table 22.5's aggregated years evenly, as was approved for Santa Cruz, or wait for a report. Either way KSM has no NPV yet (tier A31). |
| The screen's period | [screen spec open question 2](specs/model-portfolio-screen-spec.md#open-questions) | 3 fiscal years today. A longer period needs research from the filings. |
| Read the signal backtest report | [signal backtest spec A10](specs/signal-backtest-spec.md#acceptance-criteria) | `out/backtest-signals/report.txt` (local). A threshold changes in settings and Signals G:H together. |
| Review the jurisdiction comparison | [jurisdiction spec A8](specs/jurisdiction-risk-spec.md#acceptance-criteria) | `out/jurisdiction/comparison.csv` (local), including the developers' add-ons from Nov 21. |
| Google sign-in: set the OAuth consent screen to "In production" | `~/.claude/skills/gspread-oauth-token-expired/SKILL.md` (local) | The local token lasts 7 days while the screen is in "Testing". It was renewed Nov 25, 2026, so local runs fail from about Dec 2. GitHub's service account isn't affected. |

## Waiting on data

| Due | What | Then | Where |
|---|---|---|---|
| Nov 30, 2026 | Blue Moon's Nussir sale closes | Decide how to value Blue Moon. Also developer financing A9. | [coverage.csv](../data/research/coverage.csv) (MOON) |
| Early Dec 2026 | WGC Q3 2026 AISC (Gold Demand Trends) | Add a row with its source and publication date. | [industry_aisc.csv](../data/research/industry_aisc.csv), [signal backtest A9](specs/signal-backtest-spec.md#acceptance-criteria) |
| Jan 2027 | Koryx Haib PFS technical report | Record its cash flows (skill `.claude/skills/mine-study-rebuild/`). | [coverage.csv](../data/research/coverage.csv) (KRY), [tier A31](specs/tier-valuation-spec.md#acceptance-criteria) |
| Mar 2027 | Bullabulling DFS (MI6); Eskay Creek and Snip report (SKE) | Record each study. | [coverage.csv](../data/research/coverage.csv) |
| Apr–May 2027 | FY2026 sustaining capital (HMMC, AAZ) | Record it in capex_periods.csv. | [coverage.csv](../data/research/coverage.csv) |
| Jun 2027 | Oko West / Oko-Ghanie combined feasibility study (GMIN) | Record the study. | [coverage.csv](../data/research/coverage.csv) |
| Undated | Developer financing gaps: FireFly's committed funding, Osisko Metals (no study yet), Viscaria's resource split, Seabridge (KSM's PFS capex) | Update BF:BI and pnav_companies.csv together, with sources. | [developer financing A9](specs/developer-financing-spec.md#acceptance-criteria) |
| Undated | Diablillos: a study with an annual cash-flow table (its DFS gives life-of-mine totals only) | Record the study. | [coverage.csv](../data/research/coverage.csv) (ABRA) |

## Recurring

- **Earnings season** (Q4 filings, February–March 2027):
  - the [earnings-season refresh](../CLAUDE.md#earnings-season-refresh), including the `waiting` and
    `not published` rows in coverage.csv;
  - new [capex_periods.csv](../data/research/capex_periods.csv) rows;
  - `royalty-ocf` after the royalty companies' 10-K and 40-F, written to
    [royalty_ocf.csv](../data/research/royalty_ocf.csv).
- **Fraser Institute survey** (first half of 2027): the jurisdiction step in CLAUDE.md.

## Local files from the Nov 21–25, 2026 session

| Path (local) | What |
|---|---|
| `private/session-2026-11/NOTES.md` | Private handoff: the Model portfolio row to fix, sign-in and backup notes. |
| `private/session-2026-11/scratchpad/` | The whole session scratchpad, copied (589 files, ~780 MB): research downloads by company folder, `tools/` (helper scripts and the study parsers), and the logs and before/after snapshots of the valuation and financials runs. |
| `out/screen/backup-before-rev2-20261124-071038.json`, `out/screen/backup-before-column-cleanup-20261125-*.json` | Model portfolio backups, with formulas, from before revision 2 and before the column cleanup. |
| `private/screen_state.json` | The screen's state as of Nov 24, 2026. |
| `cache/research/` | Documents fetched by `research fetch`. |
| `.claude/skills/` | Project skills, kept out of git: `mine-study-rebuild`, `sheet-column-block`, `sustaining-research-batch`. |
| `~/.claude/skills/gspread-oauth-token-expired/` | Global skill: renewing the local Google sign-in. |
