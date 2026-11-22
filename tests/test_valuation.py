"""Valuation by tier (roadmap 6, docs/specs/tier-valuation-spec.md, Parts 1 and 2). Offline: fixture decks and
companies, no Sheet and no Yahoo."""
import numpy as np
import pytest

from minerval import valuation as V
from minerval.pnav import annuity

DECKS = {"Pessimistic": {"gold": 1800.0, "silver": 22.0, "copper": 3.6},
         "Base": {"gold": 2200.0, "silver": 28.0, "copper": 4.4},
         "Optimistic": {"gold": 2600.0, "silver": 34.0, "copper": 5.2}}
CFG = {"horizon_years": 10, "decks": ["Pessimistic", "Base", "Optimistic"], "pessimistic_deck": "Pessimistic",
       "base_deck": "Base", "pessimistic_cost_increase": 0.10, "capex_overrun": [0.15, 0.30],
       "max_overrun_dilution": 0.33}


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(V, "cfg", lambda: CFG)


def producer(**k):
    """A gold-copper producer: US$M, revenue shares, and the reporting period's average prices."""
    r = {"ocf_m": 500.0, "sustaining_capex_usd_m": 200.0, "fcf_m": 120.0, "revenue_m": 1000.0,
         "share_gold": 0.8, "share_silver": 0.0, "share_copper": 0.2,
         "avg_gold": 2000.0, "avg_silver": 25.0, "avg_copper": 4.0,
         "reserve_life_years": 25.0, "ev_m": 2000.0}
    r.update(k)
    return r


def test_decks_are_read_metal_by_metal_and_must_be_complete():
    assert V.decks(DECKS) == DECKS
    with pytest.raises(ValueError, match="Base has no copper"):
        V.decks({**DECKS, "Base": {"gold": 2200.0, "silver": 28.0}})
    with pytest.raises(ValueError, match="no Optimistic deck"):
        V.decks({k: v for k, v in DECKS.items() if k != "Optimistic"})


def test_changing_one_metal_of_one_deck_changes_only_that_decks_npv():
    before = V.producer_valuation(producer(), DECKS, 0.09)
    moved = {**DECKS, "Base": {**DECKS["Base"], "gold": 2500.0}}
    after = V.producer_valuation(producer(), moved, 0.09)
    assert after["npv Base"] > before["npv Base"]
    assert after["npv Pessimistic"] == before["npv Pessimistic"]
    assert after["npv Optimistic"] == before["npv Optimistic"]
    silver = producer(share_gold=0.0, share_silver=1.0, share_copper=0.0)        # no ratio links the metals
    assert V.producer_valuation(silver, moved, 0.09) == V.producer_valuation(silver, DECKS, 0.09)


def test_npv_covers_the_shorter_of_reserve_life_and_horizon_with_no_terminal_value():
    assert V.npv(100.0, 0.10, 25.0) == pytest.approx(100.0 * annuity(0.10, 10))
    assert V.npv(100.0, 0.10, 4.0) == pytest.approx(100.0 * annuity(0.10, 4))


def test_a_negative_npv_is_text_not_a_ratio():
    assert V.ev_to_npv(500.0, -10.0) == "negative NPV"
    assert V.ev_to_npv(500.0, 0.0) == "negative NPV"
    assert V.ev_to_npv(500.0, 250.0) == pytest.approx(2.0)
    assert V.ev_to_npv(500.0, None) is None


def test_cash_flow_is_ocf_less_sustaining_repriced_by_revenue_mix():
    cf, basis = V.producer_cash_flow(producer(), DECKS["Base"])
    # 0.70 of revenue x (0.8 x (2200/2000 - 1) + 0.2 x (4.4/4.0 - 1)) = 0.7 x 1000 x 0.10 = 70
    assert cf == pytest.approx(500.0 - 200.0 + 70.0) and basis == V.OCF_BASIS


def test_a_blank_sustaining_figure_falls_back_to_fcf_with_its_label():
    cf, basis = V.producer_cash_flow(producer(sustaining_capex_usd_m=np.nan), DECKS["Base"])
    assert cf == pytest.approx(120.0 + 70.0) and basis == V.FCF_BASIS == "FCF basis: sustaining not recorded"
    assert V.producer_cash_flow(producer(sustaining_capex_usd_m=np.nan, fcf_m=np.nan), DECKS["Base"])[0] is None


def test_only_the_pessimistic_deck_raises_costs():
    v = V.producer_valuation(producer(), DECKS, 0.09)
    ann = annuity(0.09, 10)
    base_cf = 300.0
    chg = {d: 0.7 * 1000.0 * (0.8 * (p["gold"] / 2000 - 1) + 0.2 * (p["copper"] / 4.0 - 1)) for d, p in DECKS.items()}
    cost = -0.7 * (1000.0 - base_cf) * 0.10                                        # cost_change on OCF − sustaining
    assert v["npv Pessimistic"] == pytest.approx((base_cf + chg["Pessimistic"] + cost) * ann)
    assert v["npv Base"] == pytest.approx((base_cf + chg["Base"]) * ann)
    assert v["npv Optimistic"] == pytest.approx((base_cf + chg["Optimistic"]) * ann)


