"""The jurisdiction add-on from the country table: score mapping, table rules, region medians, weights, override, fallback."""
import math

import pandas as pd
import pytest

from minerval import jurisdiction as J


C = {"top_addon": 3.0, "floor_score": 90.0, "step": 0.25, "years": 3}


@pytest.fixture
def table(tmp_path):
    rows = [
        {"country": "Canada", "region": "Ontario", "rule": "score", "addon_pct_points": 0.0},
        {"country": "Canada", "region": "Quebec", "rule": "score", "addon_pct_points": 0.5},
        {"country": "Canada", "region": "Manitoba", "rule": "score", "addon_pct_points": 1.0},
        {"country": "Mexico", "region": "", "rule": "score", "addon_pct_points": 1.75},
        {"country": "China", "region": "", "rule": "score", "addon_pct_points": 2.75},
        {"country": "Burkina Faso", "region": "", "rule": "fixed", "addon_pct_points": 3.25},
        {"country": "Suriname", "region": "", "rule": "top"},
        {"country": "Bulgaria", "region": "", "rule": "median"},
    ]
    T = pd.DataFrame(rows, columns=J.TABLE_COLS)
    T["basis"], T["source"], T["as_of"] = "test", "test", "2026-02"
    T.to_csv(tmp_path / "country_risk.csv", index=False)
    return J.load_table(tmp_path / "country_risk.csv", C)


@pytest.mark.parametrize("score,want", [(100, 0.0), (90, 0.0), (89, 0.0), (85, 0.25), (45, 1.5), (0, 3.0),
                                        (60, 1.0), (52.88, 1.25)])
def test_addon_from_score(score, want):
    assert J.addon_from_score(score, C) == want


def test_average_score_uses_the_latest_years_and_skips_blanks():
    assert J.average_score({"ppi_2025": 40.0, "ppi_2024": 50.0, "ppi_2023": 60.0, "ppi_2022": 0.0}, C) == 50.0
    assert J.average_score({"ppi_2025": 0.0, "ppi_2024": None, "ppi_2023": 30.0}, C) == 15.0
    assert J.average_score({"ppi_2025": None}, C) is None


def test_table_rules_and_region_median(table):
    assert table[("Canada", "Quebec")] == 0.5
    assert table[("Canada", "")] == 0.5                           # median of its provinces
    assert table[("Burkina Faso", "")] == 3.25                    # fixed
    assert table[("Suriname", "")] == 3.0                         # top
    assert table[("Bulgaria", "")] == 1.0                         # median of the scored rows


def test_build_table_rewrites_scored_rows_only(tmp_path):
    path = tmp_path / "country_risk.csv"
    pd.DataFrame([{"country": "Old", "region": "", "rule": "score", "addon_pct_points": 9.0},
                  {"country": "Cambodia", "region": "", "rule": "fixed", "addon_pct_points": 2.0, "basis": "b",
                   "source": "s", "as_of": "2026-11"}], columns=J.TABLE_COLS).to_csv(path, index=False)
    pd.DataFrame([{"country": "Chile", "region": "", "few_responses": "False", "ppi_2025": 77.93, "ppi_2024": 66.2,
                   "ppi_2023": 55.66},
                  {"country": "China", "region": "", "few_responses": "True", "ppi_2025": 0.0, "ppi_2024": None,
                   "ppi_2023": 14.35}]).to_csv(tmp_path / "scores.csv", index=False)
    J.build_table(tmp_path / "scores.csv", "Fraser 2025", "2026-02", path, C)
    T = pd.read_csv(path, keep_default_na=False, na_values=[""]).set_index("country")
    assert "Old" not in T.index and T.loc["Cambodia", "addon_pct_points"] == 2.0
    assert T.loc["Chile", "addon_pct_points"] == 0.75                  # average 66.6 -> 0.78 -> 0.75
    assert T.loc["China", "addon_pct_points"] == 2.75 and T.loc["China", "few_responses"] == "yes"


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
                           table) == (pytest.approx(0.7), "table")
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
    assert list(A.addon_pct_points[:2]) == [2.75, 1.5] and list(A.addon_basis[:2]) == ["table", "manual"]
    assert list(A.addon_manual[:2]) == [0.5, 1.5]
    cmp = J.comparison(R, table)
    assert list(cmp.ticker) == ["A", "B"] and list(cmp.change) == [2.25, 0.0]


def test_missing_table_means_every_addon_stays_manual(tmp_path):
    assert J.load_table(tmp_path / "none.csv") == {}
