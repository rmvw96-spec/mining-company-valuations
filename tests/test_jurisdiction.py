"""The jurisdiction add-on from the country table: quartile bands, region medians, weights, override, fallback."""
import math

import pandas as pd
import pytest

from minerval import jurisdiction as J


@pytest.fixture
def table(tmp_path):
    rows = [
        {"country": "Canada", "region": "Ontario", "iai_quartile": 1},
        {"country": "Canada", "region": "Quebec", "iai_quartile": 2},
        {"country": "Canada", "region": "Manitoba", "iai_quartile": 3},
        {"country": "Mexico", "region": "", "iai_quartile": 3},
        {"country": "China", "region": "", "iai_quartile": 4},
        {"country": "Burkina Faso", "region": "", "addon_pct_points": 3.25},
    ]
    T = pd.DataFrame(rows, columns=J.TABLE_COLS)
    T["basis"], T["source"], T["as_of"] = "test", "test", "2026-02-26"
    T.to_csv(tmp_path / "country_risk.csv", index=False)
    return J.load_table(tmp_path / "country_risk.csv")


@pytest.mark.parametrize("rank,q", [(1, 1), (17, 1), (18, 2), (34, 2), (35, 3), (51, 3), (52, 4), (68, 4)])
def test_quartile(rank, q):
    assert J.quartile(rank, 68) == q


def test_quartile_addon():
    assert [J.quartile_addon(q, [0.0, 1.0, 2.0, 4.0]) for q in (1, 2, 3, 4)] == [0.0, 1.0, 2.0, 4.0]


def test_table_bands_explicit_rows_and_region_median(table):
    assert table[("Canada", "Ontario")] == 0.0 and table[("Canada", "Quebec")] == 1.0
    assert table[("Canada", "Manitoba")] == 2.0
    assert table[("Canada", "")] == 1.0                           # median of its ranked provinces
    assert table[("Mexico", "")] == 2.0 and table[("China", "")] == 4.0
    assert table[("Burkina Faso", "")] == 3.25                    # not ranked: its own figure


def test_parse_and_check_weights(table):
    parts = J.parse_weights("Canada/Ontario:0.6; Mexico:0.4")
    assert parts == [("Canada", "Ontario", 0.6), ("Mexico", "", 0.4)]
    assert J.check_weights(parts, table, 0.01) == []
    assert J.parse_weights("") == [] and J.parse_weights(float("nan")) == []
    assert "weights sum to 0.900" in J.check_weights(J.parse_weights("Mexico:0.5;China:0.4"), table, 0.01)
    assert J.check_weights(J.parse_weights("Peru:1"), table, 0.01) == ["Peru is not in country_risk.csv"]
    with pytest.raises(ValueError):
        J.parse_weights("Mexico")


def test_company_addon(table):
    assert J.company_addon({"country_weights": "Canada/Ontario:0.6;Mexico:0.4", "addon_pct_points": 1.5},
                           table) == (pytest.approx(0.8), "table")
    assert J.company_addon({"country_weights": "Canada/Ontario:0.6;Mexico:0.4", "addon_override": 3.0},
                           table) == (3.0, "override")
    assert J.company_addon({"country_weights": "", "addon_pct_points": 1.5}, table) == (1.5, "manual")
    assert J.company_addon({"country_weights": "Peru:1", "addon_pct_points": 1.25}, table) == (1.25, "manual")
    v, basis = J.company_addon({"country_weights": None, "addon_pct_points": float("nan")}, table)
    assert math.isnan(v) and basis == "manual"


def test_apply_and_comparison(table):
    R = pd.DataFrame([
        {"ticker": "A", "holding": "A Co", "basis": "FCF", "addon_pct_points": 0.5, "country_weights": "China:1",
         "addon_override": None},
        {"ticker": "B", "holding": "B Co", "basis": "FCF", "addon_pct_points": 1.5, "country_weights": None,
         "addon_override": None},
        {"ticker": "C", "holding": "C Dev", "basis": None, "addon_pct_points": None, "country_weights": "China:1",
         "addon_override": None},
    ])
    A = J.apply(R, table)
    assert list(A.addon_pct_points[:2]) == [4.0, 1.5] and list(A.addon_basis[:2]) == ["table", "manual"]
    assert list(A.addon_manual[:2]) == [0.5, 1.5]
    C = J.comparison(R, table)
    assert list(C.ticker) == ["A", "B"] and list(C.change) == [3.5, 0.0]


def test_missing_table_means_every_addon_stays_manual(tmp_path):
    assert J.load_table(tmp_path / "none.csv") == {}
