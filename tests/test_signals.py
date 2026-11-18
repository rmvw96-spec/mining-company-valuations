"""Market signals: the calculations, the status rules, and writing the Signals tab. All on synthetic data."""
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from minerval import prices, signals
from minerval.config import settings
from minerval.signals import BY_KEY, SIGNALS, compute, in_window, parse_fred, percentile, status, status_formula
from minerval.sheets import MemorySheet

TODAY = date(2026, 11, 17)


def daily(values, end="2026-11-17"):
    idx = pd.bdate_range(end=end, periods=len(values))
    return pd.Series(np.asarray(values, dtype=float), index=idx)


def flat(v, n=520):
    return daily([v] * n)


def monthly(values, end="2026-11-01"):
    return pd.Series(np.asarray(values, dtype=float), index=pd.date_range(end=end, periods=len(values), freq="MS"))


def base_data(**over):
    D = {s: flat(100.0) for s in settings()["signals"]["daily"]}
    D["GC=F"], D["SI=F"] = flat(4000.0), flat(50.0)
    D.update(over)
    return {"daily": D, "monthly": {}, "real_yield": daily(np.linspace(2.0, 2.0, 300))}


def row(rows, key):
    return next(r for r in rows if r["key"] == key)


# --- building blocks ---

def test_percentile():
    assert percentile(5, range(1, 11)) == 50.0
    assert percentile(0, [1, 2, 3]) == 0.0
    assert percentile(3, [1, 2, 3]) == 100.0
    assert percentile(None, [1]) is None and percentile(1, []) is None


@pytest.mark.parametrize("d,inside", [(date(2026, 10, 31), False), (date(2026, 11, 1), True),
                                      (date(2026, 12, 31), True), (date(2027, 1, 1), False)])
def test_tax_loss_window(d, inside):
    assert in_window(d, ["11-01", "12-31"]) is inside
    assert row(compute(base_data(), d), "tax_loss_window")["value"] == int(inside)


def test_window_across_the_year_end():
    assert in_window(date(2027, 1, 10), ["12-15", "01-31"]) and not in_window(date(2027, 3, 1), ["12-15", "01-31"])


def test_200_day_average():
    s = daily([100.0] * 199 + [120.0])
    assert signals.vs_average(s, 200) == pytest.approx(120 / (100.1) - 1)
    assert signals.vs_average(s[:150], 200) is None


def test_12_month_change_and_drawdown():
    s = daily(np.r_[np.full(300, 50.0), np.full(219, 80.0), [60.0]])
    assert signals.change_12m(s) == pytest.approx(60 / 50 - 1)
    assert signals.drawdown(s) == pytest.approx(60 / 80 - 1)
    assert signals.change_12m(daily([1.0, 2.0])) is None          # less than a year of data


def test_parse_fred_skips_holidays():
    s = parse_fred("observation_date,DFII10\n2026-11-10,2.85\n2026-11-11,.\n2026-11-12,2.9\n")
    assert list(s.index.strftime("%Y-%m-%d")) == ["2026-11-10", "2026-11-12"]
    assert list(s) == [2.85, 2.9]


def test_fcf_yield_from_the_holdings_tab():
    sh = MemorySheet({"Holdings": {
        "A2": "SGDM", "C2": 10.0, "D2": 1000.0, "J2": 50.0, "O2": "AAA",
        "A3": "SGDM", "C3": 30.0, "D3": 3000.0, "J3": 60.0, "O3": "BBB",
        "A4": "SGDM", "C4": 5.0, "D4": 0, "J4": 5.0, "O4": "ZERO",             # no market cap: left out
        "A5": "SGDM", "C5": 5.0, "D5": 100.0, "J5": "", "O5": "NOFCF",        # no FCF: left out
        "A6": "SLVR", "C6": 30.0, "D6": 20000.0, "J6": 900.0, "O6": "PSLV",   # physical trust: left out
        "A7": "SLVR", "C7": 10.0, "D7": 500.0, "J7": -25.0, "O7": "CCC"}})
    y = signals.fcf_yields_from_sheet(sh)
    assert y["SGDM"] == pytest.approx((10 * 50 / 1000 + 30 * 60 / 3000) / 40)
    assert y["SLVR"] == pytest.approx(-0.05)
    assert y["COPP"] is None


# --- status rules: both sides of every threshold ---

