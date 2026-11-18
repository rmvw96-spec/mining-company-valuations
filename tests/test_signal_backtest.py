"""Signal backtest: no lookahead, the dated AISC, forward returns, independent windows and the report. Synthetic data."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from minerval import signal_backtest as bt
from minerval.config import settings
from minerval.signals import aisc_at, compute


def series(values, start="2000-08-01"):
    idx = pd.bdate_range(start=start, periods=len(values))
    return pd.Series(np.asarray(values, dtype=float), index=idx)


def synthetic(n=6000, seed=1):
    """Random walks for every signal input, from Aug 2000."""
    rng = np.random.default_rng(seed)
    S = settings()["signals"]
    walk = lambda lvl: series(lvl * np.exp(np.cumsum(rng.normal(0, 0.01, n))))  # noqa: E731
    daily = {s: walk(100.0) for s in S["daily"]}
    daily["GC=F"], daily["SI=F"] = walk(1500.0), walk(20.0)
    monthly = {s: daily[s] for s in S["monthly"]}
    ry = series(1.0 + np.cumsum(rng.normal(0, 0.03, n)))
    return {"daily": daily, "monthly": monthly, "real_yield": ry}


def test_no_lookahead_a_spike_after_the_date_changes_nothing():
    data = synthetic()
    dates = bt.month_ends(data["daily"]["GC=F"], "2010-01-01")[:24]
    before = bt.signal_table(data, dates)
    cut = dates[12]
    for s in list(data["daily"].values()) + [data["real_yield"]]:
        s[s.index > cut] *= 3                      # monthly series are the same objects: spiked too
    after = bt.signal_table(data, dates)
    a, b = before.loc[:cut].drop(columns=[c for c in before if c.endswith("__status")]), \
        after.loc[:cut].drop(columns=[c for c in after if c.endswith("__status")])
    pd.testing.assert_frame_equal(a.astype(float), b.astype(float))
    assert not before.loc[dates[13]:].equals(after.loc[dates[13]:])


def test_aisc_used_is_the_latest_published_by_the_date():
    assert aisc_at(date(2021, 7, 28)) is None                    # the first figure was published Jul 29, 2021
    assert aisc_at(date(2021, 7, 29))["value"] == 1048
    a = aisc_at(date(2024, 3, 15))                               # Q3'23 published Jan 31; Q4'23 not until Apr 30
    assert (a["quarter"], a["value"]) == ("2023Q3", 1343)
    assert aisc_at(date(2026, 11, 2))["quarter"] == "2026Q1"
    assert aisc_at(date(2026, 11, 3))["quarter"] == "2026Q2"


def test_compute_uses_the_dated_aisc_and_leaves_the_margin_blank_before_it():
    data = synthetic()
    gold = data["daily"]["GC=F"]
    early = gold.index[gold.index <= "2015-06-30"][-1]
    late = gold.index[gold.index <= "2023-06-30"][-1]          # Q4'22 (1,279) published May 5, 2023
    from minerval.history import truncate
    m = {r["key"]: r["value"] for r in compute(truncate(data, early), early.date())}
    assert m["aisc_margin"] is None
    m = {r["key"]: r["value"] for r in compute(truncate(data, late), late.date())}
    assert m["aisc_margin"] == pytest.approx(gold[late] - 1279)


def test_forward_returns_and_differences():
    idx = pd.date_range("2020-01-31", periods=24, freq="ME")
    a = pd.Series(100 * 1.01 ** np.arange(24), index=idx)          # +1% a month
    b = pd.Series(100.0, index=idx)
    s = {"A": a, "B": b}
    f = bt.forward(s, "A", idx, 3)
    assert f.iloc[0] == pytest.approx(1.01 ** 3 - 1)
    assert f.iloc[-3:].isna().all()                                 # no future yet
    d = bt.forward(s, "A-B", idx, 12)
    assert d.iloc[0] == pytest.approx(1.01 ** 12 - 1)
    assert bt.forward(s, "C", idx, 3).isna().all()


def test_non_overlapping_windows_and_the_too_few_flag():
    idx = pd.date_range("2000-01-31", periods=120, freq="ME")
    assert len(bt.non_overlapping(idx, 12)) == 10
    assert len(bt.non_overlapping(idx, 3)) == 40
    st = bt.stats(pd.Series(np.ones(120), index=idx), 12)
    assert st["months"] == 120 and st["independent"] == 10 and st["too_few"]
    assert not bt.stats(pd.Series(np.ones(120), index=idx), 3)["too_few"]


def test_bucket_stats_with_a_baseline():
    idx = pd.date_range("2000-01-31", periods=60, freq="ME")
    statuses = pd.Series(["Lean in" if i % 2 else "Wait" for i in range(60)], index=idx)
    statuses.iloc[0] = ""                                            # no status: left out of every row
    outcome = pd.Series([0.05 if i % 2 else -0.05 for i in range(60)], index=idx)
    rows = {r["bucket"]: r for r in bt.bucket_stats(statuses, outcome, 1)}
    assert set(rows) == {"Lean in", "Wait", "All months"}
    assert rows["Lean in"]["mean"] == pytest.approx(0.05) and rows["Lean in"]["hit_rate"] == 1.0
    assert rows["Wait"]["months"] == 29 and rows["All months"]["months"] == 59
    assert rows["Lean in"]["score"] is None                          # no variance: no score


def test_tax_loss_returns_from_late_year_to_february():
    idx = pd.bdate_range("2010-01-01", "2013-12-31")
    s = pd.Series(100.0, index=idx)
    s[(idx.month <= 2)] = 110.0                                     # Jan-Feb 10% above the rest of the year
    out = bt.tax_loss({"X": s}, "X")
    nov = out["Nov-end to Feb-end"]
    assert nov["years"] == 3 and nov["mean"] == pytest.approx(0.10) and nov["too_few"]


def test_aisc_share_buckets():
    assert bt.aisc_share_status(0.5, 0.45, 0.30) == "Wide margin"
    assert bt.aisc_share_status(0.30, 0.45, 0.30) == "Thin margin"
    assert bt.aisc_share_status(0.4, 0.45, 0.30) == "Middling margin"
    assert bt.aisc_share_status(None, 0.45, 0.30) == ""


def test_sweep_settings_name_real_thresholds():
    C = settings()["signal_backtest"]
    th = settings()["signals"]["thresholds"]
    keys = {t.key for t in bt.tests()}
    for key, spec in C["sweep"].items():
        assert key in keys and spec["threshold"] in ("g", "h")
        cur = C["aisc_margin_share"] if key == "aisc_margin_share" else th[key]
        assert cur[0 if spec["threshold"] == "g" else 1] in spec["values"], key   # the current value is swept


def test_run_writes_the_report_offline(tmp_path, monkeypatch):
    data = synthetic()
    total = dict(data["daily"])
    for s in ("RGLD", "FNV", "WPM"):
        total[s] = data["daily"]["GDX"] * 1.0
    monkeypatch.setattr(bt, "DEST", tmp_path)
    monkeypatch.setattr(bt, "load", lambda: (data, total))
    monkeypatch.setattr(bt, "fetch", lambda: pytest.fail("no download expected"))
    monkeypatch.setattr(bt, "BT_CACHE", tmp_path)
    (tmp_path / "GC_F_1d_max.json").write_text("{}")
    rep = bt.run()
    assert "month-ends" in rep[-1]
    text = (tmp_path / "report.txt").read_text()
    for key in ("gold_silver_ratio", "spy_drawdown", "junior_timing", "Tax-loss window", "Threshold sweep",
                "Not tested (no history)"):
        assert key in text
    O = pd.read_csv(tmp_path / "outcomes.csv")
    assert {"signal", "outcome", "horizon_months", "bucket", "months", "independent", "too_few"} <= set(O.columns)
    H = pd.read_csv(tmp_path / "signals_history.csv")
    assert "gold_silver_ratio__status" in H.columns and len(H) > 100
