"""`setup-sheet`: add the Signals tab and the new columns to the Sheet, safely and idempotently.

Each step lists the cells it touches and what each may hold now:
  exact    the cell must be empty or already hold exactly the new content (spill ranges below an
           ARRAYFORMULA are "exact" cells whose new content is empty);
  seed     an input: filled only when empty, and left alone (no conflict) when it holds anything;
  replace  the cell must hold the exact old formula (or already the new one).
A step with any conflicting cell is skipped and reported; nothing in it is written. A second run writes nothing.
Every formula is generated here from settings.toml [sheet] addresses.
"""
import json
import re
import time
from dataclasses import dataclass, field

import pandas as pd

from .config import OUT, RESEARCH, ensure, settings
from .pnav import RESOURCE_COLS
from .sheets import col_to_num, num_to_col, split_cell
from .signals import SIGNALS, look, status_formula, value_formula

DEST = OUT / "layout"

# Headers (row 11 on PNAV inputs, row 1 on P/NAV and Holdings downside, the header row on Model portfolio).
PNAV_HEADERS = {
    "buy_below": "Buy-below price US$ (framework: buy-zone top × independent NAV per share)",
    "royalty_band": "Royalty valuation band (framework; uses the independent NAV in R, refreshed by hand)",
    "resource_amount": "Resource, millions of the unit",
    "resource_unit": "Resource unit (oz Au, oz AuEq, oz AgEq, lb Cu, lb CuEq)",
    "resource_category": "Resource category",
    "resource_source": "Resource source and date",
    "cash": "Cash $M (cash and short-term investments)",
    "fcf_12m": "Free cash flow $M, last 12 months",
    "ev": "EV $M (market cap − net cash)",
    "ev_per_unit": "EV per unit in the ground US$",
    "ev_per_aueq_oz": "EV per gold-equivalent oz US$",
    "months_of_cash": "Months of cash (at the last 12 months' burn)",
    "cash_share": "Cash, % of market value",
    "developer_check": "Developer check (project loans aren't counted as cash: check undrawn facilities)",
}
PNAV_TAB_HEADERS = {"royalty_band": "Royalty band (framework)", "buy_below": "Buy-below price US$"}
DOWNSIDE_COST_HEADER = "Helper: cost base $M (revenue − FCF)"
PORTFOLIO_HEADERS = {"timing": "Timing signal (framework)",
                     "ev_per_aueq_oz": "EV per gold-equivalent oz (developers)",
                     "months_of_cash": "Months of cash (developers)"}
SIGNALS_HEADERS = ["Key (code uses it to find rows; can be hidden)", "Tier", "Signal", "Unit", "Value", "As of",
                   "Threshold 1", "Threshold 2", "Status", "What the framework says", "Source"]
INPUTS = [  # key, label, default (None = left blank), number format
    ("industry_aisc", "Industry all-in sustaining cost, $/oz", "industry_aisc", "#,##0"),
    ("producer_cost_increase", "Producer cost increase since their reported 12 months (0% = as reported)",
     "producer_cost_increase", "0.0%"),
    ("energy_share_of_costs", "Energy's share of producers' costs (your estimate)", None, "0%"),
    ("implied_cost_increase", "What the diesel move implies if energy is that share of costs", "formula", "0.0%"),
    ("near_cash_share", "Developer 'trading near cash' when cash is at least this share of market value",
     "near_cash_share", "0%"),
    ("runway_short_months", "Developer runway: short of cash below (months)", "runway_short_months", "0"),
    ("runway_ok_months", "Developer runway: watch below (months)", "runway_ok_months", "0"),
]


@dataclass
class Cell:
    tab: str
    ref: str
    new: object
    mode: str = "exact"          # exact, seed or replace
    old: object = None           # for replace


@dataclass
class Step:
    name: str
    cells: list = field(default_factory=list)
    formats: list = field(default_factory=list)     # (tab, range, pattern), applied when the step adds
    notes: list = field(default_factory=list)
    partial: bool = False       # write the cells that match even if others conflict (the Z:AC rewrite)

    def add(self, tab, ref, new, mode="exact", old=None):
        self.cells.append(Cell(tab, ref, new, mode, old))