@pytest.mark.parametrize("key,value,want", [
    ("gold_silver_ratio", 80.0, 0), ("gold_silver_ratio", 79.9, 2), ("gold_silver_ratio", 50.0, 1),
    ("gold_silver_ratio", 50.1, 2),
    ("usd_12m", -0.03, 0), ("usd_12m", -0.029, 2), ("usd_12m", 0.03, 1), ("usd_12m", 0.029, 2),
    ("spy_drawdown", -0.20, 0), ("spy_drawdown", -0.19, 1), ("spy_drawdown", -0.10, 1), ("spy_drawdown", -0.09, 2),
    ("royalty_pnav_median", 1.4, 0), ("royalty_pnav_median", 1.41, 1), ("royalty_pnav_median", 2.2, 1),
    ("royalty_pnav_median", 2.21, 2),
    ("gold_vs_diesel_12m", 0.10, 0), ("gold_vs_diesel_12m", 0.09, 2), ("gold_vs_diesel_12m", -0.10, 1),
    ("gold_vs_diesel_12m", -0.09, 2),
    ("gdx_gold_pctile10y", 20, 0), ("gdx_gold_pctile10y", 21, 2), ("gdx_gold_pctile10y", 80, 1),
    ("gdx_gold_pctile10y", 79, 2),
    ("fcf_yield_SGDM", 0.08, 0), ("fcf_yield_SGDM", 0.079, 2), ("fcf_yield_SGDM", 0.03, 1),
    ("fcf_yield_SGDM", 0.031, 2),
    ("tax_loss_window", 1, 0), ("tax_loss_window", 0, 1),
    ("uptrend_gold", 0.001, 0), ("uptrend_gold", 0.0, 1),
])
def test_status_boundaries(key, value, want):
    sig = BY_KEY[key]
    g, h = settings()["signals"]["thresholds"].get(key, [None, None])
    assert status(sig, value, g, h, {}) == sig.texts[want]


def test_real_yield_peaked_and_falling_vs_rising():
    sig, (g, h) = BY_KEY["real_yield_10y"], settings()["signals"]["thresholds"]["real_yield_10y"]
    assert status(sig, 2.6, g, h, {"real_yield_12m_high": 2.9, "real_yield_3m_change": -0.2}) == sig.texts[0]
    assert status(sig, 2.7, g, h, {"real_yield_12m_high": 2.9, "real_yield_3m_change": -0.2}) == sig.texts[2]
    assert status(sig, 2.9, g, h, {"real_yield_12m_high": 2.9, "real_yield_3m_change": 0.1}) == sig.texts[1]
    assert status(sig, 2.9, g, h, {"real_yield_12m_high": 2.9, "real_yield_3m_change": 0.05}) == sig.texts[2]
    # From the series: a rise to a peak, then a fall over the last 3 months
    up = np.r_[np.linspace(2.0, 3.0, 200), np.linspace(3.0, 2.6, 64)]
    rows = compute(base_data() | {"real_yield": daily(up)}, TODAY)
    assert row(rows, "real_yield_10y")["status"] == sig.texts[0]
    rows = compute(base_data() | {"real_yield": daily(np.linspace(2.0, 3.0, 264))}, TODAY)
    assert row(rows, "real_yield_10y")["status"] == sig.texts[1]


def test_junior_timing():
    sig = BY_KEY["junior_timing"]
    ctx = {"tax_loss_window": 1, "uptrend_gold": 0.1, "uptrend_gdx": 0.1}
    assert status(sig, 2, None, None, ctx) == sig.texts[0]
    assert status(sig, 1, None, None, ctx | {"uptrend_gdx": -0.1}) == sig.texts[1]
    assert status(sig, 1, None, None, ctx | {"tax_loss_window": 0}) == sig.texts[2]
    assert status(sig, 0, None, None, ctx | {"tax_loss_window": 0, "uptrend_gold": -0.1}) == sig.texts[3]


def test_aisc_margin_text():
    s = status(BY_KEY["aisc_margin"], 1870.0, None, None, {"industry_aisc": 1930})
    assert s == "Margin $1,870/oz (49% of the gold price)"


def test_missing_value_gives_no_status():
    assert status(BY_KEY["usd_12m"], None, -0.03, 0.03, {}) == ""


def test_every_status_formula_uses_its_row_and_texts():
    for sig in SIGNALS:
        f = status_formula(sig, 9)
        assert f.startswith('=IF(E9="","",') and f.count("(") == f.count(")")
        for t in sig.texts:
            assert '"' + t.replace('"', '""') + '"' in f, (sig.key, t)
        if sig.kind in ("high_low", "low_high", "drawdown", "band"):
            assert "G9" in f and "H9" in f


# --- compute on synthetic series ---

