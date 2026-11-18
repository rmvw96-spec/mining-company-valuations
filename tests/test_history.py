"""Signal history and company history: rows by date on the Sheet. Offline, on a MemorySheet."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from minerval import history, signals
from minerval.history import backfill_entries, company_rows, truncate, upsert_company, upsert_signals
from minerval.sheets import CLEAR, MemorySheet
from minerval.signals import SIGNALS, compute

from test_signals import base_data, signals_tab

SH, CH = "Signal history", "Company history"
KEYS = ["gold_silver_ratio", "usd_12m"]


def tab_rows(sh, tab):
    from minerval.sheets import num_to_col
    rows = sh.read(tab, f"A1:{num_to_col(min(sh.col_count(tab), 60))}{sh.row_count(tab)}")
    out = []
    for r in rows:
        r = list(r)
        while r and r[-1] == "":
            r.pop()
        out.append(r)
    return out


def test_first_write_creates_the_tab_with_headers_and_formats():
    sh = MemorySheet()
    lines = upsert_signals(sh, {"2026-11-17": ("live", {"gold_silver_ratio": 80.0, "usd_12m": 0.04})}, KEYS)
    assert tab_rows(sh, SH) == [["Date", "Source", *KEYS], ["2026-11-17", "live", 80.0, 0.04]]
    assert sh.sizes[SH][0] >= 1000
    assert (SH, "A2:A1000", "yyyy-mm-dd") in sh.formats and (SH, "D2:D1000", "0.0%") in sh.formats
    assert "1 rows added, 0 replaced (2026-11-17)" in lines[0]


def test_same_date_replaces_and_a_new_date_appends():
    sh = MemorySheet()
    upsert_signals(sh, {"2026-11-17": ("live", {"gold_silver_ratio": 80.0})}, KEYS)
    upsert_signals(sh, {"2026-11-17": ("live", {"gold_silver_ratio": 81.0, "usd_12m": 0.05})}, KEYS)
    upsert_signals(sh, {"2026-11-18": ("live", {"gold_silver_ratio": 82.0})}, KEYS)
    rows = tab_rows(sh, SH)
    assert [r[:3] for r in rows[1:]] == [["2026-11-17", "live", 81.0], ["2026-11-18", "live", 82.0]]
    assert len(rows[2]) == 3 and len(rows[1]) == 4          # a missing value is blank, not zero


def test_columns_are_found_by_key_and_new_keys_go_on_the_right():
    sh = MemorySheet({SH: {"A1": "Date", "B1": "Source", "C1": "usd_12m", "D1": "gold_silver_ratio",
                           "A2": "2026-11-16", "B2": "live", "C2": 0.03, "D2": 79.0}})
    lines = upsert_signals(sh, {"2026-11-17": ("live", {"gold_silver_ratio": 80.0, "usd_12m": 0.04,
                                                         "spy_drawdown": -0.06})}, KEYS + ["spy_drawdown"])
    rows = tab_rows(sh, SH)
    assert rows[0] == ["Date", "Source", "usd_12m", "gold_silver_ratio", "spy_drawdown"]
    assert rows[1] == ["2026-11-16", "live", 0.03, 79.0]          # old row untouched
    assert rows[2] == ["2026-11-17", "live", 0.04, 80.0, -0.06]
    assert any("new columns: spy_drawdown" in ln for ln in lines)
    assert [f[1].split(":")[0] for f in sh.formats] == ["E2"] and sh.formats[0][2] == "0.0%"


def test_a_moved_header_stops_the_write():
    sh = MemorySheet({SH: {"A1": "When", "B1": "Source"}})
    lines = upsert_signals(sh, {"2026-11-17": ("live", {})}, KEYS)
    assert "not written" in lines[0] and not sh.blocks


def test_backfill_inserts_older_dates_in_order_and_never_replaces_live_rows():
    sh = MemorySheet()
    upsert_signals(sh, {"2026-11-17": ("live", {"gold_silver_ratio": 80.0})}, KEYS)
    lines = upsert_signals(sh, {"2026-11-13": ("backfill", {"gold_silver_ratio": 78.0}),
                                "2026-11-16": ("backfill", {"gold_silver_ratio": 79.0}),
                                "2026-11-17": ("backfill", {"gold_silver_ratio": 1.0})}, KEYS)
    rows = tab_rows(sh, SH)
    assert [r[:3] for r in rows[1:]] == [["2026-11-13", "backfill", 78.0], ["2026-11-16", "backfill", 79.0],
                                         ["2026-11-17", "live", 80.0]]
    assert any("1 backfilled dates skipped" in ln for ln in lines)


def test_dry_run_writes_nothing():
    sh = MemorySheet({SH: {"A1": "Date", "B1": "Source", "C1": "gold_silver_ratio"}})
    lines = upsert_signals(sh, {"2026-11-17": ("live", {"gold_silver_ratio": 80.0})}, KEYS, dry_run=True)
    assert not sh.blocks and "dry run" in lines[0]
    assert "would create" in upsert_signals(MemorySheet(), {"2026-11-17": ("live", {})}, KEYS, dry_run=True)[0]


def test_the_tab_grows_in_chunks():
    sh = MemorySheet(sizes={SH: [3, 10]})
    sh.cells[SH] = {"A1": "Date", "B1": "Source", "A2": "2026-11-13", "B2": "live", "A3": "2026-11-16", "B3": "live"}
    upsert_signals(sh, {"2026-11-17": ("live", {"gold_silver_ratio": 80.0})}, KEYS)
    assert sh.sizes[SH][0] == 1000 and sh.cells[SH]["A4"] == "2026-11-17"


# --- Company history ---

def pnav_grid():
    """PNAV inputs rows from column A: two royalty rows (one repeated, as Wheaton is), a developer, a producer."""
    def row(**c):
        from minerval.sheets import col_to_num
        r = [""] * 57
        for k, v in c.items():
            r[col_to_num(k) - 1] = v
        return r
    return [row(B="Wheaton", AP="WPM", C=80.0, R=40.0, AJ=2.0, AL="Royalty/streaming"),
            row(B="Wheaton", AP="WPM", C=80.0, R=40.0, AJ=2.0, AL="Royalty/streaming"),
            row(B="NoNav Royalty", AP="NNR", C=5.0, AJ=9.0, AL="Royalty/streaming"),
            row(B="Skeena", AP="SKE.TO", C=27.0, BB=895.0, BC=1.4, BD=0.017, BE="Short of cash: financing likely"),
            row(B="Cashy Dev", AP="CD.V", BB=50.0, BC="Cash-generating", BD=0.4, BE="Enough cash"),
            row(B="Newmont", AP="NEM", C=90.0, AJ=1.1, AL="Senior gold")]


def test_company_rows_pick_royalties_and_developers():
    rows = company_rows(pnav_grid(), "2026-11-17")
    assert rows == [["2026-11-17", "Wheaton", "WPM", "independent_pnav", 2.0],
                    ["2026-11-17", "Wheaton", "WPM", "price_usd", 80.0],
                    ["2026-11-17", "Skeena", "SKE.TO", "ev_per_aueq_oz", 895.0],
                    ["2026-11-17", "Skeena", "SKE.TO", "months_of_cash", 1.4],
                    ["2026-11-17", "Skeena", "SKE.TO", "cash_share", 0.017],
                    ["2026-11-17", "Cashy Dev", "CD.V", "ev_per_aueq_oz", 50.0],   # text months skipped
                    ["2026-11-17", "Cashy Dev", "CD.V", "cash_share", 0.4]]


def test_company_history_appends_then_replaces_the_same_date():
    sh = MemorySheet()
    upsert_company(sh, company_rows(pnav_grid(), "2026-11-16"), "2026-11-16")
    upsert_company(sh, company_rows(pnav_grid(), "2026-11-17"), "2026-11-17")
    short = company_rows(pnav_grid()[:1], "2026-11-17")                      # fewer rows on a rerun
    lines = upsert_company(sh, short, "2026-11-17")
    rows = tab_rows(sh, CH)
    assert rows[0] == ["Date", "Holding", "Yahoo", "Metric", "Value"]
    assert sum(r[0] == "2026-11-16" for r in rows) == 7 and sum(r[0] == "2026-11-17" for r in rows) == 2
    assert len(rows) == 1 + 7 + 2                                            # the leftover rows were cleared
    assert "2 rows replaced for 2026-11-17" in lines[0]


def test_company_history_refuses_to_write_before_a_later_date():
    sh = MemorySheet({CH: {"A1": "Date", "B1": "Holding", "C1": "Yahoo", "D1": "Metric", "E1": "Value",
                           "A2": "2026-11-18"}})
    assert "dates after" in upsert_company(sh, company_rows(pnav_grid(), "2026-11-17"), "2026-11-17")[0]


# --- the hook in signals.run ---

def test_signals_run_records_history(tmp_path, monkeypatch):
    data = base_data()
    data["real_yield"] = None                                                 # a stale row is recorded blank
    monkeypatch.setattr(signals, "load_cache", lambda: data)
    cells = signals_tab()
    keys = {v: k[1:] for k, v in cells.items() if k.startswith("A")}
    cells[f"E{keys['real_yield_10y']}"], cells[f"F{keys['real_yield_10y']}"] = 2.9, "2026-11-14"
    from minerval.sheets import num_to_col
    pnav = {}
    for i, r in enumerate(pnav_grid(), start=12):
        for j, v in enumerate(r):
            if v != "":
                pnav[f"{num_to_col(j + 1)}{i}"] = v
    sh = MemorySheet({"Signals": cells, "Holdings": {}, "PNAV inputs": pnav})
    rep = signals.run(sh, out_dir=tmp_path, fetch_data=False, today=date(2026, 11, 17))
    rows = tab_rows(sh, SH)
    assert rows[0][:2] == ["Date", "Source"] and rows[0][2:] == [s.key for s in SIGNALS]
    rec = dict(zip(rows[0], rows[1]))
    assert rec["Date"] == "2026-11-17" and rec["gold_silver_ratio"] == pytest.approx(80.0)
    assert rec.get("real_yield_10y", "") == ""
    assert sum(r[0] == "2026-11-17" for r in tab_rows(sh, CH)) == 7
    assert any(ln.startswith("Company history: 7 rows added") for ln in rep)


def test_weekends_are_not_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "load_cache", lambda: base_data())
    sh = MemorySheet({"Signals": signals_tab(), "Holdings": {}})
    rep = signals.run(sh, out_dir=tmp_path, fetch_data=False, today=date(2026, 11, 21))
    assert not sh.has_tab(SH) and any("is a weekend" in ln for ln in rep)


def test_a_history_failure_never_fails_the_signals_run(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "load_cache", lambda: base_data())

    def boom(*a, **k):
        raise RuntimeError("quota")
    monkeypatch.setattr(history, "upsert_signals", boom)
    monkeypatch.setattr(history, "upsert_company", boom)
    sh = MemorySheet({"Signals": signals_tab(), "Holdings": {}})
    rep = signals.run(sh, out_dir=tmp_path, fetch_data=False, today=date(2026, 11, 17))
    assert "Signal history not written: RuntimeError: quota" in rep
    assert any(ln.startswith("Wrote") for ln in rep)


# --- backfill ---

def test_truncate_hides_later_data():
    data = base_data()
    d = data["daily"]["GC=F"].index[-10]
    data["daily"]["GC=F"].iloc[-5:] = 99_999.0                              # a spike after d
    t = truncate(data, d)
    assert t["daily"]["GC=F"].index[-1] == d and t["daily"]["GC=F"].max() < 99_999
    assert t["real_yield"].index[-1] <= d


def test_backfill_matches_compute_on_the_truncated_data():
    data = base_data()
    data["daily"]["GC=F"] = data["daily"]["GC=F"] * np.linspace(0.8, 1.2, len(data["daily"]["GC=F"]))
    idx = data["daily"]["GC=F"].index
    entries = backfill_entries(data, idx[-3], idx[-1])
    assert list(entries) == [d.date().isoformat() for d in idx[-3:]]
    d = idx[-2]
    want = {r["key"]: r["value"] for r in compute(truncate(data, d), d.date())}
    source, got = entries[d.date().isoformat()]
    assert source == "backfill" and got["gold_silver_ratio"] == pytest.approx(want["gold_silver_ratio"])
    assert "aisc_margin" not in got and "fcf_yield_SGDM" not in got and "royalty_pnav_median" not in got


def test_backfill_command_writes_rows(monkeypatch):
    monkeypatch.setattr(signals, "load_cache", lambda: base_data())
    idx = base_data()["daily"]["GC=F"].index
    sh = MemorySheet()
    lines = history.backfill(sh, idx[-5].date().isoformat(), idx[-1].date().isoformat())
    assert "5 trading days" in lines[0] and len(tab_rows(sh, SH)) == 6
    assert all(r[1] == "backfill" for r in tab_rows(sh, SH)[1:])


def test_values_and_clear_cells():
    assert history._cell(1.5) == 1.5 and history._cell(None) == CLEAR and history._cell(float("nan")) == CLEAR
    assert history._iso("2026-11-17") == "2026-11-17" and history._iso(pd.Timestamp("2026-11-17")) == "2026-11-17"
