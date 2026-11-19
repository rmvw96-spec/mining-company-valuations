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
    assert sh.sizes["PNAV inputs"][1] == col_to_num("BW")
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
    assert p["BE12"] == layout.pnav_formulas()["developer_check"] and p["BW12"].startswith("=MAP(")
    assert p["BK11"].startswith("Funding gap") and sh.cells["Model portfolio"]["Z6"].startswith("=ARRAYFORMULA(")
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
    assert not any(k[0] in "WXY" for k in mp if k != "X20")                # nothing written in the W:Y step
    assert mp["X20"] == "my note" and "Z6" in mp                           # column Z is a step of its own
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
    (1930, 1930.0, True), ("", None, True), ("Buy zone", "Buy zone ", True),
    ("=XLOOKUP(1,'Signals'!$A:$A,1)", "=XLOOKUP(1,Signals!$A:$A,1)", True),     # Google drops needless quotes
    ("=SUM('PNAV inputs'!A1)", "=SUM('PNAV inputs'!A1)", True),
    ("=SUM('PNAV inputs'!A1)", "=SUM(PNAVinputs!A1)", False)])
def test_same(a, b, same):
    assert layout.same(a, b) is same


def test_timing_formula_covers_every_bucket():
    f = layout.timing_formula()
    for k in settings()["signals"]["timing"]:
        assert f'="{k.split("|")[0]}")' in f
    assert f.index('(E6:E31="Silver")') < f.index('IF((A6:A31="Gold producers")')      # bucket|metal first
    assert '"No framework signal for physical copper"' in f and f.count("(") == f.count(")")


def test_new_signals_get_rows_inserted_in_their_tier(tmp_path):
    sh = existing_sheet()
    layout.run(sh, out_dir=tmp_path)
    tab = sh.cells["Signals"]
    keys = {v: int(k[1:]) for k, v in tab.items() if k.startswith("A") and k[1:].isdigit()}
    # Take two signal rows out, as on a Sheet set up before they existed
    for key in ("two_year_3m_change", "two_year_minus_fed_funds"):
        r = keys[key]
        for ref in [x for x in tab if x[1:].isdigit() or x[2:].isdigit()]:
            if layout.split_cell(ref)[1] == r:
                tab[ref] = ""
    tab["A90"] = "something below"                                   # rows below the tier move down
    tab["G7"] = "user's threshold"                                    # an edit elsewhere stays put
    dry = layout.run(sh, dry_run=True, out_dir=tmp_path)
    assert any("Would insert rows" in line and "two_year_3m_change" in line for line in dry)
    rep = layout.run(sh, out_dir=tmp_path)
    assert any(line.startswith("Inserted rows") for line in rep)
    tab = sh.cells["Signals"]
    now = {v: int(k[1:]) for k, v in tab.items() if k.startswith("A") and k[1:].isdigit() and v}
    order = [s.key for s in SIGNALS]
    i = order.index("two_year_3m_change")
    assert now["two_year_3m_change"] == now[order[i - 1]] + 1
    assert now["two_year_minus_fed_funds"] == now["two_year_3m_change"] + 1
    r = now["two_year_3m_change"]
    assert tab[f"I{r}"].startswith(f'=IF(E{r}="","",') and tab[f"G{r}"] == -0.25
    assert now["something below"] == 92 and tab["G7"] == "user's threshold"
    assert not layout.signal_inserts(sh)                             # idempotent


def test_first_install_is_upgraded_in_place(tmp_path):
    """A Sheet set up before the financing columns: BC and BE (and Model portfolio Y5) hold the first formulas and
    headers, the Signals tab lacks the new inputs. setup-sheet replaces those exact cells and adds the rest."""
    sh = existing_sheet()
    layout.run(sh, out_dir=tmp_path)
    p, mp, sig = sh.cells["PNAV inputs"], sh.cells["Model portfolio"], sh.cells["Signals"]
    P = S["pnav_inputs"]
    v1 = layout.pnav_formulas_v1()
    for name in layout.UPGRADED:
        p[f"{P[name]}{A - 1}"], p[f"{P[name]}{A}"] = layout.PNAV_HEADERS_V1[name], v1[name]
    for name in layout.FINANCING_HEADERS:
        for r in range(A - 1, B + 1):
            p.pop(f"{P[name]}{r}", None)
    mp["Y5"] = layout.PORTFOLIO_HEADERS_V1["months_of_cash"]
    for r in range(5, 32):
        mp.pop(f"Z{r}", None)
    keys = {v: int(k[1:]) for k, v in sig.items() if k.startswith("A") and k[1:].isdigit()}
    for key in ("raise_discount", "resource_weight_reserves", "resource_weight_mi", "resource_weight_inferred"):
        r = keys[key]
        for ref in [x for x in sig if layout.split_cell(x)[1] == r]:
            sig[ref] = ""
    p["BF60"] = "my own note"                             # a value typed in an input column isn't a conflict
    rep = layout.run(sh, out_dir=tmp_path)
    text = "\n".join(rep)
    assert "conflict" not in text, text
    assert "Inserted rows" in text and "raise_discount" in text
    assert p[f"{P['developer_check']}{A}"] == layout.pnav_formulas()["developer_check"]
    assert p[f"{P['months_of_cash']}{A - 1}"] == layout.PNAV_HEADERS["months_of_cash"]
    assert p[f"{P['funding_gap']}{A}"] == layout.financing_formulas()["funding_gap"]
    assert mp["Y5"] == layout.PORTFOLIO_HEADERS["months_of_cash"] and mp["Z6"].startswith("=ARRAYFORMULA(")
    now = {v: int(k[1:]) for k, v in sh.cells["Signals"].items() if k.startswith("A") and k[1:].isdigit() and v}
    assert now["raise_discount"] == now["runway_ok_months"] + 1
    assert sh.cells["Signals"][f"E{now['raise_discount']}"] == 0.15
    n = len(sh.blocks)
    layout.run(sh, out_dir=tmp_path)
    assert len(sh.blocks) == n                            # idempotent


def test_a_hand_edited_check_formula_is_left_alone(tmp_path):
    sh = existing_sheet()
    layout.run(sh, out_dir=tmp_path)
    ref = f"{S['pnav_inputs']['developer_check']}{A}"
    sh.cells["PNAV inputs"][ref] = "=MY_OWN()"
    rep = layout.run(sh, out_dir=tmp_path)
    assert sh.cells["PNAV inputs"][ref] == "=MY_OWN()"
    assert any("conflict" in line and ref in line for line in rep)


def test_financing_seeds_come_from_the_research_file():
    seeds = layout.financing_seeds()
    assert all(isinstance(v, (float, str)) for v in seeds.values())
    names = {name for _, name in seeds}
    assert {"remaining_capex", "financing_source", "resource_inferred"} <= names
