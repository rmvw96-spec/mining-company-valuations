"""Junior breadth: the share of SGDJ and COPJ (by weight) above their own 200-day average. Synthetic data."""
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from minerval import signals
from minerval.history import truncate
from minerval.sheets import MemorySheet
from minerval.signals import BY_KEY, breadth, breadth_holdings, compute

END = "2026-11-17"


def daily(values, end=END):
    return pd.Series(np.asarray(values, dtype=float), index=pd.bdate_range(end=end, periods=len(values)))


def rising(n=260):
    return daily(np.linspace(10, 20, n))


def falling(n=260):
    return daily(np.linspace(20, 10, n))


def book(**closes):
    H = [{"fund": "SGDJ", "holding": "A", "weight": 50.0, "yahoo": "A"},
         {"fund": "SGDJ", "holding": "B", "weight": 30.0, "yahoo": "B"},
         {"fund": "SGDJ", "holding": "C", "weight": 15.0, "yahoo": "C"},
         {"fund": "SGDJ", "holding": "No symbol", "weight": 5.0, "yahoo": ""},
         {"fund": "COPJ", "holding": "D", "weight": 100.0, "yahoo": "D"}]
    return {"holdings": H, "closes": closes}


def test_weights_and_coverage():
    v, cov, d = breadth(book(A=rising(), B=falling(), C=rising(), D=falling()), "SGDJ", 200)
    assert v == pytest.approx(65 / 95) and cov == pytest.approx(0.95) and d == pd.Timestamp(END)
    v, cov, _ = breadth(book(A=rising(), B=falling(), C=rising(), D=falling()), "COPJ", 200)
    assert v == 0.0 and cov == 1.0


def test_missing_short_and_stale_series_leave_both_sides():
    B = book(A=rising(), B=falling(150), C=falling(260, ), D=rising())
    B["closes"]["C"] = falling(260).iloc[:-20]                     # stopped trading four weeks ago
    v, cov, _ = breadth(B, "SGDJ", 200)                            # only A (50) counts: B is short, C is stale
    assert v == 1.0 and cov == pytest.approx(0.50)
    assert breadth(None, "SGDJ", 200) == (None, 0.0, None)
    assert breadth(book(), "SGDJ", 200)[0] is None


def test_compute_statuses_and_thresholds():
    rows = {r["key"]: r for r in compute({"daily": {}, "monthly": {}, "breadth": book(
        A=rising(), B=rising(), C=falling(), D=falling())}, date(2026, 11, 17))}
    s, c = rows["breadth_sgdj"], rows["breadth_copj"]
    assert s["value"] == pytest.approx(80 / 95) and s["status"] == BY_KEY["breadth_sgdj"].texts[0]
    assert c["value"] == 0.0 and c["status"] == BY_KEY["breadth_copj"].texts[1]
    assert s["asof"] == "2026-11-17"
    rows = {r["key"]: r for r in compute({"daily": {}, "monthly": {}}, date(2026, 11, 17))}
    assert rows["breadth_sgdj"]["value"] is None and rows["breadth_sgdj"]["status"] == ""


def test_truncate_cuts_the_breadth_series():
    B = book(A=rising(), D=falling())
    t = truncate({"daily": {}, "monthly": {}, "breadth": B}, pd.Timestamp("2026-06-30"))
    assert t["breadth"]["closes"]["A"].index[-1] <= pd.Timestamp("2026-06-30")
    assert t["breadth"]["holdings"] == B["holdings"]


def test_holdings_from_the_sheet():
    sh = MemorySheet({"Holdings": {
        "A2": "SGDJ", "B2": "Wesdome", "C2": 4.9, "P2": "WDO.TO",
        "A3": "COPJ", "B3": "Minsur", "C3": 5.5, "P3": "",
        "A4": "SGDM", "B4": "Agnico", "C4": 10.0, "P4": "AEM.TO"}})
    H = breadth_holdings(sh)
    assert H == [{"fund": "SGDJ", "holding": "Wesdome", "weight": 4.9, "yahoo": "WDO.TO"},
                 {"fund": "COPJ", "holding": "Minsur", "weight": 5.5, "yahoo": ""}]


def test_fetch_keeps_the_list_and_the_closes(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "SIG_CACHE", tmp_path)
    monkeypatch.setattr(signals, "BREADTH_CACHE", tmp_path / "breadth")
    monkeypatch.setattr(signals, "fred_csv", lambda S, series=None: None)
    chart = {"chart": {"result": [{"timestamp": [1763337600], "indicators": {"quote": [{"close": [12.5]}]}}]}}
    asked = []
    monkeypatch.setattr(signals.yahoo, "pmap", lambda fn, items: {i: fn(i) for i in items})
    monkeypatch.setattr(signals.yahoo, "chart", lambda s, **k: asked.append(s) or (chart if s != "BAD" else None))
    monkeypatch.setattr(signals.yahoo, "history", lambda s, interval="1mo", **k: None)
    H = [{"fund": "SGDJ", "holding": "A", "weight": 50.0, "yahoo": "A.TO"},
         {"fund": "SGDJ", "holding": "Bad", "weight": 5.0, "yahoo": "BAD"},
         {"fund": "COPJ", "holding": "None", "weight": 5.0, "yahoo": ""}]
    rep = signals.fetch(H)
    assert {"A.TO", "BAD"} <= set(asked) and "" not in asked
    assert json.loads((tmp_path / "breadth" / "holdings.json").read_text()) == H
    assert any("1 junior-breadth symbols (BAD)" in line for line in rep)
    B = signals.load_breadth(tmp_path / "breadth")
    assert list(B["closes"]) == ["A.TO"] and B["closes"]["A.TO"].iloc[-1] == 12.5
