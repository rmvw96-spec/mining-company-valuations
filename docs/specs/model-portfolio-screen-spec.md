# Model portfolio from a screen

Instructions for Claude Code. Roadmap item 5. Follow CLAUDE.md.

## Goal

The Model portfolio tab's inputs are typed by hand: which holdings (A–E), their target weights (F), the review
levels (S) and the notes (U–V). Everything else on the tab is a formula. The user holds no miners yet, so the
holdings can come from the framework's own numbers instead of a fixed list.

Three parts, one PR:

1. **Screen**: rank the companies on PNAV inputs within each bucket and propose the holdings and target weights
   for A–F. The user reviews the proposal before anything is written.
2. **Review levels from a rule**: S set from the peer norm, not typed.
3. **Backtest file from the tab**: write `private/portfolio.csv` from the Model portfolio, so `backtest` and
   `project` test what the Sheet shows.

## Privacy (read first)

Holding names, weights and statuses are Model portfolio content: they never go into the repo, an issue, a log or
the step summary (CLAUDE.md).

- **Committed** (`config/settings.toml` [portfolio_screen]): the rules. These are the filters, the score's
  measures and their weights, the bucket definitions, the review-level rule and the turnover buffer. They are a
  method, not a portfolio.
- **Private** (`private/screen.toml`, with a committed `config/screen.example.toml` using neutral numbers): each
  bucket's total target weight and how many names it holds. Together with the rules, these determine the
  portfolio, so they stay private.
- **Output**: `out/screen/` (gitignored) and the Sheet. The command never runs on GitHub. With `--email`, the
  summary of a write goes by private email (`alerts.send_email`), like the status alerts.
- `config/portfolio.example.csv` must not mirror the real portfolio. If it does today, replace it with a neutral
  example as part of this PR (ask the user first).

## Part 1: the screen

### Universe and buckets

- **Universe**: rows of PNAV inputs with a market cap and a P/NAV (P/NAV tab D numeric, not "negative" or ">20"),
  joined to data/derived/pnav.csv for the fields the Sheet doesn't show.
- **Buckets**: the existing bucket names (`[signals.timing]` keys). Physical metal is not screened: its rows keep
  what the user typed, and they come first on the tab.
- **Mapping each company to a bucket** (`[portfolio_screen.buckets]`: peer group, main metal and stage):
  - Gold producers: Senior or Intermediate producer, main metal gold.
  - Growth: expanding producers: Junior producer, or a producer whose reserve life or a study shows output rising.
  - Copper producers and Silver and polymetallic producers: producers by main metal.
  - Growth: developers: Developer, gold or copper (`[signals.timing]` already splits developers by metal).
- **Main metal**: the largest revenue share (PNAV inputs J:L) for producers, the resource unit (AU) for
  developers.
- **Overrides**: where the mapping gets a company wrong, a new `bucket` column in `pnav_companies.csv` overrides
  it, with a reason in `bucket_note`. This classifies the company; it isn't portfolio membership, so it can be
  committed.
- **Royalty companies**: the current buckets have none. Ask the user whether to add a "Royalty" bucket (scored on
  the framework band, AS, and the own-history percentile, BZ:CA) or to leave royalties out.

### Hard filters (a company failing any one isn't eligible)

Every threshold is in `[portfolio_screen.filters]` with a comment giving the reason:

