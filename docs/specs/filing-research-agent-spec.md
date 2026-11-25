# Filing research agent: a company's valuation inputs from its own documents

Roadmap 7 · Status: In progress · Depends on: 6 and 6b (the record files and coverage record), 5b (operations.csv)

Instructions for Claude Code. Follow CLAUDE.md; don't restate it here.

## Goal

The valuation's research inputs come from each company's own documents: sustaining spending, study cash flows,
production by mine, reserves and resources, developer financing, permits and stage, corrections to Yahoo's figures,
listings and the coverage record. Between Nov 21 and 25, 2026 they were gathered with about 70 one-off scripts, each
repeating the same loop: find the document, convert it to text, find the row and its period, check the totals,
append by column name. This spec turns that loop into tested `research` commands and a Claude Code subagent. Given
a ticker, the agent proposes record rows with a source and a location for every figure. Code checks them, and the
user reviews them before recording. The aim is for the agent to record by itself, one kind of input at a time, once
its track record earns it (Part 4).

## Scope

- **In:** downloads by venue, row and number extraction, the batch file and its checks, the commands in Part 3,
  the subagent, its blind test and its track record.
- **Out:**
  - Fraser survey scores (copyright: the user's PDF and `jurisdiction --build`).
  - Royalty operating cash flow (`royalty-ocf` already reads it from XBRL).
  - Yahoo's financials (`fetch`) and every Sheet write (`financials` after recording).
  - The Model portfolio: the agent never reads it.
  - Unattended runs: a later Agent SDK program could drive the same commands.

## Design

### Part 1: what the agent researches

A batch names its kinds. The rules for reading the filings are in CLAUDE.md's Research section and the project
skills.

| Kind | Record and columns | Usual documents | Checks beyond the record's own test |
|---|---|---|---|
| `sustaining` | `capex_periods.csv` | MD&A capital and AISC tables, ASX quarterlies, results announcements | dates fit the period; a 9M comparative + Q4 = FY where all three are known |
| `study` | `projects.csv`, `project_cashflows.csv` | technical report Section 22 (NI 43-101) or 19 (S-K 1300) | years sum to the published totals; `studies.rebuild` matches the published NPV |
| `operations` | `operations.csv` | MD&A highlights, reserve releases, AIF, royalty GEO tables | a move of over 50% from the year before is listed for review |
| `mine_production` | `pnav_companies.csv` `country_weights`, `country_weights_source` | annual report or results release, production by mine | weights sum to 1 and equal mine ÷ total from the batch's evidence |
| `resources` | `pnav_companies.csv` `resource_*` | reserve and resource statement, technical report | the split adds up to the total where both are given |
| `financing` | `pnav_companies.csv` `committed_funding_usd_m`, `remaining_capex_usd_m`, `funded_per_company`, `financing_source` | MD&A liquidity section, financing releases | a converted figure names its date and rate |
| `stage` | `projects.csv` `permits`, `committed`, `construction_start`, `first_production`; `pnav_companies.csv` `study_stage` | AIF permitting section, construction decision, MD&A guidance | `permits` = yes only with a source |
| `correction` | `config/corrections.csv` | company reports where Yahoo's figure is wrong | the source names the periods summed |
| `listing` | `pnav_companies.csv` listing columns | exchange and company pages | the record's listing test |
| `coverage` | `coverage.csv` | the filing that closes or explains a gap | the record's coverage tests |

A **question** records nothing: its findings, each with a source, go in the report only. Examples: a share-count
change of over 10% (`prices --shares`), or a policy or permitting event and what it affects (a suspended mine, a new
mining code, a tax change).

### Part 2: the batch

The agent writes `out/research/<TICKER>/proposal.json` and `report.md`, and never edits the proposal afterwards. The
user records the proposal as it is, or records an edited copy saved beside it.

| Key | Holds |
|---|---|
| `ticker`, `kinds`, `made` | the company, the kinds researched, the date |
| `append` | `{record: [rows by column name]}` for `capex_periods`, `operations`, `projects`, `corrections`, `coverage` and `sources`; `cashflows` as one entry per study with a list per column, year 1 first |
| `set` | `[{record, key, column, value, was}]`: one cell of an existing row |
| `remove` | `[{record, key}]`: a row to delete (a closed coverage gap) |
| `evidence` | `[{figure, value, unit, url, where}]`: the published figures a derived value comes from (each mine's production behind `country_weights`) |

A figure that isn't printed in its document carries `"derived": "how"`: a sum, a gross-up, a currency conversion,
or a value read from a page image. That key isn't a column and isn't recorded, so the row's `notes` or source
column must say the same thing.

**Checks** (`research check`). An error stops `record`. A review line goes in the report for the user.
- **Errors:**
  - a column the record doesn't have;
  - a duplicate key, within the batch or against the record;
  - a missing https `url` or source;
  - a value outside the record's allowed set;
  - a `was` that no longer matches the record;
  - period dates that don't fit the period;
  - years that don't sum to a stated total;
  - a document not downloaded;
  - a figure missing from its document's text, with no `derived`.
- **Review:**
  - a tie-out that misses by more than rounding;
  - a move of over 50% from the year before;
  - a study rebuild outside `check_npv`;
  - every `derived` figure.

The figure check reads the `research fetch` text in `cache/research/`. A figure counts as found at its own
precision, whether printed as is or in thousands or millions, and with commas, spaces or parentheses.

### Part 3: commands

Every command is under `research`, and each report also goes to `out/research/report.txt`.

| Command | Does |
|---|---|
| `plan TICKER` | lists by kind what the record holds and what's missing (periods due from the financials date, blank columns, operations years 2022–2025, coverage rows); the venues to search (EDGAR for a US listing, the ASX for ` AU`, Investegate for ` LN`, otherwise the company's site); and the documents `sources.csv` already logs |
| `locate TICKER [--match RX] [--year Y] [--site URL]` | lists candidate documents: EDGAR filings and full-text search, the ASX year list with each PDF's address, Investegate's results list, a WordPress site's media search |
| `fetch`, `find`, `filings` | as before; `fetch --url` downloads one document |
| `rows URL RX` | shows each matching row with its nearest period header and its numbers |
| `check FILE` | runs the checks in Part 2 |
| `record FILE [--write] [--agent]` | the dry run shows the rows and cells per record. `--write` applies them, logs the sources and adds to the track record; `--agent` is the agent's own write (Part 4) |
| `blind TICKER... --kinds K...` | runs in a linked git worktree only: removes those tickers' rows and cells of those kinds, for the blind test |
| `compare FILE [--ref main]` | compares figure by figure with the record at a git ref: matched, missed, extra |

The code is in three modules:
- `minerval/documents.py`: downloads, text and venues, moved out of `sustaining.py`, which keeps its old names.
- `minerval/tables.py`: numbers, rows and series.
- `minerval/research.py`: kinds, the batch, checks, plan, record, compare and blind.

Tests use recorded page layouts with invented figures and a fake download, and `tests/conftest.py` blocks
`documents._get`.

### Part 4: the agent

The agent is a Claude Code subagent in `.claude/agents/filing-researcher.md`. The file is committed, because it holds
no personal data. The agent:
1. Runs `research plan TICKER`, and reads `sources.csv` for the documents already read.
2. Finds and reads documents with `locate`, `fetch`, `rows` and `find`. Any scripts of its own go in the scratchpad.
3. Writes `proposal.json`, and reruns `research check` until it shows no errors.
4. Writes `report.md`:
   - what it found, with each judgment call (basis, combined lines, gross-ups);
   - what it didn't find, with the next step;
   - the documents the user must download, with links (always the case for SEDAR+).
5. Stops.

It never:
- writes a record file, `config/` or the Sheet, or commits;
- reads the Model portfolio tab, or anything in `private/` except documents the user names;
- records a figure it didn't read in the document, or estimates one;
- gets past a bot challenge, guesses a key, or poses as a browser.

**Earning the write.**
- Every `record --write` adds one row per kind to `data/research/agent_log.csv`: `date`, `ticker`, `kind`,
  `proposed`, `changed`, `added`, `dropped`, `file`. The counts compare the recorded file with the `proposal.json`
  beside it.
- `[research.agent] write_kinds` in `config/settings.toml` lists the kinds the agent may record itself, with
  `record --agent --write`. It starts empty. That command refuses any other kind, and any batch with errors.
- The user adds a kind once its blind test passes and its last five recorded batches have no changes.

### Part 5: the blind test

`[research.blind_test]` lists about ten companies, one for each kind and venue already in the record:
- `sustaining` from an EDGAR 10-Q (HL), a 6-K MD&A (EXK), a 40-F's page images (GFI), an ASX report (RMS AU),
  Investegate (CAML LN) and a company site (ARG CN);
- `study` from an EDGAR exhibit (NEWP) and a company site (GMIN CN);
- `mine_production` (AEM CN);
- `financing` (NEWP).

The run:
1. Make a worktree from `main` and run `research blind` in it.
2. Run the agent once per company.
3. Run `research compare` against `main`.

A figure matches when it equals the record at the record's precision. The test passes when:
- at least 90% of the record's figures are matched;
- no proposed figure lacks a source;
- `report.md` explains every miss and every extra.

## Acceptance criteria

- [x] A1. The document code lives in `minerval/documents.py`; `research fetch`, `find` and `filings`, and the
  `sustaining` names the skills use, behave as before. — `tests/test_documents.py::test_sustaining_names_still_work`;
  the existing `tests/test_sustaining.py` tests pass
- [x] A2. `locate` reads the ASX year list (with each PDF address), Investegate's results list, EDGAR full-text
  search and a WordPress media search from recorded pages, and picks the venues from the listing. —
  `tests/test_documents.py::test_asx_announcements_from_the_year_list`,
  `tests/test_documents.py::test_investegate_results_list`, `tests/test_documents.py::test_edgar_full_text_search_hits`,
  `tests/test_documents.py::test_wordpress_media_search`, `tests/test_documents.py::test_locate_picks_venues_from_the_listing`
- [x] A3. No test can download: `tests/conftest.py` blocks `documents._get`. —
  `tests/test_documents.py::test_documents_are_offline_in_tests`
- [x] A4. `rows` finds a label's row and its nearest period header, both one cell per line and in `|` tables. —
  `tests/test_tables.py::test_rows_in_pipe_tables`, `tests/test_tables.py::test_rows_in_pdf_layout_text`,
  `tests/test_tables.py::test_rows_with_period_header_one_cell_per_line`
- [x] A5. Numbers parse through the layout traps: negatives in parentheses, `-` and `--` as zero, spaces as thousands
  separators, unit tokens, EDGAR's split negatives. — `tests/test_tables.py::test_numbers_layout_traps`
- [x] A6. A series of N years and a total is refused when the years don't sum to it. —
  `tests/test_tables.py::test_series_checks_the_total`
- [ ] A7. `plan` lists, by kind, what's recorded and what's missing or due, and the venues to search. — new test
  (tests/test_research.py)
- [ ] A8. `check` raises each error in Part 2 and lists each review line. — new test
- [ ] A9. The figure check finds a number as printed, in thousands or in millions, and with commas, spaces or
  parentheses; it refuses one that isn't in the document unless it's `derived`. — new test
- [ ] A10. `record --write` applies appends, cells and removals by column name (keeping `coverage.csv`'s CRLF), logs
  the sources, and refuses a batch with errors or a stale `was`; the dry run writes nothing. — new test
- [ ] A11. `record --write` adds to the track record, counting changed, added and dropped figures against
  `proposal.json`. — new test, and a data-file test for `agent_log.csv`
- [ ] A12. `record --agent --write` refuses a kind not in `write_kinds`. — new test
- [ ] A13. `blind` runs only in a linked worktree and removes the named tickers' rows and cells of the named kinds;
  `compare` counts matched, missed and extra figures. — new tests
- [ ] A14. The agent file holds the loop, the rules and the stop, and names only `research` commands that exist. — new
  data-file test
- [ ] A15. CLAUDE.md puts the agent, the batch and `record` in the run order. — `grep -n filing-researcher CLAUDE.md`
- [ ] A16. The blind test passes across `[research.blind_test]`: at least 90% of the record's figures matched, no
  proposed figure without a source, and every miss and extra explained. — `research compare` on each company
- [ ] A17. (user) The first `operations` batches (screen A26, royalty companies first) are reviewed and recorded.
- [ ] A18. (user) A kind is added to `write_kinds` after its blind test and five clean batches.

## Decisions

- A Claude Code subagent, not a standalone Agent SDK program (the user, 2026-11-25).
- The agent proposes and the user's review comes before recording; the agent's own write is the goal, earned kind
  by kind (the user, 2026-11-25).
- The blind test passes at 90% or more of figures matched, with none lacking a source and every miss explained (the
  user, 2026-11-25).
- The agent covers every kind of research done so far (production by mine, permits and policy, company financials
  and the rest), not only A26; A26 is its first live job (the user, 2026-11-25).

## Open questions

1. Production by mine: keep only the weights and their source text in `pnav_companies.csv` (the figures stay in the
   batch's evidence), or add a mine-level record (mine, country, year, metal, amount, attributable share) that
   `jurisdiction` computes the weights from?
2. Is five clean batches per kind enough before the agent records by itself?
