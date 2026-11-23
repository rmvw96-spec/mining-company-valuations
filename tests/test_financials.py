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
    assert left[0] == CLEAR and right == ["PSLV", CLEAR, CLEAR, CLEAR, CLEAR, CLEAR]


# Key columns and formula columns on each tab (see CLAUDE.md, "The Sheet: what not to touch"). PNAV inputs P (the
# jurisdiction add-on) is written for country-table rows only: test_financials_writes_table_addons.
PROTECTED = {"Holdings": {"A", "D", "E", "F", "G", "H", "O", "P", "V"},
             "Holdings downside": {"A", "K", "L"},
             "PNAV inputs": {"C", "D", "I", "J", "K", "L", "Q", "R", "S", "AL", "AM", "AN", "AO", "AP", "AQ",
                             "AR", "AS", "AT", "AU", "AV", "AW", "AZ", "BA", "BB", "BC", "BD", "BE",
                             "CH", "CI", "CJ", "CK", "CL", "CP"}}


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
                   "fcf_per_copper_m": 0.0, "cost_base_m": 6000.0}]).to_csv(tmp_path / "stress_holdings.csv",
                                                                             index=False)
    pd.DataFrame([{"yahoo": "AEM.TO", "net_cash_m": 1000.0, "revenue_m": 9000.0, "fcf_m": 3000.0, "ocf_m": 5000.0,
                   "avg_gold": 3500.0, "avg_silver": 40.0, "avg_copper": 4.5, "cash_m": 2000.0, "fcf_12m_m": 3000.0,
                   "minority_m": 120.456},
                  {"yahoo": "NOBASIS", "net_cash_m": 5.0, "revenue_m": 1.0, "fcf_m": 1.0, "ocf_m": 1.0,
                   "avg_gold": 1.0, "avg_silver": 1.0, "avg_copper": 1.0, "minority_m": 0.0}]).to_csv(
        tmp_path / "pnav.csv", index=False)
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


def test_financials_writes_the_new_columns_once_set_up(derived, tmp_path):
    from minerval.layout import DOWNSIDE_COST_HEADER, PNAV_HEADERS
    sh = sheet()
    sh.cells["Holdings downside"]["R1"] = DOWNSIDE_COST_HEADER
    sh.cells["PNAV inputs"]["AX11"] = PNAV_HEADERS["cash"]
    from minerval.layout import valuation_headers
    sh.cells["PNAV inputs"]["CC11"] = valuation_headers()["valuation_basis"]      # every new column set up
    from minerval.layout import MINORITY_HEADER
    sh.cells["PNAV inputs"]["CT11"] = MINORITY_HEADER
    rep = financials.run(sh, out_dir=tmp_path / "out")
    d, p = sh.cells["Holdings downside"], sh.cells["PNAV inputs"]
    assert d["R2"] == 6000.0
    assert (p["AX12"], p["AY12"]) == (2000.0, 3000.0)
    assert "AX13" not in p                                         # fixed-price trust row left alone
    assert p["CT12"] == 120.46 and "CT13" not in p                 # minority interest, $M
    assert p["CT14"] == ""                                         # none reported: blank, not 0
    assert any(line.startswith("  Minority interest (CT): 1 rows with a figure") for line in rep)
    assert not any("not set up yet" in line for line in rep)


def test_financials_before_setup_leaves_new_columns_alone(derived, tmp_path):
    sh = sheet()
    rep = financials.run(sh, out_dir=tmp_path / "out")
    assert "R2" not in sh.cells["Holdings downside"] and "AX12" not in sh.cells["PNAV inputs"]
    assert "CT12" not in sh.cells["PNAV inputs"]
    assert sum("not set up yet" in line for line in rep) == 4       # cash, cost base, valuation, minority interest


def test_financials_writes_table_addons(derived, tmp_path):
    I = pd.read_csv(derived / "pnav.csv")
    I["addon_pct_points"], I["addon_basis"] = [1.5, 2.0], ["table", "manual"]
    I.to_csv(derived / "pnav.csv", index=False)
    sh = sheet()
    sh.cells["PNAV inputs"].update({"P11": "Jurisdiction add-on", "I14": "FCF", "P14": 0.03})
    rep = financials.run(sh, out_dir=tmp_path / "out")
    p = sh.cells["PNAV inputs"]
    assert p["P12"] == 0.015                                       # a fraction, as the Sheet holds it
    assert p["P14"] == 0.03                                        # manual: the Sheet's figure is kept
    assert any("1 rows from the country table" in line for line in rep)