# ---------- comparing cell contents ----------

def _norm(v):
    """Contents as read back: formulas without spaces outside strings, numbers as floats, blanks as ""."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    if s.startswith("="):
        parts = re.split(r'("(?:[^"]|"")*")', s)
        return "".join(p if i % 2 else re.sub(r"\s+", "", p) for i, p in enumerate(parts))
    try:
        return float(s) if s.strip() and re.fullmatch(r"-?\d+(\.\d+)?", s.strip()) else s.strip()
    except ValueError:
        return s.strip()


def same(a, b) -> bool:
    a, b = _norm(a), _norm(b)
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-12 * max(1.0, abs(b))
    return a == b


# ---------- the formulas ----------

def _S():
    return settings()["sheet"]


def sig(key, col="E"):
    """Value of a Signals row from another tab."""
    t = _S()["signals_tab"]
    return f'XLOOKUP("{key}",\'{t}\'!$A:$A,\'{t}\'!${col}:${col},"")'


def pnav_range(name, a=None, b=None):
    S = _S()
    c = S["pnav_inputs"][name]
    return f"{c}{a or S['pnav_first_row']}:{c}{b or S['pnav_last_row']}"


def pnav_formulas() -> dict:
    """{column name: formula for row pnav_first_row}."""
    def r(name):
        return pnav_range(name)
    return {
        "buy_below": f'=ARRAYFORMULA(IF(({r("peer_group")}="Royalty/streaming")*({r("nav_per_share")}<>""),'
                     f'{r("nav_per_share")}*{sig("royalty_pnav_median", "G")},""))',
        "royalty_band": f'=ARRAYFORMULA(LET(buy_top,{sig("royalty_pnav_median", "G")},'
                        f'normal_top,{sig("royalty_pnav_median", "H")},'
                        f'IF({r("peer_group")}<>"Royalty/streaming","",IF({r("independent_pnav")}="",'
                        f'"no independent NAV",IF({r("independent_pnav")}<=buy_top,"Buy zone",'
                        f'IF({r("independent_pnav")}<=normal_top,"Normal range","Rich"))))))',
        "ev": f'=ARRAYFORMULA(IF(ISNUMBER({r("mcap")})*ISNUMBER({r("net_cash")}),{r("mcap")}-{r("net_cash")},""))',
        "ev_per_unit": f'=ARRAYFORMULA(IF(ISNUMBER({r("ev")})*ISNUMBER({r("resource_amount")}),'
                       f'IF({r("resource_amount")}>0,{r("ev")}/{r("resource_amount")},""),""))',
        "ev_per_aueq_oz": f'=ARRAYFORMULA(IFERROR(IF({r("ev_per_unit")}="","",'
                          f'IF(({r("resource_unit")}="oz Au")+({r("resource_unit")}="oz AuEq"),{r("ev_per_unit")},'
                          f'IF({r("resource_unit")}="oz AgEq",{r("ev_per_unit")}*{sig("gold_silver_ratio")},""))),""))',
        "months_of_cash": f'=ARRAYFORMULA(IF(ISNUMBER({r("fcf_12m")})*ISNUMBER({r("cash")}),'
                          f'IF({r("fcf_12m")}<0,{r("cash")}/-{r("fcf_12m")}*12,"Cash-generating"),""))',
        "cash_share": f'=ARRAYFORMULA(IF(ISNUMBER({r("cash")})*ISNUMBER({r("mcap")}),'
                      f'IF({r("mcap")}>0,{r("cash")}/{r("mcap")},""),""))',
        "developer_check": f'=ARRAYFORMULA(LET(short,{sig("runway_short_months")},ok,{sig("runway_ok_months")},'
                           f'near,{sig("near_cash_share")},IF({r("peer_group")}<>"Developer","",'
                           f'IF({r("months_of_cash")}="","",IF(ISNUMBER({r("months_of_cash")}),'
                           f'IF({r("months_of_cash")}<short,"Short of cash: financing likely",'
                           f'IF({r("months_of_cash")}<ok,"Watch","Enough cash")),"Enough cash")&'
                           f'IF(ISNUMBER({r("cash_share")}),IF({r("cash_share")}>=near,"; trading near cash",""),""'
                           f')))))',
    }


PNAV_FORMATS = {"buy_below": "0.00", "resource_amount": "#,##0.0", "cash": "#,##0.0", "fcf_12m": "#,##0.0",
                "ev": "#,##0", "ev_per_unit": "#,##0.00", "ev_per_aueq_oz": "#,##0", "months_of_cash": "0.0",
                "cash_share": "0%"}


def cash_flow_change_old(col: str, r: int) -> str:
    """The Sheet's existing PNAV inputs Z:AC formula (cash-flow change at a scenario's prices)."""
    srow = {"Z": 5, "AA": 6, "AB": 7, "AC": 8}[col]
    return (f'=IF($I{r}="","",$H$6*$F{r}*($J{r}*($B${srow}/$M{r}-1)+$K{r}*($C${srow}/$N{r}-1)'
            f'+$L{r}*($D${srow}/$O{r}-1)))')


def cash_flow_change_new(col: str, r: int) -> str:
    """The same with the producers' cost increase, inside the outer IF so developer rows stay blank."""
    S = _S()
    P = S["pnav_inputs"]
    cost_col, cost_row = split_cell(S["pnav_cost_cell"])
    k = f"${cost_col}${cost_row}"
    old = cash_flow_change_old(col, r)
    return (old[:-1] + f'-IF(${P["basis"]}{r}="FCF",$H$6*MAX(0,N(${P["revenue"]}{r})-N(${P["fcf"]}{r}))*{k},0))')


