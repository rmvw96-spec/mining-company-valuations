"""Rick Rule-style checks: metal-price stress test, free-cash-flow breakeven, balance sheet, dilution.

Reads data/derived/holdings_detail.csv and cache/fundamentals.json (share-count history, working
capital). Writes to data/derived/:
  stress_holdings.csv   one row per fund holding (feeds the Holdings downside tab)
  stress_funds.csv      fund-level results (the Stress test & downside tab)
  multiples_today.csv   fund multiples re-estimated at today's metal prices (Metal prices reference tab)
  metals_today.json     the "Today" metal prices used, and their date (for the `snapshots` titles)
"""
import json

import numpy as np
import pandas as pd

from .config import DERIVED, ensure, fund_metal, settings
from .holdings import companies, load_cache
from .price_model import METALS, Metals, cost_change, cost_increase_default, mix_for, mixes, revenue_change

UNIT = {"gold": "gold $/oz", "silver": "silver $/oz", "copper": "copper $/lb"}


def share_change(series: dict, years: int, tolerance_days: int):
    """Change in share count over `years`, against the reported count nearest that date (or None)."""
    pts = {}
    for k in ("annualOrdinarySharesNumber", "quarterlyOrdinarySharesNumber"):
        for p in series.get(k) or []:
            pts[p["date"]] = p["val"]
    if len(pts) < 2:
        return None
    s = pd.Series(pts, dtype=float)
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    # Yahoo's share counts are already split-adjusted (checked against OceanaGold and PDI Gold).
    target = s.index[-1] - pd.DateOffset(years=years)
    i = s.index.get_indexer([target], method="nearest")[0]
    if abs((s.index[i] - target).days) > tolerance_days or s.iloc[i] <= 0:
        return None
    return s.iloc[-1] / s.iloc[i] - 1


def latest(series: dict, keys, fx):
    pts = [p for k in keys for p in (series.get(k) or []) if p.get("cur") in fx]
    return max(pts, key=lambda p: p["date"]) if pts else None


