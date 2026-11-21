"""Developers and committed growth projects: study cash flows rebuilt at our discount rate and prices (roadmap 6,
Part 3; docs/specs/tier-valuation-spec.md).

The record is two files in data/research/ (every figure from the study's technical report, with its source; nothing
estimated):

- `projects.csv`: one row per study (project, the company's share, study type and date, the study's prices, its
  published after-tax NPV and discount rate, how it discounts, the price-sensitivity rows, initial capex, the
  guided construction start, and whether it is superseded or committed).
- `project_cashflows.csv`: one row per study year from the economic-analysis table (NI 43-101 Section 22, S-K 1300
  Section 19): pre-tax and after-tax free cash flow (US$M, capital included) and payable gold (koz), silver (koz)
  and copper (Mlb). Year 1 is the first year of construction.

Rebuild, for a discount rate r and prices P:

    cash flow_y(P) = after-tax_y + tax share x net revenue share x sum over metals of payable_y,m x (P_m - study P_m)
    NPV = sum_y cash flow_y / (1 + r) ^ (y - 1 + 0.5)        (mid-year; "end-year" studies use y)

The tax share is 1 - the study's stated marginal tax rate (income and mining taxes on an extra dollar of revenue;
the average after-tax / pre-tax ratio overstates it, because depreciation shields part of the average income: on
the Silver Sand PFS, 0.675 from the stated 32.5% fits the study's price grid within 2.5%, the average 0.73 is 11%
off). Without a stated rate the average is used and flagged. The net revenue share is net / gross revenue from the
study (royalties and selling costs move with price). Metals other than gold,
silver, copper, lead and zinc (antimony, molybdenum) stay at the study's price. The rebuild is checked against the published NPV at the study's own
price and rate (within `check_npv`) and against its sensitivity rows (within `check_sensitivity`, as a share of the
study's base NPV, so a row whose NPV is near zero doesn't dominate); a study that fails isn't used for a buy signal.

Then: the time discount from today to the guided construction start, the probability of success for the study's
stage ([valuation.stage_probability]; blank until researched and confirmed by the user) and the company's share.
"""
import re
from datetime import date

import numpy as np
import pandas as pd

from .config import RESEARCH, settings

PROJECTS = RESEARCH / "projects.csv"
CASHFLOWS = RESEARCH / "project_cashflows.csv"
METALS = {"gold": "payable_gold_koz", "silver": "payable_silver_koz", "copper": "payable_copper_mlb",
          "lead": "payable_lead_mlb", "zinc": "payable_zinc_mlb"}
UNIT = {"gold": 1e3, "silver": 1e3, "copper": 1e6, "lead": 1e6, "zinc": 1e6}   # payable units -> ounces or pounds
PROJECT_COLS = ["ticker", "project", "attributable_pct", "study_type", "study_date", "study_price",
                "study_npv_usd_m", "study_discount_rate", "discounting", "marginal_tax_rate", "net_revenue_share", "sensitivity",
                "initial_capex_usd_m", "construction_start", "first_production", "committed", "superseded",
                "source", "as_of", "notes"]
CASHFLOW_COLS = ["ticker", "project", "study_date", "year", "pre_tax_fcf_usd_m", "post_tax_fcf_usd_m",
                 "payable_gold_koz", "payable_silver_koz", "payable_copper_mlb", "payable_lead_mlb",
                 "payable_zinc_mlb", "source"]
STUDY_TYPES = ["PEA", "PFS", "FS", "construction"]


def cfg() -> dict:
    return settings().get("valuation", {})


def parse_prices(s: str) -> dict:
    """'gold 3400; silver 45; copper 4.50' -> {'gold': 3400.0, ...}."""
    out = {}
    for part in str(s or "").split(";"):
        m = re.match(r"\s*([a-z]+)\s+([\d.,]+)\s*$", part.strip().lower())
        if m:
            out[m.group(1)] = float(m.group(2).replace(",", ""))
    return out


def parse_sensitivity(s: str) -> list[tuple[str, float, float, float]]:
    """'silver 18:329, 30:1124 @5%; all -20%:1551, +20%:3689 @5%' -> [(metal, price or change, npv, rate), ...].
    'all' rows change every metal in the study price by the same percentage (the price is then the change, -0.2)."""
    out = []
    for part in str(s or "").split(";"):
        m = re.match(r"\s*([a-z]+)\s+(.+?)\s*@\s*([\d.]+)%\s*$", part.strip().lower())
        if not m:
            continue
        for pair in m.group(2).split(","):
            p, v = pair.split(":")
            p = float(p.strip().rstrip("%")) / 100 if p.strip().endswith("%") else float(p)
            out.append((m.group(1), p, float(v.replace(" ", "")), float(m.group(3)) / 100))
    return out


