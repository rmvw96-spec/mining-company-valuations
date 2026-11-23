"""Model portfolio from a screen: buckets, markets, filters, score, selection, weights, the write and the backtest file.
Offline; names and weights in these fixtures are made up."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from minerval import screen as SC
from minerval.config import settings
from minerval.sheets import CLEAR, MemorySheet

TODAY = date(2026, 11, 20)


def company(**k):
    base = {"holding": "Alpha Gold", "ticker": "ALP", "ticker_buy": "ALP", "yahoo": "ALP", "peer_group":
            "Senior producer", "share_gold": 1.0, "share_silver": 0.0, "share_copper": 0.0, "resource_unit": "",
            "mcap": 5000.0, "addon": 0.005, "independent_pnav": "", "royalty_band": "", "months_of_cash": "",
            "developer_check": "", "pnav_after_raw": "", "peer_ev_ratio": "", "pnav_addon_up": 1.1, "pocf_pctile": "",
            "pnav_pctile": "", "pnav_today": 1.0, "pnav_peer": 0.8, "pnav_low": 1.5, "net_cash_pct": 5.0,
            "share_change_3y": 2.0, "breakeven": 2000.0, "breakeven_metal": "gold $/oz",
            "financials_through": "2026-09-30", "price_date": "2026-11-20", "us_listing": "NYSE: ALP",
            "canada_listing": "", "us_otc_symbol": "", "bucket": "", "sheet_row": 12}
    base.update(k)
    return base


def universe(*rows):
    return SC.add_measures(pd.DataFrame(list(rows)), {"gold": 4000.0, "silver": 50.0, "copper": 5.0})


@pytest.mark.parametrize("peer,shares,unit,want", [
    ("Royalty/streaming", (1, 0, 0), "", "Royalty"),
    ("Developer", (0, 0, 0), "lb Cu", "Growth: developers"),
    ("Junior producer", (1, 0, 0), "", "Growth: expanding producers"),
    ("Junior producer", (0, 0, 1), "", "Copper producers"),
    ("Intermediate producer", (0.3, 0.6, 0.1), "", "Silver and polymetallic producers"),
    ("Senior producer", (0.2, 0, 0.8), "", "Copper producers"),
    ("Holding company", (0, 0, 0), "", ""),
])
def test_bucket_mapping(peer, shares, unit, want):
    r = company(peer_group=peer, share_gold=shares[0], share_silver=shares[1], share_copper=shares[2],
                resource_unit=unit)
    assert SC.bucket_of(r) == want


def test_bucket_override_wins():
    assert SC.bucket_of(company(bucket="Growth: expanding producers")) == "Growth: expanding producers"


def test_developer_metal_from_the_resource_unit():
    assert SC.main_metal(company(peer_group="Developer", resource_unit="oz AgEq")) == "silver"
    assert SC.main_metal(company(peer_group="Developer", resource_unit="oz AuEq")) == "gold"


def test_markets_and_where():
    c = settings()["portfolio_screen"]
    assert SC.market(company(), c) == (True, "")
    assert SC.market(company(us_listing="", canada_listing="TSX: ALP", us_otc_symbol="ALPXF"), c) == (True, "")
    ok, note = SC.market(company(us_listing="", canada_listing="TSX: ALP"), c)
    assert ok is c["markets"]["canada_rep_assisted"] and "rep-assisted" in note
    no = {**c, "markets": {**c["markets"], "canada_rep_assisted": False}}
    assert SC.market(company(us_listing="", canada_listing="TSX: ALP"), no)[0] is False
    assert SC.market(company(us_listing=""), c) == (False, c["markets"]["foreign_fee_note"])
    assert SC.where(company(us_listing="", canada_listing="TSX: ALP", us_otc_symbol="ALPXF")) == \
        "TSX: ALP; US OTC: ALPXF"
    assert SC.where(company(us_listing="", yahoo="ALP.AX", us_otc_symbol="ALPAF")) == \
        "ASX only (US OTC: ALPAF): about $50 a trade in an IRA"


def fail(**k):
    U = universe(company(**k))
    return SC.failure(U.iloc[0], TODAY, SC.review_level(U.bucket.iloc[0]), all_markets=k.pop("_all", False))


def test_a_good_company_passes():
    assert fail() == ""


@pytest.mark.parametrize("k,starts", [
    ({"us_listing": ""}, "market"),
    ({"financials_through": "2025-12-31"}, "financials stale"),
    ({"price_date": "2026-11-10"}, "price stale"),
    ({"mcap": 299.0}, "market cap under $300M"),
    ({"share_change_3y": 30.5}, "dilution"),
    ({"pnav_peer": 1.3}, "valuation 1.30× peer norm"),
])
def test_each_filter(k, starts):
    assert fail(**k).startswith(starts)


def test_no_jurisdiction_filter_unless_configured():
    assert fail(addon=0.08) == ""                                         # 8 points: still eligible, scored lower
    c = SC.cfg()
    c = {**c, "filters": {**c["filters"], "max_addon_points": 2.5}}
    assert SC.failure(universe(company(addon=0.026)).iloc[0], TODAY, 1.3, c=c).startswith("jurisdiction add-on")


def test_filter_edges_pass():
    assert fail(share_change_3y=30.0) == "" and fail(addon=0.025) == "" and fail(mcap=300.0) == ""
    assert fail(pnav_peer=1.29) == "" and fail(financials_through="2026-02-18") == ""


def test_expanding_producers_have_their_own_dilution_limit():
    assert fail(peer_group="Junior producer", share_change_3y=90.0) == ""
    assert fail(peer_group="Junior producer", share_change_3y=101.0).startswith("dilution")


def chart(closes, volumes):
    return {"chart": {"result": [{"indicators": {"quote": [{"close": closes, "volume": volumes}]}}]}}


def test_dollar_volume_counts_missing_days_as_zero():
    assert SC.dollar_volume(chart([10.0] * 63, [1000] * 63)) == 10000.0
    assert SC.dollar_volume(chart([10.0] * 40, [1000] * 40)) == 10000.0      # 40 of 63: median still trades
    assert SC.dollar_volume(chart([10.0] * 20, [1000] * 20)) == 0.0          # most days without a trade
    assert SC.dollar_volume(chart([10.0, None], [5, None])) == 0.0
    assert np.isnan(SC.dollar_volume(None))


def test_thin_otc_adrs_are_left_out_unless_all_markets():
    U = universe(company(ticker="THIN", us_listing="OTC ADR: THNY"),
                 company(ticker="DEEP", us_listing="OTC ADR: DPPY"),
                 company(ticker="GONE", us_listing="OTC ADR: GNNY"),
                 company(ticker="TSX", us_listing="OTC ADR: TSXY", canada_listing="TSX: T"))
    fetched = []

    def fetch(s):
        fetched.append(s)
        return {"THNY": chart([5.0] * 63, [100] * 63), "DPPY": chart([5.0] * 63, [100000] * 63)}.get(s)

    vols = SC.otc_volumes(U, fetch)
    assert sorted(fetched) == ["DPPY", "GNNY", "THNY"]                       # a Canadian listing needs no check
    U2, warn = SC.apply_liquidity(U, vols)
    fail = {r.ticker: SC.failure(r, TODAY, 1.3) for _, r in U2.iterrows()}
    assert fail["THIN"].startswith("market (OTC ADR THNY thinly traded: median $500 a day")
    assert fail["DEEP"] == "" and fail["TSX"] == ""
    assert fail["GONE"] == "market (OTC ADR GNNY: trading volume not available)"
    assert len(warn) == 1 and "GNNY" in warn[0]
    assert SC.failure(U2.iloc[0], TODAY, 1.3, all_markets=True) == ""


def test_all_markets_lets_foreign_names_in():
    U = universe(company(us_listing=""))
    assert SC.failure(U.iloc[0], TODAY, 1.3, all_markets=True) == ""


def test_developer_filters():
    dev = {"peer_group": "Developer", "resource_unit": "oz Au", "mcap": 150.0, "pnav_after_raw": 0.5,
           "peer_ev_ratio": 1.0, "pnav_peer": 0.5}
    assert fail(**dev) == ""
    assert fail(**{**dev, "developer_check": "Short of cash: financing likely"}) == "developer short of cash"
    assert fail(**{**dev, "pnav_after_raw": ""}).startswith("no P/NAV after a raise")
    assert fail(**{**dev, "pnav_after_raw": "Fully funded"}) == ""
    assert fail(**{**dev, "peer_ev_ratio": 1.51}).startswith("EV per unit")
    assert fail(**{**dev, "mcap": 99.0}).startswith("market cap under $100M")


def test_royalty_filters_use_the_framework_band_and_own_history():
    roy = {"peer_group": "Royalty/streaming", "royalty_band": "Normal range", "pocf_pctile": 40.0, "pnav_peer": 1.8}
    assert fail(**roy) == ""                                       # peer norm doesn't apply to royalties
    assert fail(**{**roy, "royalty_band": "Rich"}) == "framework band: Rich"
    assert fail(**{**roy, "pocf_pctile": 75.0}).startswith("expensive for itself")
    assert fail(**{**roy, "pocf_pctile": 90.0, "pnav_pctile": 30.0}) == ""     # P/NAV percentile wins once recorded


def test_rank_pct():
    p = SC.rank_pct(pd.Series([3.0, 1.0, np.nan, 1.0]), higher_better=False)
    assert list(p[[0, 1, 3]]) == [0.0, 0.75, 0.75] and np.isnan(p[2])
    assert list(SC.rank_pct(pd.Series([7.0]), True)) == [1.0]
    assert SC.rank_pct(pd.Series([np.nan]), True).isna().all()


def test_score_averages_the_measures_each_company_has():
    U = universe(company(holding="A", pnav_peer=0.5, pnav_low=1.0), company(holding="B", pnav_peer=0.9, pnav_low=""),
                 company(holding="C", pnav_peer=0.7, pnav_low=2.0))
    S = SC.score(U, "producer")
    assert list(S.holding)[0] == "A"
    assert S.set_index("holding").loc["B", "measures_used"] == 6     # no Low-price P/NAV


def test_royalty_measure_is_the_pnav_used():
    """own-nav-first A5: royalties are scored on the P/NAV used (PNAV inputs CV: our NAV where valued), lower better."""
    assert ("pnav_used", False) in SC.MEASURES["royalty"]
    assert all(m != "independent_pnav" for m, _ in SC.MEASURES["royalty"])
    assert settings()["portfolio_screen"]["score"]["pnav_used"] == 1.0
    U = universe(company(holding="A", peer_group="Royalty/streaming", pnav_used=1.9, pnav_peer=1.0),
                 company(holding="B", peer_group="Royalty/streaming", pnav_used="1.4", pnav_peer=1.0))
    assert list(SC.score(U, "royalty").holding)[0] == "B"
    assert "no NAV" in settings()["portfolio_screen"]["filters"]["royalty_excluded_bands"]


def test_select_with_the_turnover_buffer():
    ranked = list("abcdefgh")
    assert SC.select(ranked, {"e"}, 3, 2) == ["a", "b", "e"]          # rank 5 = n + 2 stays
    assert SC.select(ranked, {"f"}, 3, 2) == ["a", "b", "c"]          # rank 6 is replaced
    assert SC.select(ranked, {"a", "b", "c", "d"}, 3, 2) == ["a", "b", "c"]
    assert SC.select(["a"], set(), 3, 2) == ["a"]


def test_weights_equal_cap_and_unallocated():
    w, un = SC.weights([0.9, 0.5, 0.1], 0.12, 0.06)
    assert w == pytest.approx([0.04] * 3) and un == pytest.approx(0)
    w, un = SC.weights([0.9, 0.5], 0.15, 0.06)
    assert w == pytest.approx([0.06, 0.06]) and un == pytest.approx(0.03)
    w, un = SC.weights([1.0, 0.0], 0.10, 0.06, tilt=0.5)
    assert w == pytest.approx([0.06, 0.04]) and sum(w) == pytest.approx(0.10)   # tilt 0.075/0.025, then the cap
    assert SC.weights([], 0.1, 0.06) == ([], 0.1)


def tab_rows(*rows):
    out = []
    for i in range(26):
        r = rows[i] if i < len(rows) else {}
        out.append({"row": 6 + i, **{k: "" for k in "ABCDEFGHIJKLMNOPQRSTUV"}, **r})
    return out


SIZES = {"Gold producers": {"weight": 0.06, "names": 2}, "Growth: developers": {"weight": 0.015, "names": 1}}


def gold_universe():
    return universe(company(holding="Alpha Gold", ticker="ALP", pnav_peer=0.5),
                    company(holding="Beta Gold", ticker="BET CN", ticker_buy="BET", pnav_peer=0.6),
                    company(holding="Gamma Gold", ticker="GAM", pnav_peer=0.9),
                    company(holding="Delta Dev", ticker="DEL", peer_group="Developer", resource_unit="oz Au",
                            mcap=200.0, pnav_after_raw="Fully funded", peer_ev_ratio=0.8, pnav_peer=0.4))


def test_plan_keeps_physical_scales_weights_and_keeps_typed_levels():
    tab = tab_rows({"A": "Physical metal", "B": "Gold trust", "D": "PHYS", "F": 0.88, "S": ""},
                   {"A": "Gold producers", "B": "beta gold", "D": "BET", "F": 0.1, "S": 1.6, "U": "my reason",
                    "V": "my view"},
                   {"A": "Gold producers", "B": "Old Gold", "D": "OLD", "F": 0.1, "S": 1.3})
    P = SC.plan(gold_universe(), tab, SIZES, TODAY, state=None)
    rows = {r["B"]: r for r in P["rows"]}
    assert set(rows) == {"Alpha Gold", "Beta Gold", "Delta Dev"}
    assert sum(r["F"] for r in P["rows"]) == pytest.approx(0.12)      # 12% left after physical: 7.5% scaled ×1.6
    assert any("scaled ×1.600" in n for n in P["notes"])
    beta = rows["Beta Gold"]
    assert beta["D"] == "BET" and beta["S"] == 1.6 and beta["typed_level"] and not beta["new"]
    assert beta["U"] == "my reason" and beta["V"] == "my view"
    alpha = rows["Alpha Gold"]
    assert alpha["S"] == 1.3 and alpha["new"] and alpha["U"].startswith("Screen: rank 1 of 3")
    assert rows["Delta Dev"]["S"] == 1.5                               # the developers' level
    assert [d[1] for d in P["drops"]] == ["Old Gold"]
    assert P["physical"][0]["B"] == "Gold trust"


def test_a_level_written_by_the_screen_follows_the_rule_and_rule_levels_resets_typed_ones():
    tab = tab_rows({"A": "Gold producers", "B": "Beta Gold", "D": "BET", "F": 0.1, "S": 1.25})
    P = SC.plan(gold_universe(), tab, SIZES, TODAY, state={"review": {"BET": 1.25}})
    assert next(r for r in P["rows"] if r["B"] == "Beta Gold")["S"] == 1.3          # recorded: the screen's own
    P = SC.plan(gold_universe(), tab, SIZES, TODAY, state={"review": {"BET": 1.2}})
    assert next(r for r in P["rows"] if r["B"] == "Beta Gold")["S"] == 1.25         # changed since: typed
    P = SC.plan(gold_universe(), tab, SIZES, TODAY, state=None, rule_levels=True)
    assert next(r for r in P["rows"] if r["B"] == "Beta Gold")["S"] == 1.3


def test_plan_warnings():
    many = universe(*[company(holding=f"Dev {i}", ticker=f"D{i}", peer_group="Developer", resource_unit="oz Au",
                              mcap=200.0, pnav_after_raw=0.5, peer_ev_ratio=1.0, pnav_peer=0.4) for i in range(30)])
    P = SC.plan(many, tab_rows(), {"Growth: developers": {"weight": 0.9, "names": 27}}, TODAY, state=None)
    text = " ".join(P["warnings"])
    assert "27 rows for 26" in text and "Speculation" in text and "Developers: 27 names" in text
    assert "unallocated" in text                                       # 27 × 3% cap = 81% < 90%
    P = SC.plan(gold_universe(), tab_rows(), {"Growth: developers": {"weight": 0.02, "names": 3}}, TODAY, None)
    assert any("1 eligible names for 3" in w for w in P["warnings"])
    assert any("Developers: 1 names" in w for w in P["warnings"])


def test_write_rows_touches_only_the_inputs_and_clears_the_rest():
    P = SC.plan(gold_universe(), tab_rows({"A": "Physical metal", "B": "Gold trust", "D": "PHYS", "F": 0.5,
                                           "S": "", "U": "core", "V": ""}), SIZES, TODAY, state=None)
    blocks = SC.write_rows(MemorySheet(), P)
    assert [b[1] for b in blocks] == ["A6", "S6", "U6"]
    af, s, uv = (b[2] for b in blocks)
    assert len(af) == len(s) == len(uv) == 26 and all(len(r) == 6 for r in af)
    assert af[0][:2] == ["Physical metal", "Gold trust"] and s[0] == [CLEAR] and uv[0] == ["core", CLEAR]
    assert af[4] == [CLEAR] * 6 and s[4] == [CLEAR]                   # 1 physical + 3 screened, then cleared
    P["rows"] = P["rows"] * 9
    with pytest.raises(ValueError, match="rows can't be added"):
        SC.write_rows(MemorySheet(), P)


def test_write_stops_when_a_name_or_ticker_wouldnt_look_up(tmp_path, monkeypatch):
    S = settings()["sheet"]
    L = S["downside_cols"]["ticker"]
    sheet = MemorySheet({S["pnav_tab"]: {f"B{S['pnav_tab_first_row']}": "Alpha Gold"},
                         S["downside_tab"]: {f"{L}{S['downside_first_row']}": "ALP"},
                         S["portfolio_tab"]: {}})
    monkeypatch.setattr(SC, "load_sizes", lambda path=None: SIZES)
    monkeypatch.setattr(SC, "read_universe", lambda sh, research=None: (gold_universe(), {}))
    monkeypatch.setattr(SC, "otc_volumes", lambda U, fetch=None: {})
    monkeypatch.setattr(SC, "read_tab", lambda sh: tab_rows())
    monkeypatch.setattr(SC, "load_state", lambda path=None: None)
    monkeypatch.setattr(SC, "STATE", tmp_path / "screen_state.json")     # never the real private/ files,
    monkeypatch.setattr(SC, "PORTFOLIO_FILE", tmp_path / "portfolio.csv")  # even if the guard breaks
    P = SC.plan(gold_universe(), tab_rows(), SIZES, TODAY, None)
    bad = SC.check_lookups(sheet, P)
    assert "Beta Gold not on the P/NAV tab" in bad and "BET not on Holdings downside" in bad
    assert not any(x.startswith("Alpha Gold") or x.startswith("ALP ") for x in bad)
    lines = SC.run(sheet, write=True, today=TODAY, out_dir=tmp_path)
    assert any(x.startswith("Not written:") for x in lines)
    assert sheet.cells[S["portfolio_tab"]] == {}                        # nothing written to the tab
    assert not list(tmp_path.glob("backup-*.json"))


def test_portfolio_rows():
    tab = tab_rows({"A": "Physical metal", "B": "Silver trust", "D": "PSLV", "E": "Silver", "F": 0.2},
                   {"A": "Gold producers", "B": "Alpha Gold", "D": "ALP", "E": "Gold", "F": 0.3},
                   {"A": "Growth: developers", "B": "Delta Dev", "D": "DEL CN", "E": "Gold", "F": 0.5})
    hold = {"ALP": ("ALP", "USD"), "DEL CN": ("DEL.TO", "CAD")}
    rows = SC.portfolio_rows(tab, 10000.0, 500.0, hold, {"ALP": "2019-11"})
    by = {r["key"]: r for r in rows}
    assert by["PSLV"]["amount_usd"] == 500.0 and by["PSLV"]["already_held"] == "yes" and by["PSLV"]["yahoo"] == "PSLV"
    assert by["PSLV-NEW"]["amount_usd"] == 1500.0 and by["PSLV-NEW"]["already_held"] == "no"
    assert by["ALP"]["amount_usd"] == 3000.0 and by["ALP"]["first_month"] == "2019-11"
    assert by["DEL CN"]["toronto_listing_in_cad"] == "yes" and by["ALP"]["toronto_listing_in_cad"] == "no"
    assert by["ALP"]["metal"] == "gold" and set(by["ALP"]) == set(SC.PORTFOLIO_COLS)


def test_portfolio_file_columns_match_what_the_backtest_reads():
    from minerval.config import CONFIG
    assert list(pd.read_csv(CONFIG / "portfolio.example.csv").columns) == SC.PORTFOLIO_COLS


def test_init_sizes_from_the_tab(tmp_path, monkeypatch):
    S = settings()["sheet"]
    sh = MemorySheet({S["portfolio_tab"]: {"A6": "Physical metal", "F6": 0.3, "A7": "Gold producers", "F7": 0.2,
                                          "A8": "Gold producers", "F8": 0.1, "A9": "Copper producers", "F9": 0.4}})
    p = tmp_path / "screen.toml"
    SC.init_sizes(sh, p)
    got = SC.load_sizes(p)
    assert got["Gold producers"] == {"weight": 0.3, "names": 2} and got["Royalty"] == {"weight": 0, "names": 0}
    assert "Physical metal" not in got
    assert "not overwritten" in SC.init_sizes(sh, p)[0]


def test_ranking_table_shows_each_measures_rank():
    U = universe(company(holding="A", ticker="A", pnav_peer=0.5), company(holding="B", ticker="B", pnav_peer=0.9),
                 company(holding="C", ticker="C", pnav_peer=2.0))
    U["bucket"] = "Gold producers"
    P = SC.plan(U, [], {"Gold producers": {"weight": 1.0, "names": 1}}, TODAY, None)
    T = SC.ranking_table(P).set_index("holding")
    assert T.loc["A", "picked"] and T.loc["A", "rank"] == 1 and T.loc["A", "p_peer_norm"] == 1.0
    assert T.loc["B", "p_peer_norm"] == 0.0 and not T.loc["B", "picked"]
    assert T.loc["C", "excluded"].startswith("valuation") and np.isnan(T.loc["C", "score"])


def test_report_names_candidates_without_an_npv_at_every_deck():
    """tier-valuation A25: the screen's report says how many eligible candidates have an NPV at all three decks
    with a basis, and names the rest (the report stays private)."""
    ranked = {"Gold producers": pd.DataFrame({"holding": ["Alpha Gold", "Beta Gold", "Gamma Gold", "Delta Gold"],
                                              "ticker": ["ALP", "BET", "GAM", "DEL"], "sheet_row": [12, 13, 14, 15],
                                              "fail": ["", "", "", "too small"], "score": [0.9, 0.8, 0.7, np.nan],
                                              "measures_used": [5, 5, 5, 0]})}
    V = pd.DataFrame({"sheet_row": [12, 13], "valuation_basis": ["OCF − sustaining", "OCF − sustaining"],
                      "npv Pessimistic": [100.0, -20.0], "npv Base": [200.0, 10.0], "npv Optimistic": [300.0, np.nan],
                      "why": ["", "negative NPV at the base deck"]})
    gaps = SC.valuation_gaps(ranked, V)
    assert gaps == [("Gold producers", "Beta Gold", "no NPV at Optimistic"),
                    ("Gold producers", "Gamma Gold", "not valued")]                  # Delta failed a filter
    P = {"notes": [], "warnings": [], "physical": [], "rows": [], "drops": [], "ranked": ranked}
    text = "\n".join(SC.report(P, False, V))
    assert "Valuation: 1 of 3 candidates have an NPV at all three decks" in text
    assert "Beta Gold: no NPV at Optimistic" in text and "Gamma Gold: not valued" in text
