# Roadmap

What to build next, in order, and why that order. Each item has a spec in `docs/specs/` written for Claude Code
to implement, on its own branch and PR, following CLAUDE.md. Sizes are rough: S is an afternoon, M a day or
two, L several days.

Written Nov 18, 2026, after the market-signals work (PR #5) and the scheduled GitHub price update went live.

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
| 1a | **Built Nov 2026.** **Signal history**: one row per run on a new Signal history tab, plus a daily snapshot of each royalty company's P/NAV and each developer's EV/oz and months of cash | [signal-history-spec.md](specs/signal-history-spec.md) | S | — |
| 1b | **Built Nov 2026.** **Alerts**: a GitHub issue (market signals) and an optional private email (Model portfolio rows) when a status changes | [alerts-spec.md](specs/alerts-spec.md) | S | 1a helps (dates of changes) |

## Phase 2: test the framework (early December 2026)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 2a | **Built Nov 2026** (the Q3 2026 AISC row is still to add). **Signal backtest**, including an industry AISC history table, so the AISC margin can be tested and the Q3 2026 figure (World Gold Council, due early December 2026) goes in from the record | [signal-backtest-spec.md](specs/signal-backtest-spec.md) | L | WGC Q3 2026 AISC for the last row |
| 2b | **Built Nov 2026.** **Junior breadth**: the share of SGDJ and COPJ (by weight) above their 200-day averages, as a confirmation signal | [junior-breadth-spec.md](specs/junior-breadth-spec.md) | S | best built alongside 2a, which tests it |

After 2a, revisit the thresholds in `config/settings.toml` [signals.thresholds] and on the Signals tab
(G:H) with the results in hand. That's a judgment call for the user, not something the code changes.

Done in Nov 2026: the real yield and the dollar's 12-month change are context only (status "Info", no
thresholds), because neither showed an edge. Their old rules stay in the backtest
(`[signal_backtest.context_thresholds]`).

Built in Nov 2026 (2c): a **rate-expectations signal** for physical gold (`two_year_3m_change`, with
`two_year_minus_fed_funds` and `two_year_yield` for context). It is the Model portfolio's timing signal for
physical gold. A one-off study (Nov 2026,
month-ends 2003–2026) found the 10-year real yield moves with gold in the same month (correlation −0.44
monthly, −0.58 over 3 months) and not ahead of it at any lag, so a rule that waits for it to peak and fall
comes late. What the market expects the Fed to do did better, from FRED's 2-year Treasury yield (DGS2) and
the effective fed funds rate (DFF):

- 2-year yield down 0.25 points or more over 3 months ("turning dovish"): gold +11.4% over the next 6
  months against +6.1% for all months, up 90% of the time, score +2.6 (17 independent windows). Positive at
  every threshold from 0.10 to 0.75, and in both 2003–2013 and 2014–2026.
- 2-year yield 0.25 points or more below fed funds ("market expects cuts"): +14.4% over 6 months, up 90%,
  score +2.4 (12 windows).
- Caveat: both fire in clusters around three or four easing cycles (2006–08, 2019–20, 2023–25), so the
  real evidence is a handful of episodes. CME FedWatch probabilities aren't freely available as history;
  Yahoo's front fed funds future (ZQ=F) covers only the next month and was too noisy.

## Phase 3: developers (December 2026 to January 2027, before the next tax-loss window closes in practice)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 3 | **Built Nov 2026.** **Developer financing and valuation**: undrawn facilities in the cash runway, an expected-raise estimate and NAV per share after it, and EV/oz weighted by resource category | [developer-financing-spec.md](specs/developer-financing-spec.md) | M | — |

Why now: Skeena showed 1.4 months of cash because its project financing wasn't counted. The "Short
of cash" checks drive the junior timing column, so they need to be right before the next junior entry.

Built: committed funding, remaining capex and a "funded" statement per developer (PNAV inputs BF:BI), the
funding gap, an equity raise for it and P/NAV after (BJ:BO, Model portfolio Z), and EV per weighted unit by
resource category (BP:BW). Filled for a first set of developers; the rest of the developer rows, and resource
splits for Collective Mining and Viscaria, are open (small items below).

## Phase 4: model improvements (with the Q4 2026 reports, February to March 2027)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 4a | **Producer costs from company AISC and energy share**, so the diesel signal feeds the cost scenario | [producer-costs-spec.md](specs/producer-costs-spec.md) | M | Q4 reports for company AISC; 2a (industry AISC table) |
| 4b | **Built Nov 2026.** **Jurisdiction risk from a country table** instead of a hand-set add-on per company | [jurisdiction-risk-spec.md](specs/jurisdiction-risk-spec.md) | M | — (can move earlier) |
| 4c | **Built Nov 2026.** **Royalties against their own history** as well as the peer median | [royalty-history-spec.md](specs/royalty-history-spec.md) | S–M | 1a (needs months of recorded P/NAVs); the Yahoo-based fallback works from day one |

## Phase 5: Model portfolio from a screen (any time; before the first purchase)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 5 | **Built Nov 2026.** **Model portfolio from a screen**: rank PNAV inputs companies within each bucket (a new Royalty bucket included) and propose the holdings and target weights (Model portfolio A–F), only names buyable on US or Canadian markets by default (`--all-markets` for the rest: about $50 a trade in a Fidelity IRA), set the review levels (S) from a rule while keeping levels typed by hand, and write `private/portfolio.csv` from the tab so the backtest tests what the Sheet shows | [model-portfolio-screen-spec.md](specs/model-portfolio-screen-spec.md) | M | — (4a later improves the breakeven measure) |

Why: the user holds no miners yet, so the holdings needn't be a fixed hand-picked list. The rules are committed;
bucket sizes, names and weights stay private (Sheet and email only). Decisions taken Nov 20, 2026 are in the spec;
two things to ask at build time are at its end.

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
