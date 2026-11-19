"""Metal-price sensitivity and P/NAV."""
import pandas as pd
import pytest

from minerval import price_model
from minerval.pnav import annuity, compute, show
from minerval.price_model import mix_for, revenue_change

from conftest import FakeMetals


def test_revenue_change():
    assert revenue_change(100.0, {"gold": 1.0}, {"gold": 110.0}, {"gold": 100.0}) == pytest.approx(10.0)
    mix = {"silver": 0.6, "gold": 0.4}
    got = revenue_change(1000.0, mix, {"silver": 60.0, "gold": 3600.0}, {"silver": 50.0, "gold": 4000.0})
    assert got == pytest.approx(1000 * (0.6 * 0.2 + 0.4 * -0.1))
    assert revenue_change(0.0, mix, {}, {}) == 0.0
    assert revenue_change(-5.0, mix, {}, {}) == 0.0


def test_mix_for_uses_table_then_fund_default():
    table = {"WPM": {"gold": 0.57, "silver": 0.4}, "BLANK": {}}
    assert mix_for("WPM", "SGDM", table) == {"gold": 0.57, "silver": 0.4}
    assert mix_for("BLANK", "SGDM", table) == {}                   # an all-blank row means no adjustment
    assert mix_for("OTHER", "SLVR", table) == {"silver": 0.6, "gold": 0.4}
    assert mix_for("OTHER", "COPJ", table) == {"copper": 0.9}


def test_metals_average_window():
    m = price_model.Metals.__new__(price_model.Metals)
    idx = pd.date_range("2025-01-01", "2026-12-31", freq="D")
    m.px = {"gold": pd.Series(range(len(idx)), index=idx, dtype=float)}
    end = pd.Timestamp("2026-06-30")
    want = m.px["gold"][(idx > end - pd.Timedelta(days=365)) & (idx <= end)].mean()
    assert m.average("gold", "2026-06-30") == pytest.approx(want)
    assert len(m.px["gold"][(idx > end - pd.Timedelta(days=365)) & (idx <= end)]) == 365


def test_annuity_and_display():
    assert annuity(0.10, 10) == pytest.approx(6.144567, rel=1e-6)
    assert annuity(0.05, 1) == pytest.approx(1 / 1.05)
    assert show(100, 0) == "negative" and show(100, -5) == "negative"
    assert show(2100, 100) == ">20"
    assert show(150, 100) == pytest.approx(1.5)


def pnav_row(**kw):
    r = {"sheet_row": 12, "basis": "FCF", "addon_pct_points": 1.0, "reserve_life_years": 40.0, "mcap_m": 1000.0,
         "net_cash_m": 100.0, "revenue_m": 500.0, "fcf_m": 80.0, "ocf_m": 150.0, "price_usd": 10.0,
         "model_nav_per_share_usd": None, "study_value_usd_m": None,
         "share_gold": 1.0, "share_silver": 0.0, "share_copper": 0.0,
         "avg_gold": 4000.0, "avg_silver": 50.0, "avg_copper": 5.0}
    r.update(kw)
    return r


def test_pnav_compute():
    scen = {"Low": {"gold": 3500.0, "silver": 35.0, "copper": 4.0},
            "High": {"gold": 5000.0, "silver": 70.0, "copper": 7.0},
            "All-time high": {"gold": 5586.2, "silver": 121.3, "copper": 6.83}}
    metals = FakeMetals(spot={"gold": 4400.0, "silver": 50.0, "copper": 5.0}, scenarios=scen)
    I = pd.DataFrame([pnav_row(), pnav_row(sheet_row=13, basis=None, model_nav_per_share_usd=8.0),
                      pnav_row(sheet_row=14, basis="OCF", fcf_m=-500.0)])
    T = compute(I, metals, ten_year_yield=0.05).set_index("sheet_row")
    rate = 0.05 + 0.03 + 0.01
    ann = annuity(rate, 25)                                       # 40 years capped at 25
    chg_today = 0.7 * 500 * (4400 / 4000 - 1)
    assert T.loc[12, "discount_rate"] == pytest.approx(rate) and T.loc[12, "years"] == 25
    assert T.loc[12, "pnav Today"] == pytest.approx(1000 / ((80 + chg_today) * ann + 100))
    assert T.loc[12, "pnav Today, 10 years"] == pytest.approx(1000 / ((80 + chg_today) * annuity(rate, 10) + 100))
    assert T.loc[12, "pnav Today, before capital spending"] == pytest.approx(1000 / ((150 + chg_today) * ann + 100))
    chg_low = 0.7 * 500 * (3500 / 4000 - 1)
    assert T.loc[12, "pnav Low"] == pytest.approx(1000 / ((80 + chg_low) * ann + 100))
    assert T.loc[13, "independent or study pnav"] == pytest.approx(10 / 8)
    assert pd.isna(T.loc[13, "pnav Today"])                       # no basis: no model P/NAV
    assert T.loc[14, "pnav Today"] == pytest.approx(1000 / ((150 + chg_today) * ann + 100))   # OCF basis


