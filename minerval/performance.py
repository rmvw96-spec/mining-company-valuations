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
"""
import json

import numpy as np
import pandas as pd

from .config import CACHE, settings
from .price_model import METALS

YEARS = 4                       # Yahoo carries four annual years: three years of change
SERIES = {"revenue": "annualTotalRevenue", "ocf": "annualOperatingCashFlow", "fcf": "annualFreeCashFlow",
          "shares": "annualOrdinarySharesNumber"}
MATCH_DAYS = 15                 # a recorded FY sustaining figure matches the annual figures' year end within this
FCF, OCF_SUS, OCF = "FCF", "OCF − sustaining", "OCF"


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
    A = pd.DataFrame(cols).sort_index()
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


def trend_growth(values) -> float:
    """Least-squares slope a year ÷ the mean absolute value (NaN for fewer than two years or an all-zero series)."""
    v = np.asarray([x for x in values if x == x], dtype=float)
    if len(v) < 2 or not np.abs(v).mean() > 0:
        return np.nan
    return float(np.polyfit(np.arange(len(v)), v, 1)[0] / np.abs(v).mean())


def measures(A: pd.DataFrame, mix: dict, monthly: dict, base: dict, k: float, sustaining: dict | None = None,
             royalty: bool = False) -> dict:
    """Cash flow (royalties: OCF) per share growth, the margin's average and lowest year, the basis and the years."""
    T = constant_price(A, mix, monthly, base, k, sustaining, royalty)
    key = "ocf_ps_growth" if royalty else "cf_ps_growth"
    if T.empty:
        return {key: np.nan, "margin_avg": np.nan, "margin_min": np.nan, "cf_basis": "", "history_years": 0}
    return {key: trend_growth(list(T.cf_ps)), "margin_avg": float(T.margin.mean()),
            "margin_min": float(T.margin.min()), "cf_basis": T.basis.iloc[0], "history_years": len(T)}


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


def add(U: pd.DataFrame, holdings: dict | None = None, monthly: dict | None = None, sustaining: dict | None = None,
        base: dict | None = None) -> pd.DataFrame:
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
    U, rows = U.copy(), []
    for _, r in U.iterrows():
        h = holdings.get(str(r.get("ticker"))) or holdings.get(str(r.get("ticker_buy"))) or {}
        A = annual(h.get("series") or {})
        mix = {m: r.get(f"share_{m}") for m in METALS}
        mix = {m: float(v) for m, v in mix.items() if isinstance(v, (int, float)) and v == v}
        curs = set(A.currency.dropna()) if len(A) else set()
        sus = {d: v for (d, cur), v in sustaining.get(str(r.get("ticker")), {}).items() if cur in curs}
        k_ = kind(str(r.get("bucket") or ""))
        if k_ == "developer":
            rows.append({"history_years": int(A.shares.dropna().tail(YEARS).size) if len(A) else 0})
            continue
        rows.append(measures(A, mix, monthly, base, k, sus, royalty=k_ == "royalty"))
    M = pd.DataFrame(rows, index=U.index)
    for c in M.columns:
        U[c] = M[c]
    return U
