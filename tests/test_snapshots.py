"""`snapshots`: the fund tables rebuilt from data/derived/, written only under the expected headers."""
import json

import pandas as pd
import pytest

from minerval import snapshots as SN
from minerval.config import settings
from minerval.sheets import MemorySheet

FUNDS = settings()["holdings"]["fund_order"]
nan = float("nan")


@pytest.fixture
def derived(tmp_path):
    F = pd.DataFrame([{"fund": f, "focus": f"{f} focus", "P/book": 2.0, "P/ocf": 8.0 + i, "P/fcf": nan if i == 5
                       else 15.04, "EV/EBITDA": 5.44, "neg_ocf_%": 1.42, "P/ocf (positive only)": 7.65,
                       "EV/EBITDA (positive only)": 5.35, "physical_metal_%": 17.96 if f == "SLVR" else 0.0,
                       "other_%": 0.0, "uncovered_company_%": 0.5} for i, f in enumerate(FUNDS)])
    F.to_csv(tmp_path / "fund_multiples.csv", index=False)
    T = pd.DataFrame([{"fund": f, "P/OCF": 8.0, "P/OCF today": [10.7, 13.0, 13.04, nan, 10.2, 22.1][i],
                       "P/FCF": 15.0, "P/FCF today": 31.5, "EV/EBITDA": 5.4, "EV/EBITDA today": 7.4,
                       "revenue change %": -16.6, "P/OCF today (positive only)": 10.5} for i, f in enumerate(FUNDS)])
    T.to_csv(tmp_path / "multiples_today.csv", index=False)
    rows = []
    for f in FUNDS:
        r = {"fund": f, "breakeven % of today": 81.5, "breakeven price": 3038.364, "breakeven metal": "gold $/oz",
             "net cash %": 3.6, "working capital %": 6.6, "burning cash %": 1.42, "runway < 2 yrs %": 1.13,
             "dil1 median": 0.039, "dil3 median": 0.555, "dil3 >20% weight": 15.22}
        for s in settings()["stress"]["scenarios"]:
            r.update({f"P/FCF {s}": nan if s == "Severe" else 31.52, f"FCF+ weight {s}": 25.81,
                      f"EV/EBITDA {s}": 28.09})
        rows.append(r)
    pd.DataFrame(rows).to_csv(tmp_path / "stress_funds.csv", index=False)
    (tmp_path / "metals_today.json").write_text(json.dumps({"gold": 3727.9, "silver": 44.95, "copper": 5.672,
                                                            "date": "2026-11-18"}))
    return tmp_path


def sheet(skip=()):
    cells = {"Summary": {}, "Metal prices reference": {}, "Stress test & downside": {}}
    from minerval.sheets import col_to_num, num_to_col, split_cell
    for t in SN.tables_layout():
        if t["header_cell"] in skip:
            continue
        c, r = split_cell(t["header_cell"])
        for j, h in enumerate(t["headers"]):
            cells[t["tab"]][f"{num_to_col(col_to_num(c) + j)}{r}"] = h
    return MemorySheet(cells)


def test_tables(derived):
    T = {(t["tab"], t["cell"]): t for t in SN.tables(derived)}
    s = T[("Summary", "A4")]
    assert s["rows"][0] == ["SGDM", "SGDM focus", 2.0, 8.0, 15.0, 5.4, 1.4, 7.7, 5.3, 0.0, 0.5]
    assert s["rows"][3][9] == 18.0 and s["rows"][5][4] == "negative"
    assert s["title"] == "Look-through valuation of Sprott miner ETFs (holdings as of Nov 13, 2026; prices as of " \
                         "Nov 18, 2026 close)"
    m = T[("Metal prices reference", "B6")]["rows"]
    assert [r[0] for r in m] == ["COPP", "SGDM", "SGDJ", "GBUG", "COPJ", "SLVR"]     # by P/OCF today; negative last
    assert [r[1] for r in m] == [1, 2, 3, 4, 5, 6] and m[0][8] == -0.166 and m[5][3] == "negative"
    sc = T[("Stress test & downside", "B6")]["rows"]
    assert sc[2] == ["Today", 3728, 44.95, 5.67] and sc[0][0] == "Severe"
    assert T[("Stress test & downside", "B22")]["rows"][0] == ["SGDM", "negative", 31.5, 31.5, 31.5]
    assert T[("Stress test & downside", "B31")]["rows"][0][1] == 25.8
    assert T[("Stress test & downside", "B40")]["rows"][0] == ["SGDM", 3038.36, "gold $/oz", 81.5, 3.6, 6.6, 1.4,
                                                              1.1, 0.0, 0.6, 15.2]


def test_run_writes_under_matching_headers_and_is_idempotent(derived, tmp_path):
    sh = sheet()
    rep = SN.run(sh, out_dir=tmp_path / "out", derived=derived)
    assert sh.cells["Summary"]["A4"] == "SGDM" and sh.cells["Stress test & downside"]["C40"] == 3038.36
    assert sh.cells["Summary"]["A1"].startswith("Look-through valuation")
    assert not any("skipped" in line for line in rep)
    rep = SN.run(sh, out_dir=tmp_path / "out", derived=derived)
    assert all(line.endswith(": 0 cells change.") for line in rep[:-1])


def test_moved_headers_skip_that_table_only(derived, tmp_path):
    sh = sheet(skip=("B39",))
    rep = SN.run(sh, out_dir=tmp_path / "out", derived=derived)
    assert any(line.startswith("Stress test & downside!B40") and "skipped" in line for line in rep)
    assert "C40" not in sh.cells["Stress test & downside"] and sh.cells["Summary"]["A4"] == "SGDM"


def test_dry_run_writes_nothing(derived, tmp_path):
    sh = sheet()
    SN.run(sh, dry_run=True, out_dir=tmp_path / "out", derived=derived)
    assert not sh.blocks and (tmp_path / "out" / "dry_run.json").exists()