def test_measures_ev_to_npv_fcf_yield_and_the_downside_test():
    v = V.producer_valuation(producer(), DECKS, 0.09)
    assert v["npv_basis"] == V.OCF_BASIS
    assert v["ev/npv Base"] == pytest.approx(2000.0 / v["npv Base"])
    assert v["sustaining_fcf_yield"] == pytest.approx((300.0 + 70.0) / 2000.0)      # base-deck cash flow ÷ EV
    assert v["downside_ok"] is (2000.0 <= v["npv Pessimistic"])
    cheap = V.producer_valuation(producer(ev_m=100.0), DECKS, 0.09)
    assert cheap["downside_ok"] is True
    loss = V.producer_valuation(producer(ocf_m=100.0, sustaining_capex_usd_m=400.0), DECKS, 0.09)
    assert loss["ev/npv Pessimistic"] == "negative NPV" and loss["downside_ok"] is False


def test_no_reserve_life_or_cash_flow_means_no_npv_and_says_why():
    v = V.producer_valuation(producer(reserve_life_years=np.nan), DECKS, 0.09)
    assert v["npv Base"] is None and v["why"] == "no reserve life"
    v = V.producer_valuation(producer(sustaining_capex_usd_m=np.nan, fcf_m=np.nan), DECKS, 0.09)
    assert v["npv Base"] is None and v["why"] == "no cash flow"


def test_the_settings_name_the_decks_consistently():
    from minerval.config import settings
    c = settings()["valuation"]
    assert len(c["decks"]) == 3 and c["pessimistic_deck"] in c["decks"] and c["base_deck"] in c["decks"]
    assert c["horizon_years"] == 10


def projects(*rows):
    import pandas as pd
    cols = {"ticker": "PRD", "project": "", "committed": "", "superseded": ""}
    return pd.DataFrame([{**cols, **r} for r in rows]), pd.DataFrame()


def test_a_committed_projects_risk_adjusted_npv_is_added_and_an_uncommitted_one_isnt(monkeypatch):
    from datetime import date

    from minerval import studies as S
    value = {"Pessimistic": 50.0, "Base": 80.0, "Optimistic": 120.0}
    by_deck = {tuple(v.items()): d for d, v in DECKS.items()}
    monkeypatch.setattr(S, "flows", lambda C, p: None)
    monkeypatch.setattr(S, "risk_adjusted", lambda p, F, px, rate, today: {
        "risk_adjusted": value[by_deck[tuple(px.items())]] * (2 if p.project == "Big" else 1), "why": ""})
    P, C = projects({"project": "Mill", "committed": "yes"}, {"project": "Big", "committed": ""},
                    {"project": "Old", "committed": "yes", "superseded": "a later study"},
                    {"ticker": "OTHER", "project": "Theirs", "committed": "yes"})
    pipe, why = V.pipeline("PRD", DECKS, 0.09, date(2026, 11, 22), P, C)
    assert pipe == value and why == []                       # only Mill: Big isn't committed, Old is superseded
    with_pipe = V.producer_valuation(producer(), DECKS, 0.09, pipe)
    alone = V.producer_valuation(producer(), DECKS, 0.09)
    assert all(with_pipe[f"npv {d}"] == pytest.approx(alone[f"npv {d}"] + value[d]) for d in DECKS)


def test_a_committed_project_that_cant_be_valued_is_left_out_and_named(monkeypatch):
    from datetime import date

    from minerval import studies as S
    monkeypatch.setattr(S, "flows", lambda C, p: None)
    monkeypatch.setattr(S, "risk_adjusted", lambda p, F, px, rate, today: {"risk_adjusted": None,
                                                                          "why": "no cash-flow table recorded"})
    P, C = projects({"project": "Mill", "committed": "yes"})
    pipe, why = V.pipeline("PRD", DECKS, 0.09, date(2026, 11, 22), P, C)
    assert pipe == {d: 0.0 for d in DECKS} and why == ["Mill: no cash-flow table recorded"]


def test_overrun_dilution_at_each_overrun_and_its_downside_test():
    # remaining capex 400, cash 100, committed 50; 50M shares at $10 (market cap 500), raised at a 15% discount
    o = V.overrun(400.0, 100.0, 50.0, 10.0, 500.0, discount=0.15)
    assert o["dilution +15%"] == pytest.approx((400 * 1.15 - 150) / 8.5 / 50)
    assert o["dilution +30%"] == pytest.approx((400 * 1.30 - 150) / 8.5 / 50)
    assert o["overrun_ok"] is False and o["capex_to_mcap"] == pytest.approx(0.8)
    funded = V.overrun(100.0, 200.0, 0.0, 10.0, 500.0, discount=0.15)
    assert funded["dilution +30%"] == 0.0 and funded["overrun_ok"] is True
    edge = V.overrun(100.0, 0.0, 0.0, 10.0, 500.0, discount=0.15)     # +30%: 130 / 8.5 = 15.3M new on 50M = 30.6%
    assert edge["dilution +30%"] < 0.33 and edge["overrun_ok"] is True


def test_no_remaining_capex_means_no_overrun_test():
    o = V.overrun(None, 100.0, 0.0, 10.0, 500.0, discount=0.15)
    assert o["overrun_ok"] is None and o["capex_to_mcap"] is None and o["why"] == "no remaining capex recorded"
