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
from datetime import date

import pandas as pd

from .config import OUT, RESEARCH, ensure, settings
from .pnav import RESOURCE_COLS
from .sheets import col_to_num, num_to_col, split_cell
from .signals import SIGNALS, VALUE_FORMULAS_V1, aisc_at, aisc_label, look, status_formula, value_formula

DEST = OUT / "layout"

# Headers (row 11 on PNAV inputs, row 1 on P/NAV and Holdings downside, the header row on Model portfolio).
PNAV_HEADERS = {
    "buy_below": "Buy-below price US$ (framework: buy-zone top × the NAV per share used in CU)",
    "royalty_band": "Royalty valuation band (framework; on the P/NAV used in CV: our NAV where valued, else R)",
    "resource_amount": "Resource, millions of the unit",
    "resource_unit": "Resource unit (oz Au, oz AuEq, oz AgEq, lb Cu, lb CuEq)",
    "resource_category": "Resource category",
    "resource_source": "Resource source and date",
    "cash": "Cash $M (cash and short-term investments)",
    "fcf_12m": "Free cash flow $M, last 12 months",
    "ev": "EV $M (market cap − net cash + minority interest in CT)",
    "ev_per_unit": "EV per unit in the ground US$",
    "ev_per_aueq_oz": "EV per gold-equivalent oz US$",
    "months_of_cash": "Months of funding (cash + committed funding in BF, at the last 12 months' burn)",
    "cash_share": "Cash, % of market value",
    "developer_check": "Developer check (funding gap when remaining capex is filled in; else the runway)",
}
# Columns whose header and formula changed after the first install: `setup-sheet` replaces the old ones (below).
UPGRADED = {"months_of_cash", "developer_check", "ev", "buy_below", "royalty_band"}
PNAV_HEADERS_V1 = {"months_of_cash": "Months of cash (at the last 12 months' burn)",
                   "buy_below": "Buy-below price US$ (framework: buy-zone top × independent NAV per share)",
                   "royalty_band": "Royalty valuation band (framework; uses the independent NAV in R, refreshed by "
                                   "hand)",
                   "ev": "EV $M (market cap − net cash)",
                   "developer_check": "Developer check (project loans aren't counted as cash: check undrawn "
                                      "facilities)"}
FINANCING_HEADERS = {
    "committed_funding": "Committed funding not in cash $M (undrawn facilities, escrowed construction cash)",
    "remaining_capex": "Remaining capex to production $M (latest study or company update)",
    "funded_statement": "Company says funded to production (Yes / blank)",
    "financing_source": "Financing sources and dates",
    "months_of_cash_only": "Months of cash, cash only (at the last 12 months' burn)",
    "funding_gap": "Funding gap $M (remaining capex − cash − committed funding)",
    "new_shares": "New shares if the gap is raised in equity, millions (pessimistic: debt and streams dilute less)",
    "dilution": "Dilution from that raise",
    "nav_per_share_after": "NAV per share after the raise US$ (NAV: CU × shares, or study value S + net cash)",
    "pnav_after": "P/NAV after an equity raise for the gap (pessimistic), or funded",
    "resource_reserves": "Reserves, millions of the unit in AU (optional split)",
    "resource_mi": "M&I excluding reserves, millions of the unit (optional split)",
    "resource_inferred": "Inferred, millions of the unit (optional split)",
    "resource_split_source": "Split source and date",
    "weighted_amount": "Weighted resource (weights on the Signals tab: reserves 1, M&I 0.5, inferred 0.2)",
    "weighting_basis": "Weighting basis",
    "ev_per_weighted": "EV per weighted unit US$ (per gold-equivalent oz for gold and silver; per lb for copper)",
    "peer_ev_ratio": "EV per weighted unit ÷ peer-group median (same unit family)",
}
# Financing columns whose header and formula changed after install (own-nav-first: the NAV used in CU).
FINANCING_UPGRADED = {"nav_per_share_after"}
FINANCING_HEADERS_V1 = {"nav_per_share_after": "NAV per share after the raise US$ (NAV: R × shares, or study value S + "
                                               "net cash)"}
FINANCING_INPUTS = ["committed_funding", "remaining_capex", "funded_statement", "financing_source",
                    "resource_reserves", "resource_mi", "resource_inferred", "resource_split_source"]
FINANCING_FORMATS = {"committed_funding": "#,##0.0", "remaining_capex": "#,##0.0", "months_of_cash_only": "0.0",
                     "funding_gap": "#,##0", "new_shares": "#,##0.0", "dilution": "0%", "nav_per_share_after": "0.00",
                     "pnav_after": "0.00", "resource_reserves": "#,##0.0##", "resource_mi": "#,##0.0##",
                     "resource_inferred": "#,##0.0##", "weighted_amount": "#,##0.0##", "ev_per_weighted": "#,##0.00",
                     "peer_ev_ratio": "0.00"}
PNAV_TAB_HEADERS = {"royalty_band": "Royalty band (framework)", "buy_below": "Buy-below price US$"}
OWN_FORMATS = {"pocf": "0.0", "pocf_pctile": "0", "pnav_pctile": "0"}


VALUATION_FORMATS = {"npv_pessimistic": "#,##0", "npv_base": "#,##0", "npv_optimistic": "#,##0", "cf_base": "#,##0",
                     "ev_npv_pessimistic": "0.00", "ev_npv_base": "0.00", "ev_npv_optimistic": "0.00",
                     "fcf_yield": "0.0%", "dilution_15": "0%", "dilution_30": "0%", "capex_to_mcap": "0.00",
                     "buy_below_value": "0.00", "fair_value_price": "0.00"}


