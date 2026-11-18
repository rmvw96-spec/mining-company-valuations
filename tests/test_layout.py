"""setup-sheet on an in-memory copy of the Sheet: fresh install, idempotent rerun, conflicts, the Z:AC rewrite."""
import pytest

from minerval import layout
from minerval.config import settings
from minerval.layout import cash_flow_change_new, cash_flow_change_old, downside_new, downside_old
from minerval.sheets import MemorySheet, col_to_num
from minerval.signals import SIGNALS

S = settings()["sheet"]
A, B = S["pnav_first_row"], S["pnav_last_row"]


def existing_sheet(**extra):
    """The parts of the current Sheet the installer reads: the old formulas and the grid sizes."""
    pnav = {f"{c}{r}": cash_flow_change_old(c, r) for r in range(A, B + 1) for c in ("Z", "AA", "AB", "AC")}
    pnav["B11"] = "Holding"
    cells = {"PNAV inputs": pnav, "Holdings downside": {"K2": downside_old(), "L1": "Sprott ticker"},
             "P_NAV": {"A1": "Fund", "A146": "How to read this"}, "Model portfolio": {"A5": "Bucket"},
             "Metal prices reference": {}}
    for tab, more in extra.items():
        cells[tab].update(more)
    sizes = {"PNAV inputs": [1000, 43], "Holdings downside": [1000, 26], "P_NAV": [1000, 26],
             "Model portfolio": [1000, 26], "Metal prices reference": [1000, 26]}
    return MemorySheet(cells, sizes)


def test_fresh_install(tmp_path):
    sh = existing_sheet()
    rep = layout.run(sh, out_dir=tmp_path)
    text = "\n".join(rep)
    assert "conflict" not in text and "Created the Signals tab." in text
    assert sh.sizes["PNAV inputs"][1] == col_to_num("BE")
    sig, p = sh.cells["Signals"], sh.cells["PNAV inputs"]
    keys = {v: int(k[1:]) for k, v in sig.items() if k.startswith("A") and k[1:].isdigit() and int(k[1:]) >= 5}
    assert set(s.key for s in SIGNALS) <= set(keys)
    r = keys["gold_silver_ratio"]
    assert sig[f"G{r}"] == 80 and sig[f"I{r}"].startswith(f'=IF(E{r}="","",')
    assert sig[f"E{keys['industry_aisc']}"] == 1930
    assert sig[f"E{keys['royalty_pnav_median']}"].startswith("=IFERROR(MEDIAN(FILTER(")
    assert f"E{keys['gold_silver_ratio']}" not in sig                       # values are written by `signals`
    assert p["H7"].startswith('=XLOOKUP("producer_cost_increase"')
    assert p["AR12"].startswith("=ARRAYFORMULA(") and p["BE12"].startswith("=ARRAYFORMULA(")
    assert p["Z12"] == cash_flow_change_new("Z", 12) and p[f"AC{B}"] == cash_flow_change_new("AC", B)
    assert sh.cells["Holdings downside"]["K2"] == downside_new()
    assert sh.cells["P_NAV"]["U2"] == "=ARRAYFORMULA('PNAV inputs'!AS12:AS154)"
    assert sh.cells["Model portfolio"]["W6"].startswith("=ARRAYFORMULA(LET(band,")
    assert any(f[0] == "Signals" for f in sh.formats)
    assert list(tmp_path.glob("backup-*.json"))
    assert "\nCheck: " in text            # MemorySheet doesn't calculate, so K2's "value" is its new formula text


def test_second_run_writes_nothing(tmp_path):
    sh = existing_sheet()
    layout.run(sh, out_dir=tmp_path)
    n = len(sh.blocks)
    rep = layout.run(sh, out_dir=tmp_path)
    assert len(sh.blocks) == n
    assert all("already in place (no change)" in line for line in rep if ": " in line and "tab" in line.lower()
               or "columns" in line or "Z:AC" in line or "helper" in line)


