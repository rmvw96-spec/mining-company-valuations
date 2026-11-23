"""Royalties against their own history: the SEC record, P/OCF history, percentiles, bands and the Sheet columns."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from minerval import layout, royalty_history as RH, signals
from minerval.config import settings
from minerval.sheets import CLEAR, MemorySheet

C = {"years": 5, "min_months": 3, "pnav_min_days": 3}


def fact(val, start, end, filed, accn, form="40-F"):
    return {"val": val, "start": start, "end": end, "filed": filed, "accn": accn, "form": form}


def test_annual_rows_first_filing_usd_preferred_cad_converted_and_shares_from_the_filing():
    facts = {"facts": {
        "ifrs-full": {"CashFlowsFromUsedInOperatingActivities": {"units": {
            "CAD": [fact(100e6, "2022-01-01", "2022-12-31", "2023-03-30", "a1"),
                    fact(200e6, "2023-01-01", "2023-12-31", "2024-03-28", "a2")],
            "USD": [fact(150e6, "2023-01-01", "2023-12-31", "2025-03-28", "a3"),            # restated later: ignored
                    fact(90e6, "2024-01-02", "2024-12-31", "2025-03-28", "a3"),
                    fact(91e6, "2024-01-01", "2024-12-31", "2026-03-28", "a4"),            # same year, later filing
                    fact(40e6, "2025-01-01", "2025-06-30", "2026-03-28", "a4"),            # six months: skipped
                    fact(10e6, "2024-01-01", "2024-12-31", "2025-03-28", "x", "6-K")]}},   # not an annual form
            "WeightedAverageShares": {"units": {"shares": [
                fact(50e6, "2022-01-01", "2022-12-31", "2023-03-30", "a1")]}}},
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            {"val": 60e6, "end": "2024-03-20", "filed": "2024-03-28", "accn": "a2", "form": "40-F"},
            {"val": 61e6, "end": "2025-03-20", "filed": "2025-03-28", "accn": "a3", "form": "40-F"}]}}}}}
    rows = RH.annual_rows(facts, "OR", 1, lambda cur, s, e: 0.75)
    got = [(r["fiscal_end"], r["currency"], r["ocf_usd_m"], r["shares_m"], r["filed"]) for r in rows]
    assert got == [("2022-12-31", "CAD", 75.0, 50.0, "2023-03-30"),     # no cover shares: the weighted average
                   ("2023-12-31", "CAD", 150.0, 60.0, "2024-03-28"),
                   ("2024-12-31", "USD", 90.0, 61.0, "2025-03-28")]
    assert "converted" in rows[0]["source"] and "converted" not in rows[2]["source"]


def record(rows):
    T = pd.DataFrame(rows, columns=["fiscal_end", "filed", "ocf_usd_m", "shares_m"])
    T["fiscal_end"], T["filed"] = pd.to_datetime(T.fiscal_end), pd.to_datetime(T.filed)
    return T


def test_pocf_uses_the_annual_figure_filed_by_each_month_end_and_skips_negative_years():
    rec = record([("2023-12-31", "2024-03-28", 100.0, 10.0), ("2024-12-31", "2025-03-28", -5.0, 10.0)])
    px = pd.Series([10.0, 20.0, 30.0, 40.0], index=pd.to_datetime(["2024-02-01", "2024-03-01", "2025-02-01",
                                                                   "2025-03-01"]))
    s = RH.pocf_history(rec, px, date(2026, 1, 1))
    assert list(s.index) == list(px.index[1:])                     # nothing filed before the end of Feb 2024
    assert s.iloc[0] == 2.0 and s.iloc[1] == 3.0                   # 20 × 10 / 100; Feb 2025 still on 2023's
    assert np.isnan(s.iloc[2])                                     # March 2025 onwards: negative cash flow


def test_current_month_counts_filings_up_to_today_only():
    rec = record([("2024-12-31", "2025-03-28", 100.0, 10.0), ("2025-12-31", "2026-03-20", 200.0, 10.0)])
    px = pd.Series([10.0], index=pd.to_datetime(["2026-03-01"]))
    assert RH.pocf_history(rec, px, date(2026, 3, 10)).iloc[0] == 1.0      # 2025's filing isn't out yet
    assert RH.pocf_history(rec, px, date(2026, 3, 25)).iloc[0] == 0.5


def test_own_pocf_window_minimum_and_today_left_out_of_the_history():
    rec = record([("2015-12-31", "2016-01-15", 10.0, 1.0)])
    idx = pd.date_range("2016-02-01", periods=80, freq="MS")
    px = pd.Series(np.arange(1, 81, dtype=float), index=idx)
    o = RH.own_pocf(rec, px, date(2022, 9, 30), C)
    assert o["months"] == 59 and o["pocf"] == 8.0                  # 5 years back from the last bar, today excluded
    assert o["pctile"] == 100.0                                    # the highest it has been
    short = RH.own_pocf(rec, px.iloc[:3], date(2016, 4, 30), C)
    assert short["months"] == 2 and short["pctile"] is None        # under min_months
    assert RH.own_pocf(rec.iloc[:0], px, date(2022, 9, 30), C)["pocf"] is None


@pytest.mark.parametrize("x,want", [(0.5, 0.0), (1.0, 25.0), (2.5, 50.0), (4.0, 100.0), (9.0, 100.0)])
def test_percentile_edges(x, want):
    assert RH.percentile(x, [1.0, 2.0, 3.0, 4.0]) == want


def test_percentile_blank_cases():
    assert RH.percentile(None, [1.0]) is None and RH.percentile(1.0, []) is None
    assert RH.percentile(float("nan"), [1.0]) is None


def test_pnav_percentile_needs_the_minimum_days_before_today():
    h = [("2026-11-17", 1.0), ("2026-11-18", 2.0), ("2026-11-19", 3.0), ("2026-11-20", 9.0)]
    assert RH.own_pnav(h, 2.0, date(2026, 11, 20), C) == pytest.approx(200 / 3)     # today's own row left out
    assert RH.own_pnav(h, 2.0, date(2026, 11, 19), C) is None                       # only 2 days before it
    assert RH.own_pnav(h, "", date(2026, 11, 20), C) is None


@pytest.mark.parametrize("nav,ocf,want", [
    (None, 25.0, "Cheap for itself (P/OCF percentile 25)"),
    (None, 25.5, "Normal for itself (P/OCF percentile 26)"),       # TEXT(p,"0") rounds half up
    (None, 74.5, "Normal for itself (P/OCF percentile 75)"),
    (None, 75.0, "Expensive for itself (P/OCF percentile 75)"),
    (80.0, 10.0, "Expensive for itself (P/NAV percentile 80)"),    # P/NAV wins once recorded
    (None, None, ""),
])
def test_band(nav, ocf, want):
    assert RH.band(nav, ocf, 25, 75) == want


def test_band_formula_matches_the_python_rule():
    f = layout.own_band_formula()
    P = settings()["sheet"]["pnav_inputs"]
    assert f.startswith("=ARRAYFORMULA(LET(lo,") and 'XLOOKUP("royalty_own_pctile_median"' in f
    for text in RH.BANDS:
        assert f'"{text}"' in f
    assert f"ISNUMBER({P['pnav_pctile']}12:{P['pnav_pctile']}154)" in f and 'TEXT(p,"0")' in f
    assert "p<=lo" in f and "p>=hi" in f


def test_timing_formula_adds_the_own_band_and_upgrades_the_old_one():
    new, old = layout.timing_formula(), layout.timing_formula(own=False)
    assert "own,XLOOKUP(" in new and 'band&IF(own<>""," / "&own,"")' in new and "own," not in old
    st = layout.step_portfolio()
    cell = next(c for c in st.cells if c.ref == f"{settings()['sheet']['portfolio_cols']['timing']}6")
    assert cell.mode == "upgrade" and cell.old == old and cell.new == new


@pytest.mark.parametrize("v,want", [(25, 0), (26, 1), (74, 1), (75, 2)])
def test_signal_status(v, want):
    sig = signals.BY_KEY["royalty_own_pctile_median"]
    assert signals.status(sig, v, 25, 75, {}) == sig.texts[want]
    f = signals.status_formula(sig, 9)
    assert "IF(E9<=G9," in f and "IF(E9>=H9," in f


def test_signal_value_formula_and_compute_median():
    f = signals.value_formula(signals.BY_KEY["royalty_own_pctile_median"])
    assert f.startswith("=IFERROR(MEDIAN(FILTER(ARRAYFORMULA(IF(ISNUMBER(")
    rows = signals.compute({}, date(2026, 11, 20), royalty_pctiles=[10.0, 30.0, 90.0, None])
    r = next(x for x in rows if x["key"] == "royalty_own_pctile_median")
    assert r["value"] == 30.0 and r["status"] == "Normal for themselves"


def test_update_sheet_writes_royalty_rows_and_clears_the_rest(monkeypatch):
    S = settings()["sheet"]
    P, tab = S["pnav_inputs"], S["pnav_inputs_tab"]
    cells = {f"{P['holding']}12": "Wheaton", f"{P['yahoo']}12": "WPM.TO", f"{P['peer_group']}12": "Royalty/streaming",
             f"{P['independent_pnav']}12": 2.0,
             f"{P['holding']}13": "Newmont", f"{P['yahoo']}13": "NEM", f"{P['peer_group']}13": "Senior gold",
             f"{P['holding']}14": "Other royalty", f"{P['yahoo']}14": "XYZ", f"{P['peer_group']}14": "Royalty/streaming"}
    hist = {"A1": "Date", "B1": "Holding", "C1": "Yahoo", "D1": "Metric", "E1": "Value"}
    for i, (d, v) in enumerate([("2026-11-17", 1.0), ("2026-11-18", 3.0), ("2026-11-19", 4.0)], start=2):
        hist.update({f"A{i}": d, f"B{i}": "Wheaton", f"C{i}": "WPM.TO", f"D{i}": "independent_pnav", f"E{i}": v})
    sh = MemorySheet({tab: dict(cells), S["company_history_tab"]: hist})
    rec = pd.DataFrame({"symbol": ["WPM"], "fiscal_end": pd.to_datetime(["2015-12-31"]),
                        "filed": pd.to_datetime(["2016-01-15"]), "ocf_usd_m": [10.0], "shares_m": [1.0]})
    monkeypatch.setattr(RH, "load_record", lambda path=None: rec)
    monkeypatch.setattr(RH, "cfg", lambda: {**settings()["royalty_history"], **C})
    px = pd.Series([1.0, 2.0, 3.0, 4.0, 2.5], index=pd.date_range("2026-07-01", periods=5, freq="MS"))
    lines, used = RH.update_sheet(sh, {"WPM": px}, date(2026, 11, 20))
    got = sh.read(tab, f"{P['pocf']}12:{P['pnav_pctile']}14")
    assert got[0][:2] == [0.25, 50.0]                              # 2.5 × 1 / 10; above 2 of the 4 months before
    assert got[0][2] == pytest.approx(100 / 3)                     # P/NAV 2.0: above 1 of the 3 recorded days
    rest = [v for r in (got + [[], []])[1:3] for v in r]
    assert all(v in ("", None, CLEAR) for v in rest)
    assert used == [pytest.approx(100 / 3)]                        # the P/NAV percentile wins
    assert "Other royalty (XYZ): not in [royalty_history] companies" in " ".join(lines)
    sh2 = MemorySheet({tab: dict(cells)})
    RH.update_sheet(sh2, {"WPM": px}, date(2026, 11, 20), dry_run=True)
    assert sh2.read(tab, f"{P['pocf']}12:{P['pocf']}12") in ([], [[""]], [[]])


def test_fx_average_drops_a_bad_month_end_print(monkeypatch):
    """Yahoo's PHP=X has one bad month-end (16.2 on Apr 30, 2026, against ~61.5 either side): a month-end more than
    25% from the period's median is left out of the average US$ per unit."""
    idx = pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31", "2026-06-30"])
    s = pd.Series([58.8, 57.6, 61.7, 16.2, 61.0, 61.5], index=idx)
    monkeypatch.setattr(RH.yahoo, "history", lambda sym, interval: {"ok": True})
    monkeypatch.setattr(signals, "closes", lambda j: s)
    rate = RH._fx_average()
    want = float((1 / s.drop(pd.Timestamp("2026-04-30"))).mean())
    assert rate("PHP", "2026-01-01", "2026-06-30") == pytest.approx(want)
    assert rate("PHP", "2026-01-01", "2026-03-31") == pytest.approx(float((1 / s[:3]).mean()))   # nothing dropped