MINORITY_HEADER = ("Minority interest $M (partners' stakes in consolidated mines, balance-sheet value; blank "
                   "where none is reported; written by `financials`, added to EV in AZ)")


def valuation_headers() -> dict:
    """PNAV inputs CC:CS headers (valuation by tier, roadmap 6)."""
    V = settings()["valuation"]
    o = V["capex_overrun"]
    by = "written by `financials`"
    h = {"valuation_basis": f"Valuation basis (OCF − sustaining; FCF basis: sustaining not recorded; OCF (royalty); "
                            f"study (risk-adjusted)); {by}"}
    for d in V["decks"]:
        h[f"npv_{d.lower()}"] = (f"NPV, {d} deck US$M (producers: {V['horizon_years']} years, no terminal value; "
                                 f"royalties: a perpetuity; developers: risk-adjusted study NPV); {by}")
    h["cf_base"] = f"Cash flow a year at the {V['base_deck']} deck US$M (producers and royalties); {by}"
    for d in V["decks"]:
        h[f"ev_npv_{d.lower()}"] = f'EV / NPV, {d} deck ("negative NPV" when the NPV is zero or below)'
    h["downside"] = (f"Downside test: EV ≤ the {V['pessimistic_deck']} NPV (producers with costs raised); developers: "
                     f"the financing note (their downside is priced into the buy-below)")
    h["fcf_yield"] = f"Sustaining FCF yield ({V['base_deck']}-deck cash flow ÷ EV)"
    h["dilution_15"] = f"Dilution of a raise at a +{o[0]:.0%} capex overrun (developers); {by}"
    h["dilution_30"] = f"Dilution of a raise at a +{o[-1]:.0%} capex overrun (developers); {by}"
    h["financing_note"] = (f"Financing note (developers): a raise at +{max(o):.0%} that more than doubles the share "
                           f"count; dilution is priced into the buy-below; {by}")
    h["capex_to_mcap"] = "Remaining capex ÷ market cap (developers)"
    h["buy_below_value"] = (f"Buy below US$/share (producers and royalties: the buy level × {V['base_deck']} NPV, no "
                            f"higher than the downside test allows; developers: value per share after a "
                            f"+{max(o):.0%} overrun's financing; levels in [valuation.buy]); {by}")
    h["fair_value_price"] = f"Fair value US$/share (review above; [valuation.buy]); {by}"
    h["valuation_why"] = f"Why there's no NPV or buy-below price; {by}"
    return h


def own_headers() -> dict:
    """PNAV inputs BY:CB headers (royalties against their own history)."""
    C = settings()["royalty_history"]
    return {"pocf": "P/OCF (price × shares ÷ latest annual operating cash flow filed; royalty rows, written by "
                    "`signals`)",
            "pocf_pctile": f"P/OCF percentile, own last {C['years']} years (0 = cheapest; written by `signals`)",
            "pnav_pctile": f"P/NAV percentile, own recorded history (blank until {C['pnav_min_days']} days; "
                           "written by `signals`)",
            "own_band": "Own-history band (P/NAV percentile once recorded, else P/OCF; thresholds on the Signals tab)"}


def sensitivity_headers() -> tuple[str, str]:
    """(PNAV inputs header, P/NAV tab header) for the add-on sensitivity column."""
    pts = settings()["pnav"]["sensitivity_points"]
    return (f"P/NAV: Medium, add-on +{pts:g} points (how much the valuation leans on the risk premium)",
            f"My P/NAV: medium prices, jurisdiction add-on +{pts:g} points")


DOWNSIDE_COST_HEADER = "Helper: cost base $M (revenue − FCF)"
PORTFOLIO_HEADERS = {"timing": "Timing signal (framework)"}
PORTFOLIO_HEADERS["review_level"] = ("Buy multiple: buy below this × the base-deck NPV ([valuation.buy]: producers and "
                                     "developers 0.6, royalties 1.0); a typed value is kept")
PORTFOLIO_HEADERS["buy_below"] = ("Buy below US$/share at N (producers and royalties: (min(N × base NPV, pessimistic "
                                  "NPV) + net cash − minority) ÷ shares; developers: after a +30% overrun's financing)")
SIGNALS_HEADERS = ["Key (code uses it to find rows; can be hidden)", "Tier", "Signal", "Unit", "Value", "As of",
                   "Threshold 1", "Threshold 2", "Status", "What the framework says", "Source"]
INPUTS = [  # key, label, default (None = left blank), number format
    ("industry_aisc", "Industry all-in sustaining cost, $/oz (written by Python from data/research/industry_aisc.csv)",
     "aisc_table", "#,##0"),
    ("producer_cost_increase", "Producer cost increase since their reported 12 months (0% = as reported)",
     "producer_cost_increase", "0.0%"),
    ("energy_share_of_costs", "Energy's share of producers' costs (your estimate)", None, "0%"),
    ("implied_cost_increase", "What the diesel move implies if energy is that share of costs", "formula", "0.0%"),
    ("near_cash_share", "Developer 'trading near cash' when cash is at least this share of market value",
     "near_cash_share", "0%"),
    ("runway_short_months", "Developer runway: short of cash below (months)", "runway_short_months", "0"),
    ("runway_ok_months", "Developer runway: watch below (months)", "runway_ok_months", "0"),
    ("raise_discount", "Developer raise: discount to today's price for an equity raise (typical bought deal)",
     "raise_discount", "0%"),
    ("resource_weight_reserves", "EV per weighted unit: weight of a reserve ounce", "resource_weight_reserves",
     "0.00"),
    ("resource_weight_mi", "EV per weighted unit: weight of an M&I ounce (excluding reserves)", "resource_weight_mi",
     "0.00"),
    ("resource_weight_inferred", "EV per weighted unit: weight of an inferred ounce", "resource_weight_inferred",
     "0.00"),
]


