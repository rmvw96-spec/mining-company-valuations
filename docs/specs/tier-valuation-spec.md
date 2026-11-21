# Valuation by tier: EV against a 10-year NPV at three price decks

Instructions for Claude Code. Roadmap item 6. Follow CLAUDE.md.

**Status: spec, being written with the user (started Nov 21, 2026).** Open questions are at the end.

## Why

The screen built in roadmap 5 ranked producers on P/NAV at **today's spot price, held flat over the reserve life
(up to 25 years), from free cash flow after all capital spending**. On Nov 21, 2026 that gave 36 of 97 producers a
negative NAV. Their capital spending was 96% of operating cash flow (median), against 35% for the rest, and only 7
of the 36 were still negative before capital spending. Most of the negatives came from treating a one-off build as
a permanent cost, while the production it builds was never counted. Spot had also just fallen about 21% below its
12-month average, so the ranking depended on the week it ran.

Rick Rule's approach (as summarised by the user, Nov 21, 2026; secondary sources, not his own published model)
values each tier as a different business, and its core test is **enterprise value against the NPV of the assets at
realistic price scenarios**. This spec moves the framework to that method for everything in it that can be
quantified with research. Judgement calls stay with the user: **explorers and takeover appeal are out of scope.**

## Gaps this closes

| Rule | Framework before this spec | This spec |
|---|---|---|
| 10-year DCF | Reserve life, capped at 25 years | 10 years (Part 1) |
| EV against NPV | Market cap against NPV + net cash | EV / NPV (Part 1) |
| Pessimistic, base and optimistic decks; not spot alone | The screen ranked on spot | Three decks you set; spot as a cross-check (Part 1) |
| Cash flow after **sustaining** capital spending | After all capital spending | Operating cash flow − sustaining spending, from MD&As (Part 2) |
| Proven pipeline projects added to NPV | Not counted; their build cost was | Risk-adjusted study NPV of committed projects (Part 2) |
| Free-cash-flow yield, AISC | Neither in the screen | Sustaining FCF yield; AISC from roadmap 4a (Part 2) |
| Cost inflation | `--cost-increase`, unused by the screen | The pessimistic case runs with costs raised (Part 2) |
| Political risk counted once | Discount-rate add-on plus two score measures | Discount-rate add-on only (Part 1; the screen spec drops the measures) |
| Developers: study NPV discounted for time and probability of success | Study NPV as published | The study's cash flows rebuilt at our discount rate and the decks, then discounted for years to production and probability by stage (Part 3) |
| Developers: survive a 15–30% capex overrun without destructive dilution | Funding gap at the stated capex | The gap and dilution at +15% and +30% (Part 3) |
| Developers: capex-to-market cap | Not measured | Remaining capex ÷ market cap (Part 3) |
| Royalties: P/NAV, cash-flow multiples, cost of capital | Independent P/NAV, P/OCF against own history | Same, plus EV / NPV of operating cash flow at the decks (Part 4) |
| Explorers: liquidation value, the "unanswered question" | — | Out of scope (judgement) |
| Developers: acquisition appeal | — | Out of scope (judgement) |
| Royalties: exploration optionality, scale arbitrage | — | Not modelled: no quantity to research. Market cap stays visible for the user's judgement |

## Step 0: data pilot (before any build)

The user asked to check the research is readily available before committing to it.

- **Sample:** 15 companies from the 60 nearest the screen's cut: 3 from each tier (royalty, senior producer,
  intermediate producer, junior/expanding producer, developer), with a small, middle and large market cap in each.
  Picked by Claude Code, confirmed by the user; the sample (company names) is research, not portfolio content,
  because it's chosen by tier and size, not by what the screen proposes.
- **For each, try to find, with a source and date:**
  - sustaining capital spending for the latest fiscal year (producers);
  - attributable production for 2022–2025 (unit as reported: oz Au, oz AuEq/GEO, oz AgEq, lb Cu, lb CuEq);
  - attributable proven and probable reserves at each year-end 2022–2025;
  - for each published study (developers, and producers' growth projects): study type and date, the annual
    after-tax cash-flow schedule and payable production by metal (the technical report's cash-flow table), the
    study's metal prices, after-tax NPV and its discount rate, initial capex, and the expected start of construction
    or first production;
  - for royalties: attributable GEO sold for 2022–2025.
- **Output:** `out/pilot/coverage.csv` (company, item, found yes/no, source, minutes taken) and a short report: what
  share of each item was found, and where it's usually published (MD&A, annual information form, 40-F/10-K,
  technical report).
- **Gate:** the user reviews the coverage and decides whether each item goes ahead, waits, or changes. Items below
  about two-thirds coverage need a fallback or a different measure.

**Pilot results (Nov 21, 2026, first pass; `out/pilot/`, local):** production 9 of 9 producers and royalty GEOs 3
of 3; sustaining spending 5 of 9 (all seniors, 2 of 3 intermediates, no juniors from their results releases);
reserves 3 of 9; study cash-flow tables 1 confirmed, 1 likely, 1 superseded by a press release. The rebuild matched
the New Pacific PFS exactly at its own price (5% and 8%) and within 1–4% of its price grid. Press releases and call
summaries aren't a record (one summary misstated Alamos's sustaining spending by a factor of three). Decisions: a
second pass on the juniors' MD&As for sustaining spending, the free-cash-flow fallback where none is split;
reserves plus M&I resources per share (screen spec); the study's own tax share; no NPV for a study superseded by a
press release.

