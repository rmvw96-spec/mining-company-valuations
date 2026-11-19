# Notes for Claude: maintaining the miner ETF valuations

README.md explains the project for people; this file is how Claude should run and change it.
Planned work is in `docs/roadmap.md`, with a spec for each item in `docs/specs/`.

## Ground rules

- Run everything from the repo root as `uv run python -m minerval <command>`. `uv run python -m pytest` and `uv run ruff check`
  must pass before any commit (CI runs the tests on Python 3.11 and 3.14, and ruff). Tests must stay offline: `tests/conftest.py`
  fails any test that reaches Yahoo, and the Sheet is a `MemorySheet`.
- Never commit `private/`, `cache/`, `out/` or `data/derived/` (they're in .gitignore), or any credentials.
  The repo is public: no personal amounts, account details or names in committed files.
- Ask the user before every `git push`.
- Model portfolio content (holding names, statuses, weights) never goes into a GitHub issue, a log, a report or the
  step summary: it is emailed only (`alerts.notify_portfolio`). Signal issues carry market data only.
- The Google Sheet is the working copy of the research inputs (PNAV inputs I–L and P–S, scenario prices,
  peer multiples). `data/research/pnav_companies.csv` and `config/settings.toml` [scenarios] are the record:
  when the user changes one, offer to update the other. The exception is the jurisdiction add-on (PNAV inputs P)
  of a company with `country_weights`: `data/research/country_risk.csv` is its record and `financials` writes it,
  so change the table, the weights or `addon_override` (with a note), not the cell.
- Sheet layout is configured in `config/settings.toml` [sheet]. The commands check headers and stop if they
  don't match; if that happens, find out what moved before changing the config.

## Commands and run order

| When | Command | Writes |
|---|---|---|
| Daily, after 4 pm New York | `prices` (`--dry-run` first if anything looks off); it runs `signals` at the end | Holdings R–T, FX table Y–AB; Metal prices reference C15:C17, C30; Signals E–F; Signal history and Company history (today's rows) |
| On its own, if needed | `signals` (`--dry-run`) | Signals E–F; Signal history, Company history; out/signals/ |
| Once, or after adding a signal | `history --backfill 2022-01-01` (`--dry-run` first) | Signal history (past dates) |
| After earnings season | `prices --shares` | Holdings U (review >10% changes in the report) |
| After earnings season | `refresh` = `fetch` + `compute` | cache/, data/derived/ |
| After `refresh` | `financials --dry-run`, then `financials` | Holdings I–N, Q; Holdings downside D–J, M–R; PNAV inputs E–H, M–O, AX–AY, and P for country-table rows |
| After `financials` | `snapshots --dry-run`, then `snapshots` | Summary A1, A4:K9; Metal prices reference B2, B6:K11; Stress test & downside B2 and its five tables |
| After changing `country_risk.csv` or `country_weights` | `jurisdiction` (review out/jurisdiction/comparison.csv with the user), then `compute` and `financials` | PNAV inputs P |
| Once, and after changing `[sheet]` layout settings | `setup-sheet --dry-run`, show the user, then `setup-sheet` | Signals tab; PNAV inputs H7, Z:AC, AR:BX; P/NAV U:W; Holdings downside K2, R; Model portfolio W:Z |
| Occasionally | `fetch-history`, `backtest`, `project` | out/backtest/ |
| After changing a signal or threshold, or yearly | `backtest-signals` (`--refresh` to download again) | out/backtest-signals/ |
| When the WGC publishes a quarter's AISC (Gold Demand Trends, ~a month after quarter end) | add a row to `data/research/industry_aisc.csv` with its source and publication date | the next run writes it to Signals |

`compute --today gold=..,silver=..,copper=..` reruns the offline analysis at chosen metal prices;
`--cost-increase 0.1` raises producers' costs 10%.
Reports go to `out/<command>/report.txt`.

## Routine price update (Google Sheet)

1. `uv run python -m minerval prices`. It reads the Sheet ID and credentials from `private/local.toml`
   (or `MINERVAL_SHEET_ID` / `GOOGLE_APPLICATION_CREDENTIALS`).
2. Read `out/prices/report.txt` and deal with what it flags:
   - **No price**: the row keeps its old price. Check whether the symbol changed (rename, delisting, takeover).
   - **Older than 6 days**: thinly traded or suspended.
   - **Moved more than 25% in 5 days**: check for a split or consolidation; a split changes the share count, so run `prices --shares`.
   - **Currency not in the FX table**: add a row at the bottom of Holdings!Y:AB with the code; the next run fills the rate.
3. Tell the user the price date, the biggest movers, today's metal prices, any Model portfolio rows
   whose Status (column T) changed to "Review: above level", and the signals whose status changed
   ("Changed since the last run" in `out/signals/report.txt`; on GitHub, the run's step summary, and an issue
   labelled `signals` once a change has held 3 trading days). If a
   line says "the Sheet's last values are kept", a download failed: say which and since when. If the report says the Sheet's and
   Python's statuses differ, a status formula or threshold on the Signals tab was edited: find out which. To read the Sheet from Python:
   `from minerval.sheets import open_google; open_google().read("Model portfolio", "B6:T31")`.

## Earnings-season refresh

1. `uv run python -m minerval prices --shares`, and check every share-count change over 10% (acquisitions paid
   in shares, financings, consolidations, or a US listing quoted in a different unit than the share count).
2. `uv run python -m minerval refresh`. If `fetch` reports a ticker not found or a name mismatch, fix it in
   `config/symbol_overrides.csv` and rerun.
3. `uv run python -m minerval financials --dry-run`. Look at `out/financials/report.txt`: holdings in the data
   but not on the Sheet need rows added first (README, "When Sprott's holdings change").
   `financials` also writes PNAV inputs AX:AY and Holdings downside R once `setup-sheet` has added them.
4. Check the companies with large changes and any new "Op. cash flow corrected" notes against company
   reports. Put verified replacements in `config/corrections.csv` (value in US$ millions, with source).
5. `uv run python -m minerval financials`.
6. Developers: check each Model portfolio developer's latest MD&A or quarterly for committed facilities,
   cost-to-complete or a new study, and a "funded to production" statement. Update PNAV inputs BF:BI and the
   same columns in `pnav_companies.csv` together, each with its source and date (convert at the stated date's
   rate and say so). Blank where a filing doesn't say: never estimate.
7. `snapshots --dry-run`, then `snapshots`: the fund tables on Summary, Metal prices reference and Stress test &
   downside. Their notes are text: if the report's facts changed (corrections, excluded holdings, reporting
   dates), tell the user which notes need editing.
8. Jurisdictions: if a company's mix of countries changed (a mine sold, started or stopped), update its
   `country_weights` and source, run `jurisdiction`, and show the user what moved. When the Fraser Institute
   publishes a new survey (usually in the first half of the year), ask the user to save the PDF to `private/`
   (fraserinstitute.org refuses automated downloads), write the Policy Perception Index scores to
   `private/fraser-<year>-scores.csv` (country, region, few_responses, ppi_<year> for the last three years;
   `private/extract_fraser_scores.py` did this for the 2025 PDF's Table 2; a place missing from the new survey
   but scored in the one before keeps that row, with its own `source` and `as_of` columns), then
   `jurisdiction --build private/fraser-<year>-scores.csv --source "..." --as-of YYYY-MM`. Review the changes
   with the user before `financials` writes them. Never commit the scores or the PDF: the survey is copyright,
   and only the rounded add-ons go in the repo.

## The Sheet: what not to touch

Single `ARRAYFORMULA`s in a column's first row spill down the column. Anything typed below them blocks the
spill and the whole column shows `#SPILL!` (or `#REF!` in Google Sheets):

- Holdings: D2:H2 and V2 (open-ended ranges to row 1000). Never write into D3:H1000 or V3:V1000.
- PNAV inputs: C12 and D12 (to row 154), AL12:AO12 (to row 146 only), and AR12:AS12, AZ12:BE12, BJ12:BO12 and
  BT12:BX12 (to row 154; BW12 is a MAP). Never write into C13:D154, AL13:AO146, AR13:AS154, AZ13:BE154, BJ13:BO154
  or BT13:BX154. H7 is a formula (the Signals cost input). AT:AW (resources), BF:BI (developer financing) and
  BP:BS (resource split) are inputs, recorded in `data/research/pnav_companies.csv` with a source for every
  figure (blank where unknown, never estimated); AX:AY are written by `financials`.
- Holdings downside: K2 (to row 337). Its ranges are fixed (`N2:N337` ...): extend them in K2 if rows are added below 337.
  R (cost base) is written by `financials`.
- P/NAV (tab `P_NAV`): U2:W2 (to row 144). Never write into U3:W162.
- Model portfolio: G6 (buy with new money: B3 split over the F weights after the silver in C4 fills PSLV, then
  the silver stocks) and H6:J6, L6:R6, T6 (to row 31). K has its own formula in each row. Never write into
  G7:J31, L7:R31 or T7:T31. W6:Z6 (timing signal, EV per ounce, months of funding, P/NAV after a raise) spill
  to row 31 too: never write into W7:Z31. To add a holding, insert a row between 6 and 31 (Sheets stretches the ranges);
  a row added below 31 is outside every range.
- Signals: `setup-sheet` inserts a row for a new signal or input (below the key before it in `SIGNALS`, then
  `layout.INPUTS`), so add new signals and inputs in code and run it rather than adding rows by hand. Context-only signals (`context=True`) show "Info"
  and have no G:H; their rule is tested by `backtest-signals` with `[signal_backtest.context_thresholds]`.
- Signals: column I (status) is a formula on every signal row, and so is E on the `royalty_pnav_median`,
  `junior_timing` and `implied_cost_increase` rows. Python writes E:F on the other signal rows, by the key in A,
  and on the `industry_aisc` input row: `data/research/industry_aisc.csv` is the record for it (the latest
  figure published by the run date), so a value typed there is overwritten.
- Signal history and Company history are written by the code, which finds rows by the date in A (and, on
  Signal history, columns by the key in row 1). Don't edit or sort them by hand; reordering Signal history's
  columns is fine. Keep Signal history A1:B1 as "Date", "Source" and Company history A1:E1 as its headers.
- Clear cells with an empty value; in Claude Sheets payloads that is `null`, never `""`.

### Holdings tab

| Col | Content | Type |
|---|---|---|
| A–C | Fund, holding, fund weight % | input |
| D | Market cap $M = R × V × U | formula |
| E–H | P/B = D/L, P/OCF = D/I, P/FCF = D/J, EV/EBITDA = (D+M)/K; blank when the denominator ≤ 0 | formula |
| I–M | Operating cash flow, free cash flow, EBITDA, book equity, net debt, $M | `financials` |
| N | Financials through (date) | `financials` |
| O, P | Sprott ticker, Yahoo symbol | input |
| Q | Note | `financials` |
| R, S, T | Price (local currency), currency code, price date | `prices` |
| U | Shares outstanding, millions | `prices --shares` |
| V | US$ per unit of the price currency (XLOOKUP into the FX table) | formula |

FX table `Y1:AB<n>`: currency, US$ per unit, source, rate date. GBX (`=GBP/100`, London pence) and ZAC
(`=ZAR/100`, Johannesburg cents) are formula rows the update skips. Yahoo's "GBp"/"ZAc" are renamed GBX/ZAC
because XLOOKUP ignores case.

### What follows Holdings

- PNAV inputs C (US$ price) and D (market cap) look up the Yahoo symbol in AP on `Holdings!P`. "not on
  Holdings" means the symbol wasn't found. Rows 25 and 54 (Sprott copper and silver trusts) take a fixed
  price from AQ, because their P/NAV compares the price with the trust's own NAV per unit, which Holdings
  doesn't track: update the price and the NAV per unit together, or leave both alone.
  Row 43 (Minsur) has no data.
- P/NAV and Model portfolio are formulas over PNAV inputs and Metal prices reference.
- Metal prices reference H15:K17 (Low/Medium/High/ATH scenario prices) feed PNAV inputs and Holdings downside K.
- Snapshots that don't follow Holdings: Summary, the fund table on Metal prices reference (B5:K11), the
  fund tables on Stress test & downside (all rewritten by `snapshots`), Backtest & projections.

## The original Claude Sheet (until the move to Google Sheets is done)

- Project `CbrKrb4TGeRGVdHkKcQFjo`, workbook node `d0c0abce-3665`; every Claude Docs call carries
  `ref={"object":"node","id":"d0c0abce-3665"}`, `container={"kind":"project","id":"CbrKrb4TGeRGVdHkKcQFjo"}`,
  `engine="workbook"`. Load `guide(items=["topic.sheets"])` before the first edit.
- Price update: `readCells` Holdings!R1:V1 (check the headers match `price_headers` in settings.toml) and
  Holdings!P1:P<last row>; save the result to `work/symbols.json` (the saved tool-result file works too), then
  `uv run python -m minerval prices --claude work/symbols.json --base <revision> --payload-dir work/prices`.
  Send each `payload_prices_N.json` as one `applyEdits`, in order, setting each `base` to the revision the
  previous call returned. Then check Holdings!D1:H6 and R1:V6 (D = R × V × U) and PNAV inputs C12:D20.
- With `--claude` the FX table order comes from `fx_rows` in settings.toml (Y2:Y18) and can't be checked,
  and the metal-price labels aren't checked: read Metal prices reference B15:C17 and B30:C30 first.
- `financials` works with Google Sheets only.

## How the code was checked (Nov 17, 2026)

The package replaced 28 one-off scripts. Run on the Nov 16 downloads, it reproduced the Sheet and the
earlier outputs: Holdings I–N and notes exactly; the stress test, breakevens, net cash, working capital and
the Holdings downside helpers exactly; all 677 P/NAV values within 0.11% (the Sheet rounds its inputs);
the backtests and the projection exactly (same random seed). Known differences: share-count changes for
two companies (PCU CN 1-year, SVM 3-year) whose reporting dates sit exactly halfway, where the old code
broke the tie the other way. Since every series is now fetched for every company, a company whose
reported operating cash flow is stale (MMG, 1208 HK) now uses free cash flow minus capital spending,
as RSG AU and BVN already did.

## Signal backtest

`backtest-signals` reports; it never changes thresholds. When the user reads it and decides to move a threshold,
change `[signals.thresholds]` in settings.toml and Signals G:H together, then run `signals` and check it says
"Sheet and Python statuses agree". Don't suggest a threshold because it scored best in the sweep: on one 25-year
period that is fitted noise. Point to plateaus, and to statuses marked "too few to judge".

## Data source notes

- Works without a login: `query1.finance.yahoo.com/v8/finance/chart/<symbol>` (prices, history),
  `ws/fundamentals-timeseries` (financials), `ws/insights` (Argus targets for a few US names).
- Blocked: `quoteSummary` (needs a crumb; 401/429).
- FX: fetch `<CUR>=X` (units per US$) and invert; `<CUR>USD=X` is rounded to 4 decimals.
- `^TNX` is the 10-year yield in percent (5.12 = 5.12%).
