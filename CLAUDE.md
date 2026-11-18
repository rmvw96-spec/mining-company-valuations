# Notes for Claude: maintaining the miner ETF valuations

README.md explains the project for people; this file is how Claude should run and change it.

## Ground rules

- Run everything from the repo root as `uv run python -m minerval <command>`. `uv run python -m pytest` and `uv run ruff check`
  must pass before any commit (CI runs the tests on Python 3.11 and 3.14, and ruff). Tests must stay offline: `tests/conftest.py`
  fails any test that reaches Yahoo, and the Sheet is a `MemorySheet`.
- Never commit `private/`, `cache/`, `out/` or `data/derived/` (they're in .gitignore), or any credentials.
  The repo is public: no personal amounts, account details or names in committed files.
- Ask the user before every `git push`.
- The Google Sheet is the working copy of the research inputs (PNAV inputs I–L and P–S, scenario prices,
  peer multiples). `data/research/pnav_companies.csv` and `config/settings.toml` [scenarios] are the record:
  when the user changes one, offer to update the other.
- Sheet layout is configured in `config/settings.toml` [sheet]. The commands check headers and stop if they
  don't match; if that happens, find out what moved before changing the config.

## Commands and run order

| When | Command | Writes |
|---|---|---|
| Daily, after 4 pm New York | `prices` (`--dry-run` first if anything looks off) | Holdings R–T, FX table Y–AB; Metal prices reference C15:C17, C30 |
| After earnings season | `prices --shares` | Holdings U (review >10% changes in the report) |
| After earnings season | `refresh` = `fetch` + `compute` | cache/, data/derived/ |
| After `refresh` | `financials --dry-run`, then `financials` | Holdings I–N, Q; Holdings downside D–J, M–Q; PNAV inputs E–H, M–O |
| Occasionally | `fetch-history`, `backtest`, `project` | out/backtest/ |

`compute --today gold=..,silver=..,copper=..` reruns the offline analysis at chosen metal prices.
Reports go to `out/<command>/report.txt`.

## Routine price update (Google Sheet)

1. `uv run python -m minerval prices`. It reads the Sheet ID and credentials from `private/local.toml`
   (or `MINERVAL_SHEET_ID` / `GOOGLE_APPLICATION_CREDENTIALS`).
2. Read `out/prices/report.txt` and deal with what it flags:
   - **No price**: the row keeps its old price. Check whether the symbol changed (rename, delisting, takeover).
   - **Older than 6 days**: thinly traded or suspended.
   - **Moved more than 25% in 5 days**: check for a split or consolidation; a split changes the share count, so run `prices --shares`.
   - **Currency not in the FX table**: add a row at the bottom of Holdings!Y:AB with the code; the next run fills the rate.
3. Tell the user the price date, the biggest movers, today's metal prices, and any Model portfolio rows
   whose Status (column T) changed to "Review: above level". To read the Sheet from Python:
   `from minerval.sheets import open_google; open_google().read("Model portfolio", "B6:T31")`.

## Earnings-season refresh

1. `uv run python -m minerval prices --shares`, and check every share-count change over 10% (acquisitions paid
   in shares, financings, consolidations, or a US listing quoted in a different unit than the share count).
2. `uv run python -m minerval refresh`. If `fetch` reports a ticker not found or a name mismatch, fix it in
   `config/symbol_overrides.csv` and rerun.
3. `uv run python -m minerval financials --dry-run`. Look at `out/financials/report.txt`: holdings in the data
   but not on the Sheet need rows added first (README, "When Sprott's holdings change").
4. Check the companies with large changes and any new "Op. cash flow corrected" notes against company
   reports. Put verified replacements in `config/corrections.csv` (value in US$ millions, with source).
5. `uv run python -m minerval financials`.
6. The Summary and Stress test & downside tabs are snapshots. If the user wants them current, the figures
   are in `data/derived/fund_multiples.csv` and `stress_funds.csv`.

## The Sheet: what not to touch

Single `ARRAYFORMULA`s in a column's first row spill down the column. Anything typed below them blocks the
spill and the whole column shows `#SPILL!` (or `#REF!` in Google Sheets):

- Holdings: D2:H2 and V2 (open-ended ranges to row 1000). Never write into D3:H1000 or V3:V1000.
- PNAV inputs: C12 and D12 (to row 154), AL12:AO12. Never write into C13:D154 or AL13:AO154.
- Holdings downside: K2 (to row 337). Its ranges are fixed (`N2:N337` ...): extend them in K2 if rows are added below 337.
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
- Snapshots that don't follow Holdings: Summary, the fund table on Metal prices reference (B5:I11), the
  fund tables on Stress test & downside, Backtest & projections.

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

## Data source notes

- Works without a login: `query1.finance.yahoo.com/v8/finance/chart/<symbol>` (prices, history),
  `ws/fundamentals-timeseries` (financials), `ws/insights` (Argus targets for a few US names).
- Blocked: `quoteSummary` (needs a crumb; 401/429).
- FX: fetch `<CUR>=X` (units per US$) and invert; `<CUR>USD=X` is rounded to 4 decimals.
- `^TNX` is the 10-year yield in percent (5.12 = 5.12%).