def load(path_p=None, path_c=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    P = pd.read_csv(path_p or PROJECTS, keep_default_na=False, dtype=str)
    C = pd.read_csv(path_c or CASHFLOWS, keep_default_na=False, dtype=str)
    for c in ["year", "pre_tax_fcf_usd_m", "post_tax_fcf_usd_m"] + list(METALS.values()):
        C[c] = pd.to_numeric(C[c], errors="coerce")
    return P, C


def flows(C: pd.DataFrame, p) -> pd.DataFrame:
    return C[(C.ticker == p.ticker) & (C.project == p.project) & (C.study_date == p.study_date)].sort_values("year")


def tax_share(F: pd.DataFrame) -> float | None:
    """After-tax / pre-tax cash flow over the production years (any payable metal), from the study's own table."""
    prod = F[F[list(METALS.values())].fillna(0).sum(axis=1) > 0]
    pre, post = prod.pre_tax_fcf_usd_m.sum(), prod.post_tax_fcf_usd_m.sum()
    if not (pre == pre and post == post) or pre <= 0 or prod.pre_tax_fcf_usd_m.isna().any():
        return None
    return float(post / pre)


def npv(F: pd.DataFrame, rate: float, prices: dict, study_prices: dict, tshare: float, rev_share: float,
        discounting: str = "mid-year") -> float:
    """The study's after-tax cash flows re-priced to `prices` and discounted at `rate` (US$M)."""
    shift = 0.5 if discounting != "end-year" else 1.0
    tot = 0.0
    for _, r in F.iterrows():
        cf = r.post_tax_fcf_usd_m
        for m, col in METALS.items():
            q = r[col]
            if q == q and m in prices and m in study_prices:
                cf += tshare * rev_share * q * UNIT[m] * (prices[m] - study_prices[m]) / 1e6
        tot += cf / (1 + rate) ** (r.year - 1 + shift)
    return tot


def rebuild(p, F: pd.DataFrame) -> dict:
    """Rebuild checks for one study: rebuilt vs published NPV, and vs each sensitivity row."""
    c = cfg()
    sp = parse_prices(p.study_price)
    ts = tax_share(F)
    out = {"tax_share": ts, "flags": []}
    if F.empty:
        out["flags"].append("no cash-flow table recorded")
        return out
    if str(p.marginal_tax_rate).strip():
        ts = 1 - float(p.marginal_tax_rate) / 100
    elif ts is not None:
        out["flags"].append(f"no marginal tax rate recorded: tax share {ts:.2f} from average cash flows (overstates)")
    else:
        ts = settings()["price_model"]["cash_flow_share"]
        out["flags"].append(f"no tax rate or pre-tax cash flows: tax share {ts} (the producers' default)")
    rs = float(p.net_revenue_share) if str(p.net_revenue_share).strip() else 1.0
    if not str(p.net_revenue_share).strip():
        out["flags"].append("net revenue share not recorded: 1.0 used")
    out.update(tax_share=ts, rev_share=rs, study_prices=sp)
    pub = float(p.study_npv_usd_m) if str(p.study_npv_usd_m).strip() else None
    rate = float(p.study_discount_rate) / 100 if str(p.study_discount_rate).strip() else None
    if pub is not None and rate is not None:
        rb = npv(F, rate, sp, sp, ts, rs, p.discounting)
        out["rebuilt_at_study"] = rb
        diff = rb / pub - 1 if pub else np.nan
        out["npv_diff"] = diff
        if not abs(diff) <= c.get("check_npv", 0.05):
            out["flags"].append(f"rebuilt NPV {rb:,.0f} vs published {pub:,.0f} ({diff:+.0%})")
    worst = 0.0
    for metal, price, v, r in parse_sensitivity(p.sensitivity):
        px = {m: q * (1 + price) for m, q in sp.items()} if metal == "all" else {**sp, metal: price}
        rb = npv(F, r, px, sp, ts, rs, p.discounting)
        base = pub if pub else abs(v)                    # measured against the base NPV: a row near zero (a low price
        worst = max(worst, abs(rb - v) / base) if base else worst   # at a high rate) would otherwise blow up
    out["sensitivity_worst"] = worst if p.sensitivity else None
    if p.sensitivity and worst > c.get("check_sensitivity", 0.10):
        out["flags"].append(f"re-pricing off the study's sensitivity rows by up to {worst:.0%}")
    out["ok"] = not any(f.startswith(("rebuilt", "re-pricing", "no cash-flow")) for f in out["flags"])
    return out


def discount_rate(ticker: str, companies: pd.DataFrame | None = None, table: dict | None = None) -> float:
    """10-year yield + risk premium + the company's jurisdiction add-on, worked out as `financials` does it for the
    Sheet (an override, else the country table over `country_weights`, else the hand-set figure; [pnav])."""
    from .jurisdiction import company_addon, load_table
    P = settings()["pnav"]
    C = companies if companies is not None else pd.read_csv(RESEARCH / "pnav_companies.csv")
    rows = C[C.ticker == ticker]
    addon = 0.0
    if len(rows):
        a, _ = company_addon(rows.iloc[0], load_table() if table is None else table)
        addon = a / 100 if a == a else 0.0
    return P["ten_year_yield"] + P["risk_premium"] + addon


def time_factor(construction_start: str, rate: float, today: date) -> float | None:
    """Discount from today to the guided construction start (1.0 when it has passed); None when not guided."""
    if not str(construction_start).strip():
        return None
    t = (pd.Timestamp(construction_start).date() - today).days / 365.25
    return 1.0 if t <= 0 else 1 / (1 + rate) ** t


def risk_adjusted(p, F: pd.DataFrame, prices: dict, rate: float, today: date) -> dict:
    """NPV at our rate and `prices`, then time, probability and share. Missing pieces leave it None, with why."""
    chk = rebuild(p, F)
    out = {"check": chk, "npv": None, "risk_adjusted": None, "why": ""}
    if str(p.superseded).strip():
        out["why"] = f"superseded: {p.superseded}"
        return out
    if not chk.get("ok"):
        out["why"] = "; ".join(chk["flags"]) or "rebuild failed"
        return out
    v = npv(F, rate, {**chk["study_prices"], **prices}, chk["study_prices"], chk["tax_share"], chk["rev_share"],
            p.discounting)
    out["npv"] = v
    tf = time_factor(p.construction_start, rate, today)
    prob = cfg().get("stage_probability", {}).get(p.study_type)
    share = float(p.attributable_pct) / 100 if str(p.attributable_pct).strip() else 1.0
    if tf is None:
        out["why"] = "no guided construction start"
    elif prob is None:
        out["why"] = f"no probability of success set for {p.study_type} ([valuation.stage_probability])"
    else:
        out["risk_adjusted"] = v * tf * prob * share
    out.update(time_factor=tf, probability=prob, share=share)
    return out


def report(today: date | None = None, prices: dict | None = None) -> list[str]:
    """The rebuild check and NPVs for every recorded study (offline: uses [scenarios] and the cached spot)."""
    from .price_model import Metals
    today = today or date.today()
    P, C = load()
    if P.empty:
        return ["No studies recorded in data/research/projects.csv."]
    m = Metals()
    decks = {"spot": dict(m.spot)} if prices is None else {"given": prices}
    if prices is None:
        for n in ("Low", "High"):
            decks[n] = m.scenario(n)
    L = []
    for _, p in P.iterrows():
        F = flows(C, p)
        rate = discount_rate(p.ticker)
        chk = rebuild(p, F)
        L.append(f"{p.ticker} {p.project} ({p.study_type} {p.study_date}), our rate {rate:.1%}:")
        if "rebuilt_at_study" in chk:
            L.append(f"  rebuilt at the study's price and {p.study_discount_rate}%: {chk['rebuilt_at_study']:,.0f} vs "
                     f"published {float(p.study_npv_usd_m):,.0f} ({chk['npv_diff']:+.1%}); tax share "
                     f"{chk['tax_share']:.2f}, net revenue share {chk['rev_share']:.3f}")
        if chk.get("sensitivity_worst") is not None:
            L.append(f"  sensitivity rows: worst difference {chk['sensitivity_worst']:.1%}")
        for f in chk["flags"]:
            L.append(f"  flag: {f}")
        for name, px in decks.items():
            x = risk_adjusted(p, F, px, rate, today)
            if x["npv"] is None:
                L.append(f"  {name}: no NPV ({x['why']})")
                break
            ra = "" if x["risk_adjusted"] is None else f"; risk-adjusted {x['risk_adjusted']:,.0f}"
            L.append(f"  {name}: NPV {x['npv']:,.0f}{ra}" + (f" ({x['why']})" if x["why"] else ""))
    return L
