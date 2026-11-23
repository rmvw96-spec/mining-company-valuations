# Model portfolio from a screen

Instructions for Claude Code. Roadmap item 5. Follow CLAUDE.md.

**Status: built** (branch `model-portfolio-screen`). Where the build differs from the plan below:
- Royalty companies aren't filtered on the peer norm. The Sheet's typical royalty multiple (1.5× × 0.94) sits below
  where the whole group trades, so all seven read 1.5–1.9× their norm (Nov 2026) and a 1.3 level would exclude and
  flag them all. They are excluded instead when the framework band is "Rich" or they are expensive for themselves
  (own-history percentile ≥ 75), and their review level is 2.0.
- Expanding producers may have diluted up to 100% in 3 years (30% excluded 5 of 8 US/Canadian names: they build and
  merge with shares).
- One row per company (Wheaton is in two funds). Tab rows are matched to companies by name (any case), else by
  ticker, and a kept holding keeps its tab ticker; a new one gets a US Sprott ticker where the Sheet carries one
  (KGC rather than K CN). Writing the P/NAV tab's name also mends rows whose name didn't look up.
- `screen --init` writes `private/screen.toml` from the tab; `--rule-review-levels` resets typed levels to the rule
  (with no state file, every level already on the tab counts as typed).
- Listings for all 143 companies were checked against Yahoo quotes (exchange and name) on Nov 20, 2026: 113 have a
  US or Canadian listing. DTC eligibility of the OTC symbols isn't recorded (Fidelity's quote page shows it); a
  Canadian name without a recorded US OTC symbol counts as rep-assisted ($32.95) but stays eligible.

## Goal

The Model portfolio tab's inputs are typed by hand: which holdings (A–E), their target weights (F), the review
levels (S) and the notes (U–V). Everything else on the tab is a formula. The user holds no miners yet, so the
holdings can come from the framework's own numbers instead of a fixed list.

Three parts, one PR:

1. **Screen**: rank the companies on PNAV inputs within each bucket, including a new Royalty bucket, and propose
   the holdings and target weights for A–F. By default only companies that can be bought on a US or Canadian
   market are proposed. The user reviews the proposal before anything is written.
2. **Review levels from a rule**: S set from the peer norm. A level the user types by hand is kept.
3. **Backtest file from the tab**: write `private/portfolio.csv` from the Model portfolio, so `backtest` and
   `project` test what the Sheet shows.

Decisions taken with the user (Nov 20, 2026):
- Add a Royalty bucket.
- Bucket sizes default to the tab's current split, with Royalty funded as below.
- A review level typed by hand stays.
- `config/portfolio.example.csv` is replaced with a neutral example.
- Default to US and Canadian markets, with an option for the rest.

## Privacy (read first)

Holding names, weights and statuses are Model portfolio content: they never go into the repo, an issue, a log or
the step summary (CLAUDE.md).

- **Committed** (`config/settings.toml` [portfolio_screen]): the rules. These are the filters, the score's
  measures and their weights, the bucket definitions, the market rule, the review-level rule, the turnover buffer,
  the per-name cap and the research ranges below (as comments). They are a method, not a portfolio.
- **Private** (`private/screen.toml`, with a committed `config/screen.example.toml` using neutral numbers): each
  bucket's total target weight and how many names it holds.
- **Output**: `out/screen/` (gitignored) and the Sheet. The command never runs on GitHub. With `--email`, the
  summary of a write goes by private email (`alerts.send_email`).
- **`config/portfolio.example.csv`** overlaps with the real Model portfolio (11 of its 18 tickers). Replace it with
  a neutral example: the four Sprott funds (SGDM, SGDJ, COPP, SLVR) and PHYS, round amounts. Note in the PR that
  the old file stays in the git history.

## Part 1: the screen

### Universe and buckets

- **Universe**: rows of PNAV inputs with a market cap and a P/NAV (P/NAV tab D numeric, not "negative" or ">20"),
  joined to data/derived/pnav.csv for the fields the Sheet doesn't show.
- **Buckets**: the existing bucket names (`[signals.timing]` keys) plus **Royalty**. Physical metal is not
  screened: its rows keep what the user typed, and they come first on the tab.
- **Mapping each company to a bucket** (`[portfolio_screen.buckets]`: peer group, main metal and stage):
  - Royalty: peer group "Royalty/streaming".
  - Gold producers: Senior or Intermediate producer, main metal gold.
  - Growth: expanding producers: Junior producer, or a producer whose reserve life or a study shows output rising.
  - Copper producers and Silver and polymetallic producers: producers by main metal.
  - Growth: developers: Developer, gold or copper (`[signals.timing]` already splits developers by metal).
