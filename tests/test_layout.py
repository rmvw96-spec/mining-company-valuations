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
    assert sh.sizes["PNAV inputs"][1] == col_to_num("CV")                     # through the P/NAV used
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
    assert p["BK11"].startswith("Funding gap")
    assert p["Z12"] == cash_flow_change_new("Z", 12) and p[f"AC{B}"] == cash_flow_change_new("AC", B)
    assert sh.cells["Holdings downside"]["K2"] == downside_new()
    assert sh.cells["P_NAV"]["U2"] == "=ARRAYFORMULA('PNAV inputs'!AS12:AS154)"
    assert p["BX12"] == layout.sensitivity_formula() and p["BX11"].startswith("P/NAV: Medium, add-on +2 points")
    assert sh.cells["P_NAV"]["W2"] == "=ARRAYFORMULA('PNAV inputs'!BX12:BX154)"
    assert sh.cells["Model portfolio"]["R6"].startswith("=ARRAYFORMULA(LET(band,")
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
    sh = existing_sheet(**{"Model portfolio": {"R20": "my note"}, "P_NAV": {"U150": "note"}})
    rep = layout.run(sh, out_dir=tmp_path)
    assert any(line.startswith("Model portfolio") and "conflict" in line and "R20" in line for line in rep)
    assert any(line.startswith("P_NAV") and "U150" in line for line in rep)
    mp = sh.cells["Model portfolio"]
    assert not any(layout.split_cell(k)[0] == "R" for k in mp if k != "R20")   # nothing written in the timing step
    assert mp["R20"] == "my note" and "S6" in mp                           # the buy-below is a step of its own
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
    """A Sheet set up before the financing columns: BC and BE hold the first formulas and headers, the Signals tab
    lacks the new inputs. setup-sheet replaces those exact cells and adds the rest."""
    sh = existing_sheet()
    layout.run(sh, out_dir=tmp_path)
    p, sig = sh.cells["PNAV inputs"], sh.cells["Signals"]
    P = S["pnav_inputs"]
    v1 = layout.pnav_formulas_v1()
    for name in layout.UPGRADED:
        p[f"{P[name]}{A - 1}"], p[f"{P[name]}{A}"] = layout.PNAV_HEADERS_V1[name], v1[name]
    for name in layout.FINANCING_HEADERS:
        for r in range(A - 1, B + 1):
            p.pop(f"{P[name]}{r}", None)
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


def test_ev_adds_minority_interest(tmp_path):
    """EV in AZ = market cap − net cash + minority interest (CT, written by `financials`; blank counts as zero)."""
    sh = existing_sheet()
    layout.run(sh, out_dir=tmp_path)
    p, P = sh.cells["PNAV inputs"], S["pnav_inputs"]
    assert P["minority"] == "CT" and p["CT11"] == layout.MINORITY_HEADER and "CT12" not in p
    ev = layout.pnav_formulas()["ev"]
    assert p[f"{P['ev']}{A}"] == ev and p[f"{P['ev']}{A - 1}"] == layout.PNAV_HEADERS["ev"]
    assert "-E12:E154+IF(ISNUMBER(CT12:CT154),CT12:CT154,0)" in ev


def test_installed_ev_is_upgraded_to_add_minority_interest(tmp_path):
    """A Sheet with the first EV formula and header gets the new ones; a hand-edited EV is a conflict, left alone."""
    sh = existing_sheet()
    layout.run(sh, out_dir=tmp_path)
    p, ref = sh.cells["PNAV inputs"], f"{S['pnav_inputs']['ev']}{A}"
    p[ref], p[f"{S['pnav_inputs']['ev']}{A - 1}"] = layout.pnav_formulas_v1()["ev"], "EV $M (market cap − net cash)"
    p.pop("CT11")
    rep = layout.run(sh, out_dir=tmp_path)
    assert not any("conflict" in line for line in rep)
    assert p[ref] == layout.pnav_formulas()["ev"] and p["CT11"] == layout.MINORITY_HEADER
    p[ref] = "=MY_OWN()"
    rep = layout.run(sh, out_dir=tmp_path)
    assert p[ref] == "=MY_OWN()" and any("conflict" in line and ref in line for line in rep)


def test_nav_used_prefers_our_valuation(tmp_path):
    """own-nav-first A2: CU is our NAV per share where CE has a base-deck NPV ((CE + E − CT) × C ÷ D), else the
    independent NAV in R; CV is the P/NAV on it, else the developers' study value (S + net cash)."""
    sh = existing_sheet()
    layout.run(sh, out_dir=tmp_path)
    p, P = sh.cells["PNAV inputs"], S["pnav_inputs"]
    assert (P["nav_used"], P["pnav_used"]) == ("CU", "CV")
    f = layout.nav_used_formulas()
    assert p["CU12"] == f["nav_used"] and p["CV12"] == f["pnav_used"] and p.get("CU13", "") == ""
    assert p["CU11"] == layout.NAV_USED_HEADERS["nav_used"] and p["CV11"] == layout.NAV_USED_HEADERS["pnav_used"]
    nav = f["nav_used"]
    assert "(CE12:CE154+E12:E154-IF(ISNUMBER(CT12:CT154),CT12:CT154,0))*C12:C154/D12:D154" in nav
    assert nav.index("CE12:CE154") < nav.index("R12:R154")                  # ours first, then the independent NAV
    assert "C12:C154/CU12:CU154" in f["pnav_used"] and "D12:D154/(S12:S154+E12:E154)" in f["pnav_used"]
    assert '"negative NAV"' in f["pnav_used"]