def downside_old() -> str:
    S = _S()
    a, b = S["downside_first_row"], S["downside_last_row"]
    m = "'Metal prices reference'!"
    return (f'=ARRAY_CONSTRAIN(ARRAYFORMULA(IF(N{a}:N{b}="","",IF(M{a}:M{b}<>L{a}:L{b},"helper mismatch",'
            f'N{a}:N{b}+O{a}:O{b}*{m}$H$15+P{a}:P{b}*{m}$H$16+Q{a}:Q{b}*{m}$H$17))), {b - a + 1}, 1)')


def downside_new() -> str:
    S = _S()
    a, b = S["downside_first_row"], S["downside_last_row"]
    R = S["downside_cols"]["cost_base"]
    pt = split_cell(S["pass_through_cell"])
    cost = (f"-'{S['metals_tab']}'!${pt[0]}${pt[1]}*IF(ISNUMBER({R}{a}:{R}{b}),{R}{a}:{R}{b},0)*"
            f"{sig('producer_cost_increase')}")
    old = downside_old()
    i = old.index(f"))), {b - a + 1}, 1)")
    return old[:i] + cost + old[i:]


def timing_formula() -> str:
    S = _S()
    a, b = S["portfolio_first_row"], S["portfolio_last_row"]
    C = S["portfolio_cols"]
    P = S["pnav_inputs"]
    tab, pa, pb = S["pnav_inputs_tab"], S["pnav_first_row"], S["pnav_last_row"]
    B, A, E = (f"{C[k]}{a}:{C[k]}{b}" for k in ("holding", "bucket", "metal"))

    def pcol(name):
        return f"'{tab}'!${P[name]}${pa}:${P[name]}${pb}"

    def piece(item):
        if item.startswith("="):
            return '"' + item[1:].replace('"', '""') + '"'
        if item == "@developer_check":
            return "dev"
        return sig(item, "I")

    SEP = '&" / "&'
    timing = settings()["signals"]["timing"]
    # "Bucket|Metal" entries are tested before plain "Bucket" ones.
    entries = sorted(timing.items(), key=lambda kv: "|" not in kv[0])
    expr = '""'
    for k, items in reversed(entries):
        bucket, _, metal = k.partition("|")
        cond = f'({A}="{bucket}")' + (f'*({E}="{metal}")' if metal else "")
        joined = SEP.join(piece(i) for i in items)
        expr = f"IF({cond},{joined},{expr})"
    return (f'=ARRAYFORMULA(LET(band,XLOOKUP({B},{pcol("holding")},{pcol("royalty_band")},""),'
            f'dev,XLOOKUP({B},{pcol("holding")},{pcol("developer_check")},""),'
            f'IF({B}="","",IF(band<>"",band,{expr}))))')


