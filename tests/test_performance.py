"""The screen's performance measures (roadmap 5b, revision 2): each year's cash flow re-priced to the base deck and
taken per share with that year's share count, growth, margins through the cycle, the FCF-basis label and too little
history. Offline; the companies are made up."""
import numpy as np
import pandas as pd
import pytest

from minerval import performance as PF

BASE = {"gold": 4550.0, "silver": 64.875, "copper": 6.49}
K = 0.7                                                       # [price_model] cash_flow_share


def yearly(**cols):
    """A Yahoo-style series dict: {annualX: [{date, cur, val}]} from {"annualX": {date: value in US$M}}."""
    return {k: [{"date": d, "cur": "USD", "val": v * 1e6} for d, v in vals.items()] for k, vals in cols.items()}


def monthly(gold_by_year: dict) -> dict:
    """Monthly closes with each calendar year at one gold price."""
    idx = pd.date_range("2021-01-01", "2025-12-01", freq="MS")
    g = pd.Series([gold_by_year.get(d.year, 1800.0) for d in idx], index=idx)
    return {"gold": g, "silver": pd.Series(25.0, index=idx), "copper": pd.Series(4.0, index=idx)}


YEARS = ["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
GOLD = {2022: 1800.0, 2023: 1950.0, 2024: 2400.0, 2025: 3400.0}


def company(**over):
    s = yearly(annualTotalRevenue=dict.fromkeys(YEARS, 1000.0),
               annualOperatingCashFlow=dict.fromkeys(YEARS, 400.0),
               annualFreeCashFlow=dict.fromkeys(YEARS, 200.0),
               annualOrdinarySharesNumber=dict(zip(YEARS, [100.0, 100.0, 110.0, 125.0])))
    s.update(yearly(**over))
    return s


def test_year_average_is_the_twelve_months_to_the_year_end():
    m = monthly(GOLD)
    assert PF.year_average(m, "2025-12-31")["gold"] == 3400.0
    assert PF.year_average(m, "2025-06-30")["gold"] == pytest.approx((6 * 2400.0 + 6 * 3400.0) / 12)


def test_each_year_is_repriced_to_the_base_deck_per_share_with_that_years_shares():
    """A20: cash flow + cash_flow_share × revenue × (base ÷ that year's average − 1), ÷ that year's share count;
    revenue re-priced the same way for the margin."""
    T = PF.constant_price(PF.annual(company()), {"gold": 1.0}, monthly(GOLD), BASE, K)
    assert list(T.index.year) == [2022, 2023, 2024, 2025] and set(T.basis) == {"FCF"}
    for (end, r), shares in zip(T.iterrows(), [100.0, 100.0, 110.0, 125.0]):
        up = BASE["gold"] / GOLD[end.year] - 1
        assert r.cf == pytest.approx(200.0 + K * 1000.0 * up)
        assert r.cf_ps == pytest.approx(r.cf / shares)
        assert r.margin == pytest.approx(r.cf / (1000.0 * (1 + up)))


def test_a_metal_outside_the_mix_isnt_repriced():
    T = PF.constant_price(PF.annual(company()), {"gold": 0.5}, monthly(GOLD), BASE, K)
    r = T.iloc[-1]
    assert r.cf == pytest.approx(200.0 + K * 1000.0 * 0.5 * (4550.0 / 3400.0 - 1))


def test_sustaining_recorded_for_every_year_uses_ocf_less_sustaining():
    sus = {pd.Timestamp(d): 150.0 for d in YEARS}
    T = PF.constant_price(PF.annual(company()), {"gold": 1.0}, monthly(GOLD), BASE, K, sustaining=sus)
    assert set(T.basis) == {"OCF − sustaining"}
    assert T.iloc[0].cf == pytest.approx(400.0 - 150.0 + K * 1000.0 * (4550.0 / 1800.0 - 1))
    part = {pd.Timestamp(YEARS[-1]): 150.0}                  # one year only: FCF for every year, labelled
    assert set(PF.constant_price(PF.annual(company()), {"gold": 1.0}, monthly(GOLD), BASE, K,
                                 sustaining=part).basis) == {"FCF"}


def test_royalties_use_operating_cash_flow():
    T = PF.constant_price(PF.annual(company()), {"gold": 1.0}, monthly(GOLD), BASE, K, royalty=True)
    assert set(T.basis) == {"OCF"} and T.iloc[0].cf == pytest.approx(400.0 + K * 1000.0 * (4550.0 / 1800.0 - 1))


def test_trend_growth_is_the_fitted_slope_over_the_mean_size():
    assert PF.trend_growth([1.0, 2.0, 3.0, 4.0]) == pytest.approx(1.0 / 2.5)
    assert PF.trend_growth([-2.0, -1.0, 1.0, 2.0]) == pytest.approx(1.4 / 1.5)     # works through a sign change
    assert np.isnan(PF.trend_growth([5.0])) and np.isnan(PF.trend_growth([0.0, 0.0, 0.0]))


def test_measures_for_a_producer_and_a_royalty():
    """A21: cash flow per share growth, the margin's average and lowest year, the basis and the years of history."""
    A = PF.annual(company())
    m = PF.measures(A, {"gold": 1.0}, monthly(GOLD), BASE, K)
    T = PF.constant_price(A, {"gold": 1.0}, monthly(GOLD), BASE, K)
    assert m["cf_ps_growth"] == pytest.approx(PF.trend_growth(list(T.cf_ps)))
    assert m["margin_avg"] == pytest.approx(T.margin.mean()) and m["margin_min"] == pytest.approx(T.margin.min())
    assert m["cf_basis"] == "FCF" and m["history_years"] == 4
    r = PF.measures(A, {"gold": 1.0}, monthly(GOLD), BASE, K, royalty=True)
    assert "ocf_ps_growth" in r and "cf_ps_growth" not in r and r["cf_basis"] == "OCF"


def test_years_missing_a_figure_dont_count_as_history():
    s = company()
    s["annualOrdinarySharesNumber"] = s["annualOrdinarySharesNumber"][-1:]        # one year with a share count
    m = PF.measures(PF.annual(s), {"gold": 1.0}, monthly(GOLD), BASE, K)
    assert m["history_years"] == 1 and np.isnan(m["cf_ps_growth"])
    assert PF.measures(PF.annual({}), {"gold": 1.0}, monthly(GOLD), BASE, K)["history_years"] == 0


def test_only_the_last_four_years_count():
    years = ["2020-12-31", "2021-12-31"] + YEARS
    s = company(annualTotalRevenue=dict.fromkeys(years, 1000.0), annualFreeCashFlow=dict.fromkeys(years, 200.0),
                annualOrdinarySharesNumber=dict.fromkeys(years, 100.0))
    assert PF.measures(PF.annual(s), {"gold": 1.0}, monthly(GOLD), BASE, K)["history_years"] == 4


def test_add_fills_the_universe_by_ticker():
    """A21: the screen's universe gets each company's measures; developers only their years of share counts."""
    U = pd.DataFrame([{"ticker": "PRD", "ticker_buy": "PRD", "bucket": "Gold producers", "share_gold": 1.0},
                      {"ticker": "ROY CN", "ticker_buy": "ROY", "bucket": "Royalty", "share_gold": 1.0},
                      {"ticker": "DEV", "ticker_buy": "DEV", "bucket": "Growth: developers", "share_gold": ""},
                      {"ticker": "NEW", "ticker_buy": "NEW", "bucket": "Gold producers", "share_gold": 1.0}])
    holdings = {"PRD": {"series": company()}, "ROY": {"series": company()}, "DEV": {"series": company()}}
    sus = {"PRD": {(pd.Timestamp(d), "USD"): 150.0 for d in YEARS}}
    V = PF.add(U, holdings, monthly(GOLD), sus, BASE).set_index("ticker")
    assert V.loc["PRD", "cf_basis"] == "OCF − sustaining" and V.loc["PRD", "history_years"] == 4
    assert V.loc["ROY CN", "cf_basis"] == "OCF" and V.loc["ROY CN", "ocf_ps_growth"] == V.loc["ROY CN", "ocf_ps_growth"]
    assert V.loc["DEV", "history_years"] == 4 and V.loc["DEV", "cf_basis"] != V.loc["DEV", "cf_basis"]
    assert V.loc["NEW", "history_years"] == 0
    other = {"PRD": {(pd.Timestamp(d), "CAD"): 150.0 for d in YEARS}}      # another currency: not used
    assert PF.add(U.iloc[:1], holdings, monthly(GOLD), other, BASE).cf_basis.iloc[0] == "FCF"


def ops(*rows):
    cols = ["ticker", "period_end", "measure", "category", "metal", "amount", "unit", "basis", "document", "url",
            "published", "notes"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows], columns=cols)