## Part 1: the common method

### Price decks

- `[scenarios]` gets **Pessimistic, Base and Optimistic**, each with gold, silver and copper set **independently**.
  No ratio links them (the gold-to-silver ratio moves with the cycle, and copper follows the economy more than the
  monetary metals). Severe and All-time high stay for the stress test.
- The numbers are the user's and change with forecasts: nothing in the design may depend on their values. Each deck
  carries a `source` and `as_of` comment in settings.
- **Spot** ("Today") stays as a cross-check column, never the basis of a buy signal or a ranking.
- On the Sheet, Metal prices reference H15:K17 (today Low / Medium / High / All-time high, with Medium equal to
  Today) becomes Pessimistic / Base / Optimistic / All-time high. Find every formula that reads H15:K17 (PNAV
  inputs, Holdings downside K) before relabelling, and keep `[scenarios]` and the cells in step as today.

### Discount rate

- 10-year Treasury yield + 3% + the jurisdiction add-on (PNAV inputs P), as now. This is now the **only** place
  jurisdiction counts; the screen spec drops its `addon` and `addon_reliance` measures.

### NPV and EV

- **Horizon:** `[valuation] horizon_years = 10`. Cash flow for min(reserve life, 10) years, no terminal value.
- **NPV** (US$M) at each deck = the PV of those cash flows. Net cash is **not** added: EV already nets it.
- **EV** = market cap + debt − cash (PNAV inputs AZ, as now).
- **EV / NPV**: 1.0 = priced at the deck's value. When NPV ≤ 0 the cell reads "negative NPV", never a number.
- **Where it's computed:** Python writes the NPVs (they change only with the financials, the research inputs or the
  decks), from `financials`. EV / NPV and the buy-below price are Sheet formulas over today's EV, so the daily
  `prices` run moves them. Python computes the same values in `data/derived/` for tests and the screen, as today.
- **Reserve-life P/NAV** (today's method) stays as a context column, so the two can be compared during the switch.

### Validation report

`valuation --check` (or part of `financials --dry-run`) compares each NPV with the independent model's NAV (PNAV
inputs R) and the analyst consensus P/NAV (P_NAV I) where present, and lists differences over 2×, so a bad input
shows before it reaches a buy signal.

## Part 2: producers

- **Cash flow** = operating cash flow (trailing 12 months) − **sustaining** capital spending, re-priced from the
  reporting period's average metal prices to each deck with the existing adjustment (cash flow moves by
  `cash_flow_share` × revenue × the price change, by revenue mix).
- **Sustaining spending** (research inputs in `pnav_companies.csv`, the record, and PNAV inputs, the working copy):
  `sustaining_capex_usd_m`, `sustaining_capex_period` (fiscal year or trailing 12 months, and its end date),
  `sustaining_source`. Converted at the stated date's rate, and the source says so. **Capitalized stripping**
  (waste removal capitalized by open-pit miners, reported separately by Teck and Capstone) **counts as sustaining
  spending** (the user, Nov 21, 2026), so open-pit and underground miners compare fairly; record it in
  `capitalized_stripping_usd_m` beside the sustaining figure. Blank where a filing doesn't
  split sustaining from growth: **never estimated**.
- **Built (Nov 21, 2026):** the record is `data/research/capex_periods.csv` (one row per filing period, as reported,
  consolidated basis); `research sustaining --write` builds the trailing 12 months to each company's financials date
  and writes `sustaining_capex_usd_m`, `capitalized_stripping_usd_m`, `sustaining_period_end` and
  `sustaining_source` to `pnav_companies.csv`; `research fetch` / `research find` download and search the filings.
  Filled for the 9 pilot producers.
- **Fallback when blank:** free cash flow after all spending, the conservative case. The row is labelled
  "FCF basis: sustaining not recorded", and the screen and the buy signal say so.
