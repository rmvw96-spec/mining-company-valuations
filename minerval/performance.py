"""The screen's performance measures (roadmap 5b, revision 2; docs/specs/model-portfolio-screen-spec.md, "Score").

Business performance per share at constant metal prices, so the ranking doesn't move with the metal:

- **Cash flow:** each fiscal year's OCF − sustaining spending where sustaining is recorded for every year in the window
  (data/research/capex_periods.csv FY rows, in the same currency as the annual figures), else free cash flow for every
  year (labelled "FCF"); royalties use operating cash flow.
- **Re-priced** from that year's average metal prices (the 12 monthly COMEX closes to the year end) to the base deck
  with the valuation's price adjustment: + cash_flow_share × revenue × Σ revenue share × (base ÷ the year's average
  − 1). Revenue is re-priced the same way for the margin (cash flow ÷ revenue).
- **Per share** with that year's share count.
- **Growth** is the fitted slope of the per-share series over its mean size, a year: it uses every year and works
  through a change of sign.

The annual figures are Yahoo's (cache/fundamentals.json): the last `YEARS` fiscal years with revenue, the cash flow
and a share count. Fewer than [portfolio_screen.filters] min_history_years is "too little history" (the screen's
filter).

Production, reserves and resources, and royalties' GEOs sold are research inputs (data/research/operations.csv, from
filings, never estimated): each year's quantity in gold ounces at the base deck's prices (a copper pound counts
copper ÷ gold ounces; metals outside the deck are left out; a royalty's reported GEOs are taken as published),
reserves and resources weighted by category as roadmap 3 (Signals inputs resource_weight_*; M&I exclusive of
reserves), ÷ the share count of the nearest fiscal year end.
"""
import json

import numpy as np
import pandas as pd

from .config import CACHE, settings
from .price_model import METALS

YEARS = 4                       # Yahoo carries four annual years: three years of change
SERIES = {"revenue": "annualTotalRevenue", "ocf": "annualOperatingCashFlow", "fcf": "annualFreeCashFlow",
          "shares": "annualOrdinarySharesNumber", "capex": "annualCapitalExpenditure",
          "ga": "annualGeneralAndAdministrativeExpense", "sga": "annualSellingGeneralAndAdministration"}
STAGE_RANK = {"none": 0, "PEA": 1, "PFS": 2, "FS": 3, "permitted": 4, "construction": 5}
MATCH_DAYS = 15                 # a recorded FY sustaining figure matches the annual figures' year end within this
FCF, OCF_SUS, OCF = "FCF", "OCF − sustaining", "OCF"
OPERATIONS_COLS = ["ticker", "period_end", "measure", "category", "metal", "amount", "unit", "basis", "document", "url",
                   "published", "notes"]
MEASURES_RECORDED = ("production", "resources", "geo_sold")
UNITS = ("oz", "koz", "Moz", "lb", "Mlb", "Blb", "t", "kt")
LB_PER_TONNE, OZ_PER_TONNE = 2204.62262, 32150.7466
SHARES_WITHIN_DAYS = 200        # a quantity is taken per share at the nearest fiscal year end within this


def annual(series: dict) -> pd.DataFrame:
    """Yahoo's annual figures by fiscal year end: revenue, ocf, fcf (millions of the reporting currency), shares
    (millions) and the reporting currency."""
    cols, cur = {}, {}
    for k, name in SERIES.items():
        pts = [p for p in (series.get(name) or []) if p.get("val") is not None and p.get("date")]
        cols[k] = pd.Series({pd.Timestamp(p["date"]): p["val"] / 1e6 for p in pts}, dtype=float)
        if k == "revenue":
            cur = {pd.Timestamp(p["date"]): p.get("cur", "") for p in pts}
    if not any(len(s) for s in cols.values()):
        return pd.DataFrame(columns=[*SERIES, "currency"])
    A = pd.DataFrame({k: s for k, s in cols.items() if len(s)}).reindex(columns=list(SERIES)).sort_index()
    A.index = pd.DatetimeIndex(A.index)
    A["currency"] = pd.Series(cur, dtype=object).reindex(A.index)
    return A


def year_average(monthly: dict, end) -> dict:
    """{metal: average monthly close over the 12 months to `end`} (NaN without prices)."""
    end = pd.Timestamp(end)
    out = {}
    for m, s in monthly.items():
        w = s[(s.index > end - pd.DateOffset(years=1)) & (s.index <= end)]
        out[m] = float(w.mean()) if len(w) else np.nan
    return out


def price_change(revenue: float, mix: dict, avg: dict, base: dict, k: float) -> float:
    """valuation._price_change for one year: cash_flow_share × revenue × Σ share × (base ÷ the year's average − 1)."""
    return k * revenue * sum(s * (base[m] / avg[m] - 1) for m, s in mix.items() if s)


