"""Stress test: dilution, breakevens and the linear free-cash-flow model."""
import numpy as np
import pandas as pd
import pytest

from minerval.stress import fund_table, latest, per_holding, share_change

from conftest import FakeMetals


def shares(*pts):
    return {"annualOrdinarySharesNumber": [{"date": d, "cur": None, "val": v} for d, v in pts]}


def test_share_change():
    s = shares(("2023-12-31", 80.0), ("2025-12-31", 100.0), ("2026-12-31", 110.0))
    assert share_change(s, 1, 100) == pytest.approx(0.10)
    assert share_change(s, 3, 200) == pytest.approx(110 / 80 - 1)
    assert share_change(shares(("2023-12-31", 80.0), ("2026-12-31", 110.0)), 1, 100) is None   # too far from 1 year
    assert share_change(shares(("2026-12-31", 110.0)), 1, 100) is None
    assert share_change(shares(("2025-12-31", 0.0), ("2026-12-31", 110.0)), 1, 100) is None


def test_quarterly_and_annual_counts_are_merged():
    s = shares(("2025-12-31", 100.0))
    s["quarterlyOrdinarySharesNumber"] = [{"date": "2026-12-31", "cur": None, "val": 120.0}]
    assert share_change(s, 1, 100) == pytest.approx(0.20)


def test_latest_skips_unknown_currencies():
    ser = {"a": [{"date": "2026-09-30", "cur": "XXX", "val": 1}, {"date": "2026-06-30", "cur": "USD", "val": 2}]}
    assert latest(ser, ["a"], {"USD": 1.0})["val"] == 2
    assert latest(ser, ["a"], {}) is None


def company(ticker, fund="SGDM", **kw):
    r = {"ticker": ticker, "fund": fund, "kind": "company", "weight_pct": 10.0, "mcap": 2000e6, "ev": 1900e6,
         "revenue": 1000e6, "fin_date": "2026-09-30", "ocf": 300e6, "fcf": 100e6, "ebitda": 400e6,
         "cash": 200e6, "debt": 100e6, "stale": False}
    r.update(kw)
    return r


@pytest.fixture
def stressed():
    metals = FakeMetals(spot={"gold": 4400.0, "silver": 50.0, "copper": 5.0},
                        avg={"gold": 4000.0, "silver": 50.0, "copper": 5.0},
                        scenarios={"Severe": {"gold": 2000.0, "silver": 25.0, "copper": 3.0},
                                   "Low": {"gold": 3000.0, "silver": 35.0, "copper": 4.0},
                                   "High": {"gold": 5000.0, "silver": 70.0, "copper": 7.0}})
    X = pd.DataFrame([company("AAA"), company("BBB", weight_pct=5.0, fcf=-50e6, ocf=-10e6, revenue=float("nan")),
                      company("PSLV", kind="physical metal", mcap=float("nan"))])
    cache = {"fx": {"USD": 1.0}, "holdings": {"AAA": {"series": {
        "quarterlyCurrentAssets": [{"date": "2026-09-30", "cur": "USD", "val": 500e6}],
        "quarterlyCurrentLiabilities": [{"date": "2026-09-30", "cur": "USD", "val": 300e6}],
        **shares(("2025-09-30", 90e6), ("2026-09-30", 99e6))}}}}
    return per_holding(X, metals, cache).set_index("ticker"), metals


def test_scenario_cash_flows(stressed):
    M, _ = stressed
    a = M.loc["AAA"]
    assert a.revenue_change_today == pytest.approx(1000e6 * 0.1)
    assert a.fcf_Today == pytest.approx(100e6 + 0.7 * 100e6)
    assert a.fcf_Severe == pytest.approx(100e6 + 0.7 * 1000e6 * (2000 / 4000 - 1))
    assert a.ebitda_High == pytest.approx(400e6 + 0.95 * 1000e6 * (5000 / 4000 - 1))
    assert M.loc["BBB"].fcf_Severe == -50e6                     # no revenue: doesn't move with metal prices


def test_breakeven(stressed):
    M, metals = stressed
    a = M.loc["AAA"]
    # FCF(k) = 0.7 x 1000 x 1.1 x k + (100 - 700): zero at k = 600 / 770
    assert a.be_k == pytest.approx(600 / 770)
    assert a.be_metal == "gold" and a.be_price == pytest.approx(600 / 770 * 4400)
    # The linear model gives the same FCF as the scenario columns, at any prices.
    for name in ("Severe", "Low", "Today", "High"):
        g = metals.scenario(name)["gold"]
        assert (a.fcf_intercept_m + a.fcf_per_gold_m * g) * 1e6 == pytest.approx(a[f"fcf_{name}"])


