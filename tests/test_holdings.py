"""Per-holding figures in US$ and the fund look-through multiples."""
import math

import pandas as pd
import pytest

from minerval import fundamentals, holdings
from minerval.holdings import fund_multiples, note, per_holding, pick

from conftest import frame


def p(date, val, cur="USD"):
    return {"date": date, "cur": cur, "val": val}


def test_pick_latest_then_first_listed():
    ts = {"a": p("2026-06-30", 1), "b": p("2026-09-30", 2), "c": p("2026-09-30", 3)}
    assert pick(ts, ["a", "b", "c"])["val"] == 2                 # newest date; on a tie, the key listed first
    assert pick(ts, ["c", "b"])["val"] == 3
    assert pick(ts, ["x"]) is None


def company(price=10.0, currency="CAD", **ts):
    return {"yahoo": "X", "price": price, "currency": currency, "ts": ts}


@pytest.fixture
def run_per_holding(monkeypatch):
    """per_holding over a made-up cache and holdings list, with no corrections unless given."""
    def go(H, rows, corrections=None):
        monkeypatch.setattr(fundamentals, "load_holdings", lambda: pd.DataFrame(rows))
        corr = pd.DataFrame(corrections or [], columns=["ticker", "field", "value_usd_m", "note", "source"])
        monkeypatch.setattr(holdings, "table", lambda name: corr)
        return per_holding({"holdings": H, "fx": {"USD": 1.0, "CAD": 0.7}}).set_index("ticker")
    return go


def test_per_holding_converts_and_derives(run_per_holding):
    H = {
        "AAA CN": company(
            quarterlyOrdinarySharesNumber=p("2026-09-30", 100e6, "CAD"),
            quarterlyStockholdersEquity=p("2026-09-30", 500e6, "CAD"),
            quarterlyTotalDebt=p("2026-09-30", 100e6, "CAD"),
            quarterlyCashCashEquivalentsAndShortTermInvestments=p("2026-09-30", 300e6, "CAD"),
            trailingOperatingCashFlow=p("2026-09-30", 200e6, "CAD"),
            trailingFreeCashFlow=p("2026-09-30", 120e6, "CAD"),
            trailingEBITDA=p("2026-09-30", 250e6, "CAD")),
        "PSLV": company(price=12.0, currency="USD"),
        "NODATA": {"yahoo": None},
    }
    rows = [{"fund": "SLVR", "holding": "A", "ticker": "AAA CN", "weight_pct": 5.0},
            {"fund": "SLVR", "holding": "P", "ticker": "PSLV", "weight_pct": 30.0},
            {"fund": "SLVR", "holding": "N", "ticker": "NODATA", "weight_pct": 1.0}]
    X = run_per_holding(H, rows)
    a = X.loc["AAA CN"]
    assert a.kind == "company"
    assert a.mcap == pytest.approx(10 * 0.7 * 100e6)
    assert a.ocf == pytest.approx(140e6) and a.fcf == pytest.approx(84e6) and a.book == pytest.approx(350e6)
    assert a.ev == pytest.approx(a.mcap + 70e6 - 210e6)
    assert a.fin_date == "2026-09-30" and not a.stale and a.note == ""
    assert X.loc["PSLV"].note == "Physical metal trust, excluded"
    assert X.loc["NODATA"].note == "No price or financial data"
    assert list(X.index) == ["PSLV", "AAA CN", "NODATA"]          # by weight within the fund


def test_ocf_derived_when_reported_figure_is_stale(run_per_holding):
    H = {"BBB CN": company(
        annualOrdinarySharesNumber=p("2025-12-31", 10e6),
        annualOperatingCashFlow=p("2022-12-31", 50e6),
        trailingFreeCashFlow=p("2026-09-30", 30e6),
        trailingCapitalExpenditure=p("2026-09-30", -20e6))}
    X = run_per_holding(H, [{"fund": "SGDM", "holding": "B", "ticker": "BBB CN", "weight_pct": 1.0}])
    b = X.loc["BBB CN"]
    assert b.ocf == pytest.approx(50e6)                           # FCF - capex = 30 - (-20)
    assert b.note == "Op. cash flow corrected: Yahoo's figure was from 2022"


