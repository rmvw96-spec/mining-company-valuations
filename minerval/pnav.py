"""Rick Rule-style price to net asset value (P/NAV), as on the P/NAV and PNAV inputs tabs.

NAV = cash flow x annuity factor over the reserve life (capped at 25 years) + net cash, where the
discount rate = 10-year Treasury yield + 3% + a jurisdiction add-on. Cash flow is free cash flow
(operating cash flow for royalty companies), re-estimated at each scenario's metal prices.
Developers have no cash flow: they are compared with their published study value instead.

Research inputs (stage, add-on, reserve life, outside NAVs and study values) are in
data/research/pnav_companies.csv. The Sheet holds the working copy of those inputs; this file is
the record, and is what the offline calculation here uses.
Writes data/derived/pnav.csv.
"""
import numpy as np
import pandas as pd

from .config import DERIVED, RESEARCH, ensure, settings
from .price_model import METALS, Metals, mix_for, mixes


def annuity(rate: float, years: float) -> float:
    return (1 - (1 + rate) ** -years) / rate


def show(mcap, nav):
    """The Sheet's display rule: 'negative' when NAV <= 0, '>20' above 20x."""
    if nav <= 0:
        return "negative"
    v = mcap / nav
    return ">20" if v > 20 else v


def inputs(X: pd.DataFrame, metals: Metals) -> pd.DataFrame:
    """The data columns of the PNAV inputs tab (E:H and J:O), one row per research row."""
    P = settings()["pnav"]
    R = pd.read_csv(RESEARCH / "pnav_companies.csv")
    D = X.drop_duplicates("ticker").set_index("ticker")
    mt = mixes()
    rows = []
    for _, r in R.iterrows():
        m = D.loc[r.ticker] if r.ticker in D.index else None
        has = m is not None and pd.notna(m.mcap)
        d = {"sheet_row": r.sheet_row, "ticker": r.ticker, "yahoo": r.yahoo, "holding": r.holding, "basis": r.basis}
        d["price_usd"] = r.fixed_price_usd if pd.notna(r.fixed_price_usd) else (m.price_usd if has else np.nan)
        if has and m.kind == "company":
            d["mcap_m"], d["net_cash_m"] = m.mcap / 1e6, (m.cash - m.debt) / 1e6
        if isinstance(r.basis, str) and r.basis:
            rev = float(m.revenue) if has and pd.notna(m.revenue) and m.revenue > 0 else 0.0
            mix = {} if r.ticker in P["no_metal_adjustment"] else mix_for(r.ticker, r.mix_fund, mt)
            d.update(revenue_m=rev / 1e6, fcf_m=m.fcf / 1e6, ocf_m=m.ocf / 1e6)
            for mtl in METALS:
                d[f"share_{mtl}"] = mix.get(mtl, 0.0) if rev > 0 else 0.0
                d[f"avg_{mtl}"] = metals.average(mtl, m.fin_date) if isinstance(m.fin_date, str) else metals.spot[mtl]
        rows.append(d)
    return R[["sheet_row", "fund", "mix_fund", "addon_pct_points", "reserve_life_years", "model_nav_per_share_usd",
              "study_value_usd_m"]].merge(pd.DataFrame(rows), on="sheet_row")


def compute(I: pd.DataFrame, metals: Metals, ten_year_yield: float | None = None) -> pd.DataFrame:
    """P/NAV at each scenario, as the PNAV inputs formulas compute it."""
    P = settings()["pnav"]
    k_cf = settings()["price_model"]["cash_flow_share"]
    y = P["ten_year_yield"] if ten_year_yield is None else ten_year_yield
    scen = {n: metals.scenario(n) for n in P["scenarios"]}
    out = []
    for _, r in I.iterrows():
        d = {"sheet_row": r.sheet_row}
        if isinstance(r.basis, str) and r.basis:
            rate = y + P["risk_premium"] + r.addon_pct_points / 100
            n = min(r.reserve_life_years, P["max_years"])
            ann, ann10 = annuity(rate, n), annuity(rate, P["short_years"])
            base = r.ocf_m if r.basis == "OCF" else r.fcf_m
            d.update(discount_rate=rate, years=n)
            for name, px in scen.items():
                chg = k_cf * r.revenue_m * sum(r[f"share_{m}"] * (px[m] / r[f"avg_{m}"] - 1) for m in METALS)
                d[f"pnav {name}"] = show(r.mcap_m, (base + chg) * ann + r.net_cash_m)
                if name == "Today":
                    d["pnav Today, 10 years"] = show(r.mcap_m, (base + chg) * ann10 + r.net_cash_m)
                    d["pnav Today, before capital spending"] = show(r.mcap_m, (r.ocf_m + chg) * ann + r.net_cash_m)
        if pd.notna(r.model_nav_per_share_usd):
            d["independent or study pnav"] = r.price_usd / r.model_nav_per_share_usd
        elif pd.notna(r.study_value_usd_m):
            d["independent or study pnav"] = r.mcap_m / (r.study_value_usd_m + r.net_cash_m)
        out.append(d)
    return I.merge(pd.DataFrame(out), on="sheet_row")


def run(today: dict | None = None):
    ensure(DERIVED)
    X = pd.read_csv(DERIVED / "holdings_detail.csv")
    metals = Metals(today)
    T = compute(inputs(X, metals), metals)
    T.to_csv(DERIVED / "pnav.csv", index=False)
    return T
