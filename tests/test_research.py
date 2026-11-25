"""The research batch: plan, check, record, track record, blind test and compare (filing-research-agent spec A7-A13).
Each test works on a copy of the record files' real headers with invented companies, figures and documents."""
import csv
import json
import subprocess
from datetime import date

import pytest

from minerval import documents as D
from minerval import research as RS
from minerval.config import ROOT

EXK_Q3 = "https://www.sec.gov/Archives/edgar/data/1/000000000026000001/exm-q3.htm"
EXK_FY = "https://www.sec.gov/Archives/edgar/data/1/000000000026000002/exm-fy.htm"
DEV_FS = "https://example-developer.com/wp-content/uploads/2026/05/fs-technical-report.pdf"
ANNUAL = "https://example-mining.com/annual-report-2025.pdf"


def add(base, name, rows):
    """Append rows to a record file by column name, in its own line ending."""
    p = base / RS.RECORDS[name][0]
    with p.open(newline="") as f:
        cols = next(csv.reader(f))
    term = "\r\n" if p.read_bytes().endswith(b"\r\n") else "\n"
    with p.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator=term)
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def read(base, name):
    with (base / RS.RECORDS[name][0]).open(newline="") as f:
        return list(csv.DictReader(f))


def doc(url, text):
    p = D.doc_path(url)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{url}\n{text}")


def capex(period, start, end, sustaining, url=EXK_Q3, **kw):
    return {"ticker": "EXM CN", "period": period, "period_start": start, "period_end": end, "basis": "consolidated",
            "currency": "USD", "sustaining": sustaining, "document": "Q3 2026 MD&A", "url": url,
            "where": "AISC reconciliation", "published": "2026-11", **kw}


def source(url, document="Q3 2026 MD&A"):
    return {"ticker": "EXM CN", "company": "Example Mining", "document": document, "period": "2026",
            "published": "2026-11-09", "url": url, "read": "yes", "found": "sustaining capital"}


@pytest.fixture
def base(tmp_path, monkeypatch):
    """The record files with their real headers (and line endings), two companies, one logged document."""
    for rel, _ in RS.RECORDS.values():
        raw = (ROOT / rel).read_bytes()
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw[:raw.index(b"\n") + 1])
    add(tmp_path, "companies", [
        {"ticker": "EXM CN", "holding": "Example Mining", "stage": "Producer", "basis": "FCF", "us_listing": "NYSE: EXM",
         "country_weights": "Canada/Ontario:1.0", "country_weights_source": "2024 production by mine: annual report"},
        {"ticker": "DEV CN", "holding": "Example Developer", "stage": "Developer (feasibility study 2025)",
         "study_stage": "FS"}])
    add(tmp_path, "sources", [source(EXK_Q3)])
    add(tmp_path, "coverage", [{"ticker": "EXM CN", "gap": "sustaining", "status": "to research",
                                "next_step": "the Q3 MD&A"}])
    monkeypatch.setattr(D, "DOCS", tmp_path / "cache" / "research")
    doc(EXK_Q3, "Nine Months Ended September 30 | 2026 | 2025\nCapital expenditures sustaining | 55.1 | 26.5\n"
                "Equipment loan payments | 2.8 | 0.2")
    return tmp_path


def batch(base, d, name="proposal.json", ticker="EXM CN"):
    folder = base / "out" / "research" / ticker
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_text(json.dumps({"ticker": ticker, "made": "2026-11-26", **d}))
    return p


GOOD = {"kinds": ["sustaining", "coverage"],
        "append": {"capex_periods": [capex("9M", "2026-01-01", "2026-09-30", 55.1, sustaining_leases=2.8),
                                     capex("9M", "2025-01-01", "2025-09-30", 26.5, sustaining_leases=0.2)]},
        "remove": [{"record": "coverage", "key": {"ticker": "EXM CN", "gap": "sustaining"}}]}