def test_production_is_valued_at_the_base_deck_and_taken_per_share():
    """A20: each year's production in gold ounces at the base deck's prices (copper lb × copper ÷ gold), ÷ that
    year's share count; metals outside the deck are left out."""
    O = ops(*[("PRD", d, "production", "", "gold", 100.0, "koz", "attributable", "AR", "https://x", d, "")
              for d in YEARS[1:]],
            *[("PRD", d, "production", "", "copper", 10.0, "Mlb", "attributable", "AR", "https://x", d, "")
              for d in YEARS[1:]],
            ("PRD", YEARS[-1], "production", "", "zinc", 50.0, "kt", "attributable", "AR", "https://x", "", ""))
    A = PF.annual(company())
    P = PF.per_share_units(O[O.measure == "production"], A, BASE)
    geo = 100_000.0 + 10e6 * BASE["copper"] / BASE["gold"]
    assert list(P.index.year) == [2023, 2024, 2025]
    assert list(P) == pytest.approx([geo / 100.0, geo / 110.0, geo / 125.0])
    assert PF.unit_factor("kt", "copper") == pytest.approx(2_204_622.6) and PF.unit_factor("Moz", "gold") == 1e6


def test_reserves_and_resources_are_weighted_by_category():
    """A21: reserves plus M&I (exclusive of reserves) at the roadmap 3 weights; developers add inferred."""
    O = ops(*[("PRD", d, "resources", c, "gold", a, "Moz", "attributable", "AR", "https://x", d, "")
              for d in YEARS[2:] for c, a in (("reserves", 1.0), ("mi", 2.0), ("inferred", 4.0))])
    A = PF.annual(company())
    w = PF.weights()
    assert w == {"reserves": 1.0, "mi": 0.5, "inferred": 0.2}
    prod = PF.per_share_units(O, A, BASE, categories=("reserves", "mi"))
    assert prod.iloc[-1] == pytest.approx((1e6 * 1.0 + 2e6 * 0.5) / 125.0)
    dev = PF.per_share_units(O, A, BASE, categories=("reserves", "mi", "inferred"))
    assert dev.iloc[-1] == pytest.approx((1e6 + 1e6 + 4e6 * 0.2) / 125.0)


