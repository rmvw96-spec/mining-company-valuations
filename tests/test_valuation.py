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
       "equity_share": 0.35, "dilution_note_above": 1.0, "check_factor": 2.0,
       "buy": {"producer": {"buy": 0.6, "fair": 1.0}, "royalty": {"buy": 1.0, "fair": 1.5},
               "developer": {"buy": 0.6, "fair": 1.0}}}


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


def test_overrun_financing_uses_rules_equity_share_and_notes_a_doubling():
    # remaining capex 400, cash 100, committed 50; 50M shares at $10 (market cap 500), raised at a 15% discount;
    # 35% of the funding gap is equity (Rule's model), the rest debt
    o = V.overrun(400.0, 100.0, 50.0, 10.0, 500.0, discount=0.15)
    worst = o["cases"][0.30]
    assert worst["equity_m"] == pytest.approx(0.35 * (400 * 1.30 - 150))
    assert worst["new_shares_m"] == pytest.approx(0.35 * (400 * 1.30 - 150) / 8.5)
    assert worst["overrun_cost_m"] == pytest.approx(0.30 * 400)
    assert o["dilution +30%"] == pytest.approx(worst["new_shares_m"] / 50)
    assert o["dilution +15%"] == pytest.approx(0.35 * (400 * 1.15 - 150) / 8.5 / 50)
    assert o["cases"][0.0]["overrun_cost_m"] == 0.0 and o["capex_to_mcap"] == pytest.approx(0.8)
    assert o["financing_note"] == ""
    big = V.overrun(3000.0, 0.0, 0.0, 10.0, 500.0, discount=0.15)              # 0.35 x 3,900 / 8.5 = 160.6M on 50M
    assert big["financing_note"] == "a raise at a +30% overrun more than doubles the share count (321% dilution)"
    funded = V.overrun(100.0, 200.0, 0.0, 10.0, 500.0, discount=0.15)          # cash covers it: no raise
    assert funded["dilution +30%"] == 0.0 and funded["cases"][0.30]["overrun_cost_m"] == pytest.approx(30.0)


def test_no_remaining_capex_means_the_dilution_cant_be_priced():
    o = V.overrun(None, 100.0, 0.0, 10.0, 500.0, discount=0.15)
    assert o["cases"] == {} and o["capex_to_mcap"] is None and o["why"] == "no remaining capex recorded"


def royalty(**k):
    r = {"ocf_m": 400.0, "revenue_m": 500.0, "share_gold": 1.0, "share_silver": 0.0, "share_copper": 0.0,
         "avg_gold": 2000.0, "avg_silver": 25.0, "avg_copper": 4.0, "reserve_life_years": 4.0, "ev_m": 3000.0}
    r.update(k)
    return r


def test_royalty_npv_is_a_perpetuity_of_operating_cash_flow_at_each_deck_with_no_cost_increase():
    v = V.royalty_valuation(royalty(), DECKS, 0.08)
    for d, px in DECKS.items():
        cf = 400.0 + 0.7 * 500.0 * (px["gold"] / 2000 - 1)                     # no sustaining, no cost increase
        assert v[f"npv {d}"] == pytest.approx(cf / 0.08)                        # no growth, not the 4-year life
    assert v["npv_basis"] == V.ROYALTY_BASIS
    assert v["downside_ok"] is (3000.0 <= v["npv Pessimistic"])
    assert V.royalty_valuation(royalty(ev_m=100.0), DECKS, 0.08)["downside_ok"] is True


def test_buy_below_price_at_each_binding_condition():
    # 50M shares, net cash $100M; producers buy at 0.6 x base NPV and no higher than the pessimistic NPV
    a = V.buy_levels("producer", npv_base=1000.0, npv_pessimistic=900.0, net_cash_m=100.0, shares_m=50.0)
    assert a["buy_below"] == pytest.approx((600 + 100) / 50) and a["binding"] == "discount"
    assert a["fair_value"] == pytest.approx((1000 + 100) / 50)
    b = V.buy_levels("producer", npv_base=1000.0, npv_pessimistic=400.0, net_cash_m=100.0, shares_m=50.0)
    assert b["buy_below"] == pytest.approx((400 + 100) / 50) and b["binding"] == "downside test"
    r = V.buy_levels("royalty", npv_base=1000.0, npv_pessimistic=1200.0, net_cash_m=100.0, shares_m=50.0)
    assert r["buy_below"] == pytest.approx(1100 / 50) and r["fair_value"] == pytest.approx(1600 / 50)