def test_compute_ratio_percentile_and_changes():
    gold = daily(np.r_[np.full(270, 3000.0), np.full(250, 3600.0)])
    data = base_data(**{"GC=F": gold, "HO=F": daily(np.r_[np.full(270, 2.0), np.full(250, 3.0)])})
    data["monthly"] = {"GC=F": monthly([1000.0] * 100), "SI=F": monthly(np.linspace(10.0, 40.0, 100))}
    rows = compute(data, TODAY)
    assert row(rows, "gold_silver_ratio")["value"] == pytest.approx(72.0)
    hist = (1000.0 / np.linspace(10.0, 40.0, 100))[:-1]          # the current month is left out
    assert row(rows, "gold_silver_ratio_pctile")["value"] == pytest.approx(100 * (hist <= 72.0).mean())
    assert row(rows, "gold_12m")["value"] == pytest.approx(0.2)
    assert row(rows, "diesel_12m")["value"] == pytest.approx(0.5)
    assert row(rows, "gold_vs_diesel_12m")["value"] == pytest.approx(-0.3)
    assert row(rows, "gold_vs_diesel_12m")["status"] == "Fuel costs outpacing gold: margin squeeze"
    assert row(rows, "aisc_margin")["value"] == pytest.approx(3600 - 1930)
    assert row(rows, "gold_12m")["asof"] == "2026-11-17"


def test_compute_uses_sheet_thresholds_and_inputs():
    rows = compute(base_data(), TODAY, thresholds={"gold_silver_ratio": [70, 40]}, inputs={"industry_aisc": 2000})
    r = row(rows, "gold_silver_ratio")
    assert (r["threshold_1"], r["status"]) == (70, "Silver cheap against gold: favours silver")
    assert row(rows, "aisc_margin")["value"] == 2000.0


def test_compute_formula_rows():
    rows = compute(base_data(), TODAY, royalty_pnavs=[2.0, 2.4, 1.3])
    assert row(rows, "royalty_pnav_median")["value"] == pytest.approx(2.0)
    assert row(rows, "royalty_pnav_median")["status"] == "Normal range"
    assert row(rows, "junior_timing")["value"] == 1                 # window open, flat prices: no uptrend
    assert row(rows, "junior_timing")["status"] == "Tax-loss window open; uptrend not confirmed"


def test_compute_with_missing_series():
    data = base_data()
    del data["daily"]["DX-Y.NYB"]
    data["real_yield"] = None
    rows = compute(data, TODAY)
    assert row(rows, "usd_12m")["value"] is None and row(rows, "usd_12m")["status"] == ""
    assert row(rows, "real_yield_10y")["value"] is None


# --- the Signals tab ---

def signals_tab():
    cells = {"A4": "Key"}
    r = 5
    for sig in SIGNALS:
        cells[f"A{r}"] = sig.key
        g = settings()["signals"]["thresholds"].get(sig.key)
        if g:
            cells[f"G{r}"], cells[f"H{r}"] = g
        if sig.formula:
            cells[f"E{r}"] = "=FORMULA()"
        r += 1
    cells[f"A{r + 1}"], cells[f"E{r + 1}"] = "industry_aisc", 2000
    return cells


def test_run_writes_values_by_key_and_reports_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "load_cache", lambda: base_data())
    monkeypatch.setattr(signals, "royalty_pnavs_from_derived", lambda: [2.5])
    sh = MemorySheet({"Signals": signals_tab(), "Holdings": {}})
    rep = signals.run(sh, out_dir=tmp_path, fetch_data=False, today=TODAY)
    tab = sh.cells["Signals"]
    keys = {v: k[1:] for k, v in tab.items() if k.startswith("A")}
    assert tab[f"E{keys['gold_silver_ratio']}"] == pytest.approx(80.0)
    assert tab[f"F{keys['gold_silver_ratio']}"] == "2026-11-17"
    assert tab[f"E{keys['aisc_margin']}"] == pytest.approx(4000 - 2000)    # the Sheet's input wins
    for k in ("royalty_pnav_median", "junior_timing"):
        assert tab[f"E{keys[k]}"] == "=FORMULA()"                         # formula rows are never written
    written = {c for _, cell, rows_ in sh.blocks for c in [cell[0]]}
    assert written == {"E"}
    text = "\n".join(rep)
    assert "Sheet and Python statuses differ" in text                      # MemorySheet has no formulas in I
    assert (tmp_path / "signals.json").exists() and (tmp_path / "last.json").exists()


def test_run_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "load_cache", lambda: base_data())
    sh = MemorySheet({"Signals": signals_tab(), "Holdings": {}})
    signals.run(sh, dry_run=True, out_dir=tmp_path, fetch_data=False, today=TODAY)
    assert not sh.blocks and not (tmp_path / "last.json").exists()


def test_run_without_the_tab(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "load_cache", lambda: base_data())
    rep = signals.run(MemorySheet({"Holdings": {}}), out_dir=tmp_path, fetch_data=False, today=TODAY)
    assert "run `setup-sheet` first" in rep[0]