def per_holding(X: pd.DataFrame, metals: Metals, cache=None, cost_increase: float | None = None) -> pd.DataFrame:
    S = settings()
    pm = S["price_model"]
    ebitda_k, cf_k = pm["ebitda_share"], pm["cash_flow_share"]
    c = cost_increase_default(cost_increase)
    tol = {int(k): v for k, v in S["stress"]["dilution_tolerance_days"].items()}
    cache = cache or load_cache()
    H, FX = cache["holdings"], cache["fx"]
    mt = mixes()
    scen = {n: metals.scenario(n) for n in S["stress"]["scenarios"]}
    comp_idx = set(companies(X).index)
    rows = []
    for i, r in X.iterrows():
        mix = mix_for(r.ticker, r.fund, mt)
        comp = i in comp_idx
        rev = r.revenue if r.kind == "company" and pd.notna(r.revenue) and r.revenue > 0 and isinstance(r.fin_date, str) else 0.0
        avg = {m: metals.average(m, r.fin_date) for m in METALS} if rev else {}
        d = {"comp": comp, "revenue_used": rev}
        # Producers' cost increase: the same in every scenario (costs don't follow metal prices here).
        cost_fcf, cost_ocf = cost_change(rev, r.fcf, c), cost_change(rev, r.ocf, c)
        cost_ebitda = cost_change(rev, r.ebitda, c, share=1.0)
        d["cost_base_m"] = max(0.0, rev - r.fcf) / 1e6 if rev and pd.notna(r.fcf) else np.nan
        for name, P in scen.items():
            dr = revenue_change(rev, mix, P, avg) if rev else 0.0
            d[f"ocf_{name}"] = r.ocf + cf_k * dr + cost_ocf if pd.notna(r.ocf) else np.nan
            d[f"fcf_{name}"] = r.fcf + cf_k * dr + cost_fcf if pd.notna(r.fcf) else np.nan
            d[f"ebitda_{name}"] = r.ebitda + ebitda_k * dr + cost_ebitda if pd.notna(r.ebitda) else np.nan
            if name == "Today":
                d["revenue_change_today"] = dr
        # Breakeven: the multiple k of today's prices (all metals together) at which FCF = 0.
        # FCF(k) = a*k + b, with a = 0.7 x revenue x sum(share x today/average), b = FCF - 0.7 x revenue x sum(share).
        # Holdings without revenue have a = 0: their FCF doesn't move with metal prices.
        A = sum(sh * metals.spot[m] / avg[m] for m, sh in mix.items()) if rev else 0.0
        B = sum(mix.values())
        if pd.notna(r.fcf):
            d["a"], d["b"] = cf_k * rev * A, r.fcf - cf_k * rev * B + cost_fcf
        if rev and A > 0 and pd.notna(r.fcf):
            d["be_k"] = -d["b"] / d["a"]
            d["be_metal"] = max(mix, key=mix.get)
            d["be_price"] = d["be_k"] * metals.spot[d["be_metal"]]
        # Linear FCF in $M: intercept + per-$ coefficients, so the Sheet can recompute FCF at any prices.
        # The cost increase is left out: the Sheet subtracts it with cost_base_m (Holdings downside R).
        if r.kind == "company" and pd.notna(r.fcf):
            a0, b = r.fcf, {m: 0.0 for m in METALS}
            for m, sh in (mix.items() if rev else []):
                a0 -= cf_k * rev * sh
                b[m] += cf_k * rev * sh / avg[m]
            d["fcf_intercept_m"] = a0 / 1e6
            for m in METALS:
                d[f"fcf_per_{m}_m"] = b[m] / 1e6
        if comp:
            ser = (H.get(r.ticker) or {}).get("series") or {}
            d["netcash_pct"] = 100 * (r.cash - r.debt) / r.mcap
            ca = latest(ser, ["quarterlyCurrentAssets", "annualCurrentAssets"], FX)
            cl = latest(ser, ["quarterlyCurrentLiabilities", "annualCurrentLiabilities"], FX)
            if ca and cl and ca["date"] == cl["date"]:
                d["wc"] = ca["val"] * FX[ca["cur"]] - cl["val"] * FX[cl["cur"]]
                d["wc_pct"] = 100 * d["wc"] / r.mcap
            if pd.notna(r.ocf) and r.ocf < 0 and pd.notna(r.fcf) and r.fcf < 0:
                d["runway"] = r.cash / -r.fcf
            for y in (1, 3):
                v = share_change(ser, y, tol[y])
                d[f"dil{y}"] = None if v is None else 100 * v
        rows.append(d)
    return pd.concat([X, pd.DataFrame(rows, index=X.index)], axis=1)


def _wavg(c, col):
    v = c[c[col].notna()]
    return (v.weight_pct * v[col]).sum() / v.weight_pct.sum() if len(v) else np.nan


def _wmedian(c, col):
    """Median by fund weight: the value at which holdings below it make up half the covered weight, so the many
    tiny explorers don't dominate (the Stress test & downside tab's definition)."""
    v = c[c[col].notna()].sort_values(col)
    if not len(v):
        return np.nan
    cum = v.weight_pct.cumsum() / v.weight_pct.sum()
    return float(v.loc[cum >= 0.5, col].iloc[0])