@dataclass
class Cell:
    tab: str
    ref: str
    new: object
    mode: str = "exact"          # exact, seed, replace or upgrade (empty, the old content or the new one)
    old: object = None           # for replace and upgrade


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
        # Strings ("...") and quoted tab names ('...') are kept as they are, except that Google drops the
        # quotes from simple tab names ('Signals'!A1 -> Signals!A1); spaces elsewhere are dropped.
        out = []
        for p in re.split(r'("(?:[^"]|"")*"|\'(?:[^\']|\'\')*\')', s):
            if p.startswith('"'):
                out.append(p)
            elif p.startswith("'"):
                out.append(p[1:-1] if re.fullmatch(r"'[A-Za-z_][A-Za-z0-9_]*'", p) else p)
            else:
                out.append(re.sub(r"\s+", "", p))
        return "".join(out)
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
        "buy_below": f'=ARRAYFORMULA(IF(({r("peer_group")}="Royalty/streaming")*ISNUMBER({r("nav_used")}),'
                     f'IF({r("nav_used")}>0,{r("nav_used")}*{sig("royalty_pnav_median", "G")},""),""))',
        "royalty_band": f'=ARRAYFORMULA(LET(buy_top,{sig("royalty_pnav_median", "G")},'
                        f'normal_top,{sig("royalty_pnav_median", "H")},pnav,{r("pnav_used")},'
                        f'IF({r("peer_group")}<>"Royalty/streaming","",IF(pnav="","no NAV",IF(ISNUMBER(pnav),'
                        f'IF(pnav<=buy_top,"Buy zone",IF(pnav<=normal_top,"Normal range","Rich")),pnav)))))',
        "ev": f'=ARRAYFORMULA(IF(ISNUMBER({r("mcap")})*ISNUMBER({r("net_cash")}),'
              f'{r("mcap")}-{r("net_cash")}+{n(r("minority"))},""))',
        "ev_per_unit": f'=ARRAYFORMULA(IF(ISNUMBER({r("ev")})*ISNUMBER({r("resource_amount")}),'
                       f'IF({r("resource_amount")}>0,{r("ev")}/{r("resource_amount")},""),""))',
        "ev_per_aueq_oz": f'=ARRAYFORMULA(IFERROR(IF({r("ev_per_unit")}="","",'
                          f'IF(({r("resource_unit")}="oz Au")+({r("resource_unit")}="oz AuEq"),{r("ev_per_unit")},'
                          f'IF({r("resource_unit")}="oz AgEq",{r("ev_per_unit")}*{sig("gold_silver_ratio")},""))),""))',
        "months_of_cash": f'=ARRAYFORMULA(IF(ISNUMBER({r("fcf_12m")})*ISNUMBER({r("cash")}),'
                          f'IF({r("fcf_12m")}<0,({r("cash")}+{n(r("committed_funding"))})/-{r("fcf_12m")}*12,'
                          f'"Cash-generating"),""))',
        "cash_share": f'=ARRAYFORMULA(IF(ISNUMBER({r("cash")})*ISNUMBER({r("mcap")}),'
                      f'IF({r("mcap")}>0,{r("cash")}/{r("mcap")},""),""))',
        "developer_check": f'=ARRAYFORMULA(LET(short,{sig("runway_short_months")},ok,{sig("runway_ok_months")},'
                           f'near,{sig("near_cash_share")},gap,{r("funding_gap")},moc,{r("months_of_cash")},'
                           f'txt,IF({r("peer_group")}<>"Developer","",IF(ISNUMBER(gap),IF(gap<=0,"Fully funded",'
                           f'"Funding gap $"&TEXT(gap,"#,##0")&"M"),IF({r("funded_statement")}="Yes",'
                           f'"Funded to production (company says)",IF(moc="","",IF(ISNUMBER(moc),'
                           f'IF(moc<short,"Short of cash: financing likely",IF(moc<ok,"Watch","Enough cash")),'
                           f'"Enough cash"))))),IF(txt="","",txt&IF(ISNUMBER({r("cash_share")}),'
                           f'IF({r("cash_share")}>=near,"; trading near cash",""),""))))',
    }


def own_band_formula() -> str:
    """PNAV inputs CB: the same rule as royalty_history.band()."""
    def r(name):
        return pnav_range(name)
    nav, ocf = r("pnav_pctile"), r("pocf_pctile")
    return (f'=ARRAYFORMULA(LET(lo,{sig("royalty_own_pctile_median", "G")},hi,{sig("royalty_own_pctile_median", "H")},'
            f'p,IF(ISNUMBER({nav}),{nav},IF(ISNUMBER({ocf}),{ocf},"")),'
            f'IF({r("peer_group")}<>"Royalty/streaming","",IF(NOT(ISNUMBER(p)),"",'
            f'IF(p<=lo,"Cheap for itself",IF(p>=hi,"Expensive for itself","Normal for itself"))&" ("&'
            f'IF(ISNUMBER({nav}),"P/NAV","P/OCF")&" percentile "&TEXT(p,"0")&")"))))')


def n(rng: str) -> str:
    """A range's numbers with blanks and text as 0, element by element (N() takes only the first cell)."""
    return f"IF(ISNUMBER({rng}),{rng},0)"