def test_plan_lists_missing_periods_and_gaps(base):
    """A7: by kind, what's recorded and what's missing or due, and the venues to search."""
    add(base, "capex_periods", [capex("FY", "2025-01-01", "2025-12-31", 60.4, url=EXK_FY)])
    add(base, "coverage", [{"ticker": "EXM CN", "gap": "growth_project", "status": "waiting", "next_step": "the PFS",
                            "due": "2026-10", "source": "https://example-mining.com/news"}])
    L = "\n".join(RS.plan("EXM CN", base=base, fin_dates={"EXM CN": "2026-09-30"}, today=date(2026, 11, 26)))
    assert "venues: edgar, site" in L
    assert "FY 2025-01-01 to 2025-12-31: recorded" in L
    assert "9M 2026-01-01 to 2026-09-30: missing" in L and "9M 2025-01-01 to 2025-09-30: missing" in L
    assert "FY + this year's 3M quarters - last year's" in L                # Amerigo: quarters only
    assert "operations 2022: missing production" in L and "resources (reserves, mi, inferred)" in L
    assert "growth_project: waiting (due 2026-10, past due)" in L
    assert "country_weights: Canada/Ontario:1.0 (2024 production by mine: annual report)" in L
    assert EXK_Q3 in L                                                    # the documents already read
    D_ = "\n".join(RS.plan("DEV CN", base=base, fin_dates={}, today=date(2026, 11, 26)))
    assert "study: none recorded" in D_ and "financing: blank committed_funding_usd_m" in D_
    assert "resources: blank resource_amount" in D_ and "sustaining" not in D_


def test_check_refuses_malformed_batches(base):
    """A8: each error in spec Part 2 stops the batch, with a line saying which row and why."""
    add(base, "capex_periods", [capex("FY", "2025-01-01", "2025-12-31", 60.4, url=EXK_FY)])
    bad = {"kinds": ["sustaining"],
           "append": {"capex_periods": [
               {**capex("9M", "2026-01-01", "2026-09-30", 55.1), "sustaning": 1},           # unknown column
               capex("FY", "2025-01-01", "2025-12-31", 60.4, url=EXK_FY),                  # already recorded
               capex("6M", "2026-01-01", "2026-06-30", 30.0, url="http://example.com/x"),  # not https
               capex("10M", "2026-01-01", "2026-10-31", 55.1),                            # period not allowed
               capex("3M", "2026-01-01", "2026-09-30", 55.1),                             # dates don't fit
               capex("9M", "2024-01-01", "2024-09-30", 55.1, url=ANNUAL),                 # not downloaded/logged
               capex("9M", "2023-01-01", "2023-09-30", 99.9)],                            # not in the document
               "operations": [{"ticker": "EXM CN", "period_end": "2025-12-31", "measure": "production", "metal": "gold",
                               "amount": "55.1", "unit": "koz", "basis": "attributable", "document": "Q3 MD&A",
                               "url": EXK_Q3, "published": "2026-11"}]},                  # kind not declared
           "set": [{"record": "companies", "key": {"ticker": "EXM CN"}, "column": "country_weights",
                    "value": "Canada/Ontario:1.0", "was": "Mexico:1.0", "url": EXK_Q3}],  # stale, and undeclared
           "cashflows": [{"ticker": "DEV CN", "project": "Dev", "study_date": "2025-04-28", "source": EXK_Q3,
                          "post": [-100.0, 55.1, 26.5], "totals": {"post": 0.0}}]}
    errors, _ = RS.check(json.loads(json.dumps(bad)), base=base)
    E = "\n".join(errors)
    for want in ("no column 'sustaning'", "already recorded", "https", "period '10M'", "dates don't fit a 3M",
                 "not downloaded", "not logged in sources.csv", "99.9 is not in", "kind 'operations' not in",
                 "was 'Mexico:1.0'", "sum to", "kind 'study' not in"):
        assert want in E, (want, E)
    assert RS.check(json.loads(json.dumps(GOOD)), base=base)[0] == []


def test_check_lists_review_lines(base):
    """A8: what passes but needs the user's eye goes in the report: tie-outs that miss, big moves from the year
    before, every derived figure, a study's totals not given or its rebuild off the published NPV."""
    add(base, "capex_periods", [capex("FY", "2025-01-01", "2025-12-31", 60.4, url=EXK_FY),
                                capex("9M", "2025-01-01", "2025-09-30", 26.5)])
    add(base, "operations", [{"ticker": "EXM CN", "period_end": "2024-12-31", "measure": "production",
                              "metal": "gold", "amount": "120", "unit": "koz", "basis": "attributable",
                              "document": "AR", "url": EXK_Q3, "published": "2025-03"}])
    doc(DEV_FS, "Table 22.6 After-Tax Cash Flow 400.0 -100.0 250.0 250.0 NPV 5% 2,163")
    add(base, "sources", [source(DEV_FS, "FS technical report")])
    rev = {"kinds": ["sustaining", "operations", "study"],
           "append": {"capex_periods": [{**capex("3M", "2025-10-01", "2025-12-31", 30.0), "derived": "FY less 9M"}],
                      "operations": [{"ticker": "EXM CN", "period_end": "2025-12-31", "measure": "production",
                                      "metal": "gold", "amount": "55.1", "unit": "koz", "basis": "attributable",
                                      "document": "Q3 MD&A", "url": EXK_Q3, "published": "2026-11"}],
                      "projects": [{"ticker": "DEV CN", "project": "Dev", "attributable_pct": "100",
                                    "study_type": "FS", "study_date": "2025-04-28", "study_price": "gold 2500",
                                    "study_npv_usd_m": "2163", "study_discount_rate": "5",
                                    "discounting": "mid-year", "marginal_tax_rate": "25", "net_revenue_share": "1",
                                    "source": DEV_FS, "as_of": "2025-04-28"}]},
           "cashflows": [{"ticker": "DEV CN", "project": "Dev", "study_date": "2025-04-28", "source": DEV_FS,
                          "post": [-100.0, 250.0, 250.0], "gold": [0.0, 100.0, 100.0]}]}
    errors, reviews = RS.check(json.loads(json.dumps(rev)), base=base)
    assert errors == []
    R = "\n".join(reviews)
    for want in ("26.5 + 30.0 = 56.5, not the FY 60.4", "production gold 55.1 koz vs 120", "derived: FY less 9M",
                 "no totals", "rebuilt NPV"):
        assert want in R, (want, R)