- **Main metal**: the largest revenue share (PNAV inputs J:L) for producers, the resource unit (AU) for
  developers.
- **Overrides**: where the mapping gets a company wrong, a new `bucket` column in `pnav_companies.csv` overrides
  it, with a reason in `bucket_note`. This classifies the company; it isn't portfolio membership, so it can be
  committed.
- **Royalty in the other formulas:** Model portfolio W already shows a royalty company's framework band and
  own-history band, so the new bucket needs no `[signals.timing]` entry. (Adding one would change W's formula and
  make `setup-sheet` report a conflict.)

### Markets: what can be bought without a per-trade fee

**Why.** The user buys in small amounts when names are cheap, in an IRA. A flat fee per trade on a small purchase
undoes that. Fidelity's Brokerage Commission and Fee Schedule (the PDF on fidelity.com, file dated Sep 2026)
says:

| How the stock is bought | Cost per trade | In an IRA? |
|---|---|---|
| US exchange listing, ADR (NYSE, Nasdaq, NYSE American; sponsored ADRs on OTC, symbols ending in Y) | $0 online | Yes |
| Foreign ordinary share on the US OTC market (symbol ending in F), placed online | $0, plus **$50** if the share isn't Depository Trust Company (DTC) eligible | Yes |
| Dollarized International Trading (a foreign exchange, settled in US$) | Rep-assisted only: $32.95; Canada adds nothing; **all other countries add $50**; plus a currency markup of about 1% under $100K | Yes |
| International Trading (local currency, online; e.g. C$19 in Canada, A$32 in Australia) | Per-country commission plus a currency markup | **No**: retirement accounts aren't eligible |

So in an IRA, a company listed only in Australia, London, Hong Kong, Johannesburg and the like costs at least $50
a trade, unless it has a DTC-eligible OTC symbol. A Canadian company costs nothing online through its US symbol
(most TSX and TSX-V companies have a DTC-eligible OTC symbol ending in F). Without one, a rep-assisted trade costs
$32.95 plus the currency markup, but no $50.

**The rule** (`[portfolio_screen.markets]`):
- **Default:** only companies with a **US listing** (US exchange or US ADR) or a **Canadian listing** (TSX,
  TSX-V, CSE).
- **`--all-markets`:** include the rest. The report then marks each such name "Foreign-only: about $50 a trade in
  an IRA".
- **Canadian names without a DTC-eligible US symbol:** in the default mode they stay eligible but are marked
  "Canada, rep-assisted: $32.95 a trade". `[portfolio_screen.markets] canada_rep_assisted = true` keeps them, and
  false drops them.

**Data** (new columns in `pnav_companies.csv`, the record):
- `us_listing`: the US symbol and venue, for example "GFI (NYSE ADR)" or "NCMGY (OTC ADR)". Blank if none.
- `canada_listing`: for example "TSX: EDV" or "TSX-V: OMG".
- `us_otc_symbol`: the F symbol, with "DTC eligible" or "not DTC eligible" where known.
- `listing_source`: the source and date.
- **Filled automatically** from the Sprott ticker. No exchange code (36 companies) means a US listing, and CN (68)
  means a Canadian listing.
- **The other 39** (AU 21, LN 7, HK 3, TI 2, and one each PW, SJ, IJ, PM, FH, SS) need researching: a NYSE ADR
  (Gold Fields, Harmony, AngloGold, Sibanye, DRDGOLD), a sponsored OTC ADR, or a TSX listing (some Australian and
  London miners have one). Until a row is researched it counts as foreign-only, and the report lists the
  unresearched names.
- **DTC eligibility:** the per-trade fee depends on it, so record it where it can be confirmed (Fidelity's quote
  page shows it). Don't guess it.
- **Fee table:** keep it in `[portfolio_screen.markets]` comments with its source and date. Check the schedule
  once a year, since the amounts change.

### Hard filters (a company failing any one isn't eligible)

Every threshold is in `[portfolio_screen.filters]` with a comment giving the reason:

- **Market:** the rule above.
- **Data:** financials through (Holdings N) within the last 9 months, and a price date (Holdings T) within 6 days.
- **Size:** market cap at least $300M for producers and royalty companies, and $100M for developers, as a
  liquidity floor.
