# Build the "when to buy each tier" signals into the Sheet and the code

Instructions for Claude Code, working in `rmvw96-spec/mining-company-valuations`.

## Goal

The model values each company: P/NAV, multiples, breakevens. It has no view on *when* to buy each tier. Add four things,
each in the Python package and on the Google Sheet:

1. **Market signals.** A new **Signals** tab with timing signals for each tier, refreshed by the daily `prices` run:
   gold/silver ratio, 10-year real yield, dollar, stock-market drawdown, metal prices against fuel costs, miners
   against their metal, fund free-cash-flow yields, the tax-loss window, and whether an uptrend is confirmed.
2. **Royalty buy zone.** Each royalty/streaming company is classed by its independent P/NAV (buy at 1.1–1.4×,
   normal 1.5–2.2×, rich above 2.2×), with a buy-below share price.
3. **Producer cost increase.** One input (a %) that raises producers' costs in the P/NAV and Low-scenario cash-flow
   formulas. The model currently holds costs at the reported 12 months, while diesel is up ~70% on the year.
4. **Developer checks.** Value per ounce in the ground (EV/oz) and months of cash for developers and explorers.

The Model portfolio tab gets a timing column that pulls the relevant signal for each holding, plus EV/oz and
months-of-cash columns.

## Ground rules (from CLAUDE.md, plus what this job needs)

- Work on a new branch, `market-signals`. Commit in logical steps and open a PR at the end. **Ask the user before every
  `git push`.**
- `uv run python -m pytest` and `uv run ruff check` must pass before each commit. Tests stay offline: `tests/conftest.py`
  fails any test that reaches the network. The FRED download below must go through code that the guard also blocks:
  route it through `minerval.yahoo.session()` or a shared HTTP helper, and extend the guard if needed.
- **Sheet safety:**
  - Never write into an existing spill range (CLAUDE.md lists them).
  - Every Sheet change goes through code that first checks the target cells are empty or already hold exactly what it
    would write. If a target holds something else, it skips that step and reports it; it never overwrites.
  - Every write command supports `--dry-run`.
  - Before the first real install, save a snapshot of every range the installer will touch to
    `out/layout/backup-<timestamp>.json`.
  - Then show the user the dry-run report and wait for their OK.
- **Two copies of each setting:** thresholds and research inputs live on the Sheet (the working copy) and in
  `config/settings.toml` or `data/research/` (the record). When the code runs against the Sheet, it reads thresholds
  from the Sheet and falls back to the config, as the scenario prices already do.
- **Layout first:** the Google Sheet was imported from the original Claude Sheet. Before relying on any cell address
  below, read the Sheet and confirm it. Addresses go in `config/settings.toml` `[sheet]`, not in the code.
- **Grid size:** the API refuses writes beyond the grid. Add columns with `worksheet.add_cols()` (PNAV inputs is 43
  columns wide, A:AQ, and this job extends it to BE) and create the new tab with `add_worksheet`. Add `ensure_tab()` and `ensure_cols()` to
  `GoogleSheet` and `MemorySheet` in `minerval/sheets.py`.
- **Formulas:** Google Sheets formulas (`ARRAYFORMULA`, `XLOOKUP`, `LET`, `FILTER` are fine). Write them with
  `valueInputOption=USER_ENTERED`, which `GoogleSheet.write` already uses. Follow the Sheet's existing pattern: one
  `ARRAYFORMULA` in the first data row of a column, spilling down.
- **Wording:** plain status text, written for an investor. No jargon in labels, and no "BUY" commands. These are
  signals from a framework, not advice.

## Current layout you'll extend (confirm on the Sheet)

- **Metal prices reference:**
  - Today's prices: C15:C17 (gold, silver, copper).
  - Scenarios: Low H15:H17, Medium I15:I17, High J15:J17, All-time high K15:K17.
  - 10-year yield C30, premium C31, share of a revenue change reaching cash flow C32 (0.70).
  - Peer P/NAV norms B39:C43 (royalty 1.5, senior 1.1, intermediate 0.8, junior 0.6, developer 0.4).
  - Size cut-offs C47:C48, silver multiplier C49, method factors C50 (producers 2.14) and C51 (royalty 0.94).
