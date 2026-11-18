"""How a change in metal prices flows through to a producer's cash flow.

revenue change = revenue x sum over metals of (share of revenue x (new price / average price - 1)),
where the average price is over the 12 months the company's reported figures cover. A set share of
that change (config: price_model) reaches EBITDA and cash flow. Costs, output, capital spending and
hedges are held fixed: these are sensitivities, not forecasts.

A cost increase c (config: price_model.cost_increase) lowers cash flow by share x (revenue - cash flow) x c:
revenue - FCF is everything the company spends (operating costs, taxes, capital spending), and costs are
tax-deductible, so the same share reaches cash flow. Taxes don't inflate, so this slightly overstates it.
"""
import json

import pandas as pd

from .config import CACHE, fund_metal, settings, table

METALS = ("gold", "silver", "copper")


class Metals:
    """Daily COMEX closes and the latest price for gold, silver and copper."""

    def __init__(self, today: dict | None = None):
        self.px, self.spot = {}, {}
        for metal, sym in settings()["yahoo"]["metals"].items():
            r = json.loads((CACHE / "metals" / f"{sym}_daily.json").read_text())["chart"]["result"][0]
            q = r["indicators"]["quote"][0]["close"]
            self.px[metal] = pd.Series(q, index=pd.to_datetime(r["timestamp"], unit="s").normalize()).dropna()
            self.spot[metal] = r["meta"]["regularMarketPrice"]
        if today:
            self.spot.update(today)

    def average(self, metal: str, end) -> float:
        """Average close over the window ending on a company's reporting date."""
        end = pd.Timestamp(end)
        days = settings()["price_model"]["average_window_days"]
        s = self.px[metal]
        return s[(s.index > end - pd.Timedelta(days=days)) & (s.index <= end)].mean()

    def scenario(self, name: str) -> dict:
        return dict(self.spot) if name == "Today" else dict(settings()["scenarios"][name])


def mixes() -> dict:
    """{ticker: {metal: revenue share}} from config/metal_mix.csv (an all-blank row means no adjustment)."""
    out = {}
    for _, r in table("metal_mix.csv").iterrows():
        out[r.ticker] = {m: float(r[m]) for m in METALS if pd.notna(r[m])}
    return out


def mix_for(ticker: str, fund: str, table_: dict | None = None) -> dict:
    t = mixes() if table_ is None else table_
    if ticker in t:
        return t[ticker]
    return dict(settings()["price_model"]["default_mix"][fund_metal()[fund]])


def revenue_change(rev: float, mix: dict, prices: dict, avg: dict) -> float:
    """Revenue change moving from each metal's average price to `prices`."""
    if not rev or rev <= 0:
        return 0.0
    return rev * sum(sh * (prices[m] / avg[m] - 1) for m, sh in mix.items())


def cost_change(revenue: float, cash_flow: float, cost_increase: float, share: float | None = None) -> float:
    """Change in a cash-flow measure when costs rise by `cost_increase`: -share x max(0, revenue - cash_flow) x c.

    share defaults to price_model.cash_flow_share; use 1.0 for EBITDA (before tax). Zero without revenue."""
    if not revenue or revenue <= 0 or cash_flow is None or pd.isna(cash_flow):
        return 0.0
    k = settings()["price_model"]["cash_flow_share"] if share is None else share
    return -k * max(0.0, revenue - cash_flow) * cost_increase


def cost_increase_default(value: float | None = None) -> float:
    return settings()["price_model"].get("cost_increase", 0.0) if value is None else value
