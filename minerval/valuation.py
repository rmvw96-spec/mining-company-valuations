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

Royalties (Part 4): base-deck operating cash flow as a perpetuity at the discount rate, with no growth (new deals
and discoveries are upside).

Developers (Part 3, steps 7-8, Rule's financing-adjusted test): the funding gap at each of [valuation]
capex_overrun is financed with [valuation] equity_share in equity (Rule's model: 35%, the rest debt), raised at the
Signals input raise_discount. The buy-below price is the value per share after the +30% case: (buy × risk-adjusted
NPV − the overrun's extra capex + net cash + the equity raised) ÷ (shares + new shares); fair value is the same at
the study's capex. Capex-to-market cap = remaining capex ÷ market cap.
"""
import pandas as pd

from .config import DERIVED, OUT, RESEARCH, ensure, settings
from .pnav import _num, annuity, funding_gap
from .price_model import METALS, cost_change

OCF_BASIS = "OCF − sustaining"
FCF_BASIS = "FCF basis: sustaining not recorded"
ROYALTY_BASIS = "OCF (royalty)"
STUDY_BASIS = "study (risk-adjusted)"


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


def cost_increase_note() -> str:
    """What the report says when the pessimistic cost increase hasn't been set (the deck then uses reported costs)."""
    return "" if cfg().get("pessimistic_cost_increase") is not None else \
        "[valuation] pessimistic_cost_increase isn't set: the pessimistic deck uses reported costs"


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


def _valuation(deck_prices: dict, rate: float, years: float, ev, cash_flow, extra: dict | None = None,
               value=None) -> dict:
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
        out[f"npv {d}"] = (value(cf) if value else npv(cf, rate, years)) + (extra or {}).get(d, 0.0)
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
        return producer_cash_flow(r, px, (c.get("pessimistic_cost_increase") or 0.0) if d == c["pessimistic_deck"]
                                  else 0.0)
    return _valuation(deck_prices, rate, years, r.get("ev_m"), cf, pipeline)


def royalty_valuation(r, deck_prices: dict, rate: float) -> dict:
    """Part 4: base-deck operating cash flow as a perpetuity at `rate` (no growth: a royalty portfolio outlives any
    one mine, and new deals and discoveries are the upside), EV / NPV, and the downside test at the pessimistic
    deck."""
    return _valuation(deck_prices, rate, 0.0, r.get("ev_m"), lambda d, px: royalty_cash_flow(r, px),
                      value=lambda cf: cf / rate)


def buy_levels(tier: str, npv_base, npv_pessimistic=None, net_cash_m=None, shares_m=None,
               financing: dict | None = None) -> dict:
    """Part 5, per share. Producers and royalties: buy-below = (min(buy × base NPV, pessimistic NPV) + net cash) ÷
    shares, fair value = (fair × base NPV + net cash) ÷ shares. Developers (Rule's financing-adjusted test, from
    overrun()["cases"]): buy-below = (buy × NPV − overrun capex + net cash + equity raised) ÷ (shares + new shares) in
    the +30% case ("worst"), fair value the same at the study's capex ("base"). Levels from [valuation.buy]."""
    L = cfg()["buy"][tier]
    out = {"buy_below": None, "fair_value": None, "binding": "", "why": ""}
    if npv_base is None:
        return out | {"why": "no NPV"}
    if npv_base <= 0:
        return out | {"why": "negative NPV at the base deck"}
    if not (_num(shares_m) and shares_m > 0):
        return out | {"why": "no share count"}
    nc = net_cash_m if _num(net_cash_m) else 0.0
    if tier == "developer":
        if not financing:
            return out | {"why": "no remaining capex recorded: the build's dilution can't be priced"}

        def per_share(mult, f):
            return (mult * npv_base - f["overrun_cost_m"] + nc + f["equity_m"]) / (shares_m + f["new_shares_m"])
        out["fair_value"] = per_share(L["fair"], financing["base"])
        price = per_share(L["buy"], financing["worst"])
        if price <= 0:
            return out | {"why": "negative value per share after a +30% overrun"}
        return out | {"buy_below": price, "binding": "financing at a +30% overrun"}
    out["fair_value"] = (L["fair"] * npv_base + nc) / shares_m
    if npv_pessimistic is None:
        return out | {"why": "no pessimistic NPV"}
    disc = L["buy"] * npv_base
    cap, binding = (disc, "discount") if disc <= npv_pessimistic else (npv_pessimistic, "downside test")
    price = (cap + nc) / shares_m
    if price <= 0:
        return out | {"why": "fails the downside test at any price"}
    return out | {"buy_below": price, "binding": binding}


def nav_per_share(npv_base, net_cash_m, shares_m) -> float | None:
    """Our NAV per share at the base deck: (NPV + net cash, less minority interest) ÷ shares (own-nav-first)."""
    if npv_base is None or not _num(npv_base) or not (_num(shares_m) and shares_m > 0):
        return None
    return (npv_base + (net_cash_m if _num(net_cash_m) else 0.0)) / shares_m


def validation_flags(npv_base, net_cash_m, shares_m, independent_nav=None, consensus_pnav=None, price=None,
                     factor: float | None = None) -> list[str]:
    """Our NAV per share at the base deck ((NPV + net cash) ÷ shares) against the independent NAV per share (PNAV
    inputs R) and the consensus NAV implied by the consensus P/NAV (P_NAV I): one line for each more than `factor`
    ([valuation] check_factor) away, so a bad input shows before it reaches a buy signal."""
    f = cfg()["check_factor"] if factor is None else factor
    ours = nav_per_share(npv_base, net_cash_m, shares_m)
    if ours is None:
        return []
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


def _projects_value(ticker: str, deck_prices: dict, rate: float, today, P, C, committed_only: bool):
    """({deck: sum of risk-adjusted study NPVs}, [projects left out, and why], number valued) for a company's
    unsuperseded projects (only committed ones when `committed_only`). A project counts only when it can be valued
    at every deck."""
    from . import studies as S
    out, why, n = {d: 0.0 for d in deck_prices}, [], 0
    sel = P.ticker.eq(ticker) & P.superseded.astype(str).str.strip().eq("")
    if committed_only:
        sel &= P.committed.astype(str).str.strip().str.lower().eq("yes")
    for _, p in P[sel].iterrows():
        F = S.flows(C, p)
        base = S.baseline(P, C, p)
        got = {d: S.risk_adjusted(p, F, px, rate, today, base) for d, px in deck_prices.items()}
        bad = next((x["why"] for x in got.values() if x["risk_adjusted"] is None), None)
        if bad is not None:
            why.append(f"{p.project}: {bad}")
            continue
        n += 1
        for d, x in got.items():
            out[d] += x["risk_adjusted"]
    return out, why, n


def pipeline(ticker: str, deck_prices: dict, rate: float, today, P=None, C=None) -> tuple[dict, list[str]]:
    """({deck: risk-adjusted NPV of the company's committed, unsuperseded projects}, [projects left out, and why])."""
    if P is None:
        from . import studies as S
        P, C = S.load()
    out, why, _ = _projects_value(ticker, deck_prices, rate, today, P, C, committed_only=True)
    return out, why


def developer_valuation(ticker: str, deck_prices: dict, rate: float, today, P, C) -> dict:
    """Part 3: the sum of the company's risk-adjusted study NPVs at each deck (each study rebuilt at our rate and the
    deck, discounted for time and probability by stage, at its share)."""
    v, why, n = _projects_value(ticker, deck_prices, rate, today, P, C, committed_only=False)
    if n == 0:
        return {f"npv {d}": None for d in deck_prices} | {"why": "; ".join(why) or "no study recorded"}
    return {f"npv {d}": v[d] for d in deck_prices} | {"why": "; ".join(why)}


def overrun(remaining_capex_m, cash_m, committed_m, price, mcap_m, discount: float | None = None) -> dict:
    """The build's financing at the study's capex and at each capex overrun (Rule's model): the funding gap
    (capex × (1 + overrun) − cash − committed funding) is financed with [valuation] equity_share in equity at
    `discount` to today's price, the rest debt. "cases" maps each overrun (0 = the study) to the equity raised, the new
    shares and the overrun's extra capex; dilution at each overrun and capex ÷ market cap are for information, with
    a note when the +30% raise more than doubles the share count."""
    c = cfg()
    d = settings()["signals"]["inputs"]["raise_discount"] if discount is None else discount
    out = {f"dilution +{o:.0%}": None for o in c["capex_overrun"]} | {"capex_to_mcap": None, "financing_note": "",
                                                                      "cases": {}, "why": ""}
    if not _num(remaining_capex_m):
        return out | {"why": "no remaining capex recorded"}
    shares = mcap_m / price if _num(mcap_m) and _num(price) and price > 0 else None
    for o in [0.0, *c["capex_overrun"]]:
        gap = funding_gap(remaining_capex_m * (1 + o), cash_m, committed_m)
        equity = c["equity_share"] * max(gap, 0.0)
        new = equity / (price * (1 - d)) if shares else None
        out["cases"][o] = {"equity_m": equity, "new_shares_m": new, "overrun_cost_m": o * remaining_capex_m}
        if o and shares:
            out[f"dilution +{o:.0%}"] = new / shares
    if not shares:
        return out | {"cases": {}, "why": "no share price or market cap"}
    worst = out[f"dilution +{max(c['capex_overrun']):.0%}"]
    if worst is not None and worst > c["dilution_note_above"]:
        out["financing_note"] = (f"a raise at a +{max(c['capex_overrun']):.0%} overrun more than doubles the share "
                                 f"count ({worst:.0%} dilution)")
    if _num(mcap_m) and mcap_m > 0:
        out["capex_to_mcap"] = remaining_capex_m / mcap_m
    return out


EXTRA = ["sustaining_capex_usd_m", "analyst_consensus_pnav_dec2025"]


def compute(I: pd.DataFrame, deck_prices: dict, today, P=None, C=None,
            ten_year_yield: float | None = None) -> pd.DataFrame:
    """One row per research row (pnav.inputs): its tier, valuation basis, NPV and EV / NPV at each deck, downside test,
    buy-below and fair-value prices, and validation flags; `why` says what's missing where there's no NPV."""
    from . import studies as S
    if P is None:
        P, C = S.load()
    if any(c not in I for c in EXTRA):
        R = pd.read_csv(RESEARCH / "pnav_companies.csv")[["sheet_row"] + EXTRA]
        I = I.drop(columns=[c for c in EXTRA if c in I]).merge(R, on="sheet_row", how="left")
    Pn = settings()["pnav"]
    y = Pn["ten_year_yield"] if ten_year_yield is None else ten_year_yield
    c = cfg()
    base, pess = c["base_deck"], c["pessimistic_deck"]
    studied = set(P.ticker)
    rows = []
    for _, s in I.iterrows():
        r = s.to_dict()
        mcap, nc, price = r.get("mcap_m"), r.get("net_cash_m"), r.get("price_usd")
        mi = r.get("minority_m")
        mi = mi if _num(mi) else None
        # EV includes partners' stakes (balance-sheet minority interest): the cash flow valued is consolidated
        ev = mcap - nc + (mi or 0.0) if _num(mcap) and _num(nc) else None
        nc_eq = nc - (mi or 0.0) if _num(nc) else nc          # per share: what's left for shareholders
        shares = mcap / price if _num(mcap) and _num(price) and price > 0 else None
        d = {"sheet_row": r["sheet_row"], "ticker": r["ticker"], "yahoo": r.get("yahoo"), "holding": r.get("holding"),
             "price_usd": price, "minority_m": mi,
             "ev_m": ev, "shares_m": shares, "tier": "", "valuation_basis": "", "why": "", "flags": ""}
        basis = r.get("basis") if isinstance(r.get("basis"), str) else ""
        if _num(r.get("fixed_price_usd")):
            rows.append(d | {"why": "physical metal"})
            continue
        tier = {"FCF": "producer", "OCF": "royalty"}.get(basis) or ("developer" if r["ticker"] in studied else "")
        if not tier:
            rows.append(d | {"why": "no cash-flow basis or study recorded"})
            continue
        addon = r.get("addon_pct_points")
        if not _num(addon):
            rows.append(d | {"tier": tier, "why": "no jurisdiction add-on"})
            continue
        rate = y + Pn["risk_premium"] + addon / 100
        d.update(tier=tier, discount_rate=rate)
        r["ev_m"] = ev
        if tier == "developer":
            v = developer_valuation(r["ticker"], deck_prices, rate, today, P, C)
            o = overrun(r.get("remaining_capex_usd_m"), r.get("cash_m"), r.get("committed_funding_usd_m"), price, mcap)
            d.update({k: v[k] for k in v if k.startswith("npv ")}, valuation_basis=STUDY_BASIS, why=v["why"])
            d.update({k: o[k] for k in o if k not in ("why", "cases")})
            for dk in deck_prices:
                d[f"ev/npv {dk}"] = ev_to_npv(ev, d[f"npv {dk}"]) if ev is not None else None
            fin = {"base": o["cases"][0.0], "worst": o["cases"][max(c["capex_overrun"])]} if o["cases"] else None
            b = buy_levels("developer", d[f"npv {base}"], None, nc_eq, shares, financing=fin)
        else:
            if tier == "producer":
                pipe, pwhy = pipeline(r["ticker"], deck_prices, rate, today, P, C)
                v = producer_valuation(r, deck_prices, rate, pipe)
                cf = producer_cash_flow(r, deck_prices[base])[0]
                v["why"] = "; ".join([x for x in [v["why"]] + pwhy if x])
            else:
                v = royalty_valuation(r, deck_prices, rate)
                cf = royalty_cash_flow(r, deck_prices[base])[0]
            d.update({k: x for k, x in v.items() if k != "npv_basis"}, valuation_basis=v["npv_basis"], cf_base=cf)
            b = buy_levels(tier, d[f"npv {base}"], d[f"npv {pess}"], nc_eq, shares)
        d.update(buy_below=b["buy_below"], fair_value=b["fair_value"], binding=b["binding"])
        if b["why"] and not d["why"]:
            d["why"] = b["why"]
        d["nav_per_share"] = nav_per_share(d.get(f"npv {base}"), nc_eq, shares)
        d["flags"] = "; ".join(validation_flags(d.get(f"npv {base}"), nc_eq, shares, r.get("model_nav_per_share_usd"),
                                                r.get("analyst_consensus_pnav_dec2025"), price))
        rows.append(d)
    return pd.DataFrame(rows)


def _money(v) -> str:
    return "" if v is None or pd.isna(v) else f"{v:,.0f}"


def _ratio(v) -> str:
    if isinstance(v, str):
        return v
    return "" if v is None or pd.isna(v) else f"{v:.2f}"


def report(T: pd.DataFrame, deck_prices: dict, K: pd.DataFrame | None = None, today=None) -> list[str]:
    """The validation report: decks, what was valued and on what basis, what wasn't and why, NAVs far from the
    outside views, the Coverage section from `K` (data/research/coverage.csv; roadmap 6b), and each company's NPV,
    EV / NPV and buy-below price at the base deck."""
    c = cfg()
    base = c["base_deck"]
    out = ["Valuation by tier at the decks in [scenarios] (spot is not used):"]
    out += [f"  {d}: gold {px['gold']:,g}, silver {px['silver']:,g}, copper {px['copper']:,g}"
            for d, px in deck_prices.items()]
    if cost_increase_note():
        out += ["", cost_increase_note()]
    val, skip = T[T.tier != ""], T[T.tier == ""]
    has = val[f"npv {base}"].notna() if f"npv {base}" in val else pd.Series(False, index=val.index)
    out += ["", f"Valued: {int(has.sum())} of {len(val)} with a tier ("
            + ", ".join(f"{k}: {v}" for k, v in val[has].groupby("valuation_basis").size().items()) + ")"]
    for why, n in val[~has].groupby("why").size().sort_values(ascending=False).items():
        out.append(f"  No NPV ({n}): {why}")
    out.append(f"Not valued: {len(skip)} (" + ", ".join(f"{k}: {v}" for k, v in skip.groupby("why").size().items())
               + ")")
    flagged = T[T["flags"].astype(str).str.len() > 0]
    out += ["", f"Check against outside views (more than {c['check_factor']:g}x away): {len(flagged)}"]
    out += [f"  {r.holding}: {r.flags}" for r in flagged.itertuples()]
    if K is not None:
        from datetime import date

        from .coverage import summary
        out += [""] + summary(K, T, today or date.today())
    for tier in ("producer", "royalty", "developer"):
        X = val[(val.tier == tier) & has]
        if X.empty:
            continue
        out += ["", f"{tier.capitalize()}s at the {base} deck (US$M; prices US$/share):",
                f"  {'Company':<34}{'Basis':<36}{'NPV':>9}{'EV/NPV':>9}{'Buy below':>11}{'Price':>9}"]
        for _, r in X.sort_values(f"npv {base}", ascending=False).iterrows():
            bb = f"{r.buy_below:,.2f}" if _num(r.buy_below) else "—"
            px = f"{r.price_usd:,.2f}" if _num(r.price_usd) else ""
            out.append(f"  {str(r.holding)[:33]:<34}{str(r.valuation_basis)[:35]:<36}{_money(r[f'npv {base}']):>9}"
                       f"{_ratio(r[f'ev/npv {base}']):>9}{bb:>11}{px:>9}")
    return out


def run(today=None) -> list[str]:
    """`valuation`: value every research row at the decks, offline; writes data/derived/valuation.csv and
    out/valuation/report.txt."""
    from datetime import date

    from . import coverage
    from .pnav import inputs
    from .price_model import Metals
    D = decks()
    m = Metals()
    today = today or date.today()
    T = compute(inputs(pd.read_csv(DERIVED / "holdings_detail.csv"), m), D, today)
    ensure(DERIVED)
    T.to_csv(DERIVED / "valuation.csv", index=False)
    dest = OUT / "valuation"
    ensure(dest)
    rep = report(T, D, coverage.load() if coverage.PATH.exists() else None, today)
    (dest / "report.txt").write_text("\n".join(rep) + "\n")
    return rep[:12] + ["", f"Full report: {dest / 'report.txt'}; data: {DERIVED / 'valuation.csv'}"]