- **PNAV inputs**, data rows 12–154 (one per company; P/NAV tab row N = PNAV inputs row N+10):
  - A fund, B holding.
  - C price US$ and D market cap $M, both formulas that look up Holdings.
  - E net cash $M, F revenue $M, G free cash flow $M, H operating cash flow $M.
  - I basis ("FCF", "OCF" or blank for developers), J–L revenue shares, M–O average metal prices over the reported period.
  - P jurisdiction add-on, Q reserve life, R independent NAV/share US$, S study value US$M.
  - U discount rate … Y base cash flow, Z–AC cash-flow change at Medium/Low/High/ATH. These are per-row formulas, e.g.
    Z12 `=IF($I12="","",$H$6*$F12*($J12*($B$5/$M12-1)+$K12*($C$5/$N12-1)+$L12*($D$5/$O12-1)))`; AA uses row 6, AB row 7,
    AC row 8.
  - AD–AI P/NAV columns, AJ independent or study P/NAV.
  - AK main metal (input), AL peer group (ARRAYFORMULA; "Royalty/streaming" when I="OCF", "Developer" when I is blank).
  - AM typical P/NAV, AN method factor, AO adjusted P/NAV.
  - AP Yahoo symbol, AQ fixed price (physical trusts).
  - Model inputs: G4:H6 (H4 yield, H5 premium, H6 pass-through, linked to Metal prices reference). **G7:H7 is empty.**
- **P/NAV:** A–T, data rows 2–144. Rows 145+ hold notes.
- **Holdings downside:**
  - Rows 2–337; L ticker.
  - K2 is one ARRAYFORMULA over fixed ranges:
    `=ARRAYFORMULA(IF(N2:N337="","",IF(M2:M337<>L2:L337,"helper mismatch",N2:N337+O2:O337*'Metal prices reference'!$H$15+P2:P337*'Metal prices reference'!$H$16+Q2:Q337*'Metal prices reference'!$H$17)))`.
  - M–Q are helpers (ticker, FCF intercept $M, $M per $1 gold/silver/copper), grouped and collapsed.