def test_financials_leaves_the_addon_alone_without_its_header(derived, tmp_path):
    I = pd.read_csv(derived / "pnav.csv")
    I["addon_pct_points"], I["addon_basis"] = [1.5, 2.0], ["table", "table"]
    I.to_csv(derived / "pnav.csv", index=False)
    sh = sheet()
    rep = financials.run(sh, out_dir=tmp_path / "out")
    assert "P12" not in sh.cells["PNAV inputs"] and any("was not written" in line for line in rep)


def valuation_csv(derived, newer=True, **k):
    import os
    row = {"sheet_row": 12, "yahoo": "AEM.TO", "ticker": "AEM CN", "tier": "producer",
           "valuation_basis": "OCF − sustaining", "npv Pessimistic": 30000.0, "npv Base": 42000.0,
           "npv Optimistic": 55000.0, "cf_base": 4800.0, "dilution +15%": float("nan"), "dilution +30%": float("nan"),
           "financing_note": "", "buy_below": 61.234, "fair_value": 90.5, "why": ""}
    row.update(k)
    pd.DataFrame([row]).to_csv(derived / "valuation.csv", index=False)
    t = (derived / "pnav.csv").stat().st_mtime + (10 if newer else -10)
    os.utime(derived / "valuation.csv", (t, t))


def valuation_sheet():
    from minerval.config import settings
    from minerval.layout import valuation_headers
    sh = sheet()
    P = settings()["sheet"]["pnav_inputs"]
    sh.cells["PNAV inputs"][f"{P['valuation_basis']}11"] = valuation_headers()["valuation_basis"]
    return sh


def test_financials_writes_the_valuation_once_set_up(derived, tmp_path):
    valuation_csv(derived)
    sh = valuation_sheet()
    rep = financials.run(sh, out_dir=tmp_path / "out")
    p = sh.cells["PNAV inputs"]
    assert p["CC12"] == "OCF − sustaining"
    assert (p["CD12"], p["CE12"], p["CF12"], p["CG12"]) == (30000.0, 42000.0, 55000.0, 4800.0)
    assert (p["CQ12"], p["CR12"]) == (61.23, 90.5)
    assert not any(f"{c}12" in p for c in ("CH", "CI", "CJ", "CK", "CL", "CP"))    # formula columns
    assert "CC13" not in p                                                         # the fixed-price trust row
    assert any(line.startswith("  Valuation (CC:CS): 1 rows") for line in rep)


def test_financials_writes_a_developers_financing_columns(derived, tmp_path):
    valuation_csv(derived, tier="developer", valuation_basis="study (risk-adjusted)", cf_base=float("nan"),
                  **{"dilution +15%": 0.5512, "dilution +30%": 1.2345},
                  financing_note="a raise at a +30% overrun more than doubles the share count (123% dilution)",
                  buy_below=float("nan"), why="KSM: no cash-flow table recorded")
    sh = valuation_sheet()
    financials.run(sh, out_dir=tmp_path / "out")
    p = sh.cells["PNAV inputs"]
    assert (p["CM12"], p["CN12"]) == (0.5512, 1.2345) and p["CO12"].startswith("a raise at a +30% overrun")
    assert p["CS12"] == "KSM: no cash-flow table recorded" and p.get("CQ12") in (None, CLEAR, "")


def test_financials_skips_a_missing_or_stale_valuation(derived, tmp_path):
    sh = valuation_sheet()
    rep = financials.run(sh, out_dir=tmp_path / "out")
    assert "CC12" not in sh.cells["PNAV inputs"] and any("run `valuation` first" in line for line in rep)
    valuation_csv(derived, newer=False)
    rep = financials.run(sh, out_dir=tmp_path / "out")
    assert "CD12" not in sh.cells["PNAV inputs"] and any("older than pnav.csv" in line for line in rep)


def test_financials_leaves_the_valuation_alone_before_setup(derived, tmp_path):
    valuation_csv(derived)
    sh = sheet()
    rep = financials.run(sh, out_dir=tmp_path / "out")
    assert "CC12" not in sh.cells["PNAV inputs"] and any("CC:CS (valuation) not set up yet" in line for line in rep)


def test_financials_writes_a_developers_table_addon_too(derived, tmp_path):
    I = pd.read_csv(derived / "pnav.csv")
    I["addon_pct_points"], I["addon_basis"] = [1.5, 2.25], ["table", "table"]
    I.to_csv(derived / "pnav.csv", index=False)
    sh = sheet()                                                   # row 14 (NOBASIS) has no cash-flow basis
    sh.cells["PNAV inputs"]["P11"] = "Jurisdiction add-on"
    rep = financials.run(sh, out_dir=tmp_path / "out")
    p = sh.cells["PNAV inputs"]
    assert p["P12"] == 0.015 and p["P14"] == 0.0225 and "P13" not in p      # not the fixed-price trust row
    assert "F14" not in p                                          # its F:H and M:O stay research inputs
    assert any("2 rows from the country table" in line for line in rep)