def test_installed_nav_readers_are_upgraded_to_the_nav_used(tmp_path):
    """own-nav-first A3: the royalty buy-below (AR) and band (AS), the NAV after a raise (BN) and the Signals royalty
    median read CU and CV; a Sheet with the exact earlier formulas and headers is upgraded in place."""
    from minerval import signals
    sh = existing_sheet()
    layout.run(sh, out_dir=tmp_path)
    p, P, sig = sh.cells["PNAV inputs"], S["pnav_inputs"], sh.cells["Signals"]
    f, fin = layout.pnav_formulas(), layout.financing_formulas()
    assert "CU12:CU154" in f["buy_below"] and "R12:R154" not in f["buy_below"]
    assert "CV12:CV154" in f["royalty_band"] and "AJ12:AJ154" not in f["royalty_band"]
    assert "CU12:CU154" in fin["nav_per_share_after"] and "R12:R154" not in fin["nav_per_share_after"]
    keys = {v: int(k[1:]) for k, v in sig.items() if k.startswith("A") and k[1:].isdigit()}
    med = f"E{keys['royalty_pnav_median']}"
    assert "!CV12:CV154" in sig[med] and "!CU12:CU154" in sig[med] and "!AJ12" not in sig[med]
    v1, fv1 = layout.pnav_formulas_v1(), layout.financing_formulas_v1()
    for name in ("buy_below", "royalty_band"):
        p[f"{P[name]}{A - 1}"], p[f"{P[name]}{A}"] = layout.PNAV_HEADERS_V1[name], v1[name]
    p[f"{P['nav_per_share_after']}{A - 1}"] = layout.FINANCING_HEADERS_V1["nav_per_share_after"]
    p[f"{P['nav_per_share_after']}{A}"] = fv1["nav_per_share_after"]
    sig[med] = signals.VALUE_FORMULAS_V1["royalty_pnav_median"]()
    rep = layout.run(sh, out_dir=tmp_path)
    assert not any("conflict" in line for line in rep), rep
    assert p[f"{P['buy_below']}{A}"] == f["buy_below"] and p[f"{P['royalty_band']}{A}"] == f["royalty_band"]
    assert p[f"{P['royalty_band']}{A - 1}"] == layout.PNAV_HEADERS["royalty_band"]
    assert p[f"{P['nav_per_share_after']}{A}"] == fin["nav_per_share_after"]
    assert p[f"{P['nav_per_share_after']}{A - 1}"] == layout.FINANCING_HEADERS["nav_per_share_after"]
    assert "!CV12:CV154" in sig[med]


def test_financing_seeds_come_from_the_research_file():
    seeds = layout.financing_seeds()
    assert all(isinstance(v, (float, str)) for v in seeds.values())
    names = {name for _, name in seeds}
    assert {"remaining_capex", "financing_source", "resource_inferred"} <= names


def test_sensitivity_formula_raises_the_discount_rate():
    f = layout.sensitivity_formula()
    assert f.startswith('=ARRAYFORMULA(IF(I12:I154="","",IFERROR(LET(rate,U12:U154+0.02,')
    assert "(Y12:Y154+Z12:Z154)*(1-(1+rate)^-V12:V154)/rate+E12:E154" in f


def test_notes_in_the_sensitivity_column_skip_its_step(tmp_path):
    sh = existing_sheet(P_NAV={"W150": "a note"})
    rep = layout.run(sh, out_dir=tmp_path)
    assert any("P/NAV with a higher add-on" in line and "conflict" in line for line in rep)
    assert "BX12" not in sh.cells["PNAV inputs"]


def test_valuation_columns_after_cb(tmp_path):
    sh = existing_sheet()
    layout.run(sh, out_dir=tmp_path)
    p, P, f = sh.cells["PNAV inputs"], settings()["sheet"]["pnav_inputs"], layout.valuation_formulas()
    assert p[f"{P['npv_base']}11"].startswith("NPV, Base deck") and p[f"{P['ev_npv_base']}12"] == f["ev_npv_base"]
    assert f"{P['ev']}12:{P['ev']}154/{P['npv_base']}12:{P['npv_base']}154" in f["ev_npv_base"]
    assert '"negative NPV"' in f["ev_npv_base"] and f"{P['financing_note']}12:{P['financing_note']}154" in f["downside"]
    for name in ("valuation_basis", "npv_base", "cf_base", "financing_note", "buy_below_value", "valuation_why"):
        assert f"{P[name]}12" not in p and p[f"{P[name]}11"]               # written by `financials`: header only
    assert P["valuation_why"] == "CS"