def test_stale_financials_are_flagged(run_per_holding):
    H = {"OLD": company(currency="USD", annualOrdinarySharesNumber=p("2024-12-31", 1e6),
                        annualFreeCashFlow=p("2024-12-31", -5e6), annualOperatingCashFlow=p("2024-12-31", -1e6))}
    X = run_per_holding(H, [{"fund": "SGDJ", "holding": "O", "ticker": "OLD", "weight_pct": 1.0}])
    assert X.loc["OLD"].stale
    assert X.loc["OLD"].note == "Negative operating cash flow"


def test_correction_replaces_the_value_and_note(run_per_holding):
    H = {"LUG CN": company(currency="USD", annualOrdinarySharesNumber=p("2026-09-30", 1e6),
                           trailingFreeCashFlow=p("2026-09-30", 5e6))}
    X = run_per_holding(H, [{"fund": "SGDM", "holding": "L", "ticker": "LUG CN", "weight_pct": 1.0}],
                        [{"ticker": "LUG CN", "field": "fcf", "value_usd_m": 1103.6, "note": "From reports",
                          "source": "x"}])
    assert X.loc["LUG CN"].fcf == pytest.approx(1103.6e6)
    assert X.loc["LUG CN"].note == "From reports"


def test_note_order():
    r = pd.Series({"kind": "other fund", "mcap": 1.0, "ocf": -1.0})
    assert note(r) == "Not a mining company, excluded"


def holding(ticker, w, mcap, kind="company", stale=False, **fin):
    base = {"book": None, "ocf": None, "fcf": None, "ebitda": None, "ev": None}
    return {"fund": "SGDM", "ticker": ticker, "weight_pct": w, "mcap": mcap, "kind": kind, "stale": stale,
            **base, **fin}


def test_fund_multiples_are_harmonic_and_count_losses():
    X = frame([
        holding("A", 60, 1000.0, fcf=100.0, ocf=200.0, ebitda=250.0, book=500.0, ev=1100.0),
        holding("B", 30, 500.0, fcf=-50.0, ocf=40.0, ebitda=60.0, book=400.0, ev=450.0),
        holding("C", 5, 100.0, stale=True, fcf=50.0),                   # stale: left out
        holding("T", 5, None, kind="physical metal"),
    ])
    X["fund"] = pd.Categorical(X.fund, ["SGDM"])
    f = fund_multiples(X).loc["SGDM"]
    y = 60 * 100 / 1000 + 30 * -50 / 500                              # weighted earnings yield
    assert f["P/fcf"] == pytest.approx(90 / y)
    assert f["P/fcf (positive only)"] == pytest.approx(60 / (60 * 100 / 1000))
    assert f["neg_fcf_%"] == 30 and f["cov_fcf_%"] == 90
    ev = 60 * 1100 / 1000 + 30 * 450 / 500
    assert f["EV/EBITDA"] == pytest.approx(ev / (60 * 250 / 1000 + 30 * 60 / 500))
    assert f["physical_metal_%"] == 5 and f["company_%"] == 95
    assert f["uncovered_company_%"] == 5
    assert f.focus == "Large gold miners"


def test_fund_multiple_is_blank_when_losses_dominate():
    X = frame([holding("A", 50, 100.0, fcf=-80.0), holding("B", 50, 100.0, fcf=10.0)])
    X["fund"] = pd.Categorical(X.fund, ["SGDM"])
    f = fund_multiples(X).loc["SGDM"]
    assert math.isnan(f["P/fcf"])
    assert f["P/fcf (positive only)"] == pytest.approx(10.0)


def test_minority_interest_is_carried_in_usd_and_zero_when_none(run_per_holding):
    H = {"AAA CN": company(quarterlyOrdinarySharesNumber=p("2026-09-30", 100e6, "CAD"),
                           annualMinorityInterest=p("2025-12-31", 50e6, "CAD"),
                           quarterlyMinorityInterest=p("2026-09-30", 80e6, "CAD")),
         "BBB CN": company(quarterlyOrdinarySharesNumber=p("2026-09-30", 100e6, "CAD"))}
    rows = [{"fund": "SGDM", "holding": "A", "ticker": "AAA CN", "weight_pct": 5.0},
            {"fund": "SGDM", "holding": "B", "ticker": "BBB CN", "weight_pct": 4.0}]
    X = run_per_holding(H, rows)
    assert X.loc["AAA CN"].minority == pytest.approx(56e6)          # the latest quarter, at 0.7 US$/CAD
    assert X.loc["BBB CN"].minority == 0.0
    assert {"quarterlyMinorityInterest", "annualMinorityInterest"} <= set(fundamentals.TYPES)
