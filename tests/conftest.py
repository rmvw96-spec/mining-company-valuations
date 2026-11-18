"""Shared fixtures. Every test runs offline: Yahoo and the Google Sheet are replaced by fakes."""
import pandas as pd
import pytest

from minerval import yahoo


class FakeMetals:
    """Stands in for price_model.Metals: fixed spot prices and a fixed 12-month average for each metal."""

    def __init__(self, spot=None, avg=None, scenarios=None):
        self.spot = spot or {"gold": 4000.0, "silver": 50.0, "copper": 5.0}
        self.avg = avg or dict(self.spot)
        self.scenarios = scenarios or {}

    def average(self, metal, end):
        return self.avg[metal]

    def scenario(self, name):
        return dict(self.spot) if name == "Today" else dict(self.scenarios[name])


@pytest.fixture
def metals():
    return FakeMetals


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if a test reaches Yahoo, and run pmap serially so tests are deterministic."""
    def refuse(*a, **k):
        raise AssertionError("a test tried to reach the network")
    monkeypatch.setattr(yahoo, "session", refuse)
    monkeypatch.setattr(yahoo, "pmap", lambda fn, items, workers=None: {i: fn(i) for i in items})


def frame(rows, **defaults):
    """A DataFrame from dicts, with defaults filled into every row."""
    return pd.DataFrame([{**defaults, **r} for r in rows])
