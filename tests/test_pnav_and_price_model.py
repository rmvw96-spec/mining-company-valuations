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