def test_valuation_headers_describe_each_tier():
    h = layout.valuation_headers()
    assert "producers: 10 years, no terminal value; royalties: a perpetuity; developers: risk-adjusted" in h["npv_base"]
    assert "developers: value per share after a +30% overrun's financing" in h["buy_below_value"]


def test_portfolio_status_and_buy_below_columns(tmp_path):
    """Screen revision 2 (A24, A25): N's header names the buy multiple, O is the status formula and S, the last
    column, the buy-below price at N. Both read PNAV inputs."""
    from minerval import screen as SC
    sh = existing_sheet(**{"Model portfolio": {"O5": "Status"}})
    rep = layout.run(sh, out_dir=tmp_path)
    assert "conflict" not in "\n".join(rep)
    mp = sh.cells["Model portfolio"]
    assert mp["N5"] == layout.PORTFOLIO_HEADERS["review_level"] and "buy multiple" in mp["N5"].lower()
    assert mp["O6"] == layout.portfolio_status_formula() and mp["S6"] == layout.portfolio_buy_below_formula()
    assert mp["S5"].startswith("Buy below US$/share")
    f = layout.portfolio_status_formula()
    i = {s: f.index(s) for s in ("No NPV: ", "Fails downside test", "Buy: below US$", "Above fair value: review")}
    assert max(i["No NPV: "], i["Fails downside test"]) < i["Buy: below US$"] < i["Above fair value: review"] \
        < f.rindex('"Hold"')                                         # the precedence of screen.status
    assert all(f'"{why}"' in f for why in SC.DOWNSIDE_FAILS) and "S6:S31" in f
    g = layout.portfolio_buy_below_formula()
    P = S["pnav_inputs"]
    for name in ("valuation_basis", "npv_pessimistic", "npv_base", "net_cash", "minority", "dilution_30",
                 "buy_below_value", "price", "mcap"):
        assert f"'PNAV inputs'!${P[name]}${A}:${P[name]}${B}" in g
    buy = settings()["valuation"]["buy"]
    assert all(f"{buy[k]['buy']}" in g for k in buy) and "N6:N31" in g
    n = len(sh.blocks)
    layout.run(sh, out_dir=tmp_path)
    assert len(sh.blocks) == n                                       # idempotent


def test_a_status_formula_typed_by_hand_is_left_alone(tmp_path):
    sh = existing_sheet(**{"Model portfolio": {"O6": '=ARRAYFORMULA(IF(N6:N31="","","mine"))'}})
    rep = layout.run(sh, out_dir=tmp_path)
    assert any("conflict" in line and "O6" in line for line in rep)
    assert sh.cells["Model portfolio"]["O6"] == '=ARRAYFORMULA(IF(N6:N31="","","mine"))'


def test_model_portfolio_columns_revision_2_left_unread_are_gone(tmp_path):
    """After screen revision 2: the tab ends at S (the buy-below price), without the peer norm, the P/NAV columns or
    the developer measures (EV per oz, months of funding, P/NAV after a raise), and nothing is installed past S."""
    C = S["portfolio_cols"]
    assert not {"peer_norm", "ev_per_aueq_oz", "months_of_cash", "pnav_after"} & set(C)
    cols = [v for k, v in C.items() if not k.endswith("_cell")]
    assert max(map(col_to_num, cols)) == col_to_num(C["buy_below"]) == col_to_num("S")
    assert [C[k] for k in ("review_level", "status", "why", "what_would_change", "timing")] == [*"NOPQR"]
    for gone in ("portfolio_lookup", "step_portfolio_after", "PORTFOLIO_STATUS_V1", "PORTFOLIO_HEADERS_V1"):
        assert not hasattr(layout, gone), gone
    assert set(layout.PORTFOLIO_HEADERS) == {"timing", "review_level", "buy_below"}
    sh = existing_sheet()
    layout.run(sh, out_dir=tmp_path)
    assert max(col_to_num(layout.split_cell(k)[0]) for k in sh.cells["Model portfolio"]) == col_to_num("S")


def _let_names(formula: str) -> list[str]:
    """The names a formula's LET()s define (each name is followed by a comma at the LET's own depth)."""
    import re
    names = []
    for m in re.finditer(r"LET\(", formula):
        i, depth, arg, args = m.end(), 0, "", []
        while i < len(formula):
            ch = formula[i]
            if ch == '"':
                j = formula.index('"', i + 1)
                arg += formula[i:j + 1]
                i = j + 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    break
                depth -= 1
            if ch == "," and depth == 0:
                args.append(arg)
                arg = ""
            else:
                arg += ch
            i += 1
        names += [a.strip() for a in args[0::2]]
    return names


def test_let_names_are_not_cell_references():
    """Sheets rejects a LET name that reads as a cell reference ("d30" is D30): #NAME? on the whole column."""
    import re
    for f in (layout.portfolio_buy_below_formula(), layout.portfolio_status_formula(), layout.timing_formula()):
        names = _let_names(f)
        assert names and not [n for n in names if re.fullmatch(r"[A-Za-z]{1,3}\d+", n)], names
