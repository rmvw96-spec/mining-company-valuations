"""Per-holding fundamentals in US$ and fund-level look-through multiples.

Reads cache/fundamentals.json; writes data/derived/holdings_detail.csv and fund_multiples.csv.

Fund multiple = sum(w) / sum(w x X / market cap): the fund owns a slice of each company in
proportion to its weight, and companies with negative X lower the fund's total.
EV/EBITDA = sum(w x EV / market cap) / sum(w x EBITDA / market cap).
"""
import json

import numpy as np
import pandas as pd

from .config import CACHE, DERIVED, ensure, settings, table

FIN_COLS = ["book", "ocf", "fcf", "ebitda"]


def load_cache():
    d = json.loads((CACHE / "fundamentals.json").read_text())
    for v in d["holdings"].values():
        v["ts"] = {k: pts[-1] for k, pts in (v.get("series") or {}).items() if pts}
    return d


def pick(ts, keys):
    """Most recent point among keys; on the same date, the key listed first wins."""
    pts = [(ts[k]["date"], -i, ts[k]) for i, k in enumerate(keys) if k in ts]
    return max(pts)[2] if pts else None


def per_holding(cache=None) -> pd.DataFrame:
    S = settings()["holdings"]
    d = cache or load_cache()
    H, FX = d["holdings"], d["fx"]

    def usd(p):
        return p["val"] * FX[p["cur"]] if p and p.get("cur") in FX else None

    rows = []
    for t, v in H.items():
        r = {"ticker": t, "yahoo": v.get("yahoo")}
        r["kind"] = ("physical metal" if t in S["physical_trusts"] else
                     "other fund" if t in S["non_operating"] else "company")
        ts = dict(v.get("ts") or {})
        if v.get("yahoo") and v.get("currency") in FX:
            r["price_usd"] = v["price"] * FX[v["currency"]]
            sh = (pick(ts, ["quarterlyOrdinarySharesNumber", "annualOrdinarySharesNumber"]) or
                  pick(ts, ["quarterlyShareIssued", "annualShareIssued"]))
            if sh:
                r["shares"] = sh["val"]
                r["mcap"] = r["price_usd"] * sh["val"]
        eq = pick(ts, ["quarterlyStockholdersEquity", "annualStockholdersEquity"])
        debt = pick(ts, ["quarterlyTotalDebt", "annualTotalDebt"])
        cash = (pick(ts, ["quarterlyCashCashEquivalentsAndShortTermInvestments",
                          "annualCashCashEquivalentsAndShortTermInvestments"]) or
                pick(ts, ["quarterlyCashAndCashEquivalents", "annualCashAndCashEquivalents"]))
        for per in ("trailing", "annual"):      # operating cash flow = FCF - capex where only those exist
            f_, c_ = ts.get(per + "FreeCashFlow"), ts.get(per + "CapitalExpenditure")
            if f_ and c_ and f_["cur"] == c_["cur"] and f_["date"] == c_["date"]:
                ts[per + "DerivedOCF"] = {"date": f_["date"], "cur": f_["cur"], "val": f_["val"] - c_["val"]}
        # The most recent period wins, so a stale trailing figure loses to a newer one from another series.
        ocf = pick(ts, ["trailingOperatingCashFlow", "trailingCashFlowFromContinuingOperatingActivities",
                        "trailingDerivedOCF", "annualOperatingCashFlow",
                        "annualCashFlowFromContinuingOperatingActivities", "annualDerivedOCF"])
        fcf = pick(ts, ["trailingFreeCashFlow", "annualFreeCashFlow"])
        ebitda = pick(ts, ["trailingEBITDA", "annualEBITDA"])
        rev = pick(ts, ["trailingTotalRevenue", "annualTotalRevenue"])
        r.update(book=usd(eq), debt=usd(debt) or 0.0, cash=usd(cash) or 0.0, ocf=usd(ocf), fcf=usd(fcf),
                 ebitda=usd(ebitda), revenue=usd(rev),
                 fin_date=max([p["date"] for p in (eq, ocf, fcf, ebitda) if p] or [None], key=lambda x: x or ""))
        r["stale"] = bool(r["fin_date"] and r["fin_date"] < S["stale_before"])
        # When the cash flow had to be derived (FCF - capex) because Yahoo's reported figure is old, say so.
        reported = pick(ts, ["trailingOperatingCashFlow", "trailingCashFlowFromContinuingOperatingActivities",
                             "annualOperatingCashFlow", "annualCashFlowFromContinuingOperatingActivities"])
        derived = ocf is not None and any(ocf is ts.get(k) for k in ("trailingDerivedOCF", "annualDerivedOCF"))
        r["ocf_note"] = (f"Op. cash flow corrected: Yahoo's figure was from {reported['date'][:4]}"
                         if derived and reported and reported["date"] < ocf["date"] else "")
        if r.get("mcap"):
            r["ev"] = r["mcap"] + r["debt"] - r["cash"]
        rows.append(r)
    T = pd.DataFrame(rows).set_index("ticker")

    corr = table("corrections.csv")
    T["correction"] = ""
    for _, c in corr.iterrows():
        if c.ticker in T.index:
            if isinstance(c.field, str) and c.field:
                T.loc[c.ticker, c.field] = float(c.value_usd_m) * 1e6
            T.loc[c.ticker, "correction"] = c.note
    from .fundamentals import load_holdings
    h = load_holdings()
    X = h.join(T, on="ticker")
    X["note"] = [note(r) for _, r in X.iterrows()]
    order = settings()["holdings"]["fund_order"]
    X["fund"] = pd.Categorical(X.fund, order)
    return X.sort_values(["fund", "weight_pct"], ascending=[True, False], kind="stable").reset_index(drop=True)