# --- producers' cost increase ---

def test_cost_change():
    from minerval.price_model import cost_change
    assert cost_change(500.0, 80.0, 0.1) == pytest.approx(-0.7 * 420 * 0.1)
    assert cost_change(500.0, 80.0, 0.1, share=1.0) == pytest.approx(-42.0)
    assert cost_change(500.0, 600.0, 0.1) == 0.0            # cash flow above revenue: nothing to inflate
    assert cost_change(0.0, -80.0, 0.1) == 0.0              # no revenue: not a producer


def pnav_inputs():
    scen = {"Low": {"gold": 3500.0, "silver": 35.0, "copper": 4.0},
            "High": {"gold": 5000.0, "silver": 70.0, "copper": 7.0},
            "All-time high": {"gold": 5586.2, "silver": 121.3, "copper": 6.83}}
    metals = FakeMetals(spot={"gold": 4400.0, "silver": 50.0, "copper": 5.0}, scenarios=scen)
    I = pd.DataFrame([pnav_row(), pnav_row(sheet_row=13, basis="OCF", model_nav_per_share_usd=8.0),
                      pnav_row(sheet_row=14, basis=None, study_value_usd_m=2000.0)])
    return I, metals


def test_pnav_zero_cost_changes_nothing(monkeypatch):
    from minerval import pnav
    I, metals = pnav_inputs()
    got = compute(I, metals, ten_year_yield=0.05, cost_increase=0.0)
    monkeypatch.setattr(pnav, "cost_change", lambda *a, **k: 0.0)
    pd.testing.assert_frame_equal(got, compute(I, metals, ten_year_yield=0.05, cost_increase=0.0), check_exact=True)


def test_pnav_ten_percent_cost_increase():
    I, metals = pnav_inputs()
    T = compute(I, metals, ten_year_yield=0.05, cost_increase=0.10).set_index("sheet_row")
    ann = annuity(0.09, 25)
    chg = 0.7 * 500 * (4400 / 4000 - 1) - 0.7 * (500 - 80) * 0.1             # FCF row: cost term applies
    assert T.loc[12, "pnav Today"] == pytest.approx(1000 / ((80 + chg) * ann + 100))
    chg_ocf = 0.7 * 500 * (4400 / 4000 - 1)                                  # royalty (OCF) row: left alone
    assert T.loc[13, "pnav Today"] == pytest.approx(1000 / ((150 + chg_ocf) * ann + 100))


# --- royalty band and developer columns ---

@pytest.mark.parametrize("pnav,band", [(1.4, "Buy zone"), (1.41, "Normal range"), (2.2, "Normal range"),
                                       (2.21, "Rich"), (None, "no independent NAV")])
def test_royalty_band(pnav, band):
    from minerval.pnav import royalty_band
    assert royalty_band(pnav, 1.4, 2.2) == band


def test_royalty_columns_in_compute():
    I, metals = pnav_inputs()
    T = compute(I, metals, ten_year_yield=0.05).set_index("sheet_row")
    assert T.loc[13, "royalty_band"] == "Buy zone"                           # price 10 ÷ NAV 8 = 1.25
    assert T.loc[13, "buy_below_price_usd"] == pytest.approx(1.4 * 8.0)
    assert pd.isna(T.loc[12, "royalty_band"])                                # FCF row: not a royalty company


@pytest.mark.parametrize("months,share,want", [
    (11.9, 0.1, "Short of cash: financing likely"), (12.0, 0.1, "Watch"), (17.9, 0.1, "Watch"),
    (18.0, 0.1, "Enough cash"), ("Cash-generating", 0.1, "Enough cash"),
    (5.0, 0.5, "Short of cash: financing likely; trading near cash"), (None, 0.9, "")])
def test_developer_check(months, share, want):
    from minerval.pnav import developer_check
    assert developer_check(months, share, 12, 18, 0.5) == want


def test_months_of_cash_and_ev_per_ounce():
    from minerval.pnav import ev_per_aueq_oz, months_of_cash
    assert months_of_cash(50.0, -150.0) == pytest.approx(4.0)
    assert months_of_cash(50.0, 10.0) == "Cash-generating"
    assert months_of_cash(50.0, float("nan")) is None
    assert ev_per_aueq_oz(2.5, "oz AgEq", 82.6) == pytest.approx(206.5)     # silver oz converted to gold oz
    assert ev_per_aueq_oz(940.0, "oz AuEq", 82.6) == 940.0
    assert pd.isna(ev_per_aueq_oz(0.05, "lb Cu", 82.6))


def test_developer_columns_in_compute():
    I, metals = pnav_inputs()
    I.loc[2, ["cash_m", "fcf_12m_m", "resource_amount", "resource_unit"]] = [50.0, -150.0, 4.0, "oz Au"]
    T = compute(I, metals, ten_year_yield=0.05).set_index("sheet_row")
    d = T.loc[14]
    assert d.ev_m == pytest.approx(900.0) and d.ev_per_aueq_oz == pytest.approx(225.0)
    assert d.months_of_cash == pytest.approx(4.0)
    assert d.developer_check == "Short of cash: financing likely"
    assert pd.isna(T.loc[12, "developer_check"])