def test_balance_sheet_and_dilution(stressed):
    M, _ = stressed
    a, b = M.loc["AAA"], M.loc["BBB"]
    assert a.netcash_pct == pytest.approx(5.0)
    assert a.wc_pct == pytest.approx(10.0)
    assert a.dil1 == pytest.approx(10.0)
    assert pd.isna(a.runway)
    assert b.runway == pytest.approx(200e6 / 50e6)               # burning cash: years of cash left
    assert not M.loc["PSLV"].comp


@pytest.mark.filterwarnings("ignore:invalid value:RuntimeWarning")   # funds with no holdings here
def test_fund_breakeven(stressed):
    M, metals = stressed
    F = fund_table(M, metals)
    f = F.loc["SGDM"]
    wm = {"AAA": 10 / 2000e6, "BBB": 5 / 2000e6}
    a = {"AAA": 0.7 * 1000e6 * 1.1, "BBB": 0.0}
    b = {"AAA": 100e6 - 0.7 * 1000e6, "BBB": -50e6}
    k = -sum(wm[t] * b[t] for t in wm) / sum(wm[t] * a[t] for t in wm)
    assert f["breakeven % of today"] == pytest.approx(100 * k)
    assert f["breakeven metal"] == "gold $/oz"
    assert f["burning cash %"] == 5.0 and f["runway < 2 yrs %"] == 0.0


# --- producers' cost increase ---

def stress_inputs():
    metals = FakeMetals(spot={"gold": 4400.0, "silver": 50.0, "copper": 5.0},
                        avg={"gold": 4000.0, "silver": 50.0, "copper": 5.0},
                        scenarios={"Severe": {"gold": 2000.0, "silver": 25.0, "copper": 3.0},
                                   "Low": {"gold": 3000.0, "silver": 35.0, "copper": 4.0},
                                   "High": {"gold": 5000.0, "silver": 70.0, "copper": 7.0}})
    X = pd.DataFrame([company("AAA"), company("BBB", weight_pct=5.0, fcf=-50e6, ocf=-10e6, revenue=float("nan")),
                      company("CCC", revenue=50e6, fcf=200e6)])               # FCF above revenue: no cost base
    return X, metals, {"fx": {"USD": 1.0}, "holdings": {}}


def test_zero_cost_increase_changes_nothing(monkeypatch):
    from minerval import stress
    X, metals, cache = stress_inputs()
    got = per_holding(X, metals, cache, cost_increase=0.0)
    monkeypatch.setattr(stress, "cost_change", lambda *a, **k: 0.0)          # the code before the cost term
    before = per_holding(X, metals, cache, cost_increase=0.0)
    pd.testing.assert_frame_equal(got, before, check_exact=True)


def test_ten_percent_cost_increase():
    X, metals, cache = stress_inputs()
    M = per_holding(X, metals, cache, cost_increase=0.10).set_index("ticker")
    a = M.loc["AAA"]
    assert a.cost_base_m == pytest.approx(900.0)                            # revenue 1000 - FCF 100
    assert a.fcf_Today == pytest.approx(100e6 + 70e6 - 0.7 * 900e6 * 0.1)   # = 107e6
    assert a.ocf_Low == pytest.approx(300e6 + 0.7 * 1000e6 * (3000 / 4000 - 1) - 0.7 * 700e6 * 0.1)
    assert a.ebitda_High == pytest.approx(400e6 + 0.95 * 1000e6 * 0.25 - 600e6 * 0.1)
    assert a.be_k == pytest.approx(663 / 770)                               # b = 100 - 700 - 63
    assert M.loc["BBB"].fcf_Today == -50e6                                  # no revenue: not a producer
    assert M.loc["CCC"].cost_base_m == 0.0


def test_dilution_median_is_by_fund_weight():
    from minerval.stress import _wmedian
    c = pd.DataFrame({"weight_pct": [10.0, 1.0, 1.0, 1.0], "dil1": [0.5, 40.0, 60.0, 80.0]})
    assert _wmedian(c, "dil1") == 0.5                       # one big holding outweighs three small diluters
    assert c.dil1.median() == 50.0                          # the unweighted median would say 50%
    assert np.isnan(_wmedian(c.assign(dil1=np.nan), "dil1"))