def portfolio_lookup(name) -> str:
    S = _S()
    a, b = S["portfolio_first_row"], S["portfolio_last_row"]
    P = S["pnav_inputs"]
    tab, pa, pb = S["pnav_inputs_tab"], S["pnav_first_row"], S["pnav_last_row"]
    B = f"{S['portfolio_cols']['holding']}{a}:{S['portfolio_cols']['holding']}{b}"

    def pcol(n):
        return f"'{tab}'!${P[n]}${pa}:${P[n]}${pb}"
    return (f'=ARRAYFORMULA(IF({B}="","",IF(XLOOKUP({B},{pcol("holding")},{pcol("peer_group")},"")="Developer",'
            f'XLOOKUP({B},{pcol("holding")},{pcol(name)},""),"")))')


# ---------- the steps ----------

def fresh_rows() -> dict:
    """{key: row} for a new tab: signals grouped by tier with a blank row between tiers, then the inputs block."""
    S = _S()
    rows, r, tier = {}, S["signals_first_row"], None
    for s in SIGNALS:
        if tier is not None and s.tier != tier:
            r += 1
        tier = s.tier
        rows[s.key] = r
        r += 1
    r += 1
    rows["_inputs_header"] = r
    r += 1
    for key, *_ in INPUTS:
        rows[key] = r
        r += 1
    return rows


def step_signals(sheet) -> Step:
    S = _S()
    tab = S["signals_tab"]
    st = Step(f"Signals tab ({tab})")
    found = {}
    if sheet.has_tab(tab):
        for i, row in enumerate(sheet.read(tab, f"A1:A{S['signals_last_row']}"), start=1):
            if row and str(row[0]).strip():
                found[str(row[0]).strip()] = i
    rows = fresh_rows()
    if found:                                  # an existing tab: find each row by its key; leave the rest alone
        missing = [k for k in rows if not k.startswith("_") and k not in found]
        if missing:
            st.notes.append("keys not on the tab (add the rows by hand, or delete the tab to rebuild): "
                            + ", ".join(missing))
        rows = {k: r for k, r in found.items() if k in rows}
    th, inp = settings()["signals"]["thresholds"], settings()["signals"]["inputs"]
    st.add(tab, "A1", "Market signals: when the framework says to lean in, by tier", "seed")
    st.add(tab, "A2", "Values (E) and dates (F) are written by `python -m minerval prices`; thresholds (G–H) and "
                      "inputs are yours to edit; Status (I) is a formula. Signals from a framework, not advice.", "seed")
    hr = S["signals_first_row"] - 1
    for j, h in enumerate(SIGNALS_HEADERS):
        st.add(tab, f"{num_to_col(j + 1)}{hr}", h, "seed")
    for s in SIGNALS:
        if s.key not in rows:
            continue
        r = rows[s.key]
        st.add(tab, f"A{r}", s.key)
        for c, v in (("B", s.tier), ("C", s.label), ("D", s.unit), ("J", s.note), ("K", s.source)):
            st.add(tab, f"{c}{r}", v, "seed")
        if s.formula:
            st.add(tab, f"E{r}", value_formula(s))
        if s.key in th:
            st.add(tab, f"G{r}", th[s.key][0], "seed")
            st.add(tab, f"H{r}", th[s.key][1], "seed")
        st.add(tab, f"I{r}", status_formula(s, r))
        st.formats.append((tab, f"E{r}", s.fmt))
        if s.key in th:
            st.formats.append((tab, f"G{r}:H{r}", s.fmt))
    if "_inputs_header" in rows:
        st.add(tab, f"A{rows['_inputs_header']}", "Inputs", "seed")
        st.add(tab, f"C{rows['_inputs_header']}", "Yours to edit (key in A, value in E)", "seed")
    for key, label, default, fmt in INPUTS:
        if key not in rows:
            continue
        r = rows[key]
        st.add(tab, f"A{r}", key)
        st.add(tab, f"C{r}", label, "seed")
        if default == "formula":
            st.add(tab, f"E{r}", f'=IF({look("energy_share_of_costs")}="","",'
                                 f'{look("energy_share_of_costs")}*{look("diesel_12m")})')
        elif default is not None:
            st.add(tab, f"E{r}", inp[default], "seed")
        if key == "industry_aisc":
            st.add(tab, f"K{r}", inp["industry_aisc_source"], "seed")
        st.formats.append((tab, f"E{r}", fmt))
    return st


