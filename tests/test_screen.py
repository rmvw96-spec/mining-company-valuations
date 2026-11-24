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
            "canada_listing": "", "us_otc_symbol": "", "bucket": "", "sheet_row": 12,
            "price": 50.0, "npv_pess": 4000.0, "npv_base": 6000.0, "net_cash": 500.0, "minority": 0.0,
            "dilution_30": "", "buy_below_value": 41.0, "fair_value_price": 65.0, "valuation_why": "",
            "valuation_basis": "OCF − sustaining"}
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
    return SC.failure(U.iloc[0], TODAY, all_markets=k.pop("_all", False))


def test_a_good_company_passes():
    assert fail() == ""


@pytest.mark.parametrize("k,starts", [
    ({"us_listing": ""}, "market"),
    ({"financials_through": "2025-12-31"}, "financials stale"),
    ({"price_date": "2026-11-10"}, "price stale"),
    ({"mcap": 299.0}, "market cap under $300M"),
    ({"share_change_3y": 30.5}, "dilution"),
])
def test_each_filter(k, starts):
    assert fail(**k).startswith(starts)


def test_no_jurisdiction_filter_unless_configured():
    assert fail(addon=0.08) == ""                                         # 8 points: still eligible, scored lower
    c = SC.cfg()
    c = {**c, "filters": {**c["filters"], "max_addon_points": 2.5}}
    assert SC.failure(universe(company(addon=0.026)).iloc[0], TODAY, c=c).startswith("jurisdiction add-on")


def test_filter_edges_pass():
    assert fail(share_change_3y=30.0) == "" and fail(addon=0.025) == "" and fail(mcap=300.0) == ""
    assert fail(financials_through="2026-02-18") == ""


def test_expanding_producers_have_their_own_dilution_limit():
    assert fail(peer_group="Junior producer", share_change_3y=90.0) == ""
    assert fail(peer_group="Junior producer", share_change_3y=101.0).startswith("dilution")


def test_too_little_history():
    """A21: fewer than min_history_years of the performance measures isn't ranked."""
    n = settings()["portfolio_screen"]["filters"]["min_history_years"]
    assert n == 3
    assert fail(history_years=2) == "too little history (2 of 3 years)"
    assert fail(history_years=3) == "" and fail() == ""             # not computed (no column): not a failure


def test_performance_measures_by_bucket():
    """A21: the score's measures are business performance per share, never price."""
    assert [m for m, _ in SC.MEASURES["producer"]] == ["cf_ps_growth", "margin_avg", "margin_min", "share_change_3y",
                                                       "net_cash_pct", "aisc_margin"]
    assert [m for m, _ in SC.MEASURES["royalty"]] == ["ocf_ps_growth", "margin_avg", "margin_min", "share_change_3y"]
    assert dict(SC.MEASURES["producer"])["share_change_3y"] is False
    assert all(hb for m, hb in SC.MEASURES["producer"] if m != "share_change_3y")


def test_aisc_margin_is_the_base_decks_margin_over_the_breakeven():
    """A21: AISC margin at the base deck (the FCF breakeven until roadmap 4a)."""
    base = settings()["scenarios"][settings()["valuation"]["base_deck"]]
    r = universe(company(breakeven=base["gold"] / 2, breakeven_metal="gold $/oz")).iloc[0]
    assert r.aisc_margin == pytest.approx(0.5)
    c = universe(company(breakeven=base["copper"] * 0.75, breakeven_metal="copper $/lb")).iloc[0]
    assert c.aisc_margin == pytest.approx(0.25)
    assert np.isnan(universe(company(breakeven="")).iloc[0].aisc_margin)