@pytest.mark.parametrize("gap,funded,months,want", [
    (-5.0, False, 3.0, "Fully funded"), (0.0, False, 3.0, "Fully funded"),
    (1234.4, False, 30.0, "Funding gap $1,234M"),                      # the gap wins over the runway
    (None, True, 3.0, "Funded to production (company says)"),
    (None, False, 3.0, "Short of cash: financing likely")])
def test_developer_check_with_financing(gap, funded, months, want):
    from minerval.pnav import developer_check
    assert developer_check(months, 0.1, 12, 18, 0.5, gap, funded) == want
    assert developer_check(months, 0.6, 12, 18, 0.5, gap, funded) == want + "; trading near cash"


def test_runway_counts_committed_funding_and_the_gap():
    from minerval.pnav import funding_gap, months_of_funding
    assert months_of_funding(50.0, -150.0, 100.0) == pytest.approx(12.0)
    assert months_of_funding(50.0, -150.0, float("nan")) == pytest.approx(4.0)      # blank counts as none
    assert months_of_funding(None, -150.0, 100.0) is None
    assert funding_gap(500.0, 120.0, 80.0) == pytest.approx(300.0)
    assert funding_gap(500.0, 120.0, None) == pytest.approx(380.0)
    assert funding_gap(float("nan"), 120.0, 80.0) is None


def test_raise_maths_worked_example():
    from minerval.pnav import raise_after
    # gap $100M, price $10, discount 15%, 50M shares, NAV $800M
    d = raise_after(100.0, 10.0, 500.0, 800.0, 0.15)
    assert d["new_shares_m"] == pytest.approx(11.7647, rel=1e-4)
    assert d["nav_per_share_after"] == pytest.approx(14.57, abs=0.005)
    assert d["dilution"] == pytest.approx(11.7647 / 50, rel=1e-4)
    assert d["pnav_after"] == pytest.approx(10 / 14.5714, rel=1e-4)
    assert raise_after(-20.0, 10.0, 500.0, 800.0, 0.15)["new_shares_m"] == 0.0
    assert "pnav_after" not in raise_after(100.0, 10.0, 500.0, None, 0.15)
    assert raise_after(100.0, None, 500.0, 800.0, 0.15) == {}


def test_weighted_resource():
    from minerval.pnav import ev_per_weighted, weighted_resource
    w = {"reserves": 1.0, "mi": 0.5, "inferred": 0.2}
    assert weighted_resource(9.0, "Mixed", 2.0, 3.0, 5.0, w) == (pytest.approx(4.5), "Split")
    assert weighted_resource(8.0, "Mixed", None, 2.5, 5.5, w) == (pytest.approx(2.35), "Split; no reserves")
    assert weighted_resource(4.0, "Measured & indicated", None, None, None, w) == (2.0, "From category: Measured & indicated")
    assert weighted_resource(4.0, "Reserves", None, None, None, w) == (4.0, "From category: Reserves")
    assert weighted_resource(5.0, "Mixed", None, None, None, w) == (None, "Needs a split (Mixed)")
    assert weighted_resource(None, None, None, None, None, w) == (None, "")
    assert ev_per_weighted(900.0, 2.0, "oz Au", 80.0) == 450.0
    assert ev_per_weighted(900.0, 100.0, "oz AgEq", 80.0) == pytest.approx(720.0)
    assert ev_per_weighted(900.0, 3000.0, "lb Cu", 80.0) == pytest.approx(0.3)
    assert pd.isna(ev_per_weighted(900.0, 0.0, "oz Au", 80.0))


def test_financing_columns_in_compute():
    I, metals = pnav_inputs()
    I.loc[2, ["cash_m", "fcf_12m_m", "resource_amount", "resource_unit", "resource_category"]] = \
        [50.0, -150.0, 4.0, "oz Au", "Measured & indicated"]
    I["committed_funding_usd_m"], I["remaining_capex_usd_m"], I["funded_per_company"] = float("nan"), float("nan"), None
    I.loc[2, ["committed_funding_usd_m", "remaining_capex_usd_m"]] = [100.0, 400.0]
    T = compute(I, metals, ten_year_yield=0.05).set_index("sheet_row")
    d = T.loc[14]
    assert d.months_of_cash == pytest.approx(12.0) and d.months_of_cash_only == pytest.approx(4.0)
    assert d.funding_gap_m == pytest.approx(250.0) and d.developer_check == "Funding gap $250M"
    assert d.new_shares_m > 0 and isinstance(d.pnav_after, float)
    assert d.weighted_amount == pytest.approx(2.0) and d.ev_per_weighted == pytest.approx(450.0)
    assert d.peer_ev_ratio == pytest.approx(1.0)                            # the only developer: its own median