def test_changes_since_last_run(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "load_cache", lambda: base_data())
    (tmp_path / "last.json").write_text('{"tax_loss_window": "Outside the window"}')
    rep = signals.run(None, out_dir=tmp_path, fetch_data=False, today=TODAY)
    assert any("Outside the window -> In the tax-loss selling window" in line for line in rep)


def test_price_update_survives_a_signals_failure(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("FRED is down")
    monkeypatch.setattr(signals, "run", boom)
    lines = prices.run_signals(MemorySheet())
    assert lines == ["Signals not updated: ConnectionError: FRED is down. The prices above were written."]


# --- running on GitHub: no FRED download, no data/derived/, no last.json ---

def test_missing_series_falls_back_to_the_sheet_and_is_not_rewritten(tmp_path, monkeypatch):
    data = base_data()
    data["real_yield"] = None
    monkeypatch.setattr(signals, "load_cache", lambda: data)
    cells = signals_tab()
    keys = {v: k[1:] for k, v in cells.items() if k.startswith("A")}
    for k, v in (("real_yield_10y", 2.9), ("real_yield_12m_high", 2.95), ("real_yield_3m_change", 0.5)):
        cells[f"E{keys[k]}"], cells[f"F{keys[k]}"] = v, "2026-11-14"
    sh = MemorySheet({"Signals": cells, "Holdings": {}})
    rep = signals.run(sh, out_dir=tmp_path, fetch_data=False, today=TODAY)
    out = {r["key"]: r for r in json.loads((tmp_path / "signals.json").read_text())["signals"]}
    assert out["real_yield_10y"]["stale"] and out["real_yield_10y"]["status"] == "Rising: keep accumulating steadily"
    assert out["real_yield_10y"]["asof"] == "2026-11-14"
    assert not any(cell == f"E{keys['real_yield_10y']}" for _, cell, _ in sh.blocks)   # not rewritten
    assert any("Sheet's last values are kept: real_yield_10y (2026-11-14)" in line for line in rep)


def test_fallback_never_overrides_fresh_data():
    rows = compute(base_data(), TODAY, fallback={"real_yield_10y": (9.9, "2026-01-01"), "junior_timing": (2, "")})
    assert row(rows, "real_yield_10y")["value"] == pytest.approx(2.0) and not row(rows, "real_yield_10y")["stale"]
    assert row(rows, "junior_timing")["value"] == 1                 # formula rows are never filled from the Sheet


def test_royalty_median_from_the_pnav_inputs_tab(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "load_cache", lambda: base_data())
    monkeypatch.setattr(signals, "royalty_pnavs_from_derived", lambda: [])
    pnav = {"R12": 50.0, "AJ12": 2.0, "AL12": "Royalty/streaming",
            "R13": 40.0, "AJ13": 2.6, "AL13": "Royalty/streaming",
            "R14": "", "AJ14": 9.0, "AL14": "Royalty/streaming",     # no NAV per share: left out, as on the Sheet
            "R15": 30.0, "AJ15": 0.5, "AL15": "Gold producer"}
    sh = MemorySheet({"Signals": signals_tab(), "Holdings": {}, "PNAV inputs": pnav})
    signals.run(sh, out_dir=tmp_path, fetch_data=False, today=TODAY)
    out = json.loads((tmp_path / "signals.json").read_text())["signals"]
    assert row(out, "royalty_pnav_median")["value"] == pytest.approx(2.3)


def test_changes_are_measured_against_the_sheet_before_the_write(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "load_cache", lambda: base_data())
    cells = signals_tab()
    keys = {v: k[1:] for k, v in cells.items() if k.startswith("A")}
    cells[f"I{keys['tax_loss_window']}"] = "Outside the window"
    (tmp_path / "last.json").write_text('{"tax_loss_window": "In the tax-loss selling window"}')   # ignored
    rep = signals.run(MemorySheet({"Signals": cells, "Holdings": {}}), out_dir=tmp_path, fetch_data=False,
                      today=TODAY)
    assert any("Outside the window -> In the tax-loss selling window" in line for line in rep)


def test_fred_api_json_becomes_the_graph_csv(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "k")
    got = {}

    def fake_json(url, params=None, tries=5, timeout=30):
        got.update(params)
        return {"observations": [{"date": "2026-11-13", "value": "2.90"}, {"date": "2026-11-14", "value": "."}]}
    monkeypatch.setattr(signals.yahoo, "get_json", fake_json)
    txt = signals.fred_csv(settings()["signals"])
    assert got["series_id"] == "DFII10" and got["file_type"] == "json"
    s = parse_fred(txt)
    assert list(s.values) == [2.9]