def test_figure_found_in_document_text():
    """A9: a figure is found at its own precision, as printed or in thousands or millions, with commas, spaces or
    parentheses; one that isn't there is not."""
    text = "Sustaining | (606.8) | 1,182.7 | 423,000 oz | 35 645 576 | 2,163.4 | 0.75"
    for v in ("606.8", 1182.7, "423", 35.6, 2163, "0.75", 0):
        assert RS.found_in(v, text), v
    for v in ("606.9", 1182.8, 424, "35.7"):
        assert not RS.found_in(v, text), v


def test_derived_by_column_keeps_the_other_figures_checked(base):
    """A9: `derived` given as a map by column exempts only those figures; the row's printed figures are still looked
    for in the document (a sum of two AISC lines beside a printed growth figure)."""
    row = capex("9M", "2026-01-01", "2026-09-30", 57.9, sustaining_leases=2.8, growth=26.5,
                derived={"sustaining": "55.1 + 2.8"})
    E, R = RS.check({"kinds": ["sustaining"], "append": {"capex_periods": [row]}}, base=base)
    assert E == [] and len([r for r in R if "derived" in r]) == 1 and "sustaining = 57.9: derived: 55.1 + 2.8" in R[0]
    row["growth"] = 99.9
    E, _ = RS.check({"kinds": ["sustaining"], "append": {"capex_periods": [row]}}, base=base)
    assert len(E) == 1 and "growth: 99.9 is not in" in E[0]


def test_record_appends_and_refuses_errors(base):
    """A10: the dry run writes nothing; --write appends rows by column name, sets cells, removes rows (coverage.csv
    keeps its CRLF), and logs new documents; a batch with an error, or a `was` that is out of date, is refused."""
    add(base, "coverage", [{"ticker": "DEV CN", "gap": "study", "status": "to research", "next_step": "y"}])
    doc(ANNUAL, "Production by mine 2025 | Example 210,000 oz")
    good = json.loads(json.dumps(GOOD))
    good["kinds"].append("mine_production")
    good["set"] = [{"record": "companies", "key": {"ticker": "EXM CN"}, "column": "country_weights_source",
                    "value": "2025 production by mine: annual report", "was": "2024 production by mine: annual report",
                    "url": ANNUAL}]
    good["append"]["sources"] = [source(ANNUAL, "2025 annual report")]
    before = {n: (base / rel).read_bytes() for n, (rel, _) in RS.RECORDS.items()}
    p = batch(base, good)
    lines = "\n".join(RS.record(p, base=base))
    assert "capex_periods: +2 rows" in lines and "coverage: -1 row" in lines and "Dry run" in lines
    assert {n: (base / rel).read_bytes() for n, (rel, _) in RS.RECORDS.items()} == before
    RS.record(p, write=True, base=base, today=date(2026, 11, 26))
    C = read(base, "capex_periods")
    assert [(r["period_end"], r["sustaining"], r["sustaining_leases"]) for r in C] == [
        ("2026-09-30", "55.1", "2.8"), ("2025-09-30", "26.5", "0.2")]
    assert read(base, "companies")[0]["country_weights_source"] == "2025 production by mine: annual report"
    raw = (base / RS.RECORDS["coverage"][0]).read_bytes()
    assert [r["ticker"] for r in read(base, "coverage")] == ["DEV CN"] and raw.count(b"\n") == raw.count(b"\r\n")
    assert [r["url"] for r in read(base, "sources")] == [EXK_Q3, ANNUAL]
    again = "\n".join(RS.record(p, write=True, base=base))                      # now stale and duplicated
    assert "Refused" in again and "already recorded" in again and "was '2024 production" in again
    assert len(read(base, "capex_periods")) == 2