def test_the_why_text_labels_the_fcf_basis():
    r = universe(company(cf_ps_growth=0.12, margin_avg=0.3, margin_min=0.1, cf_basis="FCF")).iloc[0]
    text = SC.why_text(r, "producer", 1, 5)
    assert text.startswith("Screen: rank 1 of 5") and "cash flow per share growth +12% a year (FCF basis)" in text
    r = universe(company(cf_ps_growth=0.12, cf_basis="OCF − sustaining")).iloc[0]
    assert "(FCF basis)" not in SC.why_text(r, "producer", 1, 5)


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
    fail = {r.ticker: SC.failure(r, TODAY) for _, r in U2.iterrows()}
    assert fail["THIN"].startswith("market (OTC ADR THNY thinly traded: median $500 a day")
    assert fail["DEEP"] == "" and fail["TSX"] == ""
    assert fail["GONE"] == "market (OTC ADR GNNY: trading volume not available)"
    assert len(warn) == 1 and "GNNY" in warn[0]
    assert SC.failure(U2.iloc[0], TODAY, all_markets=True) == ""


def test_all_markets_lets_foreign_names_in():
    U = universe(company(us_listing=""))
    assert SC.failure(U.iloc[0], TODAY, all_markets=True) == ""


def test_developer_filters():
    dev = {"peer_group": "Developer", "resource_unit": "oz Au", "mcap": 150.0}
    assert fail(**dev) == ""
    assert fail(**{**dev, "developer_check": "Short of cash: financing likely"}) == "developer short of cash"
    assert fail(**{**dev, "mcap": 99.0}).startswith("market cap under $100M")


def test_no_filter_on_price_or_valuation():
    """Revision 2 (A23): value drives only the buy signal, never eligibility."""
    assert fail(pnav_peer=5.0, pnav_today=4.0, pnav_low=9.0, price=500.0) == ""
    assert fail(peer_group="Developer", resource_unit="oz Au", mcap=150.0, pnav_after_raw="",
                peer_ev_ratio=3.0) == ""
    assert fail(peer_group="Royalty/streaming", royalty_band="Rich", pocf_pctile=95.0) == ""


def test_valuation_filters_and_measures_are_gone():
    """A23: the valuation filters and score measures are gone from code and settings."""
    gone = {"peer_norm", "pnav_low", "breakeven_gap", "addon", "addon_reliance", "pnav_after", "peer_ev_ratio",
            "months_of_cash", "pnav_used", "own_pctile"}
    C = settings()["portfolio_screen"]
    assert not gone & {m for ms in SC.MEASURES.values() for m, _ in ms}
    assert not gone & set(C["score"])
    assert "review" not in C
    assert not {"max_peer_ev_ratio", "royalty_excluded_bands"} & set(C["filters"])
    assert not hasattr(SC, "review_level")


def test_rank_pct():
    p = SC.rank_pct(pd.Series([3.0, 1.0, np.nan, 1.0]), higher_better=False)
    assert list(p[[0, 1, 3]]) == [0.0, 0.75, 0.75] and np.isnan(p[2])
    assert list(SC.rank_pct(pd.Series([7.0]), True)) == [1.0]
    assert SC.rank_pct(pd.Series([np.nan]), True).isna().all()


def test_score_averages_the_measures_each_company_has():
    U = universe(company(holding="A", net_cash_pct=20.0, share_change_3y=0.0),
                 company(holding="B", net_cash_pct="", share_change_3y=5.0),
                 company(holding="C", net_cash_pct=10.0, share_change_3y=10.0))
    S = SC.score(U, "producer")
    assert list(S.holding)[0] == "A"
    full = S.set_index("holding").measures_used
    assert full["B"] == full["A"] - 1                                 # no net cash figure


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
        out.append({"row": 6 + i, **{k: "" for k in [*"ABCDEFGHIJKLMNOPQRSTUVWXYZ", "AA"]}, **r})
    return out


SIZES = {"Gold producers": {"weight": 0.06, "names": 2}, "Growth: developers": {"weight": 0.015, "names": 1}}


