"""Rick Rule-style price to net asset value (P/NAV), as on the P/NAV and PNAV inputs tabs.

NAV = cash flow x annuity factor over the reserve life (capped at 25 years) + net cash, where the
discount rate = 10-year Treasury yield + 3% + a jurisdiction add-on. Cash flow is free cash flow
(operating cash flow for royalty companies), re-estimated at each scenario's metal prices.
Developers have no cash flow: they are compared with their published study value instead.

A producers' cost increase c (price_model.cost_increase) lowers the cash-flow change by
cash_flow_share x (revenue - FCF) x c, on FCF-basis rows only (royalty companies and developers are left alone).

Royalty/streaming companies (OCF basis) also get a band from their independent P/NAV (buy zone up to 1.4x,
normal range up to 2.2x, else rich: signals.thresholds.royalty_pnav_median) and a buy-below price.
Developers get EV per ounce in the ground (resource columns in the research file) and months of cash.

Research inputs (stage, add-on, reserve life, outside NAVs and study values) are in
data/research/pnav_companies.csv. The Sheet holds the working copy of those inputs; this file is
the record, and is what the offline calculation here uses.
Writes data/derived/pnav.csv.
"""
import numpy as np
import pandas as pd

from .config import DERIVED, RESEARCH, ensure, settings
from .price_model import METALS, Metals, cost_change, cost_increase_default, mix_for, mixes


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
            d["cash_m"] = m.cash / 1e6
            d["fcf_12m_m"] = m.fcf / 1e6 if pd.notna(m.fcf) else np.nan
        if isinstance(r.basis, str) and r.basis:
            rev = float(m.revenue) if has and pd.notna(m.revenue) and m.revenue > 0 else 0.0
            mix = {} if r.ticker in P["no_metal_adjustment"] else mix_for(r.ticker, r.mix_fund, mt)
            d.update(revenue_m=rev / 1e6, fcf_m=m.fcf / 1e6, ocf_m=m.ocf / 1e6)
            for mtl in METALS:
                d[f"share_{mtl}"] = mix.get(mtl, 0.0) if rev > 0 else 0.0
                d[f"avg_{mtl}"] = metals.average(mtl, m.fin_date) if isinstance(m.fin_date, str) else metals.spot[mtl]
        rows.append(d)
    keep = ["sheet_row", "fund", "mix_fund", "addon_pct_points", "reserve_life_years", "model_nav_per_share_usd",
            "study_value_usd_m", "fixed_price_usd"] + [c for c in RESOURCE_COLS if c in R.columns]
    return R[keep].merge(pd.DataFrame(rows), on="sheet_row")


RESOURCE_COLS = ["resource_amount", "resource_unit", "resource_category", "resource_source", "resource_date"]
RESOURCE_UNITS = ["oz Au", "oz AuEq", "oz AgEq", "lb Cu", "lb CuEq"]
RESOURCE_CATEGORIES = ["Reserves", "Measured & indicated", "Measured, indicated & inferred", "Mixed", "Inferred"]


def royalty_band(pnav, g: float, h: float) -> str:
    if pnav is None or pd.isna(pnav):
        return "no independent NAV"
    return "Buy zone" if pnav <= g else "Normal range" if pnav <= h else "Rich"


def months_of_cash(cash_m, fcf_m):
    """Months of cash at the last 12 months' burn, or "Cash-generating"; None without data."""
    if cash_m is None or fcf_m is None or pd.isna(cash_m) or pd.isna(fcf_m):
        return None
    return cash_m / -fcf_m * 12 if fcf_m < 0 else "Cash-generating"


def developer_check(months, cash_share, short: float, ok: float, near_cash: float) -> str:
    if months is None:
        return ""
    if isinstance(months, str):
        txt = "Enough cash"
    else:
        txt = "Short of cash: financing likely" if months < short else "Watch" if months < ok else "Enough cash"
    if cash_share is not None and not pd.isna(cash_share) and cash_share >= near_cash:
        txt += "; trading near cash"
    return txt


