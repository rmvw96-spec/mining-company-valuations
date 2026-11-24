# Valuation coverage: a tracked record of every company the valuation doesn't fully cover

Roadmap 6b · Status: Built Nov 23, 2026 · Depends on: 6 (valuation by tier)

Instructions for Claude Code. Follow CLAUDE.md; don't restate it here.

## Goal

On Nov 23, 2026 the valuation covered 143 companies unevenly. 52 producers were on the free-cash-flow fallback, 12
developers had a study that wasn't recorded, and 9 producers were flagged as far below outside NAVs, mostly
because their growth projects weren't recorded. The full picture lived only in the untracked
`out/valuation/report.txt` and the Sheet, so nothing in the repo said what was missing or what to do next. This
spec adds a committed record of each gap, a test that keeps it complete against the research files, and a summary
in the `valuation` report.

## Scope

- **In:** `data/research/coverage.csv`, its rules and test, the `valuation` report's Coverage section, and the
  docs that say when to update it.
- **Out:** closing the gaps themselves (research, tracked here as "(data)" criteria); explorers, physical metal and
  other companies the valuation leaves out by design, which get a row marked out of scope but no research; the Sheet
  (PNAV inputs CS already shows each company's reason).

## Design

**Record:** `data/research/coverage.csv`, one row per company with an open gap, written by hand (CSV writer, by
column name) like the other research records.

| Column | Values |
|---|---|
| `ticker` | as in `pnav_companies.csv` |
| `gap` | `sustaining`, `study`, `growth_project`, `out_of_scope` |
| `status` | `to research`, `not published`, `waiting`, `out of scope` |
| `next_step` | what closes it, e.g. "record the Q3 2026 MD&A rows", "the user downloads the DFS from SEDAR+" |
| `due` | `YYYY-MM` when `waiting` (a study or filing is scheduled), else blank |
| `source` | the document showing the status (https), for `not published` and `waiting` |
| `notes` | free text |

**Gaps** (a company can have more than one row, one per gap):

| `gap` | When | Closed when |
|---|---|---|
| `sustaining` | a producer (`basis` FCF) with no trailing sustaining spending built (`sustaining_capex_usd_m` blank) | `research sustaining --write` fills it |
| `study` | a developer (`study_stage` set) with no unsuperseded study row that has cash flows | a study row with cash flows is recorded |
| `growth_project` | a producer with a committed growth project not recorded in `projects.csv` | the project is recorded as committed |
| `out_of_scope` | no `basis` and no `study_stage`: explorers, physical metal, holding companies, smelters, carried interests, companies without data | by design; the row stays |

**Completeness rule** (`minerval/coverage.py` `problems`, checked from committed files only): every company in
`pnav_companies.csv` is valued from its research or has a row. Valued means a royalty (`basis` OCF), a producer with
sustaining built, or a developer with an unsuperseded study row that has cash flows. A producer on the fallback
needs a `sustaining` row, and a company with a `study_stage` but no study's cash flows a `study` row; any other
company not valued needs a row of any gap. A `sustaining` or `study` row whose gap is closed must be removed, and an
`out_of_scope` row needs a company with no `basis` and no `study_stage`. `growth_project` rows are added from
research and from the validation check; there is no rule that derives them.

**Report:** `valuation`'s report gains a Coverage section with the following:
- counts by gap and status;
- `waiting` rows past their `due` month;
- the companies flagged by the check against outside views that have no `growth_project` or `sustaining` row
  (a flag nobody has explained).

**Docs:** CLAUDE.md's Research section says to remove a row when its gap closes and to add one when research finds
a new gap, and its earnings-season steps recheck the `not published` and `waiting` rows. The README's "Valuation by
tier" section names the record.

## Acceptance criteria

- [x] A1. `coverage.csv` has the fixed columns, values from the allowed sets, `due` as `YYYY-MM` on `waiting` rows,
  and an https `source` on `not published` and `waiting` rows. —
  `tests/test_data_files.py::test_coverage_record_is_well_formed`
- [x] A2. Every company is valued from its research or has a coverage row, and no `sustaining` or `study` row stays
  after its gap closes. — `tests/test_data_files.py::test_every_valuation_gap_has_a_coverage_row`, with the rule on
  fixture companies in `tests/test_coverage.py::test_every_company_is_valued_or_explained_and_closed_gaps_are_removed`
- [x] A3. The `valuation` report's Coverage section counts rows by gap and status, names `waiting` rows past due,
  and names flagged companies with no row. — `tests/test_valuation.py::test_report_summarises_coverage`
- [x] A4. The record is filled for Nov 23, 2026: the 52 fallback producers, the developers without a recorded
  study, a `growth_project` row for each of the 9 flagged producers, and the out-of-scope companies. — the A2 test
  passes and `valuation` names no unexplained flag (Nov 23, 2026: 100 rows; no `waiting` row past due)
- [x] A5. CLAUDE.md and the README describe the record and when to update it. — `grep -n coverage.csv CLAUDE.md
  README.md` shows both
- [x] A6. (data) No `sustaining` row is still `to research`: each producer's split is recorded or marked `not
  published` with its source. — the report's Coverage counts (Nov 23, 2026: 19 `sustaining` rows, 17 `not
  published`, 2 `waiting`, none `to research`)
- [x] A7. (data) No `study` or `growth_project` row is still `to research`: each is recorded, `waiting` with a
  date, or `not published` with its source. — the report's Coverage counts (Nov 23, 2026: 8 `study` rows, 4 `not
  published`, 4 `waiting`; 17 `growth_project` rows, 16 `not published`, 1 `waiting`; none `to research`)

## Decisions

- Coverage gaps are tracked in a committed record that a test keeps complete, not only in the untracked report
  (the user, 2026-11-23).
- Out-of-scope companies get a row, so every tracked company is accounted for as valued or explained.
- `not published` and `waiting` rows are rechecked each earnings season, as a step of CLAUDE.md's
  earnings-season refresh (the user, 2026-11-23).
- A company with no `basis` and no `study_stage` that isn't out of scope by design gets the row its gap needs:
  Montage Gold (first gold Sept 2026, no trailing cash flow yet) has a `study` row.
- Rows found in research count as well as the flagged producers': committed projects with no study (AIC Mines,
  Avino, Sierra Madre, Silangan), McIlvenna Bay (remaining capex not published), Oko West (waiting for the
  combined study) and the Khoemacau expansion each have a `growth_project` row.