def test_developers_buy_below_prices_in_the_dilution_of_a_30pct_overrun():
    worst = {"equity_m": 35.0, "new_shares_m": 10.0, "overrun_cost_m": 30.0}    # the +30% overrun case
    base = {"equity_m": 20.0, "new_shares_m": 5.0, "overrun_cost_m": 0.0}       # the study's capex
    b = V.buy_levels("developer", npv_base=500.0, net_cash_m=20.0, shares_m=40.0,
                     financing={"base": base, "worst": worst})
    assert b["buy_below"] == pytest.approx((0.6 * 500 - 30 + 20 + 35) / (40 + 10))       # 6.50
    assert b["fair_value"] == pytest.approx((500 + 20 + 20) / (40 + 5))                   # 12.00
    assert b["binding"] == "financing at a +30% overrun"
    unk = V.buy_levels("developer", npv_base=500.0, net_cash_m=20.0, shares_m=40.0, financing=None)
    assert unk["buy_below"] is None and unk["why"] == "no remaining capex recorded: the build's dilution can't be priced"
    deep = V.buy_levels("developer", npv_base=100.0, net_cash_m=0.0, shares_m=40.0,
                        financing={"base": base, "worst": {"equity_m": 0.0, "new_shares_m": 0.0, "overrun_cost_m": 90.0}})
    assert deep["buy_below"] is None and deep["why"] == "negative value per share after a +30% overrun"


def test_no_npv_means_no_buy_below_price_and_says_why():
    assert V.buy_levels("producer", None, 900.0, 100.0, 50.0)["why"] == "no NPV"
    assert V.buy_levels("producer", -5.0, -50.0, 100.0, 50.0)["why"] == "negative NPV at the base deck"
    deep = V.buy_levels("producer", 1000.0, -300.0, 100.0, 50.0)          # min(600, -300) + 100 <= 0
    assert deep["buy_below"] is None and deep["why"] == "fails the downside test at any price"
    assert V.buy_levels("producer", 1000.0, 900.0, 100.0, None)["why"] == "no share count"


def test_validation_flags_npvs_more_than_twice_away_from_the_outside_views():
    # our NAV per share = (base NPV + net cash) / shares = (900 + 100) / 50 = $20
    assert V.validation_flags(900.0, 100.0, 50.0, independent_nav=9.0) == [
        "NAV $20.00/share is 2.2x the independent NAV ($9.00)"]
    assert V.validation_flags(900.0, 100.0, 50.0, independent_nav=12.0) == []          # 1.7x: within 2x
    # consensus P/NAV 0.5 at a $5 price means a consensus NAV of $10/share: ours is 2.0x, not more
    assert V.validation_flags(900.0, 100.0, 50.0, consensus_pnav=0.5, price=5.0) == []
    assert V.validation_flags(900.0, 100.0, 50.0, consensus_pnav=2.0, price=5.0) == [
        "NAV $20.00/share is 8.0x the consensus NAV ($2.50)"]                            # consensus NAV = 5 / 2.0
    assert V.validation_flags(900.0, 100.0, 50.0, consensus_pnav=0.2, price=5.0) == []  # $25: ours is 0.8x
    assert V.validation_flags(-200.0, 100.0, 50.0, independent_nav=9.0) == [
        "NAV -$2.00/share against the independent NAV ($9.00)"]
    assert V.validation_flags(900.0, 100.0, 50.0) == []                                   # nothing to compare with


def test_the_settings_set_a_buy_level_below_fair_value_for_every_tier():
    from minerval.config import settings
    c = settings()["valuation"]
    assert set(c["buy"]) == {"producer", "royalty", "developer"}
    assert all(0 < v["buy"] < v["fair"] for v in c["buy"].values()) and c["check_factor"] > 1
    assert 0 < c["equity_share"] < 1 and "max_overrun_dilution" not in c