- **Model portfolio:**
  - Holdings in rows 6–31, columns A:V (A bucket, B holding name as on P/NAV, D Sprott ticker, E main metal, … T status,
    U why it's in, V what would change the view).
  - The summary starts at row 34; the "left out" table is at rows 61–76.
- **Holdings:** company rows from 2; A fund, C weight %, D market cap $M (formula), J free cash flow $M, O Sprott ticker,
  P Yahoo symbol.

## Part 1: market signals (`minerval/signals.py`, new **Signals** tab)

### Data

- **Yahoo** (`minerval.yahoo`):
  - Daily closes, `range=2y, interval=1d`, for GC=F, SI=F, HG=F, GDX, GDXJ, SIL, SILJ, COPX, CL=F, HO=F (heating oil,
    the US diesel benchmark), DX-Y.NYB, SPY.
  - Monthly closes from the start of history for GC=F, SI=F, HG=F, GDX, SIL, COPX.
  - Latest prices from `yahoo.quote`.
- **FRED, series DFII10** (10-year TIPS real yield, %, daily):
  `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10`. No API key. CSV columns are `observation_date,DFII10`,
  and holidays are "." (skip them). This was checked working on Nov 17, 2026: the last value was 2.92 on 2026-11-16.
- Cache raw downloads in `cache/signals/`. Keep fetching separate from computing: `compute()` is a pure function of the
  series, the date and the thresholds, so tests can feed it synthetic data.

### Signals

Each signal has a key, a tier, a value written by Python, two thresholds (G and H on the Sheet, defaults in
`settings.toml` `[signals]`), and a status. Changes are "12m" (latest vs the close 12 months earlier) unless stated.

| Key | Tier | Value | Thresholds (G, H) | Status rule |
|---|---|---|---|---|
| `gold_silver_ratio` | Physical metal | gold ÷ silver, latest futures | 80, 50 | ≥G "Silver cheap against gold: favours silver"; ≤H "Gold cheap against silver: favours gold"; else "Neutral" |
| `gold_silver_ratio_pctile` | Physical metal | percentile of today's ratio among month-end ratios since 2000-08 | none | "Info" |
| `real_yield_10y` | Physical metal | latest DFII10, % | 0.25, 0.10 | Let *peak* = 12-month high and *chg3m* = latest − value ~63 trading days earlier. If latest ≤ peak − G and chg3m < 0: "Peaked and falling: the framework's signal to buy bullion more heavily". If chg3m ≥ H: "Rising: keep accumulating steadily". Else "Flat: keep accumulating steadily". |
| `real_yield_12m_high` | Physical metal | 12-month high of DFII10 | none | "Info" |
| `real_yield_3m_change` | Physical metal | latest DFII10 − the value ~63 trading days earlier | none | "Info" |
| `usd_12m` | Physical metal | DX-Y.NYB 12m change | −0.03, 0.03 | ≤G "Dollar weakening: supportive for bullion"; ≥H "Dollar strengthening: a headwind"; else "Neutral" |
| `spy_drawdown` | Physical metal and royalty | SPY latest ÷ its 12-month high − 1 | −0.10, −0.20 | ≤H "Stock-market panic: framework's moment for bullion and royalties"; ≤G "Market pullback: watch royalty companies"; else "Calm" |
| `royalty_pnav_median` | Royalty | **Sheet formula, not Python:** median of PNAV inputs AJ where AL = "Royalty/streaming" and R is filled | 1.4, 2.2 | ≤G "Buy zone"; ≤H "Normal range"; else "Rich" (normal range per the framework is 1.5–2.2×; buy zone 1.1–1.4×) |
| `gold_vs_diesel_12m` | Producers (gold) | gold 12m change − HO=F 12m change (percentage points as a fraction) | 0.10, −0.10 | ≥G "Gold outpacing fuel costs: margins widening"; ≤H "Fuel costs outpacing gold: margin squeeze"; else "Neutral" |
| `copper_vs_diesel_12m` | Producers (copper) | the same with HG=F | 0.10, −0.10 | same wording with copper |
| `silver_vs_diesel_12m` | Producers (silver) | the same with SI=F | 0.10, −0.10 | same wording with silver |
| `gold_12m`, `silver_12m`, `copper_12m`, `diesel_12m`, `crude_12m` | Producers | the 12m changes behind the rows above | none | "Info" |
| `aisc_margin` | Producers (gold) | Python writes gold latest − industry AISC. The AISC is the `industry_aisc` **input** on the Signals tab (read it from the Sheet, fall back to settings: 1930, "World Gold Council, Q2 2026"). | none | Formula: "Margin $X/oz (Y% of the gold price)" |
| `gdx_gold_pctile10y` | Producers (gold) | percentile of today's GDX ÷ gold among month-end ratios over the last 10 years | 20, 80 | ≤G "Miners cheap against gold"; ≥H "Miners expensive against gold"; else "Mid-range" |
| `sil_silver_pctile10y` | Producers (silver) | the same for SIL ÷ silver | 20, 80 | same pattern |
| `copx_copper_pctile10y` | Producers (copper) | the same for COPX ÷ copper | 20, 80 | same pattern |
| `fcf_yield_SGDM`, `fcf_yield_SGDJ`, `fcf_yield_COPP`, `fcf_yield_SLVR` | Producers | read from the Sheet's Holdings tab: Σ(weight × FCF ÷ market cap) ÷ Σ weight, over the fund's rows where D > 0 and J is a number, excluding the tickers in `physical_trusts` and `non_operating` (settings.toml). PSLV has an FCF figure on the Sheet, so it must be excluded explicitly. | 0.08, 0.03 | ≥G "High free-cash-flow yield"; ≤H "Low free-cash-flow yield"; else "Middling" |
| `tax_loss_window` | Juniors | 1 if today is in the window (default Nov 1 – Dec 31, in settings) else 0 | none | "In the tax-loss selling window" / "Outside the window" |
| `uptrend_gold`, `uptrend_gdx`, `uptrend_silver`, `uptrend_sil` | Juniors | latest ÷ 200-trading-day average − 1 | none | > 0 "Above its 200-day average" else "Below" |
| `junior_timing` | Juniors | **Sheet formula** combining the rows above | none | If in window and (gold and GDX both above): "Both buy conditions met". If in window only: "Tax-loss window open; uptrend not confirmed". If uptrend only: "Uptrend confirmed". Else "Wait". |
| `gdxj_drawdown`, `silj_drawdown` | Juniors | latest ÷ 12-month high − 1 | none | "Info" (depth of the sell-off) |

Notes:
- Percentiles use month-end closes. The current month uses the latest quote.
- Thresholds are defaults chosen to match the framework's wording; the user can edit G/H on the Sheet. Record each
  default and its reasoning in `settings.toml` comments.
- `compute()` must also return the status text, using the same rules as the Sheet formulas, so the report and the
  tests don't depend on the Sheet. Each run, read G:H and the status column back from the Sheet. Report any row where
  the Sheet's status differs from Python's; it means a formula or threshold drifted.
- `royalty_pnav_median` and `junior_timing` are formula rows: their value (E) is a Sheet formula, so the script must
  never write E on them. For the mismatch check, Python works out the same results from `data/derived/pnav.csv` and the
  other signals.

### Signals tab layout (installer creates it)

- **Rows 1–2:** title, and one line saying "Values (E) and dates (F) are written by `python -m minerval prices`;
  thresholds (G–H) and inputs are yours to edit; Status (I) is a formula."
- **Row 4 headers:**

  | Col | Header |
  |---|---|
  | A | Key (code uses it to find rows; can be hidden) |
  | B | Tier |
  | C | Signal |
  | D | Unit |
  | E | Value |
  | F | As of |
  | G | Threshold 1 |
  | H | Threshold 2 |
  | I | Status |
  | J | What the framework says |
  | K | Source |

- **One row per signal**, grouped by tier with a blank row between tiers.
- **An inputs block below** with key, label and value in E:
  - `industry_aisc`: 1930, with the source and date in K.
  - `producer_cost_increase`: 0%. Used by Part 3.
  - `energy_share_of_costs`: blank. User input.
  - `implied_cost_increase`: formula = energy share × `diesel_12m`, shown next to the input, labelled "what the diesel
    move implies if energy is that share of costs".
- Status formulas reference E, G and H on their own row. Where a status needs another row (`real_yield_10y` needs the
  12-month high and 3-month change; `junior_timing` needs several), use `XLOOKUP` on column A keys, never fixed row
  numbers. Python writes the 3-month change as its own info row, `real_yield_3m_change`, so the formula can use it.
- Python finds rows by key in column A, as `financials` matches rows by ticker, so the user can reorder or insert rows.

### Commands

- `uv run python -m minerval signals [--dry-run]` fetches, computes and writes E:F by key. It also writes
  `out/signals/report.txt`, which lists every status, the statuses that changed since the last run (keep the last run in
  `out/signals/last.json`), and any Sheet/Python mismatch. It also writes `out/signals/signals.json`.
- `prices` runs `signals` at the end by default, with a `--no-signals` flag. A failure in signals (FRED down, say) must
  not fail the price update: catch it, add a line to the price report, and exit 0.
- The GitHub workflow `update-prices.yml` then covers signals too. FRED is reachable from GitHub runners.

## Part 2: royalty buy zone

- **PNAV inputs**, new columns after AQ, each one ARRAYFORMULA in row 12 spilling to 154:
  - `AR` "Buy-below price US$ (framework: buy-zone top × independent NAV per share)":
    `IF(AL="Royalty/streaming" and R<>"", R × buy-zone top, "")`, where the buy-zone top is the G cell of
    `royalty_pnav_median` on Signals (1.4).
  - `AS` "Royalty valuation band": blank unless AL = "Royalty/streaming".
    - "no independent NAV" if AJ is blank.
    - Otherwise "Buy zone" if AJ ≤ 1.4, "Normal range" if AJ ≤ 2.2, else "Rich". Use the same Signals G/H cells.
- **P/NAV tab**, new columns:
  - U "Royalty band (framework)" = `ARRAYFORMULA('PNAV inputs'!AS12:AS154)`.
  - V "Buy-below price US$" = `ARRAYFORMULA('PNAV inputs'!AR12:AR154)`.
  - Check rows 145–162 of U:V are empty first.
- **Caveat** (put it in the header note and the README): AJ uses the independent model's NAV per share (R), which
  assumes that model's own metal prices (P/NAV column K, mostly $4,000 gold). It's a research input refreshed by hand,
  not live.
- **Python, `pnav.py`:** add `royalty_band` and `buy_below_price_usd` to `data/derived/pnav.csv` for basis == "OCF" rows,
  using the thresholds from settings. Expected today: Wheaton ~2.06, Franco-Nevada ~3.17, Royal Gold ~2.40,
  Triple Flag ~2.24, OR Royalties ~2.37, all "Rich" or top of "Normal".

## Part 3: producer cost increase

Model: a cost increase *c* (fraction) lowers free cash flow by *k* × (revenue − FCF) × *c*.
- *k* is the share reaching cash flow (0.70, Metal prices reference C32): costs are tax-deductible.
- revenue − FCF is everything the company spends: operating costs, taxes and capital spending. Taxes don't inflate, so
  this slightly overstates the effect; say so in the docs.
- It applies only to rows valued on FCF (producers). Royalty companies (OCF basis) and developers are left alone.

Changes:
- **`minerval/price_model.py`:** `cost_change(revenue, fcf, cost_increase)` returning
  −k × max(0, revenue − fcf) × c. Add `cost_increase = 0.0` to `settings.toml` `[price_model]` and a
  `--cost-increase` option on `compute`.
- **`stress.py`**, in every scenario:
  - `fcf_*`: subtract k × max(0, revenue − FCF) × c.
  - `ocf_*`: subtract k × max(0, revenue − OCF) × c. Operating cash flow is before capital spending, so its cost base is
    smaller.
  - `ebitda_*`: subtract max(0, revenue − EBITDA) × c. EBITDA is before tax, so the whole increase hits it.
  - In the breakeven, b becomes b − k × max(0, revenue − FCF) × c.
  - Add a helper column `cost_base_m` = max(0, revenue − FCF) / 1e6.
- **`pnav.py`:** the same in the cash-flow change, FCF basis only.
- **Regression test:** with c = 0, every output must equal today's exactly (compare whole frames). Also test a hand-worked
  10% case.
- **Sheet, PNAV inputs:**
  - G7 "Producer cost increase since the reported period"; H7 = the Signals `producer_cost_increase` input
    (via XLOOKUP on key).
  - Rewrite Z12:AC154: append `-IF($I12="FCF",$H$6*MAX(0,N($F12)-N($G12))*$H$7,0)` to each formula.
  - Only rewrite a cell if it currently holds exactly the old formula (or already the new one); otherwise report a
    conflict. This is 572 cells: batch them in one API call.
- **Sheet, Holdings downside:**
  - Add R "Helper: cost base $M (revenue − FCF)", inside the collapsed group if gspread allows.
  - `financials` writes R from `stress_holdings.csv` `cost_base_m`.
  - Change K2 to subtract `'Metal prices reference'!$C$32*N(R2:R337)*<producer_cost_increase cell>`. Rewrite K2 only if
    it still holds the exact formula above.
- **Check after install:** with the input at 0%, P/NAV AD:AJ and Holdings downside K must be unchanged. Snapshot both
  before installing and compare afterwards.

## Part 4: developers: EV/oz and months of cash

**Research inputs.** Add columns to `data/research/pnav_companies.csv`, and to PNAV inputs as AT:AW (inputs, seeded once
from the CSV by the installer when empty):
- `resource_amount`: millions of the unit.
- `resource_unit`: one of `oz Au`, `oz AuEq`, `oz AgEq`, `lb Cu`, `lb CuEq`.
- `resource_category`: "Reserves", "Measured & indicated", "Measured, indicated & inferred", or "Mixed".
- `resource_source` and `resource_date`. On the Sheet these go together in AW, "Resource source and date".

Seed values found on Nov 17, 2026 from news summaries. **Check each against the company's latest technical report or
resource release before committing**, and correct with a source if they differ:

| Ticker | Amount | Unit | Category | Source found |
|---|---|---|---|---|
| SKE CN | 4.6 | oz AuEq | Reserves (3.3 Moz Au + 88 Moz Ag) | skeenaresources.com/eskay-creek (2023 DFS) |
| PPTA CN | 4.8 | oz Au | Reserves (plus 148 Mlb antimony) | Creamer Media, Stibnite update, Jun 20, 2025 |
| SEA CN | 95.5 | oz Au | Measured & indicated (KSM; plus 21,146 Mlb Cu and 460 Moz Ag M&I) | Seabridge release, Mar 31, 2026 (newsfilecorp.com/release/290564) |
| OMG CN | 8 | oz Au | Mixed (indicated + inferred, Wenot + Gilt Creek) | Crux Investor, Apr 29, 2026 (resource dated Apr 14, 2026) |
| ABRA CN | 454 | oz AgEq | Measured & indicated (Diablillos) | pulse.bot, May 7, 2026 |

Research the remaining rows where `basis` is blank (developers and explorers: PDI AU, OM CN, HYMC, MAU CN, VISC SS,
MARI CN, ATX CN, REG CN, HSLV CN, KRY CN, TMQ, NEWP, PCU CN, MOON CN, ALDE CN, ECU CN, CNL CN, ETG CN, PML CN, BIG CN,
SXGC CN, NGEX CN, ANDC CN):
- Use the company's own latest resource statement, with source and date.
- Leave a row blank rather than guess.
- List any you couldn't find in the PR description.

**Data columns**, written by `financials` for every row with a Yahoo symbol:
- AX "Cash $M" (cash and short-term investments).
- AY "Free cash flow $M, last 12 months".
- Source: `holdings_detail.csv` `cash` and `fcf`.

**Formula columns**, each one ARRAYFORMULA in row 12:

| Col | Header | Formula |
|---|---|---|
| AZ | EV $M | D − E |
| BA | EV per unit US$ | AZ / AT, where AT > 0 ($M per million units = $ per unit) |
| BB | EV per gold-equivalent oz | for `oz Au`/`oz AuEq`, BA. For `oz AgEq`, BA × the live gold/silver ratio (Signals `gold_silver_ratio` E). Blank for copper units: show copper EV/lb in BA only. |
| BC | Months of cash | IF(AY<0, AX / −AY × 12, "Cash-generating") |
| BD | Cash, % of market value | AX / D |
| BE | Developer check | blank unless AL = "Developer". Otherwise: "Short of cash: financing likely" if BC < 12; "Watch" if BC < 18; "Enough cash"; plus "; trading near cash" if BD ≥ the near-cash threshold (Signals input `near_cash_share`, default 0.5). |

Thresholds 12 and 18 months come from the framework ("at least 12 to 18 months of cash"). Store them as Signals
inputs `runway_short_months` and `runway_ok_months`.

**Caveat** in the header note and README: companies building a mine on project loans (Skeena) show a short runway
because the loan isn't counted as cash. Check undrawn facilities before reading "Short of cash" literally.

**Python:** add `ev_m`, `ev_per_unit`, `ev_per_aueq_oz`, `months_of_cash`, `cash_share`, `developer_check` to
`pnav.csv`.

Expected with the Nov 17 data:

| Ticker | Months of cash | Developer check | EV per gold-equivalent oz |
|---|---|---|---|
| SA / SEA CN | 4.0 | Short | ~$34/oz M&I gold |
| SKE CN | 3.9 | Short, see caveat | ~$940/oz |
| ABRA CN | 9.7 | Short | ~$210/oz (AgEq converted at ratio ~82.6) |
| PPTA | 17.9 | Watch | ~$370/oz |
| OMG CN | 31.5 | Enough cash | ~$85/oz |

## Part 5: Model portfolio columns

New columns W:Y, each one ARRAYFORMULA in row 6 spilling to 31. Confirm W6:Y31 are empty, and that nothing below row
31 in W:Y would block the spill.

- **W "Timing signal (framework)".** Pulls Signals statuses by key, according to the bucket in A and the metal in E:

  | Bucket | Signals shown |
  |---|---|
  | Physical metal, gold | `real_yield_10y` |
  | Physical metal, silver | `gold_silver_ratio` |
  | Physical metal, copper | the text "No framework signal for physical copper" |
  | Gold producers, or growth: expanding producers | `gold_vs_diesel_12m` + " / " + `gdx_gold_pctile10y` |
  | Copper producers | `copper_vs_diesel_12m` + " / " + `copx_copper_pctile10y` |
  | Silver and polymetallic producers | `silver_vs_diesel_12m` + " / " + `sil_silver_pctile10y` |
  | Growth: developers | `junior_timing` + " / " + this row's PNAV inputs BE developer check |
  | Any royalty row | its PNAV inputs AS band |

  Put this mapping in `settings.toml` `[signals.timing]` as the record, and build the formula from it in the installer.
- **X "EV per gold-equivalent oz (developers)"** and **Y "Months of cash"**: XLOOKUP of B (holding name) into PNAV inputs
  B → BB and BC. Blank for non-developers.

## Part 6: installer (`minerval/layout.py`)

`uv run python -m minerval setup-sheet [--dry-run]` applies Parts 1–5 to the Sheet in this order:

1. Snapshot.
2. Signals tab.
3. PNAV inputs G7:H7 and new columns.
4. Z:AC rewrite.
5. P/NAV U:V.
6. Holdings downside R and K2.
7. Model portfolio W:Y.

For each step it reports one of:
- "added",
- "already in place (no change)",
- "conflict: <cell> holds <x> (skipped)".

It must be **idempotent**: a second run reports no changes. Formula text is generated from `settings.toml` `[sheet]`
addresses, never hard-coded in more than one place.

Tests on `MemorySheet` (extend it with `ensure_tab` and `ensure_cols`):
- a fresh install writes the expected blocks;
- a second run writes nothing;
- an occupied target cell causes a skip and a report line, with no write;
- the Z:AC rewrite only touches cells holding the exact old formula.

## Part 7: tests (offline) and docs

**Tests:**
- **Signals:**
  - `compute()` on synthetic series: each status boundary, including both sides of every threshold.
  - Percentile on a known series.
  - Real-yield "peaked and falling" vs "rising".
  - Tax-loss window on Oct 31, Nov 1, Dec 31 and Jan 1.
  - The 200-day average.
  - The FRED CSV parser with "." holidays.
  - The FCF-yield calculation from a `MemorySheet` Holdings tab.
  - `prices` still succeeds when signals raises.
- **Cost increase:** zero gives identical output (whole frames); 10% matches a hand-worked number in stress, pnav and
  the breakeven.
- **Royalty band and developer columns in `pnav.csv`:** boundary cases, AgEq conversion, cash-generating companies.
- **Layout:** as in Part 6.
- **Data files:** extend `tests/test_data_files.py` to validate the new research columns (unit is one of the allowed
  values; a filled amount has a source and a date).

**Docs:**
- **README:** a "Signals tab" section (what each signal means, where thresholds live), `setup-sheet`, the cost-increase
  input, the developer columns and their caveats.
- **CLAUDE.md:**
  - Daily routine step 3: also report signals whose status changed.
  - Add the new spill ranges to "what not to touch": Signals I column formulas, PNAV inputs AR:AS and AZ:BE, P/NAV U:V,
    Model portfolio W:Y.
  - Add the new commands to the run-order table.

## Order of work and checks

1. Part 1 Python (`signals.compute`, fetch, report) with tests. Run `signals --dry-run` against the real Sheet and
   compare with the sanity values below.
2. Part 3 Python with the zero-change regression test. Then Parts 2 and 4 in `pnav.py`. Research the developer
   resources.
3. Part 6 installer and its tests. Run `setup-sheet --dry-run` against the real Sheet. Show the user the report and the
   snapshot location; **wait for their OK** before the real install.
4. Install. Then run `financials` (for AX:AY and Holdings downside R), then `prices`. Check:
   - no `#REF!`, `#SPILL!` or `#N/A` anywhere new;
   - with cost increase 0%, P/NAV AD:AJ and Holdings downside K are unchanged from the snapshot;
   - the Sheet's statuses match Python's (the signals report shows no mismatches);
   - the Model portfolio W:Y read sensibly for every bucket.
5. Docs, PR description (what was added, the sanity readings, the developer resources not found, the caveats). Ask
   before pushing.

### Sanity values (Nov 17–18, 2026; yours will differ a little with newer data)

| Signal | Expected |
|---|---|
| Gold/silver ratio | ~82.6 → "Silver cheap against gold"; 83rd percentile since 2000 |
| DFII10 | 2.92 on 2026-11-16. It was 1.94 on Jan 2, then 2.44 (July auction) and 2.65 (Sept reopening). At or near its 12-month high, rising → "Rising: keep accumulating steadily" |
| Dollar index, 12m | +4.2% → "Dollar strengthening: a headwind" |
| SPY | ~4.5% below its 12-month high → "Calm" |
| 12-month changes | gold −10.7%, silver −18.5%, copper +14.2%, crude +45%, heating oil +70% |
| Metal vs diesel | "Fuel costs outpacing gold" (and silver, and copper) |
| AISC margin | $3,800 gold − $1,930 AISC ≈ $1,870/oz (~49%) |
| GDX ÷ gold | ~95th percentile of the last 10 years → "Miners expensive against gold" |
| SIL ÷ silver | ~47th percentile |
| COPX ÷ copper | compute |
| Tax-loss window | in the window |
| Uptrend | gold is ~20% below its January high; expect "Below its 200-day average" for gold and GDX → `junior_timing` "Tax-loss window open; uptrend not confirmed" |
| GDXJ, SILJ | GDXJ −16% this year; SILJ −21% this year and ~45% below its Feb 2026 high |
| Fund FCF yield | SGDM ≈ 1/27.6 ≈ 3.6% at Nov 17 prices |
