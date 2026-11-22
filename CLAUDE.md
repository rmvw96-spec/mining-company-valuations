# Notes for Claude: maintaining the miner ETF valuations

README.md explains the project for people; this file is how Claude should run and change it.
Planned work is in `docs/roadmap.md`, with a spec for each item in `docs/specs/`. Specs follow
`docs/specs/TEMPLATE.md`: the end state only (no build history or research write-ups; a setting's evidence goes in
its settings comment), and acceptance criteria that each name their proof. Tick a criterion when its test passes,
and update the item's row in the status table at the top of `docs/roadmap.md` (a test checks they agree).

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
| Daily, after 4 pm New York | `prices` (`--dry-run` first if anything looks off); it runs `signals` at the end | Holdings R–T, FX table Y–AB; Metal prices reference C15:C17, C30; Signals E–F; PNAV inputs BY:CA; Signal history and Company history (today's rows) |
| On its own, if needed | `signals` (`--dry-run`) | Signals E–F; PNAV inputs BY:CA (royalty P/OCF and own-history percentiles); Signal history, Company history; out/signals/ |
| Once, or after adding a signal | `history --backfill 2022-01-01` (`--dry-run` first) | Signal history (past dates) |
| After earnings season | `prices --shares` | Holdings U (review >10% changes in the report) |
| After earnings season | `refresh` = `fetch` + `compute` | cache/, data/derived/ |
| After `refresh` | `valuation` (read `out/valuation/report.txt`: what was valued, what wasn't, and NAVs far from outside views) | data/derived/valuation.csv; out/valuation/ |
| After `refresh` and `valuation` | `financials --dry-run`, then `financials` | Holdings I–N, Q; Holdings downside D–J, M–R; PNAV inputs E–H, M–O, AX–AY, P for country-table rows, and CC:CG, CM:CO, CQ:CS (valuation; skipped while valuation.csv is older than pnav.csv) |
| After `financials` | `snapshots --dry-run`, then `snapshots` | Summary A1, A4:K9; Metal prices reference B2, B6:K11; Stress test & downside B2 and its five tables |
| After changing `country_risk.csv` or `country_weights` | `jurisdiction` (review out/jurisdiction/comparison.csv with the user), then `compute` and `financials` | PNAV inputs P |
| Once, and after changing `[sheet]` layout settings | `setup-sheet --dry-run`, show the user, then `setup-sheet` | Signals tab; PNAV inputs H7, Z:AC, AR:CB; P/NAV U:W; Holdings downside K2, R; Model portfolio W:Z |
| After `financials`, before buying | `screen` (report only; show the user out/screen/report.txt), then `screen --write` (`--email` for a private summary) | Model portfolio A–F, S, U–V; private/portfolio.csv, private/screen_state.json |
| After editing the Model portfolio by hand | `portfolio-file` | private/portfolio.csv (for `backtest` and `project`) |
| Occasionally | `fetch-history`, `backtest`, `project` | out/backtest/ |
| After changing a signal or threshold, or yearly | `backtest-signals` (`--refresh` to download again) | out/backtest-signals/ |
| After each quarter's MD&As (roadmap 6) | add the new year-to-date rows to `data/research/capex_periods.csv` (`research fetch` / `research find` to locate them), then `research sustaining --write` | `pnav_companies.csv` sustaining columns; cache/research/ |
| After the royalty companies' annual filings (10-K in February, 40-F in March) | `royalty-ocf`, then review the diff of `data/research/royalty_ocf.csv` with the user and commit it | data/research/royalty_ocf.csv |
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
  BT12:BX12, CB12, CH12:CL12 and CP12 (to row 154; BW12 is a MAP). Never write into C13:D154, AL13:AO146,
  AR13:AS154, AZ13:BE154, BJ13:BO154, BT13:BX154, CB13:CB154, CH13:CL154 or CP13:CP154. CC:CG, CM:CO and CQ:CS
  (valuation by tier) are written by `financials` from data/derived/valuation.csv. BY:CA (royalty P/OCF and own-history percentiles) are written by `signals`
  on every run, from `data/research/royalty_ocf.csv` (annual operating cash flow from SEC filings, the record,
  written by `royalty-ocf`) and the Company history tab. H7 is a formula (the Signals cost input). AT:AW (resources), BF:BI (developer financing) and
  BP:BS (resource split) are inputs, recorded in `data/research/pnav_companies.csv` with a source for every
  figure (blank where unknown, never estimated); AX:AY are written by `financials`.
- Holdings downside: K2 (to row 337). Its ranges are fixed (`N2:N337` ...): extend them in K2 if rows are added below 337.
  R (cost base) is written by `financials`.
- P/NAV (tab `P_NAV`): U2:W2 (to row 144). Never write into U3:W162.
- Model portfolio: G6 (buy with new money: B3 split over the F weights after the silver in C4 fills PSLV, then
  the silver stocks) and H6:J6, L6:R6, T6 (to row 31). K has its own formula in each row. Never write into
  G7:J31, L7:R31 or T7:T31. W6:Z6 (timing signal, EV per ounce, months of funding, P/NAV after a raise) spill
  to row 31 too: never write into W7:Z31. To add a holding, insert a row between 6 and 31 (Sheets stretches the ranges);
  a row added below 31 is outside every range. A–F, S and U–V are inputs that `screen --write` rewrites (physical
  metal rows, review levels typed by hand, and notes typed by hand are kept); its output (names, weights) never goes
  into the repo, an issue, a log or the step summary, and it never runs on GitHub. When a company is added to
  `pnav_companies.csv`, fill its listing columns (`us_listing`, `canada_listing`, `us_otc_symbol`, `listing_source`):
  the screen proposes only US- and Canadian-listed names by default.
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

## Research (company filings)

Lessons from the Step 0 pilot (Nov 21, 2026, `docs/specs/tier-valuation-spec.md`). Each document read and what it
held is logged in `data/research/sources.csv`: check it before searching again, and add a row for every new one.

- **The record is the filing, not a summary.** Use the MD&A, 10-K/40-F/20-F, annual information form, reserve
  statement or NI 43-101 / S-K 1300 technical report. Results press releases often give only next year's guidance
  (Capstone's gave 2026 sustaining capital, not 2025 actuals), and web-search summaries and call transcripts can be
  wrong (one put Alamos's 2025 sustaining capital at $50M; its MD&A says $144.6M). Never record a figure from a
  search summary without opening the document.
- **Where things are:** sustaining vs growth capital in the MD&A's capital expenditures section (Newmont's 10-K
  splits it by mine for three years; Capstone's MD&A by mine for two). Production in the MD&A highlights table
  (often three years). Reserves in the year-end reserve release or the AIF; the MD&A may give only a total without
  saying attributable or 100%. Study cash flows in the technical report's economic analysis (Section 22 in NI
  43-101 reports: an annual production and cash-flow table, and usually NPV across prices and discount rates).
- **Bases and units to check every time:** attributable vs 100% (Mantoverde is 70% Capstone's); reporting currency
  (Teck reports in C$; OR Royalties in C$ before 2024); gold-equivalent ratios are each company's own (Andean uses
  90:1); capitalized stripping is reported separately from sustaining capital by some open-pit miners (Teck,
  Capstone) and counts as sustaining spending (the user, Nov 21, 2026).
- **Sustaining spending** (roadmap 6) is recorded per filing period in `data/research/capex_periods.csv`, never as a
  trailing figure: each row is what one filing reports for its own period (FY, 9M, 6M or a quarter), in its currency,
  on the **consolidated** basis (the basis of Yahoo's operating cash flow; Mantoverde at 100%). `research sustaining`
  builds the trailing 12 months to each company's financials date (FY + year to date − the prior year to date, or
  the quarters where a company reports only quarters, as Amerigo does), converting at period-average rates. Take the
  prior-year comparative from the current filing, not last year's (restatements, discontinued operations).
  Sustaining lease payments are added (`sustaining_leases`; the user, Nov 21, 2026). EDGAR filers' quarterly exhibits can be listed from
  `data.sec.gov/submissions/CIK##########.json` and each filing's `index.json`; Canadian-only juniors post MD&As on
  their own sites (Orezone, Andean and Amerigo do).
- **Recording sustaining spending (lessons from 31 producers, Nov 2026):**
  - Use the basis of the cash flow it is subtracted from: consolidated. A joint venture that is equity-accounted
    (Kibali for AngloGold, Red Chris for Imperial) is out; one proportionately consolidated (Côté for IAMGOLD,
    Tropicana for AngloGold, NGM for Newmont) is in at the company's share. AngloGold's "managed operations" is its
    consolidated figure; its "Group total" includes the equity-accounted joint ventures.
  - Record figures as published. Where a company publishes one combined figure (OceanaGold "sustaining capital and
    leases"; First Quantum "sustaining capital expenditure and deferred stripping"; Torex sustaining including lease
    payments; Lundin sustaining including waste stripping), record it in `sustaining` and say so in `notes`
    (`stripping_in_sustaining` = yes where stripping is inside), rather than splitting it by arithmetic.
  - Prefer the consolidated highlights or free cash flow table to the AISC reconciliation for capital (AISC tables are
    often gold-only or attributable); take leases from the AISC reconciliation when that is the only place they appear.
  - Check a period total against its parts when you can (First Quantum: nine months 363 + Q4 133 = FY 496).
  - Some companies split sustaining only in some periods (Imperial: FY2025 yes, 2026 year to date no). Record what
    exists; the blank figure leaves the trailing 12 months unbuilt and the company on the free-cash-flow fallback.
  - A company that newly listed in the US files its earlier MD&As inside a 40FR12B registration (OceanaGold March
    2026, Torex November 2026); `research filings` includes that form.
  - Some filings are page images with a scrambled text layer (Gold Fields' 6-Ks: `rr.htm` plus `rr001.jpg`...): find
    the page from the text (line n of the converted text is about image n-1), download the `.jpg` from the filing
    folder, crop it with PIL if needed, and read it as an image. Say so in `notes`.
  - Some companies publish sustaining spending only per quarter (Buenaventura's AISC appendix): record the four
    quarters to the financials date as 3M rows; `research sustaining` adds them.
  - EDGAR rate-limits at about 10 requests a second: run scans one company at a time (the downloader pauses and
    retries on 429).
  - Add rows to `capex_periods.csv` by column name (a CSV writer), never by hand-counted commas: one missing comma
    shifts every later field, which the record-file test catches.
- **A press release that supersedes a study** (new economics, no new technical report) is not used for an NPV
  (Perpetua, March 2026).
- **Juniors** split sustaining from growth less often and publish reserves less often; their MD&As may be on
  SEDAR+ only. Where a figure isn't published, leave it blank: never estimate.
- **Fetching:** SEC EDGAR HTML reads directly. PDFs (MD&As, 10-K PDFs, technical reports) come back as raw bytes:
  download with `curl` into a new folder in the scratchpad and run `pdftotext -layout`, then grep. Technical reports
  are often over the fetch tool's 10 MB limit, so download them. Some investor-site links serve HTML instead of the
  PDF. SEDAR+ hasn't been tested.

## Data source notes

- Works without a login: `query1.finance.yahoo.com/v8/finance/chart/<symbol>` (prices, history),
  `ws/fundamentals-timeseries` (financials), `ws/insights` (Argus targets for a few US names).
- Blocked: `quoteSummary` (needs a crumb; 401/429).
- FX: fetch `<CUR>=X` (units per US$) and invert; `<CUR>USD=X` is rounded to 4 decimals.
- `^TNX` is the 10-year yield in percent (5.12 = 5.12%).