def pnav_formulas_v1() -> dict:
    """The first install's formulas for the UPGRADED columns, which `setup-sheet` replaces."""
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
        "months_of_cash": f'=ARRAYFORMULA(IF(ISNUMBER({r("fcf_12m")})*ISNUMBER({r("cash")}),'
                          f'IF({r("fcf_12m")}<0,{r("cash")}/-{r("fcf_12m")}*12,"Cash-generating"),""))',
        "developer_check": f'=ARRAYFORMULA(LET(short,{sig("runway_short_months")},ok,{sig("runway_ok_months")},'
                           f'near,{sig("near_cash_share")},IF({r("peer_group")}<>"Developer","",'
                           f'IF({r("months_of_cash")}="","",IF(ISNUMBER({r("months_of_cash")}),'
                           f'IF({r("months_of_cash")}<short,"Short of cash: financing likely",'
                           f'IF({r("months_of_cash")}<ok,"Watch","Enough cash")),"Enough cash")&'
                           f'IF(ISNUMBER({r("cash_share")}),IF({r("cash_share")}>=near,"; trading near cash",""),""'
                           f')))))',
    }


def financing_formulas(nav_col: str = "nav_used") -> dict:
    """{column name: formula for row pnav_first_row} for the developer financing and weighted-resource columns. The
    NAV before a raise is the NAV per share used (CU) × shares, else the study value + net cash."""
    def r(name):
        return pnav_range(name)
    dev = f'{r("peer_group")}<>"Developer"'
    shares = f'{r("mcap")}/{r("price")}'
    nav = (f'IF(ISNUMBER({r(nav_col)}),{r(nav_col)}*{shares},'
           f'IF(ISNUMBER({r("study_value")}),{r("study_value")}+{n(r("net_cash"))},""))')
    gap, new = r("funding_gap"), r("new_shares")
    raise_ = f"IF({gap}>0,{gap},0)"
    res, mi, inf = r("resource_reserves"), r("resource_mi"), r("resource_inferred")
    anysplit = f"(ISNUMBER({res})+ISNUMBER({mi})+ISNUMBER({inf}))"
    amt, cat, unit = r("resource_amount"), r("resource_category"), r("resource_unit")
    wr, wm, wi = (sig(f"resource_weight_{k}") for k in ("reserves", "mi", "inferred"))
    wt = r("weighted_amount")
    pa, pb = _S()["pnav_first_row"], _S()["pnav_last_row"]

    def col(name):
        c = _S()["pnav_inputs"][name]
        return f"${c}${pa}:${c}${pb}"
    return {
        "months_of_cash_only": f'=ARRAYFORMULA(IF(ISNUMBER({r("fcf_12m")})*ISNUMBER({r("cash")}),'
                               f'IF({r("fcf_12m")}<0,{r("cash")}/-{r("fcf_12m")}*12,"Cash-generating"),""))',
        "funding_gap": f'=ARRAYFORMULA(IF({dev},"",IF(ISNUMBER({r("remaining_capex")}),'
                       f'{r("remaining_capex")}-{n(r("cash"))}-{n(r("committed_funding"))},"")))',
        "new_shares": f'=ARRAYFORMULA(IFERROR(IF(ISNUMBER({gap})*({r("price")}>0),'
                      f'{raise_}/({r("price")}*(1-{sig("raise_discount")})),""),""))',
        "dilution": f'=ARRAYFORMULA(IFERROR(IF(ISNUMBER({new}),{new}/({shares}),""),""))',
        "nav_per_share_after": f'=ARRAYFORMULA(IFERROR(IF(ISNUMBER({new}),({nav}+{raise_})/({shares}+{new}),""),""))',
        "pnav_after": f'=ARRAYFORMULA(IF({dev},"",IF(ISNUMBER({gap}),IF({gap}<=0,"Fully funded",'
                      f'IFERROR({r("price")}/{r("nav_per_share_after")},"")),'
                      f'IF({r("funded_statement")}="Yes","Funded (company says)",""))))',
        "weighted_amount": f'=ARRAYFORMULA(IF({anysplit},{n(res)}*{wr}+{n(mi)}*{wm}+{n(inf)}*{wi},'
                           f'IF(ISNUMBER({amt}),IF({cat}="Reserves",{amt}*{wr},IF({cat}="Measured & indicated",'
                           f'{amt}*{wm},IF({cat}="Inferred",{amt}*{wi},""))),"")))',
        "weighting_basis": f'=ARRAYFORMULA(IF({anysplit},"Split"&IF(ISNUMBER({res}),"","; no reserves")&'
                           f'IF(ISNUMBER({mi}),"","; no M&I")&IF(ISNUMBER({inf}),"","; no inferred"),'
                           f'IF(ISNUMBER({amt}),IF(({cat}="Reserves")+({cat}="Measured & indicated")+'
                           f'({cat}="Inferred"),"From category: "&{cat},"Needs a split ("&{cat}&")"),"")))',
        "ev_per_weighted": f'=ARRAYFORMULA(IFERROR(IF(ISNUMBER({r("ev")})*ISNUMBER({wt}),IF({wt}>0,'
                           f'IF(({unit}="oz Au")+({unit}="oz AuEq"),{r("ev")}/{wt},'
                           f'IF({unit}="oz AgEq",{r("ev")}/{wt}*{sig("gold_silver_ratio")},'
                           f'IF(LEFT({unit},2)="lb",{r("ev")}/{wt},""))),""),""),""))',
        "peer_ev_ratio": f'=MAP({r("peer_group")},{unit},{r("ev_per_weighted")},LAMBDA(p,u,v,IF(NOT(ISNUMBER(v)),"",'
                         f'IFERROR(v/MEDIAN(FILTER({col("ev_per_weighted")},{col("peer_group")}=p,'
                         f'LEFT({col("resource_unit")},2)=LEFT(u,2),ISNUMBER({col("ev_per_weighted")}))),""))))',
    }


