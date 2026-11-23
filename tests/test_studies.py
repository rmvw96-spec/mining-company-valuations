"""Study cash-flow rebuilds (roadmap 6, Part 3). Offline. The fixture is the Silver Sand PFS (AMC for New Pacific,
effective Jun 19, 2024, Table 22.4 and 22.6), a public technical report: rebuilt NPV 740 at 5%, 568 at 8%."""
from datetime import date

import numpy as np
import pandas as pd

from minerval import studies as S

POST = [-160, -199, 181, 197, 184, 117, 111, 109, 97, 118, 87, 68, 75, 120, 77, -13, -7]
PRE = [-160, -199, 242, 264, 244, 157, 149, 145, 129, 160, 126, 97, 110, 177, 112, -13, -7]
AG_MOZ = [0, 0, 16, 17, 16, 12, 12, 11, 11, 12, 11, 9, 10, 13, 9, 0, 0]


def silver_sand(**k):
    p = {"ticker": "NEWP", "project": "Silver Sand", "attributable_pct": "100", "study_type": "PFS",
         "study_date": "2024-06-19", "study_price": "silver 24", "study_npv_usd_m": "740",
         "study_discount_rate": "5", "discounting": "mid-year", "marginal_tax_rate": "32.5",
         "net_revenue_share": "0.917",
         "sensitivity": "silver 18:329, 30:1124 @5%; silver 18:232, 30:882 @8%", "initial_capex_usd_m": "358",
         "remaining_capex_usd_m": "", "construction_start": "", "first_production": "", "permits": "", "committed": "", "superseded": "",
         "source": "x", "as_of": "", "notes": ""}
    p.update(k)
    F = pd.DataFrame({"ticker": "NEWP", "project": "Silver Sand", "study_date": "2024-06-19",
                      "year": range(1, len(POST) + 1), "pre_tax_fcf_usd_m": PRE, "post_tax_fcf_usd_m": POST,
                      "payable_gold_koz": np.nan, "payable_silver_koz": [a * 1000 for a in AG_MOZ],
                      "payable_copper_mlb": np.nan, "payable_lead_mlb": np.nan, "payable_zinc_mlb": np.nan,
                      "source": "x"})
    return pd.Series(p), F


def test_parsers():
    assert S.parse_prices("gold 3,400; silver 45; copper 4.50") == {"gold": 3400.0, "silver": 45.0, "copper": 4.5}
    assert S.parse_sensitivity("silver 18:329, 30:1124 @5%; gold 3000:10 @8%") == [
        ("silver", 18.0, 329.0, 0.05), ("silver", 30.0, 1124.0, 0.05), ("gold", 3000.0, 10.0, 0.08)]


def test_all_metals_sensitivity_rows():
    assert S.parse_sensitivity("all -20%:1550.7, +10%:3198.3 @5%") == [("all", -0.2, 1550.7, 0.05),
                                                                        ("all", 0.1, 3198.3, 0.05)]
    p, F = silver_sand(sensitivity="all -25%:329 @5%")              # silver 24 -> 18: the same as 'silver 18'
    assert S.rebuild(p, F)["sensitivity_worst"] < 0.02


def test_rebuild_matches_the_published_npv_and_sensitivities():
    p, F = silver_sand()
    c = S.rebuild(p, F)
    assert abs(c["rebuilt_at_study"] - 740) < 2 and abs(c["npv_diff"]) < 0.01
    assert c["tax_share"] == 0.675                                   # 1 - the study's 32.5% marginal rate
    assert c["sensitivity_worst"] < 0.05 and c["ok"]
    assert abs(S.npv(F, 0.08, {"silver": 24}, {"silver": 24}, c["tax_share"], 0.917) - 568) < 2


def test_without_a_marginal_rate_the_average_share_is_used_and_flagged():
    p, F = silver_sand(marginal_tax_rate="")
    c = S.rebuild(p, F)
    assert 0.72 < c["tax_share"] < 0.74 and any("average cash flows" in f for f in c["flags"])


def test_a_study_that_does_not_rebuild_is_flagged_and_not_used():
    p, F = silver_sand(study_npv_usd_m="900")
    c = S.rebuild(p, F)
    assert not c["ok"] and c["flags"][0].startswith("rebuilt NPV")
    x = S.risk_adjusted(p, F, {"silver": 30}, 0.09, date(2026, 11, 21))
    assert x["npv"] is None and "rebuilt NPV" in x["why"]


def test_risk_adjusted_needs_a_construction_date_and_a_stage_probability(monkeypatch):
    monkeypatch.setattr(S, "cfg", lambda: {"stage_probability": {}, "years_to_start": {}})
    p, F = silver_sand()
    x = S.risk_adjusted(p, F, {"silver": 30}, 0.09, date(2026, 11, 21))
    assert x["npv"] > 0 and x["risk_adjusted"] is None and x["why"].startswith("no guided construction start")
    p2, _ = silver_sand(construction_start="2028-11-21", attributable_pct="80")
    y = S.risk_adjusted(p2, F, {"silver": 30}, 0.09, date(2026, 11, 21))
    assert "no probability of success" in y["why"]
    monkeypatch.setattr(S, "cfg", lambda: {"stage_probability": {"PFS": 0.5}, "years_to_start": {}})
    z = S.risk_adjusted(p2, F, {"silver": 30}, 0.09, date(2026, 11, 21))
    assert abs(z["risk_adjusted"] - y["npv"] / 1.09 ** 2 * 0.5 * 0.8) < 1      # two years, 50%, 80% share


