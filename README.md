# mining-company-valuations

Scripts and data behind a spreadsheet that values the miners held by six Sprott ETFs (SGDM, SGDJ, GBUG,
SLVR, COPP, COPJ), in the style of Rick Rule:

- look-through multiples for each fund (P/B, P/OCF, P/FCF, EV/EBITDA)
- a metal-price stress test, with free-cash-flow breakevens, net cash and dilution
- price to net asset value (P/NAV) for 143 companies
- a model portfolio, with a backtest and a Monte Carlo projection

The spreadsheet is meant to live in Google Sheets. The Python package `minerval` keeps it current:
prices every day, company financials after each earnings season.

## What's here

```
minerval/                the code; run it as  uv run python -m minerval <command>
config/
  settings.toml          scenario prices, model constants, Sheet layout, Yahoo settings
  corrections.csv        figures that replace Yahoo's where Yahoo is known to be wrong (with sources)
  symbol_overrides.csv   Sprott tickers whose Yahoo symbol can't be worked out automatically
  metal_mix.csv          revenue split by metal for multi-metal producers
  backtest.toml          backtest windows, episodes and benchmarks
  projection.toml        projection assumptions: rate regimes, outcome odds, valuations
  portfolio.example.csv  example portfolio for the backtest (yours goes in private/portfolio.csv)
  local.example.toml     template for your own settings (private/local.toml)
data/
  holdings.csv           the six funds' holdings (Sprott, Nov 13, 2026)
  research/pnav_companies.csv   P/NAV research inputs: stage, countries, risk add-on, reserve life,
                                outside NAV estimates and study values, with notes
tests/                   offline tests (pytest); run on every push and pull request by .github/workflows/tests.yml
```

These are created when you run the commands and are not committed to git: `cache/` (raw Yahoo
downloads), `data/derived/` (computed company figures), `out/` (reports, backtest results) and
`private/` (your settings, credentials and portfolio).

## Setup

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs Python 3.11
or later for you if you don't have it.

```
git clone https://github.com/rmvw96-spec/mining-company-valuations
cd mining-company-valuations
uv sync                                                 # creates .venv/ from pyproject.toml and uv.lock
uv run python -m pytest                                 # offline tests: no network, no Sheet
uv run ruff check                                       # lint
```

`uv run` keeps `.venv/` in step with `uv.lock` before each command. To add or upgrade a dependency,
use `uv add <package>` or `uv lock --upgrade` and commit `pyproject.toml` and `uv.lock` together.

### Move the spreadsheet to Google Sheets

1. On the Claude Sheet's page, download it as .xlsx.
2. In Google Drive: **New → File upload**, then open the file and choose **File → Save as Google Sheets**.
3. Check that it calculates. On the Holdings tab, columns D–H and V should show numbers, not errors,
   and so should the P/NAV and Model portfolio tabs. These use `ARRAYFORMULA`, which is a Google
   Sheets function, so the import should keep them. If a column shows `#NAME?` or `#REF!`, retype the
   formula in its first cell (row 2 on Holdings, row 12 on PNAV inputs).
4. Copy the ID from the Sheet's address: `docs.google.com/spreadsheets/d/<ID>/edit`.

### Let the scripts write to it (service account)

A service account is a robot Google account that the scripts sign in as. It can only open files you share with it.

1. Go to [console.cloud.google.com](https://console.cloud.google.com), create a project (any name),
   and enable the **Google Sheets API** for it (APIs & Services → Library).
2. APIs & Services → Credentials → **Create credentials → Service account**. Give it a name; it needs no roles.
3. Open the service account → **Keys → Add key → JSON**. Save the downloaded file as
   `private/service_account.json` in this folder.
4. Share the Google Sheet with the service account's email address (it ends in
   `iam.gserviceaccount.com`), as **Editor**.
5. `cp config/local.example.toml private/local.toml` and put the Sheet ID in it.
6. Try it without writing anything: `uv run python -m minerval prices --dry-run`.

If you'd rather sign in as yourself, create an **OAuth client ID** (Desktop app) instead, save it as
`private/oauth_client.json`, set `credentials = "private/oauth_client.json"` and `auth = "oauth"` in
`private/local.toml`. The first run opens a browser to sign in.

## Daily: prices

```
uv run python -m minerval prices
```

Run it after the US close (about 4 pm New York time) to get closing prices; during market hours they
are intraday. Asian and Australian markets close earlier, so their price dates can be a day behind.
It updates:

- on the Holdings tab: the share price, currency and price date for every row with a Yahoo symbol
  (columns R–T), and the FX table (Y–AB)
- on the Metal prices reference tab: today's gold, silver and copper prices (C15:C17) and the
  10-year Treasury yield (C30)

Everything else (market caps, ratios, P/NAV, the model portfolio's valuation columns and status
flags) recalculates in the Sheet. The script checks the column headers first and stops without
writing if the layout has changed.

Read `out/prices/report.txt` afterwards. It lists:

- **No price**: the row keeps its old price. Check whether the company was renamed, delisted or taken over.
- **Price older than 6 days**: thinly traded or suspended.
- **Moved more than 25% in 5 days**: check for a share split or consolidation. A split changes the share
  count too, so update it (`--shares`, below).
- **Currency not in the FX table**: add a row at the bottom of Holdings!Y:AB with the code; the next run fills it in.

To run it automatically, use cron (or Task Scheduler on Windows) on your computer, or the GitHub
workflow in `.github/workflows/update-prices.yml`, which explains its setup.

## After each earnings season: financials