def gold_universe():
    return universe(company(holding="Alpha Gold", ticker="ALP", pnav_peer=0.5),
                    company(holding="Beta Gold", ticker="BET CN", ticker_buy="BET", pnav_peer=0.6),
                    company(holding="Gamma Gold", ticker="GAM", pnav_peer=0.9),
                    company(holding="Delta Dev", ticker="DEL", peer_group="Developer", resource_unit="oz Au",
                            mcap=200.0, pnav_after_raw="Fully funded", peer_ev_ratio=0.8, pnav_peer=0.4))


def test_selection_ignores_price():
    """A22: the best business is picked even when it's expensive; it just has no buy status."""
    U = universe(company(holding="Pricey Gold", ticker="PRC", net_cash_pct=30.0, share_change_3y=0.0,
                         pnav_peer=3.0, pnav_today=4.0, price=120.0),
                 company(holding="Cheap Gold", ticker="CHP", net_cash_pct=-20.0, share_change_3y=25.0,
                         pnav_peer=0.3, pnav_today=0.4, price=20.0))
    P = SC.plan(U, [], {"Gold producers": {"weight": 0.1, "names": 1}}, TODAY, None)
    assert [r["B"] for r in P["rows"]] == ["Pricey Gold"]
    assert P["rows"][0]["status"] == "Above fair value: review"


@pytest.mark.parametrize("k,want", [
    ({"npv_base": "", "buy_below_value": "", "fair_value_price": "", "valuation_why": "no cash-flow table recorded"},
     "No NPV: no cash-flow table recorded"),
    ({"npv_base": -100.0, "buy_below_value": "", "fair_value_price": "",
      "valuation_why": "negative NPV at the base deck"}, "No NPV: negative NPV at the base deck"),
    ({"buy_below_value": "", "valuation_why": "fails the downside test at any price"}, "Fails downside test"),
    ({"peer_group": "Developer", "valuation_basis": "study (risk-adjusted)", "buy_below_value": "",
      "valuation_why": "negative value per share after a +30% overrun"}, "Fails downside test"),
    ({"price": 41.0}, "Buy: below US$41.00"),
    ({"price": 41.01}, "Hold"),
    ({"price": 64.99}, "Hold"),
    ({"price": 65.0}, "Above fair value: review"),
])
def test_status_at_each_edge(k, want):
    """A24: T's statuses in order: no NPV, downside test, buy (at or below), above fair value (at or above), hold."""
    r = universe(company(**k)).iloc[0]
    assert SC.status(r, SC.buy_multiple(r)) == want


def test_buy_below_at_each_binding_condition():
    """A24: at the rule's level the valuation's own price (PNAV inputs CQ); a typed level is re-priced the same way:
    producers and royalties (min(level × base NPV, pessimistic NPV) + net cash − minority) ÷ shares, developers
    the +30% overrun case with the level's change spread over the shares after the raise."""
    r = universe(company(price=50.0, mcap=5000.0, npv_base=6000.0, npv_pess=4000.0, net_cash=500.0, minority=100.0,
                         buy_below_value=40.0)).iloc[0]
    assert SC.buy_multiple(r) == 0.6
    assert SC.buy_below_at(r, 0.6) == pytest.approx(40.0)
    assert SC.buy_below_at(r, 0.5) == pytest.approx((3000 + 500 - 100) / 100)          # the discount binds
    assert SC.buy_below_at(r, 0.8) == pytest.approx((4000 + 500 - 100) / 100)          # the downside test binds
    assert SC.status(r, 0.5) == "Hold"                                                  # 50 > 34
    roy = universe(company(peer_group="Royalty/streaming", valuation_basis="OCF (royalty)", npv_pess=9000.0,
                           buy_below_value=65.0)).iloc[0]
    assert SC.buy_multiple(roy) == 1.0 and SC.buy_below_at(roy, 1.0) == 65.0
    assert SC.buy_below_at(roy, 0.9) == pytest.approx((5400 + 500) / 100)
    dev = universe(company(peer_group="Developer", resource_unit="oz Au", valuation_basis="study (risk-adjusted)",
                           price=2.0, mcap=200.0, npv_base=300.0, npv_pess=100.0, net_cash=10.0, dilution_30=0.5,
                           buy_below_value=1.10)).iloc[0]
    assert SC.buy_multiple(dev) == 0.6 and SC.buy_below_at(dev, 0.6) == 1.10
    assert SC.buy_below_at(dev, 0.7) == pytest.approx(1.10 + 0.1 * 300.0 / (100 * 1.5))
    assert SC.buy_below_at(universe(company(npv_base="", buy_below_value="")).iloc[0], 0.5) is None
    assert SC.buy_below_at(universe(company(npv_pess=-600.0, buy_below_value="")).iloc[0], 0.5) is None