def test_production_years_start_at_the_first_year_with_payable_metal():
    _, F = silver_sand()
    P = S.production_years(F)
    assert list(P.year) == list(range(1, len(POST) - 1)) and list(P.post_tax_fcf_usd_m) == POST[2:]


def test_a_project_under_construction_is_valued_from_first_production(monkeypatch):
    """Construction under way: the study's years from first production, placed at the guided date, less the
    remaining capex the company states (the capex already spent isn't counted again)."""
    monkeypatch.setattr(S, "cfg", lambda: {"stage_probability": {"construction": 0.9}, "years_to_start": {}})
    p, F = silver_sand(committed="yes", construction_start="2025-01-01", first_production="2027-11-21",
                       remaining_capex_usd_m="100", attributable_pct="80")
    x = S.risk_adjusted(p, F, {"silver": 30}, 0.09, date(2026, 11, 21))
    v = S.npv(S.production_years(F), 0.09, {"silver": 24 + 6}, {"silver": 24}, x["check"]["tax_share"],
              x["check"]["rev_share"], "mid-year")
    assert x["npv"] == v and x["stage"] == "construction"
    assert abs(x["risk_adjusted"] - (v / 1.09 * 0.9 - 100) * 0.8) < 0.5          # one year to first production
    assert x["why"] == ""


def test_under_construction_needs_first_production_and_remaining_capex(monkeypatch):
    monkeypatch.setattr(S, "cfg", lambda: {"stage_probability": {"construction": 0.9}, "years_to_start": {}})
    p, F = silver_sand(committed="yes", construction_start="2025-01-01", remaining_capex_usd_m="100")
    x = S.risk_adjusted(p, F, {"silver": 30}, 0.09, date(2026, 11, 21))
    assert x["risk_adjusted"] is None and "no guided first production" in x["why"]
    p, F = silver_sand(committed="yes", construction_start="2025-01-01", first_production="2027-11-21")
    y = S.risk_adjusted(p, F, {"silver": 30}, 0.09, date(2026, 11, 21))
    assert y["risk_adjusted"] is None and "no remaining capex" in y["why"]
    p, F = silver_sand(committed="yes", construction_start="2027-11-21")          # not started: the whole study
    z = S.risk_adjusted(p, F, {"silver": 30}, 0.09, date(2026, 11, 21))
    assert abs(z["risk_adjusted"] - z["npv"] / 1.09 * 0.9) < 0.5


def test_superseded_study_has_no_npv():
    p, F = silver_sand(superseded="Carangas PEA, Jul 2026")
    assert S.risk_adjusted(p, F, {}, 0.09, date(2026, 11, 21))["why"].startswith("superseded")


def test_record_files_are_well_formed():
    P, C = S.load()
    assert list(P.columns) == S.PROJECT_COLS and list(C.columns) == S.CASHFLOW_COLS
    assert set(P.study_type) <= set(S.STUDY_TYPES)
    for _, p in P.iterrows():
        assert p.source.startswith("https://") and S.parse_prices(p.study_price)
        F = S.flows(C, p)
        if len(F):
            assert list(F.year) == list(range(1, len(F) + 1)), f"{p.project}: years must run 1, 2, 3..."


def test_discount_rate_uses_the_country_table_add_on():
    from minerval.config import settings
    P = settings()["pnav"]
    C = pd.DataFrame({"ticker": ["A", "B", "C"], "addon_override": [np.nan, 2.0, np.nan],
                      "country_weights": ["Ecuador:1", "", ""], "addon_pct_points": [np.nan, np.nan, 1.5]})
    table = {("Ecuador", ""): 3.0}
    base = P["ten_year_yield"] + P["risk_premium"]
    assert abs(S.discount_rate("A", C, table) - (base + 0.03)) < 1e-9          # the country table
    assert abs(S.discount_rate("B", C, table) - (base + 0.02)) < 1e-9          # an override
    assert abs(S.discount_rate("C", C, table) - (base + 0.015)) < 1e-9         # the hand-set figure


def test_stage_and_assumed_time_to_construction(monkeypatch):
    p, F = silver_sand()
    assert S.stage(p) == "PFS"
    assert S.stage(silver_sand(permits="yes")[0]) == "permitted"
    assert S.stage(silver_sand(permits="yes", study_type="PEA")[0]) == "PEA"      # permits before a PFS don't count
    assert S.stage(silver_sand(committed="yes")[0]) == "construction"
    monkeypatch.setattr(S, "cfg", lambda: {"stage_probability": {"PFS": 0.5}, "years_to_start": {"PFS": 3}})
    x = S.risk_adjusted(p, F, {"silver": 30}, 0.09, date(2026, 11, 21))
    assert abs(x["risk_adjusted"] - x["npv"] / 1.09 ** 3 * 0.5) < 1 and x["why"].startswith("assumed 3 years")
    g = S.risk_adjusted(silver_sand(construction_start="2025-01-01")[0], F, {"silver": 30}, 0.09, date(2026, 11, 21))
    assert g["years"] == 0.0 and g["why"] == ""                                     # a guided date in the past: no wait