def test_missing_inputs_give_no_price_and_no_flags():
    assert V.buy_levels("producer", 1000.0, None, 100.0, 50.0)["why"] == "no pessimistic NPV"
    assert V.validation_flags(None, 100.0, 50.0, independent_nav=9.0) == []
    assert V.validation_flags(900.0, 100.0, None, independent_nav=9.0) == []


def test_an_unset_cost_increase_leaves_the_pessimistic_deck_at_reported_costs(monkeypatch):
    monkeypatch.setattr(V, "cfg", lambda: {k: v for k, v in CFG.items() if k != "pessimistic_cost_increase"})
    v = V.producer_valuation(producer(), DECKS, 0.09)
    cf, _ = V.producer_cash_flow(producer(), DECKS["Pessimistic"])
    assert v["npv Pessimistic"] == pytest.approx(V.npv(cf, 0.09, 25.0, 10))
    assert V.cost_increase_note() == "[valuation] pessimistic_cost_increase isn't set: the pessimistic deck uses reported costs"


def test_the_real_decks_are_complete_and_ordered():
    d = V.decks()
    assert list(d) == ["Pessimistic", "Base", "Optimistic"]
    assert all(d["Pessimistic"][m] < d["Base"][m] < d["Optimistic"][m] for m in ("gold", "silver", "copper"))


def inputs_frame():
    """Three research rows as pnav.inputs gives them: a producer (FCF basis), a royalty (OCF) and a developer."""
    import pandas as pd
    base = {"share_gold": 1.0, "share_silver": 0.0, "share_copper": 0.0, "avg_gold": 2000.0, "avg_silver": 25.0,
            "avg_copper": 4.0, "addon_pct_points": 1.0, "fixed_price_usd": np.nan, "model_nav_per_share_usd": np.nan,
            "analyst_consensus_pnav_dec2025": np.nan, "remaining_capex_usd_m": np.nan, "committed_funding_usd_m": np.nan}
    rows = [
        {**base, "sheet_row": 12, "ticker": "PRD", "holding": "Producer Co", "basis": "FCF", "price_usd": 10.0,
         "mcap_m": 1000.0, "net_cash_m": 100.0, "cash_m": 150.0, "revenue_m": 1000.0, "ocf_m": 500.0, "fcf_m": 120.0,
         "sustaining_capex_usd_m": 200.0, "reserve_life_years": 12.0, "model_nav_per_share_usd": 2.0},
        {**base, "sheet_row": 13, "ticker": "ROY", "holding": "Royalty Co", "basis": "OCF", "price_usd": 50.0,
         "mcap_m": 5000.0, "net_cash_m": 0.0, "cash_m": 50.0, "revenue_m": 400.0, "ocf_m": 350.0, "fcf_m": 300.0,
         "sustaining_capex_usd_m": np.nan, "reserve_life_years": np.nan},
        {**base, "sheet_row": 14, "ticker": "DEV", "holding": "Developer Co", "basis": np.nan, "price_usd": 2.0,
         "mcap_m": 200.0, "net_cash_m": 30.0, "cash_m": 30.0, "revenue_m": 0.0, "ocf_m": np.nan, "fcf_m": np.nan,
         "sustaining_capex_usd_m": np.nan, "reserve_life_years": np.nan, "remaining_capex_usd_m": 300.0,
         "committed_funding_usd_m": 0.0},
        {**base, "sheet_row": 15, "ticker": "PHYS", "holding": "Gold trust", "basis": np.nan, "price_usd": 30.0,
         "mcap_m": 9000.0, "net_cash_m": 0.0, "fixed_price_usd": 30.0},
    ]
    return pd.DataFrame(rows)


def study_stub(monkeypatch, value=400.0):
    from minerval import studies as S
    monkeypatch.setattr(S, "flows", lambda C, p: None)
    monkeypatch.setattr(S, "risk_adjusted", lambda p, F, px, rate, today: {
        "risk_adjusted": value * px["gold"] / 2200.0, "why": ""})
    P, C = projects({"ticker": "DEV", "project": "Big Pit"})
    return P, C


