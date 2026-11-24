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


def test_start_year_discounting_leaves_year_one_undiscounted():
    """Oko West's FS discounts from the start of year 1 (its NPV is the mid-year one x 1.05^0.5)."""
    _, F = silver_sand()
    mid = S.npv(F, 0.05, {}, {}, 0.7, 0.9, "mid-year")
    assert abs(S.npv(F, 0.05, {}, {}, 0.7, 0.9, "start-year") - mid * 1.05 ** 0.5) < 1e-9


def test_production_years_start_at_the_first_year_with_payable_metal():
    _, F = silver_sand()
    P = S.production_years(F)
    assert list(P.year) == list(range(1, len(POST) - 1)) and list(P.post_tax_fcf_usd_m) == POST[2:]


def test_a_commissioning_year_still_carrying_construction_capex_isnt_a_production_year():
    """Skouries' study year -1 has first concentrate (15.7 koz) but -202.8 of construction capex: production starts
    at the first year with payable metal and a positive after-tax cash flow."""
    _, F = silver_sand()
    F.loc[F.year == 2, "payable_silver_koz"] = 500.0                  # commissioning metal in a construction year
    P = S.production_years(F)
    assert P.post_tax_fcf_usd_m.iloc[0] == POST[2] and list(P.year)[:2] == [1, 2]


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


def test_study_prices_can_vary_by_year():
    """A study whose deck changes by year (Island Gold: gold $4,000 in 2026-27, $3,200 from 2030) records each year's
    price in `study_prices`; blank years use the row's `study_price`. Each year is re-priced from its own price, and
    the rebuild at the study's prices is the table's own after-tax cash flow, discounted."""
    p, F = silver_sand(sensitivity="")
    F["study_prices"] = ["silver 30"] * 8 + [""] * (len(F) - 8)        # years 1-8 at $30, then the row's $24
    c = S.rebuild(p, F)
    plain = S.npv(F, 0.05, {}, {}, c["tax_share"], c["rev_share"])
    assert abs(c["rebuilt_at_study"] - plain) < 1e-9 and c["ok"]        # no re-pricing at the study's own prices
    got = S.npv(F, 0.09, {"silver": 36}, c["study_prices"], c["tax_share"], c["rev_share"])
    want = sum((r.post_tax_fcf_usd_m + c["tax_share"] * c["rev_share"] * r.payable_silver_koz * 1e3
                * (36 - (30 if r.year <= 8 else 24)) / 1e6) / 1.09 ** (r.year - 0.5) for _, r in F.iterrows())
    assert abs(got - want) < 1e-9
    rel = S.npv(F, 0.09, {}, c["study_prices"], c["tax_share"], c["rev_share"], rel=0.9)   # "all -10%" rows
    want = sum((r.post_tax_fcf_usd_m - 0.1 * c["tax_share"] * c["rev_share"] * r.payable_silver_koz * 1e3
                * (30 if r.year <= 8 else 24) / 1e6) / 1.09 ** (r.year - 0.5) for _, r in F.iterrows())
    assert abs(rel - want) < 1e-9


def expansion_pair(**k):
    """A base-case study (2025-2041) and an expansion study of the same operation (2026-2042), as Alamos's Island
    Gold District 2025 Base Case and 2026 Expansion Study."""
    b, Fb = silver_sand(project="District", study_date="2025-08-06", study_npv_usd_m="", sensitivity="",
                        committed="yes", first_year="2025", superseded="by the 2026 Expansion Study (its baseline)")
    e, Fe = silver_sand(project="District", study_date="2026-03-20", study_npv_usd_m="", sensitivity="",
                        committed="yes", first_year="2026", baseline="2025-08-06", **k)
    for F, d in ((Fb, "2025-08-06"), (Fe, "2026-03-20")):
        F["project"], F["study_date"] = "District", d
    Fe["post_tax_fcf_usd_m"] = Fe.post_tax_fcf_usd_m * 1.5 + 20
    Fe["payable_silver_koz"] = Fe.payable_silver_koz * 1.4
    return b, Fb, e, Fe


def test_an_expansion_is_valued_as_its_increment_over_the_base_case(monkeypatch):
    """The expansion study covers the whole operation, already in trailing cash flow: only expansion - base case
    counts, by calendar year (`first_year`), from today (the current year in proportion to what's left of it),
    discounted from today in the study's convention, x the construction probability x share."""
    monkeypatch.setattr(S, "cfg", lambda: {"stage_probability": {"construction": 0.9}, "years_to_start": {}})
    b, Fb, e, Fe = expansion_pair(attributable_pct="80")
    today, rate, px = date(2026, 7, 2), 0.09, {"silver": 30}
    x = S.risk_adjusted(e, Fe, px, rate, today, base=(b, Fb))
    cb, ce = S.rebuild(b, Fb), S.rebuild(e, Fe)

    def cal(F, chk, first):
        out = {}
        for _, r in F.iterrows():
            out[first + int(r.year) - 1] = (r.post_tax_fcf_usd_m + chk["tax_share"] * chk["rev_share"]
                                            * r.payable_silver_koz * 1e3 * (30 - 24) / 1e6)
        return out
    E, B = cal(Fe, ce, 2026), cal(Fb, cb, 2025)
    now = 2026 + (today - date(2026, 1, 1)).days / 365
    inc = 0.0
    for y in sorted(set(E) | set(B)):
        if y < 2026:
            continue                                                    # 2025 is past
        w = (date(2027, 1, 1) - today).days / 365 if y == 2026 else 1.0
        inc += (E.get(y, 0.0) - B.get(y, 0.0)) * w / (1 + rate) ** max(y + 0.5 - now, 0.0)
    assert abs(x["npv"] - inc) < 0.01 and x["stage"] == "construction"
    assert abs(x["risk_adjusted"] - inc * 0.9 * 0.8) < 0.01 and x["why"] == ""
    assert S.risk_adjusted(b, Fb, px, rate, today)["why"].startswith("superseded")    # not valued on its own


def test_an_expansion_needs_its_base_case_and_calendar_years(monkeypatch):
    monkeypatch.setattr(S, "cfg", lambda: {"stage_probability": {"construction": 0.9}, "years_to_start": {}})
    b, Fb, e, Fe = expansion_pair()
    x = S.risk_adjusted(e, Fe, {"silver": 30}, 0.09, date(2026, 7, 2))
    assert x["risk_adjusted"] is None and "base-case study" in x["why"]
    b2 = b.copy()
    b2["first_year"] = ""
    y = S.risk_adjusted(e, Fe, {"silver": 30}, 0.09, date(2026, 7, 2), base=(b2, Fb))
    assert y["risk_adjusted"] is None and "first_year" in y["why"]
    b3 = b.copy()
    b3["study_npv_usd_m"] = "9999"                                      # the base case doesn't rebuild
    z = S.risk_adjusted(e, Fe, {"silver": 30}, 0.09, date(2026, 7, 2), base=(b3, Fb))
    assert z["risk_adjusted"] is None and z["why"].startswith("base case:")


def test_baseline_lookup_finds_the_base_case_row():
    b, Fb, e, Fe = expansion_pair()
    P = pd.DataFrame([b, e])
    C = pd.concat([Fb, Fe], ignore_index=True)
    found = S.baseline(P, C, e)
    assert found is not None and found[0].study_date == "2025-08-06" and len(found[1]) == len(Fb)
    assert S.baseline(P, C, b) is None
