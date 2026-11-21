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
         "construction_start": "", "first_production": "", "committed": "", "superseded": "",
         "source": "x", "as_of": "", "notes": ""}
    p.update(k)
    F = pd.DataFrame({"ticker": "NEWP", "project": "Silver Sand", "study_date": "2024-06-19",
                      "year": range(1, len(POST) + 1), "pre_tax_fcf_usd_m": PRE, "post_tax_fcf_usd_m": POST,
                      "payable_gold_koz": np.nan, "payable_silver_koz": [a * 1000 for a in AG_MOZ],
                      "payable_copper_mlb": np.nan, "source": "x"})
    return pd.Series(p), F


def test_parsers():
    assert S.parse_prices("gold 3,400; silver 45; copper 4.50") == {"gold": 3400.0, "silver": 45.0, "copper": 4.5}
    assert S.parse_sensitivity("silver 18:329, 30:1124 @5%; gold 3000:10 @8%") == [
        ("silver", 18.0, 329.0, 0.05), ("silver", 30.0, 1124.0, 0.05), ("gold", 3000.0, 10.0, 0.08)]


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
    p, F = silver_sand()
    x = S.risk_adjusted(p, F, {"silver": 30}, 0.09, date(2026, 11, 21))
    assert x["npv"] > 0 and x["risk_adjusted"] is None and x["why"] == "no guided construction start"
    p2, _ = silver_sand(construction_start="2028-11-21", attributable_pct="80")
    y = S.risk_adjusted(p2, F, {"silver": 30}, 0.09, date(2026, 11, 21))
    assert "no probability of success" in y["why"]
    monkeypatch.setattr(S, "cfg", lambda: {"stage_probability": {"PFS": 0.5}})
    z = S.risk_adjusted(p2, F, {"silver": 30}, 0.09, date(2026, 11, 21))
    assert abs(z["risk_adjusted"] - y["npv"] / 1.09 ** 2 * 0.5 * 0.8) < 1      # two years, 50%, 80% share


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