def test_user_edits_to_inputs_are_not_conflicts(tmp_path):
    sh = existing_sheet()
    layout.run(sh, out_dir=tmp_path)
    sig = sh.cells["Signals"]
    r = next(int(k[1:]) for k, v in sig.items() if v == "gold_silver_ratio")
    sig[f"G{r}"] = 85                                                       # the user's own threshold
    n = len(sh.blocks)
    rep = layout.run(sh, out_dir=tmp_path)
    assert len(sh.blocks) == n and not any("conflict" in line for line in rep)
    assert sig[f"G{r}"] == 85


def test_dry_run_writes_nothing(tmp_path):
    sh = existing_sheet()
    rep = layout.run(sh, dry_run=True, out_dir=tmp_path)
    assert not sh.blocks and "Signals" not in sh.cells
    assert "Would create the Signals tab." in rep and any("would add" in line for line in rep)
    assert not list(tmp_path.glob("backup-*.json"))


def test_occupied_cell_skips_the_step(tmp_path):
    sh = existing_sheet(**{"Model portfolio": {"X20": "my note"}, "P_NAV": {"U150": "note"}})
    rep = layout.run(sh, out_dir=tmp_path)
    assert any(line.startswith("Model portfolio") and "conflict" in line and "X20" in line for line in rep)
    assert any(line.startswith("P_NAV") and "U150" in line for line in rep)
    mp = sh.cells["Model portfolio"]
    assert mp == {"A5": "Bucket", "X20": "my note"}                         # nothing written in the step
    assert "U2" not in sh.cells["P_NAV"]


def test_downside_formula_changed_by_hand_is_left_alone(tmp_path):
    sh = existing_sheet(**{"Holdings downside": {"K2": "=SOMETHING()"}})
    rep = layout.run(sh, out_dir=tmp_path)
    assert sh.cells["Holdings downside"]["K2"] == "=SOMETHING()"
    assert any("conflict" in line and "K2" in line for line in rep)


def test_cash_flow_rewrite_touches_only_the_exact_old_formula(tmp_path):
    sh = existing_sheet(**{"PNAV inputs": {"AA30": "=1+1", "Z31": ""}})
    rep = layout.run(sh, out_dir=tmp_path)
    p = sh.cells["PNAV inputs"]
    assert p["AA30"] == "=1+1" and p["Z31"] == ""
    assert p["Z30"] == cash_flow_change_new("Z", 30)
    line = next(x for x in rep if "Z:AC" in x and "conflict" in x)
    assert "AA30" in line and "Z31" in line


def test_cash_flow_formula_keeps_developer_rows_blank():
    new = cash_flow_change_new("Z", 12)
    assert new.startswith('=IF($I12="","",') and new.endswith('*$H$7,0))')
    assert new.count("(") == new.count(")")
    assert '-IF($I12="FCF",$H$6*MAX(0,N($F12)-N($G12))*$H$7,0)' in new


def test_downside_formula():
    new = downside_new()
    assert new.startswith("=ARRAY_CONSTRAIN(ARRAYFORMULA(") and new.endswith("))), 336, 1)")
    assert "IF(ISNUMBER(R2:R337),R2:R337,0)" in new and "'Metal prices reference'!$C$32" in new


@pytest.mark.parametrize("a,b,same", [
    ('=IF(A1="", "x", B1)', '=IF(A1="","x",B1)', True),
    ('=IF(A1="a b","",1)', '=IF(A1="ab","",1)', False),                     # spaces inside strings count
    (1930, 1930.0, True), ("", None, True), ("Buy zone", "Buy zone ", True)])
def test_same(a, b, same):
    assert layout.same(a, b) is same


def test_timing_formula_covers_every_bucket():
    f = layout.timing_formula()
    for k in settings()["signals"]["timing"]:
        assert f'="{k.split("|")[0]}")' in f
    assert f.index('(E6:E31="Silver")') < f.index('IF((A6:A31="Gold producers")')      # bucket|metal first
    assert '"No framework signal for physical copper"' in f and f.count("(") == f.count(")")