def _sustaining_for(A: pd.DataFrame, sustaining: dict | None) -> pd.Series | None:
    """Each row's recorded sustaining spending (matched by year end), or None unless every row has one."""
    if not sustaining or A.empty:
        return None
    out = {}
    for end in A.index:
        hit = [v for d, v in sustaining.items() if abs((pd.Timestamp(d) - end).days) <= MATCH_DAYS]
        if not hit:
            return None
        out[end] = hit[0]
    return pd.Series(out)


def constant_price(A: pd.DataFrame, mix: dict, monthly: dict, base: dict, k: float, sustaining: dict | None = None,
                   royalty: bool = False) -> pd.DataFrame:
    """The last YEARS fiscal years, each re-priced to `base`: cf, rev, shares, cf_ps, margin and basis."""
    mix = {m: float(s) for m, s in mix.items() if m in METALS and s == s and s}
    cols = ["cf", "rev", "shares", "cf_ps", "margin", "basis"]
    if A.empty:
        return pd.DataFrame(columns=cols)
    A = A[(A.revenue > 0) & (A.shares > 0)]
    if royalty:
        A = A[A.ocf.notna()].tail(YEARS)
        basis, cash = OCF, A.ocf
    else:
        W = A[A.ocf.notna()].tail(YEARS)
        F = A[A.fcf.notna()].tail(YEARS)
        sus = _sustaining_for(W, sustaining)
        if sus is not None and len(W) >= len(F):
            A, basis, cash = W, OCF_SUS, W.ocf - sus
        else:
            A, basis, cash = F, FCF, F.fcf
    rows = {}
    for end, r in A.iterrows():
        avg = year_average(monthly, end)
        if any(avg.get(m) != avg.get(m) for m in mix):
            continue                                  # no metal prices for that year
        up = sum(s * (base[m] / avg[m] - 1) for m, s in mix.items())
        cf = cash[end] + price_change(r.revenue, mix, avg, base, k)
        rev = r.revenue * (1 + up)
        rows[end] = {"cf": cf, "rev": rev, "shares": r.shares, "cf_ps": cf / r.shares,
                     "margin": cf / rev if rev > 0 else np.nan, "basis": basis}
    return pd.DataFrame.from_dict(rows, orient="index", columns=cols) if rows else pd.DataFrame(columns=cols)


def trend_growth(values, x=None) -> float:
    """Least-squares slope a year ÷ the mean absolute value (NaN for fewer than two points or an all-zero series).
    `x`: each value's time in years (default one a year)."""
    x = list(range(len(values))) if x is None else list(x)
    pts = [(a, v) for a, v in zip(x, values) if v == v]
    v = np.asarray([b for _, b in pts], dtype=float)
    if len(v) < 2 or not np.abs(v).mean() > 0:
        return np.nan
    return float(np.polyfit([a for a, _ in pts], v, 1)[0] / np.abs(v).mean())


def measures(A: pd.DataFrame, mix: dict, monthly: dict, base: dict, k: float, sustaining: dict | None = None,
             royalty: bool = False) -> dict:
    """Cash flow (royalties: OCF) per share growth, the margin's average and lowest year, the basis and the years."""
    T = constant_price(A, mix, monthly, base, k, sustaining, royalty)
    key = "ocf_ps_growth" if royalty else "cf_ps_growth"
    if T.empty:
        return {key: np.nan, "margin_avg": np.nan, "margin_min": np.nan, "cf_basis": "", "history_years": 0}
    return {key: trend_growth(list(T.cf_ps)), "margin_avg": float(T.margin.mean()),
            "margin_min": float(T.margin.min()), "cf_basis": T.basis.iloc[0], "history_years": len(T)}


# ---------- research quantities: production, reserves and resources, GEOs ----------

def unit_factor(unit: str, metal: str) -> float:
    """Multiplier to ounces (gold, silver, GEOs) or pounds (base metals)."""
    precious = metal in ("gold", "silver", "geo")
    f = {"oz": 1.0, "koz": 1e3, "Moz": 1e6, "lb": 1.0, "Mlb": 1e6, "Blb": 1e9}.get(unit)
    if f is None:
        f = {"t": 1.0, "kt": 1e3}[unit] * (OZ_PER_TONNE if precious else LB_PER_TONNE)
    return f


def weights() -> dict:
    """Roadmap 3's category weights (Signals inputs): reserves, M&I (exclusive of reserves), inferred."""
    inp = settings()["signals"]["inputs"]
    return {k: float(inp[f"resource_weight_{k}"]) for k in ("reserves", "mi", "inferred")}


def _gold_ounces(r, base: dict) -> float:
    if r.metal == "geo":
        return float(r.amount) * unit_factor(r.unit, "geo")
    if r.metal not in base:
        return 0.0
    return float(r.amount) * unit_factor(r.unit, r.metal) * base[r.metal] / base["gold"]