def financing_formulas_v1() -> dict:
    """The installed formulas for FINANCING_UPGRADED before own-nav-first (the NAV from the independent NAV in R)."""
    return {k: v for k, v in financing_formulas("nav_per_share").items() if k in FINANCING_UPGRADED}


NAV_USED_HEADERS = {
    "nav_used": "NAV per share used US$: ours ((CE + E − CT) ÷ shares) where CE has a base-deck NPV, else the "
                "independent NAV in R",
    "pnav_used": "P/NAV used: price ÷ CU (a NAV at or below zero shows \"negative NAV\"); developers without one: "
                 "market cap ÷ (study value S + net cash)",
}
NAV_USED_FORMATS = {"nav_used": "0.00", "pnav_used": "0.00"}


def nav_used_formulas() -> dict:
    """PNAV inputs CU:CV (own-nav-first): our NAV per share where the valuation has a base-deck NPV, else R; and the
    P/NAV on it. Our valuation takes precedence over an independent value (the user, Nov 23, 2026)."""
    def r(name):
        return pnav_range(name)
    ce, e, c, d, cu, s = r("npv_base"), r("net_cash"), r("price"), r("mcap"), r("nav_used"), r("study_value")
    return {
        "nav_used": f'=ARRAYFORMULA(IFERROR(IF(ISNUMBER({ce})*ISNUMBER({e})*ISNUMBER({c})*ISNUMBER({d}),'
                    f'IF(({c}>0)*({d}>0),({ce}+{e}-{n(r("minority"))})*{c}/{d},""),'
                    f'IF(ISNUMBER({r("nav_per_share")}),{r("nav_per_share")},"")),""))',
        "pnav_used": f'=ARRAYFORMULA(IFERROR(IF(ISNUMBER({cu}),IF({cu}>0,{c}/{cu},"negative NAV"),'
                     f'IF(ISNUMBER({s}),{d}/({s}+{e}),"")),""))',
    }


def sensitivity_formula() -> str:
    """Today's P/NAV (AD) with the discount rate (U) raised by [pnav] sensitivity_points."""
    def r(c):
        S = _S()
        return f"{c}{S['pnav_first_row']}:{c}{S['pnav_last_row']}"
    pts = settings()["pnav"]["sensitivity_points"] / 100
    return (f'=ARRAYFORMULA(IF({pnav_range("basis")}="","",IFERROR(LET(rate,{r("U")}+{pts:g},'
            f'nav,({r("Y")}+{r("Z")})*(1-(1+rate)^-{r("V")})/rate+{pnav_range("net_cash")},'
            f'IF(nav<=0,"negative",IF({pnav_range("mcap")}/nav>20,">20",{pnav_range("mcap")}/nav))),"")))')


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


def timing_formula(own: bool = True) -> str:
    """Model portfolio R. Royalty rows show the framework band, then (own=True) their own-history band."""
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
    if not own:                             # the first install's formula, which `setup-sheet` upgrades
        return (f'=ARRAYFORMULA(LET(band,XLOOKUP({B},{pcol("holding")},{pcol("royalty_band")},""),'
                f'dev,XLOOKUP({B},{pcol("holding")},{pcol("developer_check")},""),'
                f'IF({B}="","",IF(band<>"",band,{expr}))))')
    return (f'=ARRAYFORMULA(LET(band,XLOOKUP({B},{pcol("holding")},{pcol("royalty_band")},""),'
            f'own,XLOOKUP({B},{pcol("holding")},{pcol("own_band")},""),'
            f'dev,XLOOKUP({B},{pcol("holding")},{pcol("developer_check")},""),'
            f'IF({B}="","",IF(band<>"",band&IF(own<>""," / "&own,""),{expr}))))')


def _portfolio_refs():
    S = _S()
    a, b, C, P = S["portfolio_first_row"], S["portfolio_last_row"], S["portfolio_cols"], S["pnav_inputs"]
    tab, pa, pb = S["pnav_inputs_tab"], S["pnav_first_row"], S["pnav_last_row"]

    def rng(k):
        return f"{C[k]}{a}:{C[k]}{b}"

    def look(name):
        return f"XLOOKUP({rng('holding')},'{tab}'!${P['holding']}${pa}:${P['holding']}${pb},'{tab}'!${P[name]}${pa}:" \
               f"${P[name]}${pb},\"\")"
    return rng, look


def portfolio_buy_below_formula() -> str:
    """Model portfolio S: the buy-below price (US$/share) at the row's buy multiple N, as screen.buy_below_at: the
    valuation's own price (PNAV inputs CQ) at the rule's multiple; a typed multiple re-priced from CC:CE, E, CT and
    CN (shares = market cap ÷ price). Blank without an NPV, a price or a positive value."""
    from .screen import ROYALTY_BASIS, STUDY_BASIS
    rng, look = _portfolio_refs()
    buy = settings()["valuation"]["buy"]
    rule = (f'IF(basis="{STUDY_BASIS}",{buy["developer"]["buy"]:g},IF(basis="{ROYALTY_BASIS}",{buy["royalty"]["buy"]:g},'
            f'{buy["producer"]["buy"]:g}))')                  # 1, not 1.0: as Sheets stores it
    typed = (f'IF(basis="{STUDY_BASIS}",IF(ISNUMBER(cq),cq+(lvl-rule)*base/(shares*(1+IF(ISNUMBER(dil),dil,0))),""),'
             f'IF(ISNUMBER(pess),(IF(lvl*base<pess,lvl*base,pess)+IF(ISNUMBER(nc),nc,0)-IF(ISNUMBER(mi),mi,0))'
             f'/shares,""))')
    return (f'=ARRAYFORMULA(LET(basis,{look("valuation_basis")},base,{look("npv_base")},'
            f'pess,{look("npv_pessimistic")},nc,{look("net_cash")},mi,{look("minority")},dil,{look("dilution_30")},'
            f'cq,{look("buy_below_value")},shares,{look("mcap")}/{look("price")},lvl,{rng("review_level")},'
            f'rule,{rule},v,IF(ABS(lvl-rule)<0.000001,cq,IF(ISNUMBER(base),IF(base>0,{typed},""),"")),'
            f'IF(({rng("holding")}="")+({rng("review_level")}=""),"",IF(ISNUMBER(v),IF(v>0,v,""),""))))')


