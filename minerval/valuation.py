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
ROYALTY_BASIS = "OCF (royalty)"


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


def _price_change(r, prices: dict) -> float:
    """Cash-flow change moving from the reporting period's average metal prices to `prices`, by revenue mix."""
    rev = r.get("revenue_m")
    rev = rev if _num(rev) and rev > 0 else 0.0
    k = settings()["price_model"]["cash_flow_share"]
    return k * rev * sum(r[f"share_{m}"] * (prices[m] / r[f"avg_{m}"] - 1) for m in METALS if r.get(f"share_{m}"))


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
    return base + _price_change(r, prices) + cost_change(rev, base, cost_increase), basis


def royalty_cash_flow(r, prices: dict) -> tuple[float | None, str]:
    """Operating cash flow at `prices`: royalties carry no sustaining spending and no operating-cost increase."""
    ocf = r.get("ocf_m")
    return (ocf + _price_change(r, prices), ROYALTY_BASIS) if _num(ocf) else (None, "no cash flow")


def _valuation(deck_prices: dict, rate: float, years: float, ev, cash_flow, extra: dict | None = None) -> dict:
    """NPV and EV / NPV at each deck from `cash_flow(deck, prices)`, plus the base-deck cash flow ÷ EV and the
    downside test (EV ≤ the pessimistic NPV)."""
    c = cfg()

    def blank(why: str = "") -> dict:
        return {f"npv {d}": None for d in deck_prices} | {f"ev/npv {d}": None for d in deck_prices} | {
            "npv_basis": "", "sustaining_fcf_yield": None, "downside_ok": None, "why": why}
    out = blank()
    for d, px in deck_prices.items():
        cf, basis = cash_flow(d, px)
        if cf is None:
            return blank(basis)
        out[f"npv {d}"] = npv(cf, rate, years) + (extra or {}).get(d, 0.0)
        out[f"ev/npv {d}"] = ev_to_npv(ev, out[f"npv {d}"]) if _num(ev) else None
        out["npv_basis"] = basis
        if d == c["base_deck"] and _num(ev) and ev > 0:
            out["sustaining_fcf_yield"] = cf / ev
    pess = out.get(f"npv {c['pessimistic_deck']}")
    if _num(ev) and pess is not None:
        out["downside_ok"] = bool(pess > 0 and ev <= pess)
    return out


def producer_valuation(r, deck_prices: dict, rate: float, pipeline: dict | None = None) -> dict:
    """NPV and EV / NPV at each deck over min(reserve life, horizon), the basis, the sustaining FCF yield (base-deck
    cash flow ÷ EV) and the downside test (EV ≤ the pessimistic NPV with costs raised). `pipeline` ({deck: US$M},
    from pipeline()) adds committed projects."""
    c = cfg()
    years = r.get("reserve_life_years")
    if not (_num(years) and years > 0):
        return _valuation(deck_prices, rate, 1.0, None, lambda d, px: (None, "no reserve life"))

    def cf(d, px):
        return producer_cash_flow(r, px, c["pessimistic_cost_increase"] if d == c["pessimistic_deck"] else 0.0)
    return _valuation(deck_prices, rate, years, r.get("ev_m"), cf, pipeline)


def royalty_valuation(r, deck_prices: dict, rate: float) -> dict:
    """Part 4: NPV of operating cash flow over horizon_years at each deck (not the reserve life: a royalty's
    portfolio outlives any one mine), EV / NPV, and the downside test at the pessimistic deck."""
    return _valuation(deck_prices, rate, cfg()["horizon_years"], r.get("ev_m"),
                      lambda d, px: royalty_cash_flow(r, px))


def buy_levels(tier: str, npv_base, npv_pessimistic=None, net_cash_m=None, shares_m=None, overrun_ok=None) -> dict:
    """Part 5, per share: buy-below = (min(buy × base NPV, pessimistic NPV) + net cash) ÷ shares, the highest price
    meeting both conditions (developers: buy × base risk-adjusted NPV, only when the capex-overrun test passes);
    fair value = (fair × base NPV + net cash) ÷ shares. Levels from [valuation.buy]. None, with why, otherwise."""
    L = cfg()["buy"][tier]
    out = {"buy_below": None, "fair_value": None, "binding": "", "why": ""}
    if npv_base is None:
        return out | {"why": "no NPV"}
    if npv_base <= 0:
        return out | {"why": "negative NPV at the base deck"}
    if not (_num(shares_m) and shares_m > 0):
        return out | {"why": "no share count"}
    nc = net_cash_m if _num(net_cash_m) else 0.0
    out["fair_value"] = (L["fair"] * npv_base + nc) / shares_m
    disc = L["buy"] * npv_base
    if tier == "developer":
        if overrun_ok is None:
            return out | {"why": "no capex-overrun test (no remaining capex recorded)"}
        if not overrun_ok:
            return out | {"why": "fails the capex-overrun test"}
        cap, binding = disc, "discount"
    elif npv_pessimistic is None:
        return out | {"why": "no pessimistic NPV"}
    else:
        cap, binding = (disc, "discount") if disc <= npv_pessimistic else (npv_pessimistic, "downside test")
    price = (cap + nc) / shares_m
    if price <= 0:
        return out | {"why": "fails the downside test at any price"}
    return out | {"buy_below": price, "binding": binding}


def validation_flags(npv_base, net_cash_m, shares_m, independent_nav=None, consensus_pnav=None, price=None,
                     factor: float | None = None) -> list[str]:
    """Our NAV per share at the base deck ((NPV + net cash) ÷ shares) against the independent NAV per share (PNAV
    inputs R) and the consensus NAV implied by the consensus P/NAV (P_NAV I): one line for each more than `factor`
    ([valuation] check_factor) away, so a bad input shows before it reaches a buy signal."""
    f = cfg()["check_factor"] if factor is None else factor
    if npv_base is None or not (_num(shares_m) and shares_m > 0):
        return []
    ours = (npv_base + (net_cash_m if _num(net_cash_m) else 0.0)) / shares_m
    others = []
    if _num(independent_nav) and independent_nav > 0:
        others.append(("independent NAV", independent_nav))
    if _num(consensus_pnav) and consensus_pnav > 0 and _num(price) and price > 0:
        others.append(("consensus NAV", price / consensus_pnav))
    out = []
    for name, v in others:
        if ours <= 0:
            out.append(f"NAV -${abs(ours):.2f}/share against the {name} (${v:.2f})")
        elif ours / v > f or ours / v < 1 / f:
            out.append(f"NAV ${ours:.2f}/share is {ours / v:.1f}x the {name} (${v:.2f})")
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