def per_share_units(O: pd.DataFrame, A: pd.DataFrame, base: dict, categories: tuple | None = None) -> pd.Series:
    """{year end: gold ounces at the base deck per share (millions of shares)} for the last YEARS year ends; with
    `categories`, the resources rows of those categories at roadmap 3's weights."""
    if O.empty or A.empty or A.shares.dropna().empty:
        return pd.Series(dtype=float)
    if categories:
        w = weights()
        O = O[(O.measure == "resources") & O.category.isin(categories)]
        scale = O.category.map(w).astype(float)
    else:
        scale = pd.Series(1.0, index=O.index)
    vals = {}
    ends = pd.to_datetime(O.period_end)
    for end in sorted(set(ends)):
        part = O[ends == end]
        oz = sum(_gold_ounces(r, base) * scale[i] for i, r in part.iterrows())
        S = A.shares.dropna()
        gap = abs((S.index - end).days)
        if gap.min() > SHARES_WITHIN_DAYS:
            continue
        vals[end] = oz / S.iloc[int(np.argmin(gap))]
    return pd.Series(vals, dtype=float).sort_index().tail(YEARS)


def research_measures(O: pd.DataFrame, A: pd.DataFrame, base: dict, tier: str) -> dict:
    """The research-input measures for a company's operations rows, by tier."""
    def g(s):
        return trend_growth(list(s))
    if tier == "royalty":
        return {"geo_ps_growth": g(per_share_units(O[O.measure == "geo_sold"], A, base))}
    if tier == "developer":
        return {"resource_ps_growth": g(per_share_units(O, A, base, ("reserves", "mi", "inferred")))}
    return {"production_ps_growth": g(per_share_units(O[O.measure == "production"], A, base)),
            "reserves_ps_growth": g(per_share_units(O, A, base, ("reserves", "mi")))}


# ---------- developers: study progress, spending, NPV per share across studies ----------

def study_progress(P: pd.DataFrame, ticker: str, now: str, today, years: int = 3) -> float:
    """Stages moved in `years`: the stage now (pnav_companies `study_stage`) less the latest study recorded by then
    (its type, or construction once construction had started; none recorded counts as 0). NaN without a stage now."""
    if now not in STAGE_RANK:
        return np.nan
    then = pd.Timestamp(today) - pd.DateOffset(years=years)
    R = P[(P.ticker == ticker) & (pd.to_datetime(P.study_date, errors="coerce") <= then)]
    if R.empty:
        return float(STAGE_RANK[now])
    r = R.assign(_d=pd.to_datetime(R.study_date)).sort_values("_d").iloc[-1]
    cs = pd.to_datetime(r.get("construction_start") or None, errors="coerce")
    was = "construction" if cs == cs and cs is not None and cs <= then else str(r.study_type)
    return float(STAGE_RANK[now] - STAGE_RANK.get(was, 0))


def spending_shares(A: pd.DataFrame) -> dict:
    """Over the window: exploration and development ÷ all spending, and G&A (SG&A where G&A isn't reported) ÷ all
    spending, where all spending = cash used in operations + capital spending."""
    nan = {"explore_dev_share": np.nan, "ga_share": np.nan}
    if A.empty:
        return nan
    W = A[A.ocf.notna() & A.capex.notna()].tail(YEARS)
    ga = W.ga if W.ga.notna().any() else W.sga
    W, ga = W[ga.notna()], ga[ga.notna()]
    spend = float((-W.ocf).clip(lower=0).sum() + (-W.capex).clip(lower=0).sum())
    if W.empty or spend <= 0:
        return nan
    g = float(ga.sum()) / spend
    return {"explore_dev_share": 1 - g, "ga_share": g}


def study_values(P: pd.DataFrame, C: pd.DataFrame, ticker: str, base: dict, rate: float) -> dict:
    """{study date: risk-adjusted NPV at `base`, valued as of that date} for every recorded study of the company,
    superseded ones too (an expansion's increment is left out: it isn't the company's value)."""
    from . import studies as S
    out = {}
    for _, p in P[P.ticker == ticker].iterrows():
        if str(p.get("baseline", "") or "").strip():
            continue
        q = p.copy()
        q["superseded"] = ""
        d = pd.Timestamp(p.study_date)
        v = S.risk_adjusted(q, S.flows(C, q), base, rate, d.date()).get("risk_adjusted")
        if v is not None and v == v:
            out[d] = float(v)
    return dict(sorted(out.items()))