def ev_per_aueq_oz(ev_per_unit, unit, gold_silver_ratio):
    if ev_per_unit is None or pd.isna(ev_per_unit):
        return np.nan
    if unit in ("oz Au", "oz AuEq"):
        return ev_per_unit
    if unit == "oz AgEq":
        return ev_per_unit * gold_silver_ratio
    return np.nan                       # copper units: EV per lb only


def compute(I: pd.DataFrame, metals: Metals, ten_year_yield: float | None = None,
            cost_increase: float | None = None) -> pd.DataFrame:
    """P/NAV at each scenario, as the PNAV inputs formulas compute it."""
    P = settings()["pnav"]
    k_cf = settings()["price_model"]["cash_flow_share"]
    c = cost_increase_default(cost_increase)
    SG = settings()["signals"]
    g, h = SG["thresholds"]["royalty_pnav_median"]
    inp = SG["inputs"]
    gsr = metals.spot["gold"] / metals.spot["silver"]
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
            cost = cost_change(r.revenue_m, r.fcf_m, c) if r.basis == "FCF" else 0.0
            d.update(discount_rate=rate, years=n)
            for name, px in scen.items():
                chg = k_cf * r.revenue_m * sum(r[f"share_{m}"] * (px[m] / r[f"avg_{m}"] - 1) for m in METALS) + cost
                d[f"pnav {name}"] = show(r.mcap_m, (base + chg) * ann + r.net_cash_m)
                if name == "Today":
                    d["pnav Today, 10 years"] = show(r.mcap_m, (base + chg) * ann10 + r.net_cash_m)
                    d["pnav Today, before capital spending"] = show(r.mcap_m, (r.ocf_m + chg) * ann + r.net_cash_m)
        if pd.notna(r.model_nav_per_share_usd):
            d["independent or study pnav"] = r.price_usd / r.model_nav_per_share_usd
        elif pd.notna(r.study_value_usd_m):
            d["independent or study pnav"] = r.mcap_m / (r.study_value_usd_m + r.net_cash_m)
        ind = d.get("independent or study pnav")
        # Part 2: royalty band and buy-below price (the Sheet's PNAV inputs AS and AR)
        if r.basis == "OCF":
            d["royalty_band"] = royalty_band(ind, g, h)
            if pd.notna(r.model_nav_per_share_usd):
                d["buy_below_price_usd"] = g * r.model_nav_per_share_usd
        # Part 4: EV per unit in the ground and months of cash (PNAV inputs AZ:BE)
        mcap, nc = r.get("mcap_m"), r.get("net_cash_m")
        if pd.notna(mcap) and pd.notna(nc):
            d["ev_m"] = mcap - nc
            amt = r.get("resource_amount")
            if pd.notna(amt) and amt > 0:
                d["ev_per_unit"] = d["ev_m"] / amt
                d["ev_per_aueq_oz"] = ev_per_aueq_oz(d["ev_per_unit"], r.get("resource_unit"), gsr)
        moc = months_of_cash(r.get("cash_m"), r.get("fcf_12m_m"))
        if moc is not None:
            d["months_of_cash"] = moc
        if pd.notna(mcap) and mcap > 0 and pd.notna(r.get("cash_m")):
            d["cash_share"] = r.cash_m / mcap
        developer = (not isinstance(r.basis, str) or not r.basis) and pd.isna(r.get("fixed_price_usd")) \
            and ind is not None and pd.notna(ind)
        if developer:
            d["developer_check"] = developer_check(moc, d.get("cash_share"), inp["runway_short_months"],
                                                   inp["runway_ok_months"], inp["near_cash_share"])
        out.append(d)
    return I.merge(pd.DataFrame(out), on="sheet_row")


def run(today: dict | None = None, cost_increase: float | None = None):
    ensure(DERIVED)
    X = pd.read_csv(DERIVED / "holdings_detail.csv")
    metals = Metals(today)
    T = compute(inputs(X, metals), metals, cost_increase=cost_increase)
    T.to_csv(DERIVED / "pnav.csv", index=False)
    return T