def note(r) -> str:
    """The Holdings tab's Note column."""
    if r.kind == "physical metal":
        return "Physical metal trust, excluded"
    if r.kind == "other fund":
        return "Not a mining company, excluded"
    if pd.isna(r.get("mcap")):
        return "No price or financial data"
    if r.get("correction"):
        return r.correction
    if r.get("ocf_note"):
        return r.ocf_note
    if pd.notna(r.ocf) and r.ocf <= 0:
        return "Negative operating cash flow"
    return ""


def companies(X: pd.DataFrame) -> pd.DataFrame:
    """Holdings that count toward company multiples: operating companies with a market cap and current data."""
    return X[(X.kind == "company") & X.mcap.notna() & (X.mcap > 0) & ~X.stale.astype(bool)]


def fund_multiples(X: pd.DataFrame) -> pd.DataFrame:
    out = []
    for f, g in X.groupby("fund", sort=False, observed=True):
        c = g[(g.kind == "company") & g.mcap.notna() & (g.mcap > 0)]
        res = {"fund": f, "focus": settings()["funds"][f]["focus"],
               "physical_metal_%": g.loc[g.kind == "physical metal", "weight_pct"].sum(),
               "other_%": g.loc[g.kind == "other fund", "weight_pct"].sum(),
               "company_%": g.loc[g.kind == "company", "weight_pct"].sum()}
        for m in FIN_COLS:
            cc = c[c[m].notna() & ~c.stale.astype(bool)]
            y = (cc.weight_pct * cc[m] / cc.mcap).sum()
            res[f"cov_{m}_%"] = cc.weight_pct.sum()
            res[f"neg_{m}_%"] = cc.loc[cc[m] <= 0, "weight_pct"].sum()
            res[f"P/{m}"] = cc.weight_pct.sum() / y if y > 0 else np.nan
            pos = cc[cc[m] > 0]
            yp = (pos.weight_pct * pos[m] / pos.mcap).sum()
            res[f"P/{m} (positive only)"] = pos.weight_pct.sum() / yp if yp > 0 else np.nan
            if m == "ebitda":
                res["EV/EBITDA"] = (cc.weight_pct * cc.ev / cc.mcap).sum() / y if y > 0 else np.nan
                res["EV/EBITDA (positive only)"] = ((pos.weight_pct * pos.ev / pos.mcap).sum() / yp
                                                   if yp > 0 else np.nan)
        res["uncovered_company_%"] = res["company_%"] - c.loc[~c.stale.astype(bool), "weight_pct"].sum()
        out.append(res)
    return pd.DataFrame(out).set_index("fund")


def run():
    ensure(DERIVED)
    X = per_holding()
    X.to_csv(DERIVED / "holdings_detail.csv", index=False)
    F = fund_multiples(X)
    F.to_csv(DERIVED / "fund_multiples.csv")
    return X, F