def _spill(st: Step, tab: str, col: str, a: int, b: int, formula: str):
    st.add(tab, f"{col}{a}", formula)
    for r in range(a + 1, b + 1):
        st.add(tab, f"{col}{r}", "")


def research_seeds() -> dict:
    """{sheet_row: [amount, unit, category, "source, date"]} from data/research/pnav_companies.csv."""
    R = pd.read_csv(RESEARCH / "pnav_companies.csv")
    out = {}
    if not set(RESOURCE_COLS) <= set(R.columns):
        return out
    for _, r in R.iterrows():
        if pd.notna(r.resource_amount):
            src = ", ".join(str(x) for x in (r.resource_source, r.resource_date) if pd.notna(x))
            out[int(r.sheet_row)] = [float(r.resource_amount), r.resource_unit, r.resource_category, src]
    return out


def step_pnav(sheet) -> Step:
    S = _S()
    tab, a, b, P = S["pnav_inputs_tab"], S["pnav_first_row"], S["pnav_last_row"], S["pnav_inputs"]
    st = Step(f"{tab}: cost-increase input ({S['pnav_cost_label_cell']}:{S['pnav_cost_cell']}) and columns "
              f"{P['buy_below']}:{P['developer_check']}")
    st.add(tab, S["pnav_cost_label_cell"], "Producer cost increase since the reported period")
    st.add(tab, S["pnav_cost_cell"], f'=XLOOKUP("producer_cost_increase",\'{S["signals_tab"]}\'!$A:$A,'
                                     f'\'{S["signals_tab"]}\'!$E:$E,0)')
    st.formats.append((tab, S["pnav_cost_cell"], "0.0%"))
    for name, h in PNAV_HEADERS.items():
        st.add(tab, f"{P[name]}{a - 1}", h)
    for name, f in pnav_formulas().items():
        _spill(st, tab, P[name], a, b, f)
    for row, vals in research_seeds().items():
        for name, v in zip(("resource_amount", "resource_unit", "resource_category", "resource_source"), vals):
            st.add(tab, f"{P[name]}{row}", v, "seed")
    for name, fmt in PNAV_FORMATS.items():
        st.formats.append((tab, f"{P[name]}{a}:{P[name]}{b}", fmt))
    return st


def step_cash_flow_change() -> Step:
    S = _S()
    tab, a, b = S["pnav_inputs_tab"], S["pnav_first_row"], S["pnav_last_row"]
    st = Step(f"{tab}: Z:AC cash-flow change with the producers' cost increase", partial=True)
    for r in range(a, b + 1):
        for col in ("Z", "AA", "AB", "AC"):
            st.add(tab, f"{col}{r}", cash_flow_change_new(col, r), "replace", cash_flow_change_old(col, r))
    return st