def portfolio_status_formula() -> str:
    """Model portfolio O, as screen.status: "No NPV: <why>"; "Fails downside test"; "Buy: below US$<S>" (with the
    listing currency's price from Holdings S and V); "Above fair value: review"; "Hold". Blank where N is blank
    (physical metal rows)."""
    from .screen import DOWNSIDE_FAILS
    S = _S()
    rng, look = _portfolio_refs()
    a, b, C = S["portfolio_first_row"], S["portfolio_last_row"], S["portfolio_cols"]
    h, last = S["holdings_tab"], S["last_row"]
    D = rng("ticker")
    fails = "+".join(f'(why="{w}")' for w in DOWNSIDE_FAILS)
    return (f'=ARRAYFORMULA(LET(px,{look("price")},fair,{look("fair_value_price")},why,{look("valuation_why")},'
            f'bb,{C["buy_below"]}{a}:{C["buy_below"]}{b},cur,XLOOKUP({D},{h}!$O$2:$O${last},{h}!$S$2:$S${last},""),'
            f'fx,XLOOKUP({D},{h}!$O$2:$O${last},{h}!$V$2:$V${last},""),'
            f'IF({rng("review_level")}="","",IF(NOT(ISNUMBER(bb)),IF({fails}>0,"Fails downside test",'
            f'"No NPV: "&IF(why="","not valued",why)),IF(NOT(ISNUMBER(px)),"Hold",IF(px<=bb,"Buy: below US$"&'
            f'TEXT(bb,"#,##0.00")&IF((cur<>"")*(cur<>"USD")*ISNUMBER(fx)," ("&cur&" "&TEXT(bb/fx,"#,##0.00")&")",""),'
            f'IF(ISNUMBER(fair)*(px>=fair),"Above fair value: review","Hold")))))))')


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


def signal_inserts(sheet) -> list[tuple[str, int]]:
    """(key, row) for each signal or input missing from an existing Signals tab: a new row just below the key before
    it (SIGNALS order, then INPUTS), so it lands in its tier or in the inputs block. Rows are given as they'll be once
    the earlier inserts are done."""
    S = _S()
    tab = S["signals_tab"]
    if not sheet.has_tab(tab):
        return []
    found = {}
    for i, row in enumerate(sheet.read(tab, f"A1:A{S['signals_last_row']}"), start=1):
        if row and str(row[0]).strip():
            found[str(row[0]).strip()] = i
    if not any(s.key in found for s in SIGNALS):
        return []
    out, prev = [], None
    for key in [s.key for s in SIGNALS] + [k for k, *_ in INPUTS]:
        if key not in found:
            at = (found[prev] if prev else S["signals_first_row"] - 1) + 1
            found = {k: r + 1 if r >= at else r for k, r in found.items()}
            found[key] = at
            out.append((key, at))
        prev = key
    return out


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
            old = VALUE_FORMULAS_V1.get(s.key)
            st.add(tab, f"E{r}", value_formula(s), *(("upgrade", old()) if old else ()))
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
        elif default == "aisc_table":
            a = aisc_at(date.today())
            if a:
                st.add(tab, f"E{r}", a["value"], "seed")
                st.add(tab, f"F{r}", aisc_label(a), "seed")
                st.add(tab, f"K{r}", "World Gold Council, Gold Demand Trends (Metals Focus data)", "seed")
        elif default is not None:
            st.add(tab, f"E{r}", inp[default], "seed")
        st.formats.append((tab, f"E{r}", fmt))
    return st


def valuation_formulas() -> dict:
    """{column name: formula for row pnav_first_row} for the valuation columns that move with today's EV."""
    def r(name):
        return pnav_range(name)
    ev = r("ev")
    out = {}
    for d in settings()["valuation"]["decks"]:
        npv = r(f"npv_{d.lower()}")
        out[f"ev_npv_{d.lower()}"] = (f'=ARRAYFORMULA(IF(ISNUMBER({npv}),IF({npv}<=0,"negative NPV",'
                                      f'IFERROR({ev}/{npv},"")),""))')
    pess = r(f"npv_{settings()['valuation']['pessimistic_deck'].lower()}")
    out["downside"] = (f'=ARRAYFORMULA(IF({r("basis")}="",{r("financing_note")},IF(ISNUMBER({pess})*ISNUMBER({ev}),'
                       f'IF(({pess}>0)*({ev}<={pess}),"Passes","Fails"),"")))')
    out["fcf_yield"] = (f'=ARRAYFORMULA(IFERROR(IF(ISNUMBER({r("cf_base")})*ISNUMBER({ev}),'
                        f'IF({ev}>0,{r("cf_base")}/{ev},""),""),""))')
    out["capex_to_mcap"] = (f'=ARRAYFORMULA(IFERROR(IF(ISNUMBER({r("remaining_capex")})*ISNUMBER({r("mcap")}),'
                            f'IF({r("mcap")}>0,{r("remaining_capex")}/{r("mcap")},""),""),""))')
    return out


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
    v1 = pnav_formulas_v1()
    for name, h in PNAV_HEADERS.items():
        if name in UPGRADED:
            st.add(tab, f"{P[name]}{a - 1}", h, "upgrade", PNAV_HEADERS_V1[name])
        else:
            st.add(tab, f"{P[name]}{a - 1}", h)
    for name, f in pnav_formulas().items():
        _spill(st, tab, P[name], a, b, f)
        if name in UPGRADED:
            st.cells[-(b - a + 1)] = Cell(tab, f"{P[name]}{a}", f, "upgrade", v1[name])
    for row, vals in research_seeds().items():
        for name, v in zip(("resource_amount", "resource_unit", "resource_category", "resource_source"), vals):
            st.add(tab, f"{P[name]}{row}", v, "seed")
    for name, fmt in PNAV_FORMATS.items():
        st.formats.append((tab, f"{P[name]}{a}:{P[name]}{b}", fmt))
    return st