def fund_table(M: pd.DataFrame, metals: Metals) -> pd.DataFrame:
    S = settings()
    out = []
    for f in S["holdings"]["fund_order"]:
        c = M[(M.fund == f) & M.comp]
        res = {"fund": f}
        for name in S["stress"]["scenarios"]:
            cc = c[c[f"fcf_{name}"].notna()]
            y = (cc.weight_pct * cc[f"fcf_{name}"] / cc.mcap).sum()
            res[f"P/FCF {name}"] = cc.weight_pct.sum() / y if y > 0 else np.nan
            res[f"FCF+ weight {name}"] = c.loc[c[f"fcf_{name}"] > 0, "weight_pct"].sum()
            cc = c[c[f"ebitda_{name}"].notna()]
            y = (cc.weight_pct * cc[f"ebitda_{name}"] / cc.mcap).sum()
            res[f"EV/EBITDA {name}"] = (cc.weight_pct * cc.ev / cc.mcap).sum() / y if y > 0 else np.nan
        # Fund breakeven: one multiple of today's prices at which the holdings' total FCF is zero.
        cc = c[c.fcf.notna()]
        wm = cc.weight_pct / cc.mcap
        k = -(wm * cc.b).sum() / (wm * cc.a).sum()
        metal = fund_metal()[f]
        res.update({"breakeven % of today": 100 * k, "breakeven price": k * metals.spot[metal],
                    "breakeven metal": UNIT[metal],
                    "net cash %": _wavg(c, "netcash_pct"), "working capital %": _wavg(c, "wc_pct"),
                    "burning cash %": c.loc[c.runway.notna(), "weight_pct"].sum(),
                    "runway < 2 yrs %": c.loc[c.runway < 2, "weight_pct"].sum()})
        for y in (1, 3):
            res[f"dil{y} wavg"], res[f"dil{y} median"] = _wavg(c, f"dil{y}"), _wmedian(c, f"dil{y}")
            res[f"dil{y} cov"] = c.loc[c[f"dil{y}"].notna(), "weight_pct"].sum()
        res["dil3 >20% weight"] = c.loc[c.dil3 > 20, "weight_pct"].sum()
        out.append(res)
    return pd.DataFrame(out).set_index("fund")


def multiples_today(M: pd.DataFrame) -> pd.DataFrame:
    """Fund P/OCF, P/FCF and EV/EBITDA as reported and at today's metal prices."""
    def agg(c, col):
        cc = c[c[col].notna()]
        y = (cc.weight_pct * cc[col] / cc.mcap).sum()
        return (cc.weight_pct.sum() / y if y > 0 else np.nan), cc, y
    out = []
    for f in settings()["holdings"]["fund_order"]:
        c = M[(M.fund == f) & M.comp]
        res = {"fund": f}
        for base, lab in (("ocf", "P/OCF"), ("fcf", "P/FCF")):
            res[lab] = agg(c, base)[0]
            res[lab + " today"] = agg(c, f"{base}_Today")[0]
        res["P/OCF today (positive only)"] = agg(c[c.ocf_Today > 0], "ocf_Today")[0]
        for col, lab in (("ebitda", "EV/EBITDA"), ("ebitda_Today", "EV/EBITDA today")):
            _, cc, y = agg(c, col)
            res[lab] = (cc.weight_pct * cc.ev / cc.mcap).sum() / y if y > 0 else np.nan
        p = c[c.revenue_used > 0]
        res["revenue change %"] = (100 * (p.weight_pct * p.revenue_change_today / p.mcap).sum()
                                   / (p.weight_pct * p.revenue_used / p.mcap).sum())
        out.append(res)
    return pd.DataFrame(out).set_index("fund")


def run(today: dict | None = None, cost_increase: float | None = None):
    ensure(DERIVED)
    X = pd.read_csv(DERIVED / "holdings_detail.csv")
    metals = Metals(today)
    M = per_holding(X, metals, cost_increase=cost_increase)
    M.to_csv(DERIVED / "stress_holdings.csv", index=False)
    F = fund_table(M, metals)
    F.to_csv(DERIVED / "stress_funds.csv")
    T = multiples_today(M)
    T.to_csv(DERIVED / "multiples_today.csv")
    (DERIVED / "metals_today.json").write_text(json.dumps({**metals.spot, "date": metals.date()}, indent=1))
    return M, F, T