def test_compute_values_each_tier_and_skips_what_it_cant_value(monkeypatch):
    from datetime import date
    P, C = study_stub(monkeypatch)
    T = V.compute(inputs_frame(), DECKS, date(2026, 11, 22), P, C, ten_year_yield=0.04).set_index("ticker")
    assert T.loc["PRD", "tier"] == "producer" and T.loc["PRD", "valuation_basis"] == V.OCF_BASIS
    assert T.loc["ROY", "tier"] == "royalty" and T.loc["ROY", "valuation_basis"] == V.ROYALTY_BASIS
    assert T.loc["DEV", "tier"] == "developer" and T.loc["DEV", "valuation_basis"] == V.STUDY_BASIS
    assert T.loc["DEV", "npv Base"] == pytest.approx(400.0)                       # the projects' risk-adjusted sum
    assert T.loc["PHYS", "tier"] == "" and T.loc["PHYS", "why"] == "physical metal"
    rate = 0.04 + 0.03 + 0.01                                                       # 10-year + premium + add-on
    prd = V.producer_valuation({**inputs_frame().iloc[0].to_dict(), "ev_m": 900.0}, DECKS, rate)
    assert T.loc["PRD", "npv Base"] == pytest.approx(prd["npv Base"])
    assert T.loc["PRD", "ev_m"] == pytest.approx(900.0) and T.loc["PRD", "shares_m"] == pytest.approx(100.0)


def test_compute_gives_buy_levels_overrun_and_validation_flags(monkeypatch):
    from datetime import date
    P, C = study_stub(monkeypatch)
    T = V.compute(inputs_frame(), DECKS, date(2026, 11, 22), P, C, ten_year_yield=0.04).set_index("ticker")
    prd = T.loc["PRD"]
    want = V.buy_levels("producer", prd["npv Base"], prd["npv Pessimistic"], 100.0, 100.0)
    assert prd["buy_below"] == pytest.approx(want["buy_below"]) and prd["binding"] == want["binding"]
    assert "the independent NAV ($2.00)" in prd["flags"]                          # far from the outside NAV
    dev = T.loc["DEV"]
    o = V.overrun(300.0, 30.0, 0.0, 2.0, 200.0)
    assert dev["dilution +30%"] == pytest.approx(o["dilution +30%"]) and dev["financing_note"] == o["financing_note"]
    want = V.buy_levels("developer", dev["npv Base"], None, 30.0, 100.0,
                        financing={"base": o["cases"][0.0], "worst": o["cases"][0.30]})
    assert dev["buy_below"] == pytest.approx(want["buy_below"]) and dev["fair_value"] == pytest.approx(want["fair_value"])
    assert dev["capex_to_mcap"] == pytest.approx(1.5)


def test_report_states_the_decks_the_cost_note_and_the_flags(monkeypatch):
    from datetime import date
    P, C = study_stub(monkeypatch)
    monkeypatch.setattr(V, "cfg", lambda: {k: v for k, v in CFG.items() if k != "pessimistic_cost_increase"})
    T = V.compute(inputs_frame(), DECKS, date(2026, 11, 22), P, C, ten_year_yield=0.04)
    text = "\n".join(V.report(T, DECKS))
    assert "Base: gold 2,200, silver 28, copper 4.4" in text
    assert V.cost_increase_note() in text
    assert "Producer Co" in text and "independent NAV" in text
    assert "Not valued: 1 (physical metal: 1)" in text


def test_report_summarises_coverage(monkeypatch):
    """valuation-coverage A3: the Coverage section counts data/research/coverage.csv by gap and status, names `waiting`
    rows past their due month, and names companies flagged against outside views with no growth_project or
    sustaining row (a flag nobody has explained)."""
    from datetime import date

    import pandas as pd

    from minerval import coverage
    P, C = study_stub(monkeypatch)
    T = V.compute(inputs_frame(), DECKS, date(2026, 11, 22), P, C, ten_year_yield=0.04)
    rows = [("XYZ", "study", "waiting", "wait for the PFS technical report", "2026-10", "https://example.com/a"),
            ("ABC", "study", "waiting", "wait for the FS", "2027-01", "https://example.com/b"),
            ("DEF", "study", "to research", "record the PEA's cash flows"),
            ("PHYS", "out_of_scope", "out of scope")]
    K = pd.DataFrame([dict(zip(coverage.COLS, r + ("",) * (7 - len(r)))) for r in rows], columns=coverage.COLS)
    text = "\n".join(V.report(T, DECKS, K, date(2026, 11, 22)))
    assert "Coverage (data/research/coverage.csv): 4 rows" in text
    assert "  study: 3 (to research 1, waiting 2)" in text and "  out_of_scope: 1 (out of scope 1)" in text
    assert "  Waiting past due: XYZ (study, due 2026-10): wait for the PFS technical report" in text
    assert "ABC (study" not in text                                          # due next year
    assert "  Flagged with no growth_project or sustaining row: Producer Co (PRD)" in text
    K2 = pd.concat([K, pd.DataFrame([dict(zip(coverage.COLS, ("PRD", "growth_project", "to research", "record it",
                                                                "", "", "")))])])
    text = "\n".join(V.report(T, DECKS, K2, date(2026, 11, 22)))
    assert "  Flagged with no growth_project or sustaining row: none" in text


