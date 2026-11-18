"""The Yahoo client: retries, response parsing and currency conversion. No request leaves the machine."""
import pytest
import requests

from minerval import yahoo


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body

    def json(self):
        if self.body is None:
            raise ValueError("no JSON")
        return self.body


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def sleeps(monkeypatch):
    waits = []
    monkeypatch.setattr(yahoo.time, "sleep", waits.append)
    return waits


def use(monkeypatch, *responses):
    s = FakeSession(responses)
    monkeypatch.setattr(yahoo, "session", lambda: s)
    return s


def test_get_json_success(monkeypatch, sleeps):
    s = use(monkeypatch, FakeResponse(200, {"ok": 1}))
    assert yahoo.get_json("u") == {"ok": 1}
    assert s.calls == 1 and not sleeps


def test_get_json_gives_up_at_once_on_404(monkeypatch, sleeps):
    s = use(monkeypatch, FakeResponse(404))
    assert yahoo.get_json("u") is None
    assert s.calls == 1 and not sleeps


def test_get_json_retries_rate_limits_and_errors(monkeypatch, sleeps):
    s = use(monkeypatch, FakeResponse(429), requests.ConnectionError(), FakeResponse(503), FakeResponse(200, {"ok": 1}))
    assert yahoo.get_json("u") == {"ok": 1}
    assert s.calls == 4 and len(sleeps) == 3
    assert sleeps == sorted(sleeps)                             # backs off


def test_get_json_returns_none_after_last_try(monkeypatch, sleeps):
    s = use(monkeypatch, *[FakeResponse(500)] * 3)
    assert yahoo.get_json("u", tries=3) is None
    assert s.calls == 3


def chart_meta(**meta):
    return {"chart": {"result": [{"meta": meta}]}}


def test_quote(monkeypatch):
    monkeypatch.setattr(yahoo, "chart", lambda s, **p: chart_meta(
        regularMarketPrice=12.5, currency="CAD", regularMarketTime=1795363200, chartPreviousClose=12.0))
    assert yahoo.quote("X.TO") == {"price": 12.5, "currency": "CAD", "date": "2026-11-22", "prev": 12.0}


@pytest.mark.parametrize("body", [None, {"chart": {"result": []}}, chart_meta(regularMarketPrice=0)])
def test_no_quote(monkeypatch, body):
    monkeypatch.setattr(yahoo, "chart", lambda s, **p: body)
    assert yahoo.quote("GONE") is None


def test_timeseries_parsing(monkeypatch):
    body = {"timeseries": {"result": [
        {"meta": {"type": ["annualEBITDA"]}, "annualEBITDA": [
            None, {"asOfDate": "2025-12-31", "currencyCode": "USD", "reportedValue": {"raw": 5.0}}]},
        {"meta": {"type": ["annualTotalDebt"]}},                # no data for this series
    ]}}
    monkeypatch.setattr(yahoo, "get_json", lambda url, params, **k: body)
    assert yahoo.timeseries("X", ["annualEBITDA", "annualTotalDebt"], "2020-01-01") == {
        "annualEBITDA": [{"date": "2025-12-31", "cur": "USD", "val": 5.0}]}
    monkeypatch.setattr(yahoo, "get_json", lambda url, params, **k: None)
    assert yahoo.timeseries("X", ["annualEBITDA"], "2020-01-01") == {}


@pytest.mark.parametrize("code,expected", [("GBp", "GBX"), ("GBX", "GBX"), ("ZAc", "ZAC"), ("ILA", "ILA"),
                                           ("GBP", "GBP"), ("USD", "USD"), (None, None)])
def test_sheet_code(code, expected):
    assert yahoo.sheet_code(code) == expected


def test_usd_per_unit(monkeypatch):
    rates = {"GBP=X": 0.8, "IDR=X": 16000.0}                    # units per US$
    asked = []

    def quote(sym):
        asked.append(sym)
        return {"price": rates[sym]} if sym in rates else None
    monkeypatch.setattr(yahoo, "quote", quote)
    assert yahoo.usd_per_unit("USD") == (1.0, "Fixed")
    assert yahoo.usd_per_unit("GBP") == (1.25, "Yahoo GBP=X, inverted")
    rate, src = yahoo.usd_per_unit("GBp")
    assert rate == pytest.approx(0.0125) and src == "Yahoo GBP=X, inverted, /100"
    assert yahoo.usd_per_unit("IDR")[0] == pytest.approx(1 / 16000)   # full precision, not rounded to 4 places
    assert yahoo.usd_per_unit("XYZ") == (None, "Yahoo XYZ=X, inverted")
    assert "USD=X" not in asked