def npv_ps_growth(values: dict, A: pd.DataFrame) -> float:
    """Growth a year of the risk-adjusted NPV per share across successive studies (shares at the nearest year end)."""
    if len(values) < 2 or A.empty or A.shares.dropna().empty:
        return np.nan
    S, pts = A.shares.dropna(), []
    for d, v in values.items():
        gap = abs((S.index - d).days)
        if gap.min() <= SHARES_WITHIN_DAYS:
            pts.append((d, v / S.iloc[int(np.argmin(gap))]))
    if len(pts) < 2:
        return np.nan
    first = pts[0][0]
    return trend_growth([v for _, v in pts], [(d - first).days / 365.25 for d, _ in pts])


def load_operations(path=None) -> pd.DataFrame:
    from .config import RESEARCH
    p = path or RESEARCH / "operations.csv"
    if not p.exists():
        return pd.DataFrame(columns=OPERATIONS_COLS)
    return pd.read_csv(p, keep_default_na=False, dtype={"amount": float})


# ---------- loading the inputs for the screen ----------

def load_monthly() -> dict:
    """{metal: monthly COMEX closes} from the signals cache (cache/signals/<symbol>_1mo.json, from 2000)."""
    out = {}
    for m, sym in settings()["yahoo"]["metals"].items():
        p = CACHE / "signals" / f"{sym.replace('=', '_')}_1mo.json"
        if not p.exists():
            continue
        r = json.loads(p.read_text())["chart"]["result"][0]
        out[m] = pd.Series(r["indicators"]["quote"][0]["close"],
                           index=pd.to_datetime(r["timestamp"], unit="s").normalize()).dropna()
    return out


def load_sustaining(path=None) -> dict:
    """{ticker: {(year end, currency): total sustaining spending, millions}} from the FY rows of capex_periods.csv
    (sustaining.py's total: with leases, and stripping unless it's inside sustaining)."""
    from .sustaining import _amount, load_record
    R = load_record(path) if path else load_record()
    out = {}
    for _, r in R[R.period.astype(str).str.upper() == "FY"].iterrows():
        if r.sustaining == r.sustaining:
            out.setdefault(r.ticker, {})[(pd.Timestamp(r.period_end), str(r.currency))] = _amount(r)[0]
    return out


def _rates() -> dict:
    """{ticker: discount rate} from the last `valuation` (data/derived/valuation.csv), for the developers' studies."""
    from .config import DERIVED
    f = DERIVED / "valuation.csv"
    if not f.exists():
        return {}
    V = pd.read_csv(f)
    return {t: r for t, r in zip(V.ticker, V.get("discount_rate", [])) if r == r}


def add(U: pd.DataFrame, holdings: dict | None = None, monthly: dict | None = None, sustaining: dict | None = None,
        base: dict | None = None, operations: pd.DataFrame | None = None, studies: tuple | None = None,
        rates: dict | None = None, today=None) -> pd.DataFrame:
    """The universe with each company's performance measures (the keys of `measures`) added; developers get only
    their years of share counts here."""
    from .screen import kind
    from .valuation import decks
    if holdings is None:
        f = CACHE / "fundamentals.json"
        holdings = json.loads(f.read_text())["holdings"] if f.exists() else {}
    monthly = load_monthly() if monthly is None else monthly
    sustaining = load_sustaining() if sustaining is None else sustaining
    base = base or decks()[settings()["valuation"]["base_deck"]]
    k = settings()["price_model"]["cash_flow_share"]
    O = load_operations() if operations is None else operations
    from datetime import date
    from . import studies as S
    P, C = S.load() if studies is None else studies
    rates = _rates() if rates is None else rates
    today = today or date.today()
    U, rows = U.copy(), []
    for _, r in U.iterrows():
        h = holdings.get(str(r.get("ticker"))) or holdings.get(str(r.get("ticker_buy"))) or {}
        A = annual(h.get("series") or {})
        mix = {m: r.get(f"share_{m}") for m in METALS}
        mix = {m: float(v) for m, v in mix.items() if isinstance(v, (int, float)) and v == v}
        curs = set(A.currency.dropna()) if len(A) else set()
        sus = {d: v for (d, cur), v in sustaining.get(str(r.get("ticker")), {}).items() if cur in curs}
        k_ = kind(str(r.get("bucket") or ""))
        mine = O[O.ticker == str(r.get("ticker"))]
        extra = research_measures(mine, A, base, k_)
        if k_ == "developer":
            t = str(r.get("ticker"))
            npv = npv_ps_growth(study_values(P, C, t, base, rates[t]), A) if t in rates else np.nan
            rows.append({"history_years": int(A.shares.dropna().tail(YEARS).size) if len(A) else 0, **extra,
                         "study_progress": study_progress(P, t, str(r.get("study_stage") or ""), today),
                         **spending_shares(A), "npv_ps_growth": npv})
            continue
        rows.append({**measures(A, mix, monthly, base, k, sus, royalty=k_ == "royalty"), **extra})
    M = pd.DataFrame(rows, index=U.index)
    for c in M.columns:
        U[c] = M[c]
    return U