```
uv run python -m minerval prices --shares          # share counts (review changes over 10% in the report)
uv run python -m minerval refresh                  # download financials, rebuild data/derived/
uv run python -m minerval financials --dry-run     # report what would change on the Sheet
uv run python -m minerval financials               # write it
```

`refresh` is `fetch` (download, about a minute) followed by `compute` (no network). `financials`
writes, matching rows by fund and ticker rather than by position:

| Tab | Columns written | Matched on |
|---|---|---|
| Holdings | I–N (operating and free cash flow, EBITDA, book equity, net debt, report date) and Q (note) | fund + Sprott ticker |
| Holdings downside | D–J (net cash, working capital, cash runway, dilution, breakeven) and M–Q (helpers for column K) | fund + Sprott ticker |
| PNAV inputs | E–H (net cash, revenue, free and operating cash flow) and M–O (average metal prices over the reported period) | Yahoo symbol |

It leaves the research inputs alone (PNAV inputs I–L and P–S). After writing, look over the
companies whose Note says "Op. cash flow corrected" or that have new negative cash flows: Yahoo's
data has gaps, and `config/corrections.csv` is where a company-reported figure replaces Yahoo's.

## When Sprott's holdings change

There's no download script for this: Sprott's fund pages list each fund's holdings.

1. Update `data/holdings.csv` (fund, holding name, Sprott's ticker such as `AEM CN`, weight %).
2. On the Holdings tab, add a row for each new holding under the last one: fund, name and weight
   (A–C), Sprott ticker (O) and Yahoo symbol (P). Don't type into D–H or V; they fill themselves.
   Do the same on Holdings downside (A–C and the ticker in L). Its column K formula covers rows 2–337
   only, so if the list grows past row 337, extend the ranges in K2 (`N2:N337` and so on).
3. Run `refresh`, then `financials`, then `prices --shares`.
4. If `fetch` reports a ticker it couldn't find, or found under a different name, add the right Yahoo
   symbol to `config/symbol_overrides.csv` and run `refresh` again.

To add a company to the P/NAV tabs, fill in its research inputs on PNAV inputs (and in
`data/research/pnav_companies.csv` to keep a record), with its Yahoo symbol in column AP spelled
exactly as on the Holdings tab.

## What each tab depends on

| Tab | Kept current by |
|---|---|
| Holdings | `prices` daily (R–T, FX table), `financials` (I–N, Q); D–H and V are formulas |
| Metal prices reference | `prices` (C15:C17, C30); scenario prices and peer multiples are yours to edit; the fund table at the top is a Nov 16 snapshot |
| PNAV inputs, P/NAV | formulas over Holdings and Metal prices reference; `financials` (PNAV inputs E–H, M–O) |
| Model portfolio | formulas over P/NAV; inputs in B3 (new money) and B4 (ounces held) |
| Holdings downside | `financials` (D–J, M–Q); K is a formula that follows the Low scenario prices |
| Summary, Stress test & downside | snapshots from Nov 16, 2026. `compute` writes the current figures to `data/derived/fund_multiples.csv` and `stress_funds.csv`; paste them in to update |
| Backtest & projections | snapshot from Nov 17, 2026. `backtest` and `project` write the current figures to `out/backtest/` |

## How the numbers are worked out

- **Fund multiples** treat each fund as owning a slice of every company in proportion to its weight:
  fund P/X = total weight ÷ sum of (weight × X ÷ market cap). Companies with negative cash flow
  count against the total. Physical metal trusts and companies with no data are left out.
- **Metal-price changes**: a producer's revenue moves with each metal it sells (`config/metal_mix.csv`,
  or its fund's metal) from the average price over its reported 12 months; 95% of the change reaches
  EBITDA and 70% reaches cash flow (after about 30% tax). Costs, output and capital spending are held
  fixed, so these are sensitivities, not forecasts.
- **P/NAV**: NAV = cash flow × an annuity over the reserve life (capped at 25 years) + net cash,
  discounted at the 10-year Treasury yield + 3% + a country risk add-on. Royalty companies use
  operating cash flow. Developers are compared with their published study value instead.
- **Backtest and projection**: see the docstrings in `minerval/backtest.py` and
  `minerval/projection.py`, and the assumptions in `config/projection.toml`.

## Data sources and their limits

- **Prices, financials and FX** come from Yahoo Finance's public endpoints (`v8/finance/chart` and
  `ws/fundamentals-timeseries`). They're unofficial and can change or rate-limit without notice.
  FX rates are fetched as `CAD=X` (units per US$) and inverted, because Yahoo rounds `CADUSD=X` to
  four decimals, which puts small rates like the Indonesian rupiah far off.
- Yahoo quotes London prices in pence ("GBp") and Johannesburg prices in cents ("ZAc"). The Sheet
  calls these GBX and ZAC, because XLOOKUP ignores case and would match "GBp" to the pound rate.
- **Holdings** are from Sprott's ETF pages. **P/NAV research inputs** (stages, country risk, reserve
  lives, outside NAV estimates, study values) came from company reports and analyst sources found by
  web search in November 2026; each row's notes say where a figure is uncertain.

## Other commands

```
uv run python -m minerval fetch-history   # monthly price histories for the backtest (cache/history/)
uv run python -m minerval backtest        # out/backtest/: recent windows, 2008-2011, since 2000
uv run python -m minerval project         # out/backtest/projection_k15.json
uv run python -m minerval prices --claude FILE --base REV   # payloads for the original Claude Sheet (see CLAUDE.md)
```

The backtest and projection use `private/portfolio.csv` (columns as in `config/portfolio.example.csv`):
one row per holding with the dollars invested, and `already_held = yes` for metal you already own,
which is kept separate from new purchases in the results.
