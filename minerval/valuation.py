"""Valuation by tier (roadmap 6, docs/specs/tier-valuation-spec.md): EV against a 10-year NPV at the user's
pessimistic, base and optimistic price decks ([valuation] decks, set metal by metal in [scenarios]; nothing here
depends on their values). Spot is only a cross-check, never the basis.

Producers (Part 2): cash flow = operating cash flow (trailing 12 months) − sustaining spending (research:
pnav_companies.csv `sustaining_capex_usd_m`, built by `research sustaining`), or free cash flow where sustaining
isn't recorded (labelled), re-priced from the reporting period's average metal prices to each deck by revenue mix
(cash_flow_share × revenue × the price change, as pnav.py does). The pessimistic deck also raises costs by
[valuation] pessimistic_cost_increase (price_model.cost_change). NPV = that cash flow for min(reserve life,
horizon_years) years at the discount rate, with no terminal value; net cash isn't added, because EV nets it.
A committed growth project (projects.csv `committed` = yes: a construction decision and a published study) adds
its risk-adjusted study NPV at the company's share (minerval/studies.py).

Developers (Part 3, steps 7-8): the funding gap with remaining capex raised by each of [valuation] capex_overrun,
funded by an equity raise at the Signals input raise_discount; the downside test passes when the dilution at the
largest overrun is at most max_overrun_dilution. Capex-to-market cap = remaining capex ÷ market cap.
"""
from .config import settings
from .pnav import _num, annuity, funding_gap, raise_after
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


def producer_valuation(r, deck_prices: dict, rate: float, pipeline: dict | None = None) -> dict:
    """NPV and EV / NPV at each deck, the basis, the sustaining FCF yield (base-deck cash flow ÷ EV) and the
    downside test (EV ≤ the pessimistic NPV with costs raised). `pipeline` ({deck: US$M}, from pipeline()) adds
    committed projects."""
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
        out[f"npv {d}"] = npv(cf, rate, years) + (pipeline or {}).get(d, 0.0)
        out[f"ev/npv {d}"] = ev_to_npv(ev, out[f"npv {d}"]) if _num(ev) else None
        out["npv_basis"] = basis
        if d == c["base_deck"] and _num(ev) and ev > 0:
            out["sustaining_fcf_yield"] = cf / ev
    pess = out.get(f"npv {c['pessimistic_deck']}")
    if _num(ev) and pess is not None:
        out["downside_ok"] = bool(pess > 0 and ev <= pess)
    return out



def pipeline(ticker: str, deck_prices: dict, rate: float, today, P=None, C=None) -> tuple[dict, list[str]]:
    """({deck: risk-adjusted NPV of the company's committed, unsuperseded projects}, [projects left out, and why]).
    A project counts only when it can be valued at every deck."""
    from . import studies as S
    if P is None:
        P, C = S.load()
    out, why = {d: 0.0 for d in deck_prices}, []
    yes = P.committed.astype(str).str.strip().str.lower().eq("yes")
    live = P.superseded.astype(str).str.strip().eq("")
    for _, p in P[P.ticker.eq(ticker) & yes & live].iterrows():
        F = S.flows(C, p)
        got = {d: S.risk_adjusted(p, F, px, rate, today) for d, px in deck_prices.items()}
        bad = next((x["why"] for x in got.values() if x["risk_adjusted"] is None), None)
        if bad is not None:
            why.append(f"{p.project}: {bad}")
            continue
        for d, x in got.items():
            out[d] += x["risk_adjusted"]
    return out, why


def overrun(remaining_capex_m, cash_m, committed_m, price, mcap_m, discount: float | None = None) -> dict:
    """Dilution of an equity raise for the funding gap at each capex overrun, the downside test, and capex ÷ market
    cap. A gap at or below zero needs no raise (no dilution)."""
    c = cfg()
    d = settings()["signals"]["inputs"]["raise_discount"] if discount is None else discount
    out = {f"dilution +{o:.0%}": None for o in c["capex_overrun"]} | {"overrun_ok": None, "capex_to_mcap": None,
                                                                      "why": ""}
    if not _num(remaining_capex_m):
        return out | {"why": "no remaining capex recorded"}
    for o in c["capex_overrun"]:
        x = raise_after(funding_gap(remaining_capex_m * (1 + o), cash_m, committed_m), price, mcap_m, None, d)
        out[f"dilution +{o:.0%}"] = x.get("dilution")
    worst = out[f"dilution +{max(c['capex_overrun']):.0%}"]
    if worst is not None:
        out["overrun_ok"] = bool(worst <= c["max_overrun_dilution"])
    if _num(mcap_m) and mcap_m > 0:
        out["capex_to_mcap"] = remaining_capex_m / mcap_m
    return out