def test_compute_says_why_a_row_has_no_valuation(monkeypatch):
    from datetime import date

    import pandas as pd
    P, C = study_stub(monkeypatch)
    F = inputs_frame()
    more = pd.DataFrame([{**F.iloc[0].to_dict(), "sheet_row": 16, "ticker": "EXP", "basis": np.nan},
                         {**F.iloc[0].to_dict(), "sheet_row": 17, "ticker": "NOJ", "addon_pct_points": np.nan}])
    T = V.compute(pd.concat([F, more]), DECKS, date(2026, 11, 22), P, C, ten_year_yield=0.04).set_index("ticker")
    assert T.loc["EXP", "tier"] == "" and T.loc["EXP", "why"] == "no cash-flow basis or study recorded"
    assert T.loc["NOJ", "tier"] == "producer" and T.loc["NOJ", "why"] == "no jurisdiction add-on"


def test_ev_adds_minority_interest_because_cash_flow_is_consolidated(monkeypatch):
    from datetime import date
    P, C = study_stub(monkeypatch)
    F = inputs_frame()
    F["minority_m"] = [250.0, np.nan, np.nan, np.nan]
    T = V.compute(F, DECKS, date(2026, 11, 22), P, C, ten_year_yield=0.04).set_index("ticker")
    assert T.loc["PRD", "ev_m"] == pytest.approx(1000.0 - 100.0 + 250.0)       # market cap − net cash + minorities
    assert T.loc["ROY", "ev_m"] == pytest.approx(5000.0)                       # none recorded: nothing added
    assert T.loc["PRD", "minority_m"] == pytest.approx(250.0)


def test_compute_gives_our_nav_per_share(monkeypatch):
    """own-nav-first A1: our base-deck NAV per share, (NPV + net cash − minority interest) ÷ shares, as the check uses."""
    from datetime import date
    P, C = study_stub(monkeypatch)
    F = inputs_frame()
    F["minority_m"] = [250.0, np.nan, np.nan, np.nan]
    T = V.compute(F, DECKS, date(2026, 11, 22), P, C, ten_year_yield=0.04).set_index("ticker")
    prd = T.loc["PRD"]
    assert prd["nav_per_share"] == pytest.approx((prd["npv Base"] + 100.0 - 250.0) / 100.0)
    assert f"NAV ${prd['nav_per_share']:.2f}/share" in prd["flags"]
    assert T.loc["DEV", "nav_per_share"] == pytest.approx((T.loc["DEV", "npv Base"] + 30.0) / 100.0)
    assert np.isnan(T.loc["PHYS", "nav_per_share"])                        # not valued: no NAV of ours


def test_per_share_figures_subtract_minority_interest(monkeypatch):
    from datetime import date
    P, C = study_stub(monkeypatch)
    F = inputs_frame()
    F["minority_m"] = [250.0, np.nan, np.nan, np.nan]
    prd = V.compute(F, DECKS, date(2026, 11, 22), P, C, ten_year_yield=0.04).set_index("ticker").loc["PRD"]
    want = V.buy_levels("producer", prd["npv Base"], prd["npv Pessimistic"], 100.0 - 250.0, 100.0)
    assert prd["buy_below"] == pytest.approx(want["buy_below"])                 # equity holders' share only
    assert prd["fair_value"] == pytest.approx(want["fair_value"])
    assert f"NAV ${(prd['npv Base'] - 150.0) / 100.0:.2f}/share" in prd["flags"]