def test_a_typed_level_is_kept_and_sets_the_status():
    """A24: a level typed in S is kept by the plan and used for the row's buy-below price."""
    U = universe(company(holding="Beta Gold", ticker="BET", price=36.0, mcap=3600.0, buy_below_value=41.0))
    tab = tab_rows({"A": "Gold producers", "B": "Beta Gold", "D": "BET", "F": 0.1, "S": 0.5})
    row = SC.plan(U, tab, {"Gold producers": {"weight": 0.1, "names": 1}}, TODAY, None)["rows"][0]
    assert row["S"] == 0.5 and row["typed_level"]
    assert row["buy_below"] == pytest.approx(35.0) and row["status"] == "Hold"


def test_a_buy_status_gives_the_listing_currency_price_too():
    r = universe(company(price=41.0, currency_buy="CAD", fx_buy=0.7)).iloc[0]
    assert SC.status(r, 0.6) == "Buy: below US$41.00 (CAD 58.57)"
    assert SC.status(universe(company(price=41.0, currency_buy="USD", fx_buy=1.0)).iloc[0], 0.6) == \
        "Buy: below US$41.00"


def test_sheet_statuses_are_checked_against_python():
    """A24: the screen's report compares Model portfolio T and AA with the same rule computed in Python."""
    U = universe(company(holding="Alpha Gold", ticker="ALP", price=40.0, mcap=4000.0, buy_below_value=41.0))
    row = {"A": "Gold producers", "B": "Alpha Gold", "D": "ALP", "S": 0.6, "T": "Buy: below US$41.00", "AA": 41.0}
    phys = {"A": "Physical metal", "B": "Gold trust", "D": "PHYS", "S": ""}
    assert SC.sheet_check(U, tab_rows(phys, row)) == \
        ["Model portfolio T and AA agree with the screen's rule (1 rows)."]
    out = SC.sheet_check(U, tab_rows({**row, "T": "Hold", "AA": 41.004}))
    assert out[0].startswith("Model portfolio T or AA differ from the screen's rule in 1 rows")
    assert "Alpha Gold" in out[1] and "'Hold'" in out[1] and "Buy: below US$41.00" in out[1]


def test_sheet_check_names_rows_whose_name_wont_look_up():
    """The Sheet's T and AA look B up on PNAV inputs by name; a name that differs (found only by its ticker) is
    reported as a lookup to fix, not as a formula difference."""
    U = universe(company(holding="Alpha Gold", ticker="ALP", price=40.0, mcap=4000.0, buy_below_value=41.0))
    row = {"A": "Gold producers", "B": "Alpha Gold (formerly Alfa)", "D": "ALP", "S": 0.6,
           "T": "No NPV: not valued", "AA": ""}
    out = SC.sheet_check(U, tab_rows(row))
    assert out[0] == "Model portfolio T and AA agree with the screen's rule (0 rows)."
    assert out[1].startswith("Names in B that PNAV inputs doesn't have (T, AA and the other lookups stay blank")
    assert "Alpha Gold (formerly Alfa)" in out[2] and "Alpha Gold" in out[2]
    same = {**row, "B": "ALPHA GOLD", "T": "Buy: below US$41.00", "AA": 41.0}        # XLOOKUP ignores case
    assert SC.sheet_check(U, tab_rows(same)) == ["Model portfolio T and AA agree with the screen's rule (1 rows)."]


