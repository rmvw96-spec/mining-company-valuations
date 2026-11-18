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
| 1a | **Signal history**: one row per run on a new Signal history tab, plus a daily snapshot of each royalty company's P/NAV and each developer's EV/oz and months of cash | [signal-history-spec.md](specs/signal-history-spec.md) | S | — |
| 1b | **Alerts**: a GitHub issue (market signals) and an optional private email (Model portfolio rows) when a status changes | [alerts-spec.md](specs/alerts-spec.md) | S | 1a helps (dates of changes) |

## Phase 2: test the framework (early December 2026)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 2a | **Signal backtest**, including an industry AISC history table, so the AISC margin can be tested and the Q3 2026 figure (World Gold Council, due early December 2026) goes in from the record | [signal-backtest-spec.md](specs/signal-backtest-spec.md) | L | WGC Q3 2026 AISC for the last row |
| 2b | **Junior breadth**: the share of SGDJ and COPJ (by weight) above their 200-day averages, as a confirmation signal | [junior-breadth-spec.md](specs/junior-breadth-spec.md) | S | best built alongside 2a, which tests it |

After 2a, revisit the thresholds in `config/settings.toml` [signals.thresholds] and on the Signals tab
(G:H) with the results in hand. That's a judgment call for the user, not something the code changes.

## Phase 3: developers (December 2026 to January 2027, before the next tax-loss window closes in practice)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 3 | **Developer financing and valuation**: undrawn facilities in the cash runway, an expected-raise estimate and NAV per share after it, and EV/oz weighted by resource category | [developer-financing-spec.md](specs/developer-financing-spec.md) | M | — |

Why now: Skeena shows 1.4 months of cash because its project-finance facilities aren't counted. The "Short
of cash" checks drive the junior timing column, so they need to be right before the next junior entry.

## Phase 4: model improvements (with the Q4 2026 reports, February to March 2027)

| # | Item | Spec | Size | Depends on |
|---|---|---|---|---|
| 4a | **Producer costs from company AISC and energy share**, so the diesel signal feeds the cost scenario | [producer-costs-spec.md](specs/producer-costs-spec.md) | M | Q4 reports for company AISC; 2a (industry AISC table) |
| 4b | **Jurisdiction risk from a country table** instead of a hand-set add-on per company | [jurisdiction-risk-spec.md](specs/jurisdiction-risk-spec.md) | M | — (can move earlier) |
| 4c | **Royalties against their own history** as well as the peer median | [royalty-history-spec.md](specs/royalty-history-spec.md) | S–M | 1a (needs months of recorded P/NAVs); the Yahoo-based fallback works from day one |

## Small items, any time

- A `snapshots` command that rewrites the Summary and Stress test & downside fund tables (and the fund
  table on Metal prices reference) from `data/derived/`, so step 6 of the earnings-season refresh stops
  being a by-hand job.
- Turn on "Automatically delete head branches" in the repo settings.
- Entrée Resources (ETG): read its attributable resource from the 2025 Oyu Tolgoi JV technical report.
- Explorers expecting maiden resources: Southern Cross Gold (around Q1 2027), NGEx (Lunahuasi), Hercules
  Metals. Add them to `data/research/pnav_companies.csv` and PNAV inputs AT:AW when published.

## Calendar

| When | What |
|---|---|
| Daily, weekdays | Scheduled `prices` + `signals` on GitHub (21:40 UTC) |
| Early December 2026 | WGC Q3 2026 industry AISC: add to the AISC table (2a) |
| Mid-February to March 2027 | Q4 / full-year reports: earnings-season refresh (CLAUDE.md), then 4a |
| May, August, November | Quarterly earnings-season refreshes |
| November 1 to December 31 | Tax-loss window: junior timing signal is live |