- **Pipeline:** a growth project counts only when it is **committed** (construction decision taken or under
  construction) and has a published study. Its value is the developer method (Part 3) applied to the project, at
  the company's attributable share, added to the NPV. Projects live in a new `data/research/projects.csv` (one row
  per project; columns in Part 3).
- **Cost inflation:** the pessimistic deck runs with costs raised by `[valuation] pessimistic_cost_increase` (the
  existing cost-change function; 4a's company AISC improves it when built). Base and optimistic use reported costs.
- **New measures** (for the screen and the Sheet):
  - EV / NPV at each deck;
  - sustaining FCF yield = cash flow at the base deck ÷ EV;
  - the downside test: EV ≤ NPV at the pessimistic deck (with costs raised).

## Part 3: developers

### Inputs (the record: `data/research/projects.csv` and `data/research/project_cashflows.csv`)

Decided with the user (Nov 21, 2026): **rebuild each study's cash flows** rather than take its NPV, so every tier is
discounted at our rate and priced at our decks.

`projects.csv`, one row per study, each figure with its source:

| Column | Content |
|---|---|
| `ticker`, `project`, `attributable_pct` | Company, project, its share |
| `study_type`, `study_date` | PEA, PFS, FS (or DFS), or construction (a feasibility study with a construction decision) |
| `study_price` | The study's price per metal (e.g. `gold 2600; copper 4.00`) |
| `study_npv_usd_m`, `study_discount_rate` | The published after-tax NPV and its rate, kept to check the rebuild |
| `sensitivity` | The study's price-sensitivity rows (`gold 3000:850; 3500:1240`), kept to check the re-pricing |
| `initial_capex_usd_m` | The study's initial capex |
| `first_production` | Expected first production (company guidance, with its date) |
| `committed` | For a producer's growth project: "yes" when a construction decision is taken |
| `source`, `as_of` | Where each figure is from |

`project_cashflows.csv`, one row per study and year (from the technical report's cash-flow table): `year` (1 =
first year of construction), after-tax free cash flow (US$M, capex included), and payable production per metal.

### Method

1. **Re-price each year** to each deck: free cash flow + tax share × payable production × (deck price − study
   price), by metal. **The tax share is the study's own** (the user, Nov 21, 2026): the change in post-tax cash flow
   ÷ the change in pre-tax cash flow, from the study's tables, or 1 − its effective tax rate. `cash_flow_share`
   (0.70) only where a study publishes neither. `project_cashflows.csv` also records pre-tax cash flow for this.
2. **Discount at our rate** (10-year + 3% + the add-on) from year 1. Developers keep the study's whole mine life:
   Rule discounts the study's value, not a 10-year window (the 10-year window is for producers).
3. **Check the rebuild:** at the study's own price and rate, the rebuilt NPV should be within 5% of the published
   one, and the re-pricing should match the sensitivity rows within 10%. A study that fails is flagged and not used
   for a buy signal until it's checked.
   **A study superseded by a press release** (new economics with no new technical report, e.g. Perpetua's March
   2026 update over its 2020 feasibility study): no NPV, status "No NPV: awaiting technical report", until a
   report with a cash-flow table is filed (the user, Nov 21, 2026).
4. **Discount for time:** from year 1 to today. Year 1 is the expected construction start (company guidance, with
   its date); a study with no construction decision and no guided date is flagged.
5. **Probability of success by stage:** `[valuation.stage_probability]` for PEA, PFS, FS, permitted and
   construction. The values are to be researched at build time with sources, and the user confirms them (open
   question).
6. **Risk-adjusted NPV** = rebuilt NPV × time discount × probability × attributable share.
7. **Capex overrun:** the funding gap (roadmap 3: remaining capex − cash − committed funding) recomputed with
   remaining capex raised by each of `[valuation] capex_overrun = [0.15, 0.30]`, with the new shares and dilution of
   an equity raise for each (the existing raise at `raise_discount`). **The downside test passes** when dilution at
   +30% is at most `[valuation] max_overrun_dilution = 0.33` (the user, Nov 21, 2026).
8. **Capex-to-market cap** = remaining capex ÷ market cap.

New measures: EV / risk-adjusted NPV at each deck, the overrun dilution at +15% and +30%, and capex-to-market cap.
EV per weighted unit (roadmap 3) stays.

### Structured stage

`stage` in `pnav_companies.csv` is free text today ("Developer (DFS June 2026; investment decision due Q2 2027)").
Add `study_stage` (PEA / PFS / FS / permitted / construction / none), filled from the text and checked against the
latest study row.

## Part 4: royalties

- **NPV of operating cash flow** at each deck over 10 years (royalties carry no sustaining spending), with the same
  discount rate. Rule's lower cost of capital for royalties shows in the buy level, not in the rate (Part 5).
- Kept: independent P/NAV (AJ), the framework band (AS), P/OCF and own-history percentiles (BY:CA).
- New: EV / NPV at each deck, and the downside test at the pessimistic deck.

## Part 5: the buy level and fair value (used by the screen spec)

Decided with the user (Nov 21, 2026): **a discount to the base-deck NPV plus a downside test at the pessimistic
deck**, levels configurable per tier in `[valuation.buy]`:

| Tier | Buy when (both) | Fair value (review above) |
|---|---|---|
| Producers | EV ≤ 0.6 × base NPV, and EV ≤ pessimistic NPV with costs raised | EV ≥ 1.0 × base NPV |
| Royalties | EV ≤ 1.0 × base NPV, and EV ≤ pessimistic NPV | EV ≥ 1.5 × base NPV (the top of the framework's normal range) |
| Developers | EV ≤ 0.6 × base risk-adjusted NPV, and the +30% overrun test passes | EV ≥ 1.0 × base risk-adjusted NPV |

- **Why these levels:** Rule buys at large discounts to his own NPV (about 40% in a Dec 2025 example, Exxon), uses
  his own conservative price (about $3,400 gold, Kitco Sept 2026, from secondary write-ups) and checks the downside
  before the upside. Royalties trade at premiums for low risk: Rule cites 15–20× cash flow for precious-metals
  royalties against 5–7× for base-metal producers (Kitco, Feb 2026). For context, Sprott's August 2022 table of
  typical P/NAV by stage: PEA 0.2–0.5×, PFS/FS 0.5–0.7×, construction 0.5–0.8×, production 0.6–1.5×. None of these
  is a published Rule threshold; they are starting values for the user to set, not fitted to data.
- **Buy-below price per share** (US$ and the listing currency) = the highest price that meets both conditions:
  (min(buy × base NPV, pessimistic NPV) + net cash) ÷ shares. A Sheet formula, so it moves with the decks and the
  financials, and the status moves with the price.
- **No NPV** (negative at the base deck, or inputs missing): no buy-below price, and the status says why.

## Sheet

- New PNAV inputs columns after CB (placed by `setup-sheet`, layout in `[sheet.pnav_inputs]`): sustaining spending
  and its source; NPV at each deck and its basis (OCF − sustaining / FCF fallback / study); EV / NPV at each deck
  (formulas); the downside test; sustaining FCF yield; developer overrun dilution and capex-to-market cap; the
  buy-below price (formula).
- The Company history tab records each company's daily EV / base NPV, so an own-history view can come later.
- `setup-sheet --dry-run` first, shown to the user, as always.

## Tests (offline)

- The 10-year NPV, EV / NPV and "negative NPV".
- Decks: each metal independent; changing a deck changes NPVs and nothing else.
- Producers: OCF − sustaining, the FCF fallback and its label, re-pricing by mix, the pessimistic cost increase, a
  committed project added and an uncommitted one not.
- Developers: re-pricing a cash-flow schedule by metal, the rebuild check against the published NPV and the
  sensitivity rows, the time discount (including no guided construction date), probability by stage, attributable
  share, the overrun dilution and its test.
- Royalties: OCF NPV and the downside test.
- Buy-below price at each binding condition (the discount or the downside test).
- Data files: `projects.csv` and `project_cashflows.csv` well formed and consistent (years per study, metals named
  in `study_price`), every figure with a source, `study_stage` values valid.

## Docs

- README: the valuation method by tier, the decks (the user's, with sources), and why spot is only a cross-check.
- CLAUDE.md: the new research inputs and their record (`projects.csv`, `project_cashflows.csv`, the sustaining
  columns); never estimate;
  after a new study or a sustaining figure, update the row and the Sheet together.
- Roadmap: mark item 6.

## Done when

- The pilot coverage has been reviewed and the research items agreed.
- Every Model portfolio candidate has an NPV at the three decks with its basis shown, and the validation report has
  been read with the user.
- The buy-below price and fair-value level are on the Sheet for every company with an NPV.

## Decided with the user (Nov 21, 2026)

- Scope: everything in Rule's method that research can quantify; judgement calls (explorers, takeover appeal) stay
  with the user.
- Jurisdiction counts once, through the discount-rate add-on.
- Decks are configurable, metal by metal, and the design doesn't depend on their values.
- Buy level: a discount to the base-deck NPV plus a downside test at the pessimistic deck (Part 5).
- Developers: rebuild the study cash flows at our rate and decks.
- Royalties: fair value at 1.5× base NPV.
- Developer overrun test: at most 33% dilution at a 30% capex overrun.
- Production, reserves and sustaining spending are researched from the start, after the Step 0 pilot.

## Open questions (ask as they come up)

1. **Probability of success by stage:** research values with sources at build time; the user confirms them.