- **Dilution:** share-count change over 3 years (Model portfolio R's source, Holdings downside H) no more than 30%
  for producers.
- **Jurisdiction:** add-on (PNAV inputs P) no more than 2.5 points.
- **Developers:**
  - The developer check isn't "Short of cash".
  - P/NAV after the raise (BO) is numeric or "Fully funded" / "Funded (company says)".
  - EV per weighted unit against the peer median (BW) is no more than 1.5.
- **Royalty:** the framework band isn't "no independent NAV". A royalty company with no own-history percentile
  (Metalla today) stays eligible, and that measure is left out of its score.
- **Valuation:** "valuation vs peer norm" (P/NAV tab N) is below the bucket's review level (Part 2), so the screen
  never proposes a company it would flag at once.

### Score (ranking within a bucket)

For each measure: rank percentiles within the bucket, 0 for the worst and 1 for the best. The score is their
weighted average, with weights in `[portfolio_screen.score]` (equal by default). Measures with no value for a
company are left out of its average, and the report says how many it had.

| Bucket | Measures (better = ...) |
|---|---|
| Producers (gold, copper, silver, expanding) | valuation vs peer norm (lower); P/NAV at Low prices (lower); free-cash-flow breakeven vs today's price (lower); net cash, % of market value (higher); share-count change, 3 years (lower); jurisdiction add-on (lower); P/NAV with the add-on raised ÷ P/NAV today, BX (lower: less reliant on the risk premium) |
| Developers | P/NAV after a raise (lower; funded counts as best); EV per weighted unit against the peer median, BW (lower); months of funding (higher); jurisdiction add-on (lower) |
| Royalty | independent P/NAV, AJ (lower); own-history percentile, P/NAV when recorded else P/OCF, CA or BZ (lower); valuation vs peer norm (lower); jurisdiction add-on (lower) |

Don't tune the weights to the backtest: most of these measures have no history, and one period's best fit is
noise (CLAUDE.md, "Signal backtest").

### Bucket sizes: defaults and the research behind the limits

- **Defaults** (`private/screen.toml`, written once at build time from the tab):
  - Each bucket's current total weight and number of names.
  - **Royalty:** its weight is taken from Gold producers, the same metal with the operating risk removed (Rick
    Rule's preference). The user sets the amount at build time; the recommendation from the research is below.
  - The file is the user's to edit afterwards.
- **What the sources say** (as comments in `[portfolio_screen]`, so the limits can be explained):

| Source | Royalty / streaming | Producers ("investments") | Developers and juniors ("speculation") |
|---|---|---|---|
| Rick Rule (interviews; a secondary summary for the sleeve figures) | The best business in mining: margins near 80% against 15–20% for operators. His own core holdings lead with Franco-Nevada and Wheaton. | High-quality producers as "investments", after savings (bullion, about 40% of his liquid portfolio in one report). Gold equities about 10%, split between seniors and juniors. | "70% of resource juniors are never cheap because they're worth nothing." A junior sleeve of 5–10% of total assets, at most 12–15 names, 8–10 core convictions at 3–10% of the sleeve each (secondary source, not in his own words). |
| Doug Casey | — | — | Cautious investors: about 90% in lower-risk holdings, the rest in speculation; overweighting juniors is "very dangerous". |
| Newsletter and blog models | 20–40% streaming/royalty in a growth mix; seniors and streamers 50–70% of a defensive mix | 30–50% miners | Juniors 15–30% of a mining-stock portfolio; 2–5% of total wealth for conservative investors |

- **Committed limits from that research** (`[portfolio_screen.limits]`). They are warnings in the report, not
  hard stops, because the user decides the sizes:
  - **Per-name cap:** royalty and producers 6% of the portfolio; developers and expanding producers 3%. Rule's
    "3–10% of the sleeve" is about 1% of a whole portfolio, and this model is a mining-only sleeve, so it can be
    larger.
  - **Speculation (developers + expanding producers):** at most 25% of the model portfolio, warned above 25%.
    Rule's 5–10% and Casey's ~10% are shares of *total* wealth. This tab is a mining sleeve alongside bullion, so
    the newsletter range of 15–30% of the mining stocks is the comparable figure.
  - **Developers:** at least 6 names when the bucket holds any. With most juniors worth nothing, fewer names is a
    concentrated bet. At most 15 names, Rule's cap.
  - **Royalty:** 2–4 names. The universe is about six companies, and the large ones dominate.

### Selection and weights

- **Names**: the top N per bucket, with N from `private/screen.toml`.
- **Turnover buffer** (`buffer`, default 2): a holding already on the tab stays while it ranks within N + buffer
  and passes the filters, so the list doesn't churn on small rank changes. A holding that fails a filter is
  dropped and the reason is reported.
- **Weights**: each bucket's total weight is split equally among its names. Optionally tilt by score within
  ±`tilt` (default 0, which means equal weights). The per-name cap spreads any excess over the rest of the bucket.
  Physical metal rows keep their typed weights, and the screened weights are scaled so all of F sums to 1.
- **Fewer eligible names than N** (likely in Royalty or Silver with the default markets): hold what's eligible,
  give the bucket's leftover weight to the same bucket's names up to the cap, and report the rest as unallocated
  rather than moving it to another bucket.
- **The silver rule in G** (PSLV filled first from C4) is unaffected: PSLV stays a Physical metal row, and silver
  stocks keep E = "Silver".

### The command

`python -m minerval screen` (needs the Sheet; reads PNAV inputs, P/NAV, Holdings, Holdings downside and the Model
portfolio):

- **`--dry-run`** (the default): writes `out/screen/proposal.csv` and `out/screen/report.txt`.
  - The report shows each bucket's ranked eligible companies, with their score and measures.
  - It lists the companies excluded by a filter, with the filter (including "market").
  - It shows any limit warnings.
  - It shows the proposal against what's on the tab now: added, kept, dropped (with why) and weight changes.
  - These files are local only. Show the user the report before any write.
- **`--all-markets`**: include companies without a US or Canadian listing, marked with their fee.
- **`--write`**: writes the proposal to Model portfolio rows 6–31:
  - **A–F:** bucket, holding (the P/NAV tab's name, exactly, since H–N look it up by B), where it trades,
    Sprott ticker (Holdings downside L, since O–R look it up by D), main metal and target weight.
  - **C ("Where it trades"):** comes from the listing columns, for example "NYSE (ADR)", "TSX; US OTC: XXXXF",
    "ASX only: about $50 a trade in an IRA".
  - **S:** the review level (Part 2).
  - **U** ("Why it's in"): a generated line from the measures, for example "Screen: valuation 0.71× peer norm;
    breakeven 38% below today's gold; net cash 14% of market value; add-on 0.5". Kept for a holding that stays if
    the user has edited it (any text not starting with "Screen:").
  - **V** ("What would change the view"): kept for a holding that stays; for a new one, "Screen: review above
    <S>× peer norm, or if it fails a filter".
  - **Rows:** Physical metal rows first, as they are, then buckets in `[signals.timing]` order with Royalty after
    Physical metal. If the proposal needs more than 26 rows, stop and say so: rows can't be added below 31
    (CLAUDE.md). Clear any rows left over in A–F, S and U–V with empty values.
  - **Never** write G–R, T or W–Z (formulas; K has its own formula in each row and follows B).
  - **Before writing:**
    - Save A6:V31 (with formulas) to `out/screen/backup-<time>.json`.
    - Check that every B is on the P/NAV tab and every D is on Holdings downside L, and stop if not.
  - **After writing:** read back H, K and T. Report rows showing "" or "Check by hand" where the screen had
    numbers, which means a lookup failed.
- **`--email`** (with `--write`): one private email listing what changed (added, dropped, weights), through the
  alerts SMTP settings. The next `prices` run will also email the Status changes, as usual.
- **Part 3** runs at the end of `--write`.

## Part 2: review levels from a rule

- T reads "Review: above level" when K (valuation vs peer norm, 1.0 = in line) is above S.
- The rule is `review_multiple` from `[portfolio_screen.review]`: 1.3 by default (30% above the peer norm), with
  per-bucket overrides (developers might warrant 1.5, since study NPVs are rougher).
- **A level typed by hand stays** (the user's choice):
  - `screen --write` records the S values it wrote in `private/screen_state.json` (by Sprott ticker).
  - On the next write, a row whose S still equals the recorded value is the screen's, and it is updated.
  - A row whose S differs was typed by the user, and it is kept. The report lists it as "review level typed by
    hand: kept".
  - A new holding gets the rule's level. If the state file is missing, every non-blank S is treated as typed by
    hand.
- Physical metal rows: S stays as typed.
- The filter in Part 1 uses the rule's level (or the typed one, for a holding that has one), so a new name always
  starts below it.

## Part 3: `private/portfolio.csv` from the tab

- `python -m minerval portfolio-file` (also run at the end of `screen --write`) reads Model portfolio A–F and B3,
  C4, and writes `private/portfolio.csv` in the format `backtest.portfolio()` reads:

| Column | From |
|---|---|
| key | D (Sprott ticker) |
| label | B |
| group | A |
| metal | E, lower case |
| amount_usd | F × (B3 + C4), the target position in US$ |
| already_held | "yes" only for the silver covered by C4 (the PSLV row up to C4); else "no" |
| yahoo | Holdings P for that ticker (Holdings O); for physical trusts, `[portfolio_screen.physical_symbols]` (PHYS, PSLV, COP-U.TO) |
| toronto_listing_in_cad | "yes" when the Yahoo symbol ends in .TO or .V and its currency (Holdings S) is CAD |
| first_month | blank (the backtest finds each series' start), unless the old file had a value for the same key, which is kept |

- Before overwriting, keep the old file as `private/portfolio.<date>.csv`.
- Then `backtest` and `project` test the tab's portfolio. The report says the file was written and how many rows,
  never the names or amounts.
- If a symbol has no monthly history (`fetch-history` reports it), say so; the backtest already skips such series.

## Tests (offline, MemorySheet; no real names or weights in fixtures)

- Bucket mapping, Royalty included, and the override column.
- Market rule:
  - US and Canadian listings in, foreign-only out by default and in with `--all-markets`;
  - Canada rep-assisted kept or dropped by the setting;
  - unresearched rows count as foreign-only;
  - the listing columns are filled from the Sprott exchange code.
- Each hard filter, at its edge.
- Rank-percentile score: ties, missing measures (a royalty company with no own-history percentile), and a
  one-company bucket.
- Selection with the turnover buffer: a holding at rank N + 2 stays, and one at N + 3 is replaced.
- Weights:
  - an equal split, and the cap spreading the excess;
  - a bucket with fewer eligible names than N;
  - physical rows kept;
  - F sums to 1.
- Limit warnings: speculation share, developer count, per-name cap.
- The write:
  - only A–F, S and U–V are touched;
  - leftover rows are cleared with CLEAR;
  - the 26-row limit stops the write;
  - a B or D that doesn't look up stops it;
  - U lines typed by the user are kept.
- Review level:
  - the rule's level, and a bucket override;
  - a typed S kept (it differs from the state file);
  - a screen-written S updated;
  - with no state file, typed S kept.
- portfolio-file:
  - columns and types match `config/portfolio.example.csv`;
  - amount = F × (B3 + C4);
  - already_held for PSLV;
  - the CAD flag;
  - first_month carried over.
- Data-file checks:
  - `[portfolio_screen]` thresholds present;
  - every bucket is in `[signals.timing]` or is Royalty;
  - listing columns well formed;
  - the new example portfolio holds no Model portfolio ticker other than PHYS (checked against a fixed list in
    the test, not the Sheet).

## Docs

- **README:** a "Model portfolio from a screen" section covering:
  - what is screened and what isn't;
  - the market rule and why (the fee table);
  - the filters, the score and the research limits;
  - that the rules are public and the bucket sizes private;
  - the run order: `refresh`, `financials`, `screen --dry-run`, review, then `screen --write`.
- **CLAUDE.md:**
  - the commands table (`screen`, `portfolio-file`) and what they write (Model portfolio A–F, S, U–V;
    `private/portfolio.csv`, `private/screen_state.json`);
  - that A–F, S and U–V are now written by `screen`, and S typed by hand is kept;
  - that the screen's output stays out of the repo and the logs;
  - to research a new company's listings when it's added to `pnav_companies.csv`.
- **Roadmap:**
  - mark item 5 built;
  - add the yearly fee-schedule check to the calendar;
  - add the unresearched listings as a small item if any are left.

## Done when

- `screen --dry-run` gives a ranked, explained proposal for each equity bucket, Royalty included, with US and
  Canadian names only by default, and the user has reviewed it.
- `screen --write` has filled the tab with no lookup failures.
- S follows the rule except where the user typed it.
- `backtest` runs on the `private/portfolio.csv` written from the tab.
- The example portfolio is neutral.

## At build time, ask the user

1. **Royalty's weight:** how much to move from Gold producers, and how many names. The research suggests 2–4
   names; the recommendation is given in conversation, not here, because the weights are private.
2. **Listings:** confirm the researched US and Canadian listings for the 39 non-US, non-Canadian companies before
   the first `--write`.
