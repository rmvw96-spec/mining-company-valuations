# mining-company-valuations

Scripts and data behind a spreadsheet that values the miners held by six Sprott ETFs (SGDM, SGDJ, GBUG,
SLVR, COPP, COPJ), in the style of Rick Rule:

- look-through multiples for each fund (P/B, P/OCF, P/FCF, EV/EBITDA)
- a metal-price stress test, with free-cash-flow breakevens, net cash and dilution
- price to net asset value (P/NAV) for 143 companies
- a model portfolio, with a backtest and a Monte Carlo projection
- market signals for when to buy each tier (Signals tab), a royalty buy zone, a producer cost-increase
  input, and cash and value-in-the-ground checks for developers

The spreadsheet is meant to live in Google Sheets. The Python package `minerval` keeps it current:
prices and market signals every day, company financials after each earnings season.

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
                                outside NAV estimates and study values, and developers' resource
                                estimates (amount, unit, category, source, date), with notes
docs/specs/              specifications for larger changes
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

`prices` then refreshes the Signals tab (see [Signals tab](#signals-tab)) and adds its statuses to
the report: which changed since the last run (against the Sheet's statuses before the write, so it
works wherever the last run was), and any row where the Sheet's status formula disagrees with Python's
(a sign a formula or threshold was edited). If a series can't be downloaded and isn't cached, the
Signals tab keeps its last value and the report names it with its date. `--no-signals` skips it; a
failure there is reported but never stops the price update. `signals` on its own does just that part.

The GitHub workflow in `.github/workflows/update-prices.yml` runs it every weekday after the New York
close (its header explains the secrets). FRED's CSV download often fails from GitHub's servers: add a
free FRED API key as the `FRED_API_KEY` secret to keep the real yield current there. Locally, cron (or
Task Scheduler on Windows) works too.

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
| PNAV inputs | E–H (net cash, revenue, free and operating cash flow) and M–O (average metal prices over the reported period); AX–AY (cash, 12-month free cash flow) | Yahoo symbol |
| Holdings downside | R (cost base: revenue − free cash flow, for the cost increase) | fund + Sprott ticker |

It leaves the research inputs alone (PNAV inputs I–L and P–S). After writing, look over the
companies whose Note says "Op. cash flow corrected" or that have new negative cash flows: Yahoo's
data has gaps, and `config/corrections.csv` is where a company-reported figure replaces Yahoo's.

## Signals tab

One row per signal, grouped by tier. Python writes the value (E) and its date (F); the thresholds (G–H)
and the inputs block below the signals are yours to edit; the status (I) is a formula over E, G and H.
Rows are found by the key in column A, so you can reorder them or insert rows. The defaults, and why
each was chosen, are in `config/settings.toml` `[signals.thresholds]`: that file is the record, the Sheet
is the working copy, and the code reads the Sheet's values when it runs against it.

| Tier | Signals | What the framework says |
|---|---|---|
| Physical metal | gold/silver ratio and its percentile since 2000; 10-year real yield (FRED DFII10) with its 12-month high and 3-month change; dollar index, 12 months | buy silver when the ratio is high; buy bullion more heavily when real yields peak and turn down; a falling dollar helps |
| Physical metal and royalty | S&P 500 below its 12-month high | panics are when to buy bullion and royalty companies |
| Royalty | median independent P/NAV of the royalty companies (a formula over PNAV inputs) | buy at 1.1–1.4× NAV; 1.5–2.2× is normal |
| Producers | gold, silver and copper against diesel over 12 months; gold price minus the industry AISC; GDX, SIL and COPX against their metal (percentile of 10 years); each fund's free-cash-flow yield from the Holdings tab | margins widen when metals outrun costs; buy miners when they're cheap against their metal |
| Juniors | the tax-loss selling window (Nov 1 – Dec 31); gold, GDX, silver and SIL against their 200-day average; GDXJ and SILJ below their 12-month high; and a formula combining them | buy juniors in the tax-loss window, or once the uptrend is confirmed |

These are signals from a framework, not advice. The Model portfolio's column W shows the ones that apply
to each bucket (set in `[signals.timing]`), and a royalty company's valuation band where there is one.

### Signal history and Company history

Each `signals` run (so each daily `prices` run) also keeps its readings, on two tabs the code creates and
manages:

- **Signal history**: one row per trading day. A is the date, B the source (`live`, or `backfill` for rows
  recomputed from past prices), then one column per signal key (row 1 holds the keys, so you can reorder
  the columns; new signals get a column on the right). A second run on the same day replaces that day's
  row. A value that couldn't be downloaded that day is left blank rather than repeated.
- **Company history**: Date, Holding, Yahoo symbol, Metric, Value. Each royalty company's independent P/NAV
  and price, and each developer's EV per gold-equivalent ounce, months of cash and cash share of market value.

Weekend runs aren't recorded. To fill in the past from the cached prices (five years of daily data):

```
uv run python -m minerval history --backfill 2022-01-01 --dry-run
uv run python -m minerval history --backfill 2022-01-01
```

The fund free-cash-flow yields, the royalty median and the AISC margin need past fundamentals, P/NAVs or
costs, so they aren't backfilled. A backfilled row never replaces a live one.

### Royalty buy zone

PNAV inputs AS classes each royalty/streaming company by its independent P/NAV (AJ): "Buy zone" up to
1.4×, "Normal range" up to 2.2×, else "Rich", using the thresholds on the `royalty_pnav_median` Signals
row; AR is the buy-below price (1.4 × the independent NAV per share). P/NAV U:V show both. AJ uses the
independent model's NAV per share (PNAV inputs R), which assumes that model's own metal prices (P/NAV
column K, mostly $4,000 gold): it's a research input refreshed by hand, not live.

### Producer cost increase

The model holds producers' costs at their reported 12 months. The Signals input `producer_cost_increase`
(0% by default; PNAV inputs H7 follows it) raises them: free cash flow falls by 0.70 × (revenue − free
cash flow) × the increase, in the P/NAV cash flows (Z:AC, producers valued on FCF only) and the
Low-scenario cash flows on Holdings downside (K, using the cost base in R). Revenue − FCF counts all
spending, including taxes, which don't inflate, so this slightly overstates the effect. Next to it,
`energy_share_of_costs` (yours to fill in) and `implied_cost_increase` show what the diesel move implies.
Offline, `compute --cost-increase 0.1` does the same for `data/derived/`.

### Developer checks

PNAV inputs AT:AW hold each developer's resource (millions of the unit: oz Au, oz AuEq, oz AgEq, lb Cu
or lb CuEq), its category and source, seeded from `data/research/pnav_companies.csv`. From those and
AX:AY: EV (AZ), EV per unit (BA), EV per gold-equivalent ounce (BB; silver ounces converted at the live
gold/silver ratio, copper shown per pound in BA only), months of cash (BC), cash as a share of market
value (BD), and a check (BE): "Short of cash: financing likely" under 12 months, "Watch" under 18, plus
"trading near cash" when cash is at least half the market value. Companies building a mine on project
loans (Skeena) show a short runway because the loan isn't counted as cash: check undrawn facilities
before reading "Short of cash" literally. Model portfolio X:Y show EV per ounce and months of cash for
the developers.

### Setting up the layout: `setup-sheet`

```
uv run python -m minerval setup-sheet --dry-run   # report what it would add
uv run python -m minerval setup-sheet             # add it
```

It creates the Signals tab and the columns above, and rewrites PNAV inputs Z:AC and Holdings downside
K2 to include the cost increase. It checks every cell first: a target that holds anything unexpected
skips that step and is reported, inputs are only filled when blank, and a rewrite only replaces the
exact old formula. It saves a snapshot of every cell it touches to `out/layout/backup-<time>.json`
first, and running it again changes nothing. Cell addresses are in `config/settings.toml` `[sheet]`.

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
| PNAV inputs, P/NAV | formulas over Holdings, Metal prices reference and Signals; `financials` (PNAV inputs E–H, M–O, AX–AY); resource inputs AT–AW are yours |
| Signals | `prices` daily (E–F); thresholds (G–H) and inputs are yours; status (I) is a formula |
| Model portfolio | formulas over P/NAV, PNAV inputs and Signals; inputs in B3 (new money) and B4 (ounces held) |
| Holdings downside | `financials` (D–J, M–R); K is a formula that follows the Low scenario prices and the cost increase |
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
- **Signals** use Yahoo daily and monthly closes (COMEX futures, NYMEX heating oil and crude, the
  dollar index, SPY and the miner ETFs) and the 10-year TIPS real yield from FRED
  (`fredgraph.csv?id=DFII10`, no key needed; FRED's API instead when `FRED_API_KEY` is set).
- **Developers' resources** are each company's latest published estimate (Nov 2026), with source and
  date in the research file; pounds are worked out from tonnes and grade where that's all a source gives.
- **Holdings** are from Sprott's ETF pages. **P/NAV research inputs** (stages, country risk, reserve
  lives, outside NAV estimates, study values) came from company reports and analyst sources found by
  web search in November 2026; each row's notes say where a figure is uncertain.

## Other commands

```
uv run python -m minerval fetch-history   # monthly price histories for the backtest (cache/history/)
uv run python -m minerval backtest        # out/backtest/: recent windows, 2008-2011, since 2000
uv run python -m minerval project         # out/backtest/projection_k15.json
uv run python -m minerval prices --claude FILE --base REV   # payloads for the original Claude Sheet (see CLAUDE.md)
uv run python -m minerval compute --cost-increase 0.1       # derived figures with producers' costs up 10%
```

The backtest and projection use `private/portfolio.csv` (columns as in `config/portfolio.example.csv`):
one row per holding with the dollars invested, and `already_held = yes` for metal you already own,
which is kept separate from new purchases in the results.
