"""Writing refreshed company data to the Sheet: matching rows by key, and never touching formula cells."""
import pandas as pd
import pytest

from minerval import financials
from minerval.financials import _m, _num, _same, downside_rows
from minerval.sheets import CLEAR, MemorySheet, col_to_num, num_to_col, split_cell

from conftest import frame


def test_value_helpers():
    assert _num(None, 1) == CLEAR and _num(float("nan"), 1) == CLEAR
    assert _num(1.234567, 2) == 1.23
    assert _m(12_345_678.0) == 12.3 and _m(float("nan")) == CLEAR
    assert _same("", CLEAR) and _same(None, "")
    assert _same(1.0, 1.0 + 1e-10) and not _same(1.0, 1.01)
    assert _same("'2026-09-30", "2026-09-30")                     # a typed date keeps its quote on the Sheet


@pytest.mark.parametrize("be_k,expected", [(0.5, 2200.0), (-0.2, "below zero"), (3.5, "over 3x today")])
def test_breakeven_labels(be_k, expected):
    M = frame([{"fund": "SGDM", "ticker": "A", "kind": "company", "be_k": be_k, "be_metal": "gold",
                "be_price": be_k * 4400, "netcash_pct": 1.0}])
    left, _ = downside_rows(M)[("SGDM", "A")]
    assert left[5] == expected and left[6] == "gold $/oz"


def test_non_companies_get_cleared_rows():
    M = frame([{"fund": "SLVR", "ticker": "PSLV", "kind": "physical metal", "netcash_pct": 3.0}])
    left, right = downside_rows(M)[("SLVR", "PSLV")]
    assert left[0] == CLEAR and right == ["PSLV", CLEAR, CLEAR, CLEAR, CLEAR]


# Key columns and formula columns on each tab (see CLAUDE.md, "The Sheet: what not to touch").
PROTECTED = {"Holdings": {"A", "D", "E", "F", "G", "H", "O", "P", "V"},
             "Holdings downside": {"A", "K", "L"},
             "PNAV inputs": {"C", "D", "I", "J", "K", "L", "P", "Q", "R", "S", "AL", "AM", "AN", "AO", "AP", "AQ"}}


def touched(blocks):
    for tab, cell, rows in blocks:
        c, r = split_cell(cell)
        for i, row in enumerate(rows):
            for j, _ in enumerate(row):
                yield tab, col_to_num(c) + j, r + i


@pytest.fixture
def derived(tmp_path, monkeypatch):
    nan = float("nan")
    pd.DataFrame([
        {"fund": "SGDM", "ticker": "AEM CN", "ocf": 5e9, "fcf": 3e9, "ebitda": 6e9, "book": 20e9, "debt": 1e9,
         "cash": 2e9, "mcap": 80e9, "fin_date": "2026-09-30", "note": nan},
        {"fund": "SGDM", "ticker": "NEW", "ocf": nan, "fcf": nan, "ebitda": nan, "book": nan, "debt": 0.0,
         "cash": 0.0, "mcap": nan, "fin_date": nan, "note": "No price or financial data"},
    ]).to_csv(tmp_path / "holdings_detail.csv", index=False)
    pd.DataFrame([{"fund": "SGDM", "ticker": "AEM CN", "kind": "company", "netcash_pct": 1.25, "wc_pct": 2.0,
                   "runway": nan, "dil1": 0.5, "dil3": 1.5, "be_k": 0.4, "be_metal": "gold", "be_price": 1600.0,
                   "fcf_intercept_m": -100.0, "fcf_per_gold_m": 0.5, "fcf_per_silver_m": 0.0,
                   "fcf_per_copper_m": 0.0}]).to_csv(tmp_path / "stress_holdings.csv", index=False)
    pd.DataFrame([{"yahoo": "AEM.TO", "net_cash_m": 1000.0, "revenue_m": 9000.0, "fcf_m": 3000.0, "ocf_m": 5000.0,
                   "avg_gold": 3500.0, "avg_silver": 40.0, "avg_copper": 4.5},
                  {"yahoo": "NOBASIS", "net_cash_m": 5.0, "revenue_m": 1.0, "fcf_m": 1.0, "ocf_m": 1.0,
                   "avg_gold": 1.0, "avg_silver": 1.0, "avg_copper": 1.0}]).to_csv(tmp_path / "pnav.csv", index=False)
    monkeypatch.setattr(financials, "DERIVED", tmp_path)
    return tmp_path


def sheet():
    return MemorySheet({
        "Holdings": {"A2": "SGDM", "O2": "AEM CN", "I2": 1.0, "Q2": "old note", "A3": "SGDM", "O3": "GONE"},
        "Holdings downside": {"A2": "SGDM", "L2": "AEM CN"},
        "PNAV inputs": {"AP12": "AEM.TO", "I12": "FCF", "AP13": "SLV.TRUST", "AQ13": 12.0,
                        "AP14": "NOBASIS", "AP15": "UNKNOWN"},
    })


def test_financials_writes_by_key(derived, tmp_path):
    sh = sheet()
    rep = financials.run(sh, out_dir=tmp_path / "out")
    h, d, p = sh.cells["Holdings"], sh.cells["Holdings downside"], sh.cells["PNAV inputs"]
    assert [h[f"{c}2"] for c in "IJKLMN"] == [5000.0, 3000.0, 6000.0, 20000.0, -1000.0, "2026-09-30"]
    assert h["Q2"] == ""                                           # stale note cleared
    assert [d[f"{c}2"] for c in "DEFGHIJ"] == [1.2, 2.0, "", 0.5, 1.5, 1600.0, "gold $/oz"]
    assert [d[f"{c}2"] for c in "MNOPQ"] == ["AEM CN", -100.0, 0.5, 0.0, 0.0]
    assert [p[f"{c}12"] for c in "EFGHMNO"] == [1000.0, 9000.0, 3000.0, 5000.0, 3500.0, 40.0, 4.5]
    assert "E13" not in p                                          # fixed-price trust row left alone
    assert p["E14"] == 5.0 and "F14" not in p                      # no basis in I: only net cash is written
    text = "\n".join(rep)
    assert "SGDM NEW" in text and "rows 3" in text and "UNKNOWN" in text


def test_financials_never_writes_formula_columns(derived, tmp_path):
    sh = sheet()
    financials.run(sh, out_dir=tmp_path / "out")
    bad = [(t, f"{num_to_col(c)}{r}") for t, c, r in touched(sh.blocks) if num_to_col(c) in PROTECTED.get(t, ())]
    assert not bad


def test_financials_dry_run_writes_nothing(derived, tmp_path):
    sh = sheet()
    before = {t: dict(c) for t, c in sh.cells.items()}
    rep = financials.run(sh, dry_run=True, out_dir=tmp_path / "out")
    assert sh.cells == before and not sh.blocks
    assert (tmp_path / "out" / "dry_run.json").exists()
    assert any("cells change" in line and not line.startswith("Holdings downside") for line in rep)