def test_plan_keeps_physical_scales_weights_and_keeps_typed_levels():
    tab = tab_rows({"A": "Physical metal", "B": "Gold trust", "D": "PHYS", "F": 0.88, "S": ""},
                   {"A": "Gold producers", "B": "beta gold", "D": "BET", "F": 0.1, "S": 0.5, "U": "my reason",
                    "V": "my view"},
                   {"A": "Gold producers", "B": "Old Gold", "D": "OLD", "F": 0.1, "S": 0.6})
    P = SC.plan(gold_universe(), tab, SIZES, TODAY, state=None)
    rows = {r["B"]: r for r in P["rows"]}
    assert set(rows) == {"Alpha Gold", "Beta Gold", "Delta Dev"}
    assert sum(r["F"] for r in P["rows"]) == pytest.approx(0.12)      # 12% left after physical: 7.5% scaled ×1.6
    assert any("scaled ×1.600" in n for n in P["notes"])
    beta = rows["Beta Gold"]
    assert beta["D"] == "BET" and beta["S"] == 0.5 and beta["typed_level"] and not beta["new"]
    assert beta["U"] == "my reason" and beta["V"] == "my view"
    alpha = rows["Alpha Gold"]
    assert alpha["S"] == 0.6 and alpha["new"] and alpha["U"].startswith("Screen: rank ")
    assert alpha["V"] == "Screen: review above fair value, or if it fails a filter"
    assert rows["Delta Dev"]["S"] == 0.6                               # the developers' buy multiple
    roy = SC.plan(universe(company(holding="Roy", peer_group="Royalty/streaming", valuation_basis="OCF (royalty)")), [],
                  {"Royalty": {"weight": 0.05, "names": 1}}, TODAY, None)["rows"][0]
    assert roy["S"] == 1.0
    assert [d[1] for d in P["drops"]] == ["Old Gold"]
    assert P["physical"][0]["B"] == "Gold trust"


def test_a_level_written_by_the_screen_follows_the_rule_and_rule_levels_resets_typed_ones():
    tab = tab_rows({"A": "Gold producers", "B": "Beta Gold", "D": "BET", "F": 0.1, "S": 0.55})
    P = SC.plan(gold_universe(), tab, SIZES, TODAY, state={"review": {"BET": 0.55}})
    assert next(r for r in P["rows"] if r["B"] == "Beta Gold")["S"] == 0.6          # recorded: the screen's own
    P = SC.plan(gold_universe(), tab, SIZES, TODAY, state={"review": {"BET": 0.5}})
    assert next(r for r in P["rows"] if r["B"] == "Beta Gold")["S"] == 0.55         # changed since: typed
    P = SC.plan(gold_universe(), tab, SIZES, TODAY, state=None, rule_levels=True)
    assert next(r for r in P["rows"] if r["B"] == "Beta Gold")["S"] == 0.6


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
    from minerval import performance
    monkeypatch.setattr(performance, "add", lambda U, *a, **k: U)          # offline: no cache/fundamentals.json
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
    U = universe(company(holding="A", ticker="A", net_cash_pct=20.0), company(holding="B", ticker="B", net_cash_pct=5.0),
                 company(holding="C", ticker="C", mcap=100.0))
    U["bucket"] = "Gold producers"
    P = SC.plan(U, [], {"Gold producers": {"weight": 1.0, "names": 1}}, TODAY, None)
    T = SC.ranking_table(P).set_index("holding")
    assert T.loc["A", "picked"] and T.loc["A", "rank"] == 1 and T.loc["A", "p_net_cash_pct"] == 1.0
    assert T.loc["B", "p_net_cash_pct"] == 0.0 and not T.loc["B", "picked"]
    assert T.loc["C", "excluded"].startswith("market cap") and np.isnan(T.loc["C", "score"])


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
