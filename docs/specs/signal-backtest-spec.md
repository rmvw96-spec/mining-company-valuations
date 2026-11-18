# Signal backtest, and an industry AISC history

Instructions for Claude Code. Roadmap item 2a. Follow CLAUDE.md.

## Goal

The Signals tab's thresholds are judgment calls (framework rules of thumb). Test each signal on history:
when it said "lean in", did the tier it applies to do better over the following months than when it didn't?
The result is a report the user reads to decide which signals to trust and where the thresholds (Signals G:H,
`config/settings.toml` [signals.thresholds]) should sit. **The code reports; it never changes thresholds.**

This job also makes the industry AISC a dated history instead of one hand-typed number, so the AISC margin can
be backtested and the World Gold Council's Q3 2026 figure (due early December 2026) is entered once, in the record.

## Part 1: industry AISC history

- New file `data/research/industry_aisc.csv`: `quarter` (e.g. `2026Q2`), `aisc_usd_oz`, `published` (date the
  figure became public), `source` (report name and URL), `note`.
- Fill it from the World Gold Council's quarterly gold-mining cost series (Metals Focus data) as far back as it
  is published. Every figure must come from a source in the `source` column; leave a quarter out rather than
  estimate it. Check whether WGC revises past quarters: if so, keep the latest figure and note the revision.
- `signals.compute()` uses the latest **published** quarter as of `today` (so a backtest on 2024-03-15 uses
  the figure that was public then, not a later one). `[signals.inputs] industry_aisc` and its source are then
  derived from the table: remove them from settings.toml, or keep them only as an override (decide, and say
  which in the PR).
- The Signals tab input row `industry_aisc` stays (the AISC status formula reads it). Python writes the latest
  published figure there, with the quarter and source in F, on each run. Treat that cell as Python-written
  from now on: update CLAUDE.md's what-not-to-touch.
- Add the Q3 2026 row when WGC publishes it (early December 2026). If this job lands before then, note in the
  PR that the row is pending.

## Part 2: historical signal values

- Reuse the truncation helper from [signal-history-spec.md](signal-history-spec.md) (build it here if that job
  hasn't landed): for each month-end since the earliest date the inputs allow, run `compute()` on series cut at
  that date. Month-ends are enough for a 3- to 12-month question and keep it fast.
- Data: daily and monthly Yahoo series already in `[signals]` (add `start` dates where needed: GDX from 2006,
  GDXJ 2009, SIL 2010, SILJ 2012, COPX 2010), FRED DFII10 (from 2003), the AISC table above.
- Signals with no history: the fund FCF yields (need past fundamentals) and the royalty median (needs past
  P/NAVs). Skip them and say so in the report. The junior breadth signal
  ([junior-breadth-spec.md](junior-breadth-spec.md)) is tested here if it exists.

## Part 3: outcomes

For each signal, define the tier outcome it is meant to predict. Starting point (confirm against the
framework's wording on the Signals tab, note column):

| Signal | Outcome over the next 3, 6 and 12 months |
|---|---|
| Gold/silver ratio high | Silver return minus gold return |
| Real yield peaked and falling | Gold return |
| Dollar 12-month change | Gold return |
| SPY drawdown | Gold and royalty (GDX as proxy before royalty data) return |
| Metal vs diesel | Miner ETF minus metal (GDX−gold, SIL−silver, COPX−copper) |
| Miners vs metal percentile | Miner ETF minus metal |
| AISC margin | GDX minus gold |
| Uptrends (200-day) and junior timing | GDXJ and SILJ return; GDXJ minus GDX |
| Tax-loss window | GDXJ return from window to end of February |

Report, per signal and status bucket: number of months, mean and median forward return, hit rate (share of
months with a positive outcome), and the same for all months as the baseline. Use **non-overlapping** windows
for the significance note, or say plainly that overlapping 12-month windows overstate confidence. Flag any
bucket with fewer than 12 independent observations as "too few to judge".

Then a threshold sweep for the signals with numeric thresholds: the same table at a few thresholds around the
current one (e.g. gold/silver ratio 70, 75, 80, 85, 90), so the user sees whether the current choice sits on a
plateau or a knife edge. No optimisation: an optimised threshold on 25 years of data would be fitted noise.

## Commands and output

- `uv run python -m minerval backtest-signals` → `out/backtest-signals/report.txt` and `signals_history.csv`
  (the month-end signal values), plus `outcomes.csv`.
- Offline after the first download: reads `cache/signals/` and `cache/history/`; `--refresh` downloads again.

## Tests (offline, synthetic series)

- Truncation: `compute()` at date d sees no data after d (inject a spike after d; the value must not move).
- AISC table: the figure used at a date is the latest with `published <= date`.
- Outcomes: forward returns on a known series; non-overlapping sampling; the "too few" flag.
- `data/research/industry_aisc.csv` validation in `tests/test_data_files.py`: quarters unique and ordered,
  values positive, every row has a source.

## Docs

README: what the backtest answers and its limits (one cycle-heavy period; survivorship in the ETFs; Yahoo
futures continuations roll). CLAUDE.md: the AISC table is the record; the Signals input is written by Python.

## Done when

The report exists, the user has read it, and any threshold changes they choose are made in both
settings.toml and the Signals tab (and the run reports "Sheet and Python statuses agree").