- **Data:** financials through (Holdings N) within the last 9 months, and a price date (Holdings T) within 6 days.
- **Size:** market cap at least $300M for producers and $100M for developers, as a liquidity floor.
- **Dilution:** share-count change over 3 years (Model portfolio R's source, Holdings downside H) no more than 30%
  for producers.
- **Jurisdiction:** add-on (PNAV inputs P) no more than 2.5 points.
- **Developers:**
  - The developer check isn't "Short of cash".
  - P/NAV after the raise (BO) is numeric or "Fully funded" / "Funded (company says)".
  - EV per weighted unit against the peer median (BW) is no more than 1.5.
- **Valuation:** "valuation vs peer norm" (P/NAV tab N) is below the bucket's review level (Part 2), so the screen
  never proposes a company it would flag at once.

### Score (ranking within a bucket)

For each measure: rank percentiles within the bucket, 0 for the worst and 1 for the best. The score is their
weighted average, with weights in `[portfolio_screen.score]` (equal by default). Measures with no value for a
company are left out of its average, and the report says how many it had.

| Bucket | Measures (better = ...) |
|---|---|
| Producers (all three, and expanding) | valuation vs peer norm (lower); P/NAV at Low prices (lower); free-cash-flow breakeven vs today's price (lower); net cash, % of market value (higher); share-count change, 3 years (lower); jurisdiction add-on (lower); P/NAV with the add-on raised ÷ P/NAV today, BX (lower: less reliant on the risk premium) |
| Developers | P/NAV after a raise (lower; funded counts as best); EV per weighted unit against the peer median, BW (lower); months of funding (higher); jurisdiction add-on (lower) |
| Royalty (if added) | independent P/NAV (lower); own-history percentile (lower) |

Don't tune the weights to the backtest: most of these measures have no history, and one period's best fit is
noise (CLAUDE.md, "Signal backtest").

### Selection and weights

- **Names**: the top N per bucket, with N in `private/screen.toml`.
- **Turnover buffer** (`buffer`, default 2): a holding already on the tab stays while it ranks within N + buffer
  and passes the filters, so the list doesn't churn on small rank changes. A holding that fails a filter is
  dropped and the reason is reported.
- **Weights**: each bucket's total weight (private) is split equally among its names. Optionally tilt by score
  within ±`tilt` (default 0, which means equal weights). No name may exceed `max_weight` (default 0.06); any excess
  is spread over the rest of the bucket. Physical metal rows keep their typed weights, and the screened weights
  are scaled so all of F sums to 1.
- **The silver rule in G** (PSLV filled first from C4) is unaffected: PSLV stays a Physical metal row, and silver
  stocks keep E = "Silver".

### The command

`python -m minerval screen` (needs the Sheet; reads PNAV inputs, P/NAV, Holdings, Holdings downside and the Model
portfolio):

- **`--dry-run`** (the default): writes `out/screen/proposal.csv` and `out/screen/report.txt`.
  - The report shows each bucket's ranked eligible companies, with their score and measures.
  - It lists the companies excluded by a filter, with the filter.
  - It shows the proposal against what's on the tab now: added, kept, dropped (with why) and weight changes.
  - These files are local only. Show the user the report before any write.
- **`--write`**: writes the proposal to Model portfolio rows 6–31:
  - **A–F:** bucket, holding (the P/NAV tab's name, exactly, since H–N look it up by B), where it trades,
    Sprott ticker (Holdings downside L, since O–R look it up by D), main metal and target weight.
  - **S:** the review level (Part 2).
  - **U** ("Why it's in"): a generated line from the measures, for example "Valuation 0.71× peer norm;
    breakeven 38% below today's gold; net cash 14% of market value; add-on 0.5". Kept as typed for a holding that
    stays and whose U the user has edited (any text not starting with "Screen:"). Generated lines start with
    "Screen:".
  - **V** ("What would change the view"): kept for a holding that stays; for a new one, "Screen: review above
    <S>× peer norm, or if it fails a filter".
  - **Rows:** Physical metal rows first, as they are, then buckets in `[signals.timing]` order. If the proposal
    needs more than 26 rows, stop and say so: rows can't be added below 31 (CLAUDE.md). Clear any rows left over
    in A–F, S and U–V with empty values.
  - **Never** write G–R, T or W–Z (formulas; K has its own formula in each row and follows B).
  - **Before writing:**
    - Save A6:V31 (with formulas) to `out/screen/backup-<time>.json`.
    - Check that every B is on the P/NAV tab and every D is on Holdings downside L, and stop if not.
  - **After writing:** read back H, K and T. Report rows showing "" or "Check by hand" where the screen had
    numbers, which means a lookup failed.
- **`--email`** (with `--write`): one private email listing what changed (added, dropped, weights), through the
  alerts SMTP settings. The next `prices` run will also email the Status changes, as usual.
- **Option 3** runs at the end of `--write` (below).

## Part 2: review levels from a rule

- T reads "Review: above level" when K (valuation vs peer norm, 1.0 = in line) is above S.
- S becomes `review_multiple` from `[portfolio_screen.review]`: 1.3 by default (30% above the peer norm), with
  per-bucket overrides (developers might warrant 1.5, since study NPVs are rougher). It is written by `screen
  --write`, and that is the only writer.
- Physical metal rows: S stays as typed (often blank, which shows "Check by hand" or nothing).
- The filter in Part 1 uses the same level, so a new name always starts below it.
- If the user later types an S by hand, the next `screen --write` replaces it unless `[portfolio_screen.review]
  keep_typed = true`. Ask the user which they prefer, and default to replacing.

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

- Bucket mapping and the override column.
- Each hard filter, at its edge.
- Rank-percentile score: ties, missing measures, and a one-company bucket.
- Selection with the turnover buffer: a holding at rank N + 2 stays, and one at N + 3 is replaced.
- Weights:
  - an equal split, and the cap spreading the excess;
  - physical rows kept;
  - F sums to 1.
- The write:
  - only A–F, S and U–V are touched;
  - leftover rows are cleared with CLEAR;
  - the 26-row limit stops the write;
  - a B or D that doesn't look up stops it;
  - U lines typed by the user are kept.
- Review level: the default, a bucket override, and keep_typed.
- portfolio-file:
  - columns and types match `config/portfolio.example.csv`;
  - amount = F × (B3 + C4);
  - already_held for PSLV;
  - the CAD flag;
  - first_month carried over.
- Data-file checks: `[portfolio_screen]` thresholds present, and every bucket in `[signals.timing]`.

## Docs

- **README:** a "Model portfolio from a screen" section covering:
  - what is screened and what isn't;
  - the filters and the score;
  - that the rules are public and the bucket sizes private;
  - the run order: `refresh`, `financials`, `screen --dry-run`, review, then `screen --write`.
- **CLAUDE.md:**
  - the commands table (`screen`, `portfolio-file`) and what they write (Model portfolio A–F, S, U–V;
    `private/portfolio.csv`);
  - that A–F, S and U–V are now written by `screen`;
  - that the screen's output stays out of the repo and the logs.
- **Roadmap:** mark item 5 built.

## Done when

`screen --dry-run` gives a ranked, explained proposal for each equity bucket and the user has reviewed it,
`screen --write` has filled the tab with no lookup failures, S follows the rule, and `backtest` runs on the
`private/portfolio.csv` written from the tab.

## Questions for the user before building

1. **Royalties:** add a Royalty bucket, or leave royalties out?
2. **Bucket sizes:** each bucket's weight and number of names (for `private/screen.toml`). Default: the tab's
   current split.
3. **Review levels:** replace S typed by hand on every write, or keep it?
4. **`config/portfolio.example.csv`:** is it a real version of the Model portfolio? If so, replace it with a
   neutral example.
