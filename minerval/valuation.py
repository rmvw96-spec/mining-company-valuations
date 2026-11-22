"""Valuation by tier (roadmap 6, docs/specs/tier-valuation-spec.md): EV against a 10-year NPV at the user's
pessimistic, base and optimistic price decks ([valuation] decks, set metal by metal in [scenarios]; nothing here
depends on their values). Spot is only a cross-check, never the basis.

Producers (Part 2): cash flow = operating cash flow (trailing 12 months) − sustaining spending (research:
pnav_companies.csv `sustaining_capex_usd_m`, built by `research sustaining`), or free cash flow where sustaining
isn't recorded (labelled), re-priced from the reporting period's average metal prices to each deck by revenue mix
(cash_flow_share × revenue × the price change, as pnav.py does). The pessimistic deck also raises costs by
[valuation] pessimistic_cost_increase (price_model.cost_change). NPV = that cash flow for min(reserve life,
horizon_years) years at the discount rate, with no terminal value; net cash isn't added, because EV nets it.
"""
from .config import settings
from .pnav import _num, annuity
from .price_model import METALS, cost_change

OCF_BASIS = "OCF − sustaining"
FCF_BASIS = "FCF basis: sustaining not recorded"


def cfg() -> dict:
    return settings()["valuation"]


def decks(scenarios: dict | None = None, names: list | None = None) -> dict:
    """{deck: {metal: price}} for each of [valuation] decks, from [scenarios]. Each metal is set on its own."""
    S = settings()["scenarios"] if scenarios is None else scenarios
    out = {}
    for n in cfg()["decks"] if names is None else names:
        if n not in S:
            raise ValueError(f"[scenarios] has no {n} deck: set its gold, silver and copper prices")
        miss = [m for m in METALS if not isinstance(S[n].get(m), (int, float))]
        if miss:
            raise ValueError(f"[scenarios] {n} has no {', '.join(miss)} price")
        out[n] = {m: float(S[n][m]) for m in METALS}
    return out


def npv(cash_flow: float, rate: float, years: float, horizon: float | None = None) -> float:
    """A level cash flow for min(years, horizon) years at `rate`, with no terminal value."""
    return cash_flow * annuity(rate, min(years, cfg()["horizon_years"] if horizon is None else horizon))


def ev_to_npv(ev, npv_):
    """EV ÷ NPV; "negative NPV" when the NPV is zero or below; None without an NPV."""
    if npv_ is None:
        return None
    return "negative NPV" if npv_ <= 0 else ev / npv_


def producer_cash_flow(r, prices: dict, cost_increase: float = 0.0) -> tuple[float | None, str]:
    """(cash flow at `prices`, its basis): OCF − sustaining when sustaining is recorded, else FCF (labelled)."""
    sus, ocf, fcf = r.get("sustaining_capex_usd_m"), r.get("ocf_m"), r.get("fcf_m")
    if _num(sus) and _num(ocf):
        base, basis = ocf - sus, OCF_BASIS
    elif _num(fcf):
        base, basis = fcf, FCF_BASIS
    else:
        return None, "no cash flow"
    rev = r.get("revenue_m")
    rev = rev if _num(rev) and rev > 0 else 0.0
    k = settings()["price_model"]["cash_flow_share"]
    chg = k * rev * sum(r[f"share_{m}"] * (prices[m] / r[f"avg_{m}"] - 1) for m in METALS if r.get(f"share_{m}"))
    return base + chg + cost_change(rev, base, cost_increase), basis


def producer_valuation(r, deck_prices: dict, rate: float) -> dict:
    """NPV and EV / NPV at each deck, the basis, the sustaining FCF yield (base-deck cash flow ÷ EV) and the
    downside test (EV ≤ the pessimistic NPV with costs raised)."""
    c = cfg()
    out = {f"npv {d}": None for d in deck_prices} | {f"ev/npv {d}": None for d in deck_prices}
    out.update(npv_basis="", sustaining_fcf_yield=None, downside_ok=None, why="")
    years, ev = r.get("reserve_life_years"), r.get("ev_m")
    if not (_num(years) and years > 0):
        return out | {"why": "no reserve life"}
    for d, px in deck_prices.items():
        cf, basis = producer_cash_flow(r, px, c["pessimistic_cost_increase"] if d == c["pessimistic_deck"] else 0.0)
        if cf is None:
            return out | {"why": basis}
        out[f"npv {d}"] = npv(cf, rate, years)
        out[f"ev/npv {d}"] = ev_to_npv(ev, out[f"npv {d}"]) if _num(ev) else None
        out["npv_basis"] = basis
        if d == c["base_deck"] and _num(ev) and ev > 0:
            out["sustaining_fcf_yield"] = cf / ev
    pess = out.get(f"npv {c['pessimistic_deck']}")
    if _num(ev) and pess is not None:
        out["downside_ok"] = bool(pess > 0 and ev <= pess)
    return out