def financing_seeds() -> dict:
    """{(sheet_row, column name): value} for the financing and resource-split inputs in pnav_companies.csv."""
    R = pd.read_csv(RESEARCH / "pnav_companies.csv")
    cols = {"committed_funding": "committed_funding_usd_m", "remaining_capex": "remaining_capex_usd_m",
            "funded_statement": "funded_per_company", "financing_source": "financing_source",
            "resource_reserves": "resource_reserves", "resource_mi": "resource_mi_excl_reserves",
            "resource_inferred": "resource_inferred", "resource_split_source": "resource_split_source"}
    out = {}
    for _, r in R.iterrows():
        for name, c in cols.items():
            if c in R.columns and pd.notna(r[c]) and str(r[c]).strip():
                v = r[c]
                out[(int(r.sheet_row), name)] = float(v) if isinstance(v, (int, float)) else str(v)
    return out


def step_financing() -> Step:
    S = _S()
    tab, a, b, P = S["pnav_inputs_tab"], S["pnav_first_row"], S["pnav_last_row"], S["pnav_inputs"]
    st = Step(f"{tab}: developer financing and weighted resource columns "
              f"{P['committed_funding']}:{P['peer_ev_ratio']}")
    v1 = financing_formulas_v1()
    for name, h in FINANCING_HEADERS.items():
        if name in FINANCING_UPGRADED:
            st.add(tab, f"{P[name]}{a - 1}", h, "upgrade", FINANCING_HEADERS_V1[name])
        else:
            st.add(tab, f"{P[name]}{a - 1}", h)
    for name, f in financing_formulas().items():
        _spill(st, tab, P[name], a, b, f)
        if name in FINANCING_UPGRADED:
            st.cells[-(b - a + 1)] = Cell(tab, f"{P[name]}{a}", f, "upgrade", v1[name])
    for (row, name), v in financing_seeds().items():
        st.add(tab, f"{P[name]}{row}", v, "seed")
    for name, fmt in FINANCING_FORMATS.items():
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


def step_sensitivity() -> Step:
    """PNAV inputs BX (P/NAV with the add-on raised) and its copy on the P/NAV tab (W)."""
    S = _S()
    tab, a, b, P = S["pnav_inputs_tab"], S["pnav_first_row"], S["pnav_last_row"], S["pnav_inputs"]
    ptab, pa, pb, col = S["pnav_tab"], S["pnav_tab_first_row"], S["pnav_tab_last_row"], S["pnav_tab_cols"]["pnav_addon_up"]
    h_in, h_tab = sensitivity_headers()
    st = Step(f"{tab}: column {P['pnav_addon_up']} and {ptab}: column {col} (P/NAV with a higher add-on)")
    st.add(tab, f"{P['pnav_addon_up']}{a - 1}", h_in)
    _spill(st, tab, P["pnav_addon_up"], a, b, sensitivity_formula())
    st.add(ptab, f"{col}{pa - 1}", h_tab)
    _spill(st, ptab, col, pa, pb, f"=ARRAYFORMULA('{tab}'!{P['pnav_addon_up']}{a}:{P['pnav_addon_up']}{b})")
    for r in range(pb + 1, pb + 19):                    # the notes below the table must not block the spill
        st.add(ptab, f"{col}{r}", "")
    st.formats += [(tab, f"{P['pnav_addon_up']}{a}:{P['pnav_addon_up']}{b}", "0.00"),
                   (ptab, f"{col}{pa}:{col}{pb}", "0.00")]
    return st


def step_own_history() -> Step:
    """PNAV inputs BY:CA (written by `signals`: headers only here) and CB (the own-history band)."""
    S = _S()
    tab, a, b, P = S["pnav_inputs_tab"], S["pnav_first_row"], S["pnav_last_row"], S["pnav_inputs"]
    st = Step(f"{tab}: columns {P['pocf']}:{P['own_band']} (royalties against their own history)")
    for name, h in own_headers().items():
        st.add(tab, f"{P[name]}{a - 1}", h)
    _spill(st, tab, P["own_band"], a, b, own_band_formula())
    for name, fmt in OWN_FORMATS.items():
        st.formats.append((tab, f"{P[name]}{a}:{P[name]}{b}", fmt))
    return st


def step_valuation() -> Step:
    """PNAV inputs CC:CS (valuation by tier): headers for the columns `financials` writes, spill formulas for the
    ones over today's EV."""
    S = _S()
    tab, a, b, P = S["pnav_inputs_tab"], S["pnav_first_row"], S["pnav_last_row"], S["pnav_inputs"]
    st = Step(f"{tab}: columns {P['valuation_basis']}:{P['valuation_why']} (valuation by tier)")
    for name, h in valuation_headers().items():
        st.add(tab, f"{P[name]}{a - 1}", h)
    for name, f in valuation_formulas().items():
        _spill(st, tab, P[name], a, b, f)
    for name, fmt in VALUATION_FORMATS.items():
        st.formats.append((tab, f"{P[name]}{a}:{P[name]}{b}", fmt))
    return st


