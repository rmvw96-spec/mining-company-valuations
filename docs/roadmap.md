# Roadmap

What to build next, in order, and why that order. Each item has a spec in `docs/specs/` written for Claude Code
to implement, on its own branch and PR, following CLAUDE.md and the format in
[specs/TEMPLATE.md](specs/TEMPLATE.md). Sizes are rough: S is an afternoon, M a day or
two, L several days.

Written Nov 18, 2026, after the market-signals work (PR #5, [market-signals-spec.md](specs/market-signals-spec.md)) and the scheduled GitHub price update went live.

## Status

Each item, its spec and its acceptance criteria checked off. **Built**: the build is done, and anything still open
waits on the user or on data not yet published (criteria marked "(user)" or "(data)"). **In progress**: partly
built. **Outstanding**: not started. `tests/test_data_files.py` checks this table against the specs.

| # | Item | Spec | Status | Criteria | Checked | Still open |
|---|---|---|---|---|---|---|
| 0 | Market signals (PR #5) | [market-signals-spec.md](specs/market-signals-spec.md) | Built | A1–A15 | 15 of 15 | — |
| 1a | Signal history | [signal-history-spec.md](specs/signal-history-spec.md) | Built | A1–A9 | 9 of 9 | — |
| 1b | Alerts | [alerts-spec.md](specs/alerts-spec.md) | Built | A1–A7 | 7 of 7 | — |
| 2a | Signal backtest | [signal-backtest-spec.md](specs/signal-backtest-spec.md) | Built | A1–A10 | 8 of 10 | WGC Q3 2026 AISC, early December (data); the user's read of the report (user) |
| 2b | Junior breadth | [junior-breadth-spec.md](specs/junior-breadth-spec.md) | Built | A1–A7 | 7 of 7 | — |
| 2c | Rate-expectations signal | [market-signals-spec.md](specs/market-signals-spec.md) | Built | A2, A4 | 2 of 2 | — |
| 3 | Developer financing | [developer-financing-spec.md](specs/developer-financing-spec.md) | Built | A1–A10 | 9 of 10 | figures not yet published (data) |
| 4a | Producer costs | [producer-costs-spec.md](specs/producer-costs-spec.md) | Outstanding | A1–A8 | 0 of 8 | all |
| 4b | Jurisdiction risk | [jurisdiction-risk-spec.md](specs/jurisdiction-risk-spec.md) | Built | A1–A8 | 7 of 8 | the user's review of the comparison before `financials` writes it (user) |
| 4c | Royalty history | [royalty-history-spec.md](specs/royalty-history-spec.md) | Built | A1–A10 | 10 of 10 | — |
| 5 | Model portfolio screen, revision 1 | [model-portfolio-screen-spec.md](specs/model-portfolio-screen-spec.md) | Built | A1–A19 | 18 of 19 | the first `screen --write` (user) |
| 5b | Model portfolio screen, revision 2 | [model-portfolio-screen-spec.md](specs/model-portfolio-screen-spec.md) | In progress | A20–A28 | 5 of 9 | the developers' measures (A21); production and reserves research (data); the score weighting (user); docs (A28) |
| 6 | Valuation by tier | [tier-valuation-spec.md](specs/tier-valuation-spec.md) | Built | A1–A32 | 30 of 32 | the decks with `pessimistic_cost_increase` (user); NPVs for the last three candidates (data) |
| 6b | Valuation coverage | [valuation-coverage-spec.md](specs/valuation-coverage-spec.md) | Built | A1–A7 | 7 of 7 | — |
| 6c | Our NAV first | [own-nav-first-spec.md](specs/own-nav-first-spec.md) | Built | A1–A7 | 7 of 7 | — |

## Principles

- **Start the clocks that can't be rushed.** Some features need history that only accumulates day by day
  (signal history, our own P/NAV history). Those go first, even though they're small, because every day
  before they exist is lost.
- **Test the framework before tuning it.** The Signals thresholds are judgment calls. The backtest tells us
  which signals deserve weight; model refinements come after.
- **Keep the record and the working copy in step.** Every new input lives on the Sheet (working copy) and in
  `config/` or `data/research/` (the record), as today.
- **Nothing personal in the repo or in anything public** (issues, logs, step summaries): no amounts, no
  account details.

## Phase 1: start recording (late November 2026)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 1a | **Signal history**: one row per run on a new Signal history tab, plus a daily snapshot of each royalty company's P/NAV and each developer's EV/oz and months of cash | [signal-history-spec.md](specs/signal-history-spec.md) | S | — |
| 1b | **Alerts**: a GitHub issue (market signals) and an optional private email (Model portfolio rows) when a status changes | [alerts-spec.md](specs/alerts-spec.md) | S | 1a helps (dates of changes) |

## Phase 2: test the framework (early December 2026)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 2a | **Signal backtest**, including an industry AISC history table, so the AISC margin can be tested and the Q3 2026 figure (World Gold Council, due early December 2026) goes in from the record | [signal-backtest-spec.md](specs/signal-backtest-spec.md) | L | WGC Q3 2026 AISC for the last row |
| 2b | **Junior breadth**: the share of SGDJ and COPJ (by weight) above their 200-day averages, as a confirmation signal | [junior-breadth-spec.md](specs/junior-breadth-spec.md) | S | best built alongside 2a, which tests it |
| 2c | **Rate-expectations signal** for physical gold: the two-year yield's 3-month change (with the two-year minus fed funds and the two-year yield for context); the real yield and the dollar become context only | [market-signals-spec.md](specs/market-signals-spec.md) | S | 2a (tested it) |

After 2a, revisit the thresholds in `config/settings.toml` [signals.thresholds] and on the Signals tab
(G:H) with the results in hand. That's a judgment call for the user, not something the code changes.

The evidence for 2c, and why the real yield and the dollar became context only, is in the market-signals spec's
Decisions.

## Phase 3: developers (December 2026 to January 2027, before the next tax-loss window closes in practice)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 3 | **Developer financing and valuation**: undrawn facilities in the cash runway, an expected-raise estimate and NAV per share after it, and EV/oz weighted by resource category | [developer-financing-spec.md](specs/developer-financing-spec.md) | M | — |

Why now: Skeena showed 1.4 months of cash because its project financing wasn't counted. The "Short
of cash" checks drive the junior timing column, so they need to be right before the next junior entry.

## Phase 4: model improvements (with the Q4 2026 reports, February to March 2027)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 4a | **Producer costs from company AISC and energy share**, so the diesel signal feeds the cost scenario | [producer-costs-spec.md](specs/producer-costs-spec.md) | M | Q4 reports for company AISC; 2a (industry AISC table) |
| 4b | **Jurisdiction risk from a country table** instead of a hand-set add-on per company | [jurisdiction-risk-spec.md](specs/jurisdiction-risk-spec.md) | M | — (can move earlier) |
| 4c | **Royalties against their own history** as well as the peer median | [royalty-history-spec.md](specs/royalty-history-spec.md) | S–M | 1a (needs months of recorded P/NAVs); the Yahoo-based fallback works from day one |

## Phase 5: Model portfolio from a screen (any time; before the first purchase)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 5 | **Model portfolio from a screen**: rank PNAV inputs companies within each bucket (a new Royalty bucket included) and propose the holdings and target weights (Model portfolio A–F), only names buyable on US or Canadian markets by default (`--all-markets` for the rest: about $50 a trade in a Fidelity IRA), set the review levels (S) from a rule while keeping levels typed by hand, and write `private/portfolio.csv` from the tab so the backtest tests what the Sheet shows | [model-portfolio-screen-spec.md](specs/model-portfolio-screen-spec.md) | M | — (4a later improves the breakeven measure) |

Why: the user holds no miners yet, so the holdings needn't be a fixed hand-picked list. The rules are committed;
bucket sizes, names and weights stay private (Sheet and email only). The decisions are in the spec.

## Phase 6: value by tier, then a portfolio of the best businesses (specified from Nov 21, 2026)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 6 | **Valuation by tier** (Rick Rule's method): EV against a 10-year NPV at pessimistic, base and optimistic decks; producers on operating cash flow − sustaining spending, with committed pipeline projects; developers from rebuilt study cash flows, discounted for time and probability by stage, with a capex-overrun test; royalties on operating cash flow. A buy-below price and a fair-value level per company | [tier-valuation-spec.md](specs/tier-valuation-spec.md) | L | Step 0 data pilot (done Nov 21, 2026); 4a improves the pessimistic cost case |
| 6b | **Valuation coverage**: a committed record of every company the valuation doesn't fully cover (producers on the fallback, developers without a recorded study, unrecorded growth projects, out of scope by design), kept complete by a test and summarised in the `valuation` report | [valuation-coverage-spec.md](specs/valuation-coverage-spec.md) | S | 6 |
| 6c | **Our NAV first**: the Sheet's P/NAV decisions (royalty buy-below and band, developers' P/NAV after a raise, the Signals royalty median, the screen's royalty measure) use our NAV per share where the valuation has one, with the independent NAV in R kept as the outside reference | [own-nav-first-spec.md](specs/own-nav-first-spec.md) | S | 6 |
| 5b | **Model portfolio revision 2**: select each bucket's best business performers per share at constant metal prices (not on price), and a buy signal per row when the price reaches its tier's buy level; review above fair value | [model-portfolio-screen-spec.md](specs/model-portfolio-screen-spec.md) (revision 2) | M–L | 6; research of production, reserves and sustaining spending for 2022–2025 |

Why: on Nov 21, 2026, P/NAV at spot over 25 years with all capital spending made 36 of 97 producers' NAV negative,
mostly companies mid-build, and ranking on spot made the list depend on the week it ran. The user wants the
portfolio to hold the best businesses and to buy each when its own tier's valuation says it's cheap.

## Done in November 2026 (not in the original plan)

- A "Send a test email" checkbox on the manual price-update run (`test-email` command), to check the email
  secrets without waiting for a Model portfolio status change.
- Repo setting "Automatically delete head branches" turned on; merged branches cleaned up.
- A `snapshots` command that rewrites the Summary, Metal prices reference and Stress test & downside fund
  tables from `data/derived/` (the earnings-season refresh's last by-hand step).

## Small items, any time

- **Country weights: three companies left on the hand-set add-on** (filled Nov 19, 2026 for the other 30):
  Royal Gold (fill if a 10-K or MD&A names revenue for its "Other" properties), Harmony (its FY2027 results or
  20-F, if they split South Africa, Papua New Guinea and Australia) and Central Asia Metals (its 2026 results, if
  they split Kounrad and Sasa revenue). When a weighted company's mix changes (a mine sold or started: Skouries for
  Eldorado, Kurmuk for Allied, Bolañitos sold), refresh its weights from the next annual figures.
- **Provisional median add-ons in `country_risk.csv`**: Bulgaria (dropped from the 2024 survey for too few
  responses), Greece, Poland, Honduras and North Macedonia (in neither survey). Replace them if a later survey
  ranks them.

- **Developer financing: what's left.** Filled Nov 19, 2026 for Minerals 260, Faraday, Hycroft, Marimaca, New
  Pacific, Aldebaran, Viscaria (committed 0; no published cost-to-complete) and Panoro (committed 0; no current
  study). Still blank: Osisko Metals (no economic study yet) and Blue Moon (selling Nussir to ACG Metals,
  closing expected Nov 30, 2026: once it closes, update its row's stage, resource and study). Viscaria's resource
  split (BP:BR): the category table in its May 2025 releases is an image, so read it from the PDF by eye or wait
  for an update. Collective Mining's split is filled.
- **Minerals 260's BF counts placement tranche 1 and the Franco-Nevada royalty** as money not yet in the Sheet's
  cash (June 30, 2026). After the next refresh brings in the September 30 cash, take out what that cash includes.
- **Keep the filled developers current**: Perpetua's EXIM loan (move it into BF when definitive
  documentation closes, expected Q1 2027), AbraSilver's project financing (targeted Q4 2026), Seabridge's KSM
  joint venture, and Skeena's cost-to-complete if it publishes one.
- **Developer cash from Yahoo lags the latest quarterly** for some companies (FireFly: A$337M at Sep 30,
  2026 after a raise, against the older figure on the Sheet). The earnings-season `refresh` + `financials`
  catches up; a big raise in between can be put in BF with a note.

- Entrée Resources (ETG): read its attributable resource from the 2025 Oyu Tolgoi JV technical report.
- Explorers expecting maiden resources: Southern Cross Gold (around Q1 2027), NGEx (Lunahuasi), Hercules
  Metals. Add them to `data/research/pnav_companies.csv` and PNAV inputs AT:AW when published.

## Calendar

| When | What |
|---|---|
| Daily, weekdays | Scheduled `prices` + `signals` on GitHub (21:40 UTC) |
| Early December 2026 | WGC Q3 2026 industry AISC: add to the AISC table (2a) |
| Q1 2027 | Perpetua's EXIM loan expected to close: update its committed funding (BF) |
| Mid-February to March 2027 | Q4 / full-year reports: earnings-season refresh (CLAUDE.md), then 4a |
| End of March 2027 | Royalty companies' 10-K and 40-F filed: `royalty-ocf`, review and commit the new year (4c) |
| Every November | Check Fidelity's Brokerage Commission and Fee Schedule against `[portfolio_screen.markets]` (the IRA fees behind the US/Canada default) |
| Late 2027 | 250 days of recorded royalty P/NAVs: PNAV inputs CA fills in and replaces P/OCF in the own-history band |
| May, August, November | Quarterly earnings-season refreshes |
| November 1 to December 31 | Tax-loss window: junior timing signal is live |