def step_pnav_tab() -> Step:
    S = _S()
    tab, a, b = S["pnav_tab"], S["pnav_tab_first_row"], S["pnav_tab_last_row"]
    C, P = S["pnav_tab_cols"], S["pnav_inputs"]
    src, pa, pb = S["pnav_inputs_tab"], S["pnav_first_row"], S["pnav_last_row"]
    st = Step(f"{tab}: columns {C['royalty_band']}:{C['buy_below']}")
    for name in ("royalty_band", "buy_below"):
        col = C[name]
        st.add(tab, f"{col}{a - 1}", PNAV_TAB_HEADERS[name])
        _spill(st, tab, col, a, b, f"=ARRAYFORMULA('{src}'!{P[name]}{pa}:{P[name]}{pb})")
        for r in range(b + 1, b + 19):                 # the notes below the table must not block the spill
            st.add(tab, f"{col}{r}", "")
    st.formats.append((tab, f"{C['buy_below']}{a}:{C['buy_below']}{b}", "0.00"))
    return st


def step_downside() -> Step:
    S = _S()
    tab, D = S["downside_tab"], S["downside_cols"]
    st = Step(f"{tab}: helper {D['cost_base']} and {D['low_fcf']}{S['downside_first_row']} with the cost increase")
    st.add(tab, f"{D['cost_base']}{S['downside_first_row'] - 1}", DOWNSIDE_COST_HEADER)
    st.add(tab, f"{D['low_fcf']}{S['downside_first_row']}", downside_new(), "replace", downside_old())
    return st


def step_portfolio() -> Step:
    S = _S()
    tab, a, b, C = S["portfolio_tab"], S["portfolio_first_row"], S["portfolio_last_row"], S["portfolio_cols"]
    st = Step(f"{tab}: columns {C['timing']}:{C['months_of_cash']}")
    for name, f in (("timing", timing_formula()), ("ev_per_aueq_oz", portfolio_lookup("ev_per_aueq_oz")),
                    ("months_of_cash", portfolio_lookup("months_of_cash"))):
        st.add(tab, f"{C[name]}{a - 1}", PORTFOLIO_HEADERS[name])
        _spill(st, tab, C[name], a, b, f)
    st.formats.append((tab, f"{C['ev_per_aueq_oz']}{a}:{C['ev_per_aueq_oz']}{b}", "#,##0"))
    st.formats.append((tab, f"{C['months_of_cash']}{a}:{C['months_of_cash']}{b}", "0.0"))
    return st


# ---------- running ----------

def _read_cells(sheet, cells) -> dict:
    """{(tab, ref): current contents (formula text where there is one)}; cells beyond the grid read as ""."""
    out = {}
    by_tab = {}
    for c in cells:
        by_tab.setdefault(c.tab, []).append(c.ref)
    for tab, refs in by_tab.items():
        if not sheet.has_tab(tab):
            out.update({(tab, r): "" for r in refs})
            continue
        width = sheet.col_count(tab)
        pos = [split_cell(r) for r in refs]
        cols = [col_to_num(c) for c, _ in pos]
        rows = [r for _, r in pos]
        c1, c2 = min(cols), min(max(cols), width)
        if c1 > width:
            out.update({(tab, r): "" for r in refs})
            continue
        r1, r2 = min(rows), max(rows)
        grid = sheet.read(tab, f"{num_to_col(c1)}{r1}:{num_to_col(c2)}{r2}", formulas=True)
        for ref, (c, r), cn in zip(refs, pos, cols):
            row = grid[r - r1] if r - r1 < len(grid) else []
            out[(tab, ref)] = row[cn - c1] if cn <= c2 and cn - c1 < len(row) else ""
    return out


def plan(step: Step, current: dict):
    """(writes, conflicts) for a step."""
    writes, conflicts = [], []
    for c in step.cells:
        cur = current.get((c.tab, c.ref), "")
        if c.mode == "seed":
            if _norm(cur) == "" and _norm(c.new) != "":
                writes.append(c)
        elif same(cur, c.new):
            continue
        elif c.mode == "replace" and same(cur, c.old):
            writes.append(c)
        elif c.mode == "exact" and _norm(cur) == "":
            writes.append(c)
        else:
            conflicts.append((c, cur))
    return writes, conflicts


def _short(v, n=70):
    s = str(v)
    return s if len(s) <= n else s[:n] + "…"


def steps(sheet) -> list[Step]:
    return [step_signals(sheet), step_pnav(sheet), step_cash_flow_change(), step_pnav_tab(), step_downside(),
            step_portfolio()]