def step_minority() -> Step:
    """PNAV inputs CT: the header for minority interest, which `financials` writes and EV in AZ adds."""
    S = _S()
    tab, a, b, P = S["pnav_inputs_tab"], S["pnav_first_row"], S["pnav_last_row"], S["pnav_inputs"]
    st = Step(f"{tab}: column {P['minority']} (minority interest, added to EV in {P['ev']})")
    st.add(tab, f"{P['minority']}{a - 1}", MINORITY_HEADER)
    st.formats.append((tab, f"{P['minority']}{a}:{P['minority']}{b}", "#,##0.0"))
    return st


def step_nav_used() -> Step:
    """PNAV inputs CU:CV (own-nav-first): the NAV per share and P/NAV used, spill formulas over CE, E, CT and R."""
    S = _S()
    tab, a, b, P = S["pnav_inputs_tab"], S["pnav_first_row"], S["pnav_last_row"], S["pnav_inputs"]
    st = Step(f"{tab}: columns {P['nav_used']}:{P['pnav_used']} (NAV per share and P/NAV used: ours first)")
    for name, h in NAV_USED_HEADERS.items():
        st.add(tab, f"{P[name]}{a - 1}", h)
    for name, f in nav_used_formulas().items():
        _spill(st, tab, P[name], a, b, f)
    for name, fmt in NAV_USED_FORMATS.items():
        st.formats.append((tab, f"{P[name]}{a}:{P[name]}{b}", fmt))
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
    st = Step(f"{tab}: column {C['timing']} (timing signal)")
    st.add(tab, f"{C['timing']}{a - 1}", PORTFOLIO_HEADERS["timing"])
    _spill(st, tab, C["timing"], a, b, timing_formula())
    st.cells[-(b - a + 1)] = Cell(tab, f"{C['timing']}{a}", timing_formula(), "upgrade", timing_formula(own=False))
    return st


def step_portfolio_status() -> Step:
    """Screen revision 2: the buy multiple's header (N), the status (O) and the buy-below price at N (S)."""
    S = _S()
    tab, a, b, C = S["portfolio_tab"], S["portfolio_first_row"], S["portfolio_last_row"], S["portfolio_cols"]
    st = Step(f"{tab}: {C['review_level']} buy multiple, {C['status']} status, {C['buy_below']} buy-below price")
    st.add(tab, f"{C['review_level']}{a - 1}", PORTFOLIO_HEADERS["review_level"])
    _spill(st, tab, C["status"], a, b, portfolio_status_formula())
    st.add(tab, f"{C['buy_below']}{a - 1}", PORTFOLIO_HEADERS["buy_below"])
    _spill(st, tab, C["buy_below"], a, b, portfolio_buy_below_formula())
    st.formats.append((tab, f"{C['buy_below']}{a}:{C['buy_below']}{b}", "0.00"))
    return st


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
        elif c.mode == "upgrade" and (_norm(cur) == "" or same(cur, c.old)):
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
    return [step_signals(sheet), step_pnav(sheet), step_financing(), step_cash_flow_change(), step_pnav_tab(),
            step_sensitivity(), step_own_history(), step_valuation(), step_minority(), step_nav_used(), step_downside(), step_portfolio(),
            step_portfolio_status()]


def run(sheet, dry_run=False, out_dir=None) -> list[str]:
    S = _S()
    out_dir = out_dir or DEST
    ensure(out_dir)
    rep = []
    # New signals on an existing Signals tab: insert their rows first, so the steps below find them by key.
    inserts = signal_inserts(sheet)
    if inserts:
        names = ", ".join(f"{k} (row {r})" for k, r in inserts)
        if dry_run:
            rep.append(f"Would insert rows on the {S['signals_tab']} tab for new signals and inputs: {names}.")
        else:
            for key, r in inserts:
                sheet.insert_rows(S["signals_tab"], r)
                sheet.write([(S["signals_tab"], f"A{r}", [[key]])])        # the key, so the step below finds it
                sig_ = next((x for x in SIGNALS if x.key == key), None)
                if sig_:
                    sheet.number_formats([(S["signals_tab"], f"E{r}", sig_.fmt),
                                          (S["signals_tab"], f"G{r}:H{r}", sig_.fmt)])
                else:
                    fmt = next(f for k, _, _, f in INPUTS if k == key)
                    sheet.number_formats([(S["signals_tab"], f"E{r}", fmt)])
            rep.append(f"Inserted rows on the {S['signals_tab']} tab for new signals and inputs: {names}.")
    all_steps = steps(sheet)
    pnav_tab = S["pnav_inputs_tab"]
    last_col = max(S["pnav_inputs"].values(), key=col_to_num)
    need_cols = col_to_num(last_col)

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
            rep.append(f"Would add {n} columns to {pnav_tab} (to {last_col}).")
        else:
            sheet.ensure_cols(pnav_tab, need_cols)
            rep.append(f"Added {n} columns to {pnav_tab}.")
    ptab, plast = S["portfolio_tab"], max(S["portfolio_cols"].values(), key=lambda c: col_to_num(c) if c.isalpha()
                                                                         else 0)
    if sheet.has_tab(ptab) and sheet.col_count(ptab) < col_to_num(plast):
        n = col_to_num(plast) - sheet.col_count(ptab)
        if dry_run:
            rep.append(f"Would add {n} columns to {ptab} (to {plast}).")
        else:
            sheet.ensure_cols(ptab, col_to_num(plast))
            rep.append(f"Added {n} columns to {ptab}.")

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
            if fresh:
                sheet.number_formats(st.formats)

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