def test_research_measures_by_tier():
    """A21: production and reserves per share growth (producers), GEOs sold per share (royalties), resources per
    share (developers), each the trend growth of the per-share series."""
    O = ops(*[("PRD", d, "production", "", "gold", a, "koz", "attributable", "AR", "https://x", d, "")
              for d, a in zip(YEARS, [100.0, 110.0, 130.0, 150.0])],
            *[("ROY", d, "geo_sold", "", "geo", a, "koz", "attributable", "AR", "https://x", d, "")
              for d, a in zip(YEARS, [50.0, 55.0, 60.0, 70.0])])
    A = PF.annual(company())
    m = PF.research_measures(O[O.ticker == "PRD"], A, BASE, "producer")
    shares = [100.0, 100.0, 110.0, 125.0]
    assert m["production_ps_growth"] == pytest.approx(
        PF.trend_growth([a * 1000 / s for a, s in zip([100.0, 110.0, 130.0, 150.0], shares)]))
    assert np.isnan(m["reserves_ps_growth"])
    r = PF.research_measures(O[O.ticker == "ROY"], A, BASE, "royalty")
    assert r["geo_ps_growth"] == pytest.approx(
        PF.trend_growth([a * 1000 / s for a, s in zip([50.0, 55.0, 60.0, 70.0], shares)]))
    assert set(PF.research_measures(O.iloc[:0], A, BASE, "developer")) == {"resource_ps_growth"}