def run(sheet, dry_run=False, out_dir=None) -> list[str]:
    S = _S()
    out_dir = out_dir or DEST
    ensure(out_dir)
    rep = []
    all_steps = steps(sheet)
    pnav_tab, need_cols = S["pnav_inputs_tab"], col_to_num(S["pnav_inputs"]["developer_check"])

    # 1. Snapshot every range the installer touches, and the values the post-install check compares.
    check_ranges = [(pnav_tab, f"AD{S['pnav_first_row']}:AJ{S['pnav_last_row']}"),
                    (S["downside_tab"], f"K{S['downside_first_row']}:K{S['downside_last_row']}")]
    before_vals = {f"{t}!{r}": sheet.read(t, r) for t, r in check_ranges}
    if not dry_run:
        current_all = _read_cells(sheet, [c for s in all_steps for c in s.cells])
        snap = {f"{t}!{r}": v for (t, r), v in current_all.items()}
        f = out_dir / f"backup-{time.strftime('%Y%m%d-%H%M%S')}.json"
        f.write_text(json.dumps({"cells": snap, "values": before_vals}, indent=0, default=str))
        rep.append(f"Snapshot of {len(snap)} cells saved to {f}.")

    # Grid: the Signals tab and PNAV inputs' new columns
    if not sheet.has_tab(S["signals_tab"]):
        if dry_run:
            rep.append(f"Would create the {S['signals_tab']} tab.")
        else:
            sheet.ensure_tab(S["signals_tab"], rows=150, cols=11)
            rep.append(f"Created the {S['signals_tab']} tab.")
    if sheet.col_count(pnav_tab) < need_cols:
        n = need_cols - sheet.col_count(pnav_tab)
        if dry_run:
            rep.append(f"Would add {n} columns to {pnav_tab} (to {S['pnav_inputs']['developer_check']}).")
        else:
            sheet.ensure_cols(pnav_tab, need_cols)
            rep.append(f"Added {n} columns to {pnav_tab}.")

    # 2-7. The steps, in order
    total = 0
    for st in all_steps:
        cur = _read_cells(sheet, st.cells)
        writes, conflicts = plan(st, cur)
        for n in st.notes:
            rep.append(f"{st.name}: note: {n}")
        if conflicts:
            shown = "; ".join(f"{c.tab}!{c.ref} holds {_short(v)!r}" for c, v in conflicts[:5])
            more = f" (and {len(conflicts) - 5} more)" if len(conflicts) > 5 else ""
            rep.append(f"{st.name}: conflict: {shown}{more} (skipped)")
            if not st.partial:
                continue
        if not writes:
            rep.append(f"{st.name}: already in place (no change)")
            continue
        total += len(writes)
        verb = "would add" if dry_run else "added"
        rep.append(f"{st.name}: {verb} ({len(writes)} cells)")
        if not dry_run:
            sheet.write([(c.tab, c.ref, [[c.new]]) for c in writes])
            # Formats only on a fresh install of the step, so later formatting by hand is kept.
            written = {(c.tab, c.ref) for c in writes}
            fresh = all((c.tab, c.ref) in written for c in st.cells if c.mode != "seed" and _norm(c.new) != "")
            for t, r, pattern in st.formats if fresh else []:
                sheet.number_format(t, r, pattern)

    # Check: with the cost increase at 0%, P/NAV and the Low-scenario cash flows must not move.
    if not dry_run and total:
        moved = []
        for (t, r) in check_ranges:
            after = sheet.read(t, r)
            if json.dumps(after, default=str) != json.dumps(before_vals[f"{t}!{r}"], default=str):
                moved.append(f"{t}!{r}")
        rep.append("Check: " + ("P/NAV AD:AJ and Holdings downside K unchanged." if not moved else
                                "these changed (expected only if the cost increase isn't 0%): " + ", ".join(moved)))
    if dry_run:
        rep.append(f"Dry run: nothing written ({total} cells would be).")
    (out_dir / "report.txt").write_text("\n".join(rep) + "\n")
    return rep