def test_track_record_counts_corrections(base):
    """A11: --write adds one agent_log.csv row per kind, counting the recorded figures that differ from the agent's
    proposal.json beside the file, were added, or were dropped."""
    prop = {"kinds": ["sustaining"], "append": {"capex_periods": [
        capex("9M", "2026-01-01", "2026-09-30", 55.1, sustaining_leases=2.8),
        capex("9M", "2025-01-01", "2025-09-30", 26.5, sustaining_leases=0.3)]}}
    batch(base, prop)
    edited = json.loads(json.dumps(prop))
    edited["append"]["capex_periods"][1]["sustaining_leases"] = 0.2                       # corrected
    edited["append"]["capex_periods"][0].pop("sustaining_leases")                         # dropped
    edited["append"]["capex_periods"][1]["growth"] = "26.5"                               # added
    p = batch(base, edited, name="edited.json")
    RS.record(p, write=True, base=base, today=date(2026, 11, 26))
    L = read(base, "agent_log")
    assert L == [{"date": "2026-11-26", "ticker": "EXM CN", "kind": "sustaining", "proposed": "4", "changed": "1",
                  "added": "1", "dropped": "1", "file": "edited.json"}]


def test_agent_write_needs_the_kind_granted(base):
    """A12: the agent's own write refuses any kind not in [research.agent] write_kinds."""
    p = batch(base, json.loads(json.dumps(GOOD)))
    refused = "\n".join(RS.record(p, write=True, agent=True, base=base, granted=["sustaining"]))
    assert "Refused" in refused and "coverage" in refused and read(base, "capex_periods") == []
    RS.record(p, write=True, agent=True, base=base, granted=["sustaining", "coverage"], today=date(2026, 11, 26))
    assert len(read(base, "capex_periods")) == 2 and read(base, "agent_log")[0]["file"] == "proposal.json (agent)"


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout


def test_blind_only_in_a_worktree(base, tmp_path_factory):
    """A13: `blind` refuses the main checkout; in a linked worktree it removes the tickers' rows and cells of the
    kinds named, and their logged documents (which would give the answers away)."""
    add(base, "capex_periods", [capex("FY", "2025-01-01", "2025-12-31", 60.4, url=EXK_FY)])
    git(base, "init", "-q", "-b", "main")
    git(base, "add", "data", "config")
    git(base, "commit", "-q", "-m", "record")
    assert "Refused" in "\n".join(RS.blind(["EXM CN"], ["sustaining", "mine_production"], base=base))
    wt = tmp_path_factory.mktemp("wt") / "blind"
    git(base, "worktree", "add", "-q", str(wt))
    lines = "\n".join(RS.blind(["EXM CN"], ["sustaining", "mine_production"], base=wt))
    assert "capex_periods: -1 row" in lines
    assert read(wt, "capex_periods") == [] and read(wt, "sources") == []
    assert read(wt, "companies")[0]["country_weights"] == "" and read(base, "capex_periods") != []


def test_compare_scores_matches_misses_extras(base):
    """A13: the proposal against the record at a git ref, figure by figure: matched at the record's precision,
    missed (absent or different), extra (not in the record), and any proposed figure without a source."""
    add(base, "capex_periods", [capex("9M", "2026-01-01", "2026-09-30", 55.1, sustaining_leases=2.8),
                                capex("FY", "2025-01-01", "2025-12-31", 60.4, url=EXK_FY)])
    git(base, "init", "-q", "-b", "main")
    git(base, "add", "data", "config")
    git(base, "commit", "-q", "-m", "record")
    prop = {"kinds": ["sustaining"], "append": {"capex_periods": [
        capex("9M", "2026-01-01", "2026-09-30", "55.10", sustaining_leases=2.7),         # one match, one miss
        capex("3M", "2026-07-01", "2026-09-30", 18.1, url="")]}}                         # extra, no source
    p = batch(base, prop)
    S = RS.compare(p, ref="main", base=base)
    assert (S["matched"], S["missed"], S["extra"], S["unsourced"]) == (1, 2, 1, 1)
    assert S["record"] == 3 and abs(S["share"] - 1 / 3) < 1e-9
    assert any("sustaining_leases 2.7, record 2.8" in x for x in S["lines"])
