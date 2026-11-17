"""Small client for the Yahoo Finance endpoints that work without a login.

Works:   /v8/finance/chart (prices, history) and /ws/fundamentals-timeseries (financials).
Blocked: /v10/finance/quoteSummary needs a "crumb" cookie and is refused, so it isn't used.
These endpoints are unofficial: Yahoo can change or rate-limit them at any time.
"""
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

from .config import settings

BASE = "https://query1.finance.yahoo.com"
_session = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = settings()["yahoo"]["user_agent"]
    return _session


def get_json(url: str, params: dict | None = None, tries: int = 5, timeout: int = 30):
    """GET with retries and backoff. Returns parsed JSON, or None after the last failure."""
    for i in range(tries):
        try:
            r = session().get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code not in (429,) and r.status_code < 500:
                return None                     # 404 and similar: retrying won't help
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 ** i + random.random())
    return None


def pmap(fn, items, workers: int | None = None) -> dict:
    """Run fn over items in parallel; returns {item: result}."""
    items = list(items)
    with ThreadPoolExecutor(workers or settings()["yahoo"]["workers"]) as ex:
        return dict(zip(items, ex.map(fn, items)))


def chart(symbol: str, **params):
    return get_json(f"{BASE}/v8/finance/chart/{symbol}", params)


def meta(symbol: str):
    """Quote metadata (last price, currency, time, name), or None if Yahoo has no price."""
    j = chart(symbol, range="5d", interval="1d")
    try:
        m = j["chart"]["result"][0]["meta"]
    except (TypeError, KeyError, IndexError):
        return None
    return m if m.get("regularMarketPrice") else None


def quote(symbol: str):
    """{"price", "currency", "date", "prev"} for the latest trade; prev is the close before the 5-day window."""
    m = meta(symbol)
    if not m:
        return None
    return {"price": m["regularMarketPrice"], "currency": m.get("currency"),
            "date": datetime.fromtimestamp(m["regularMarketTime"], timezone.utc).strftime("%Y-%m-%d"),
            "prev": m.get("chartPreviousClose")}


def history(symbol: str, interval: str = "1mo", **params):
    """Full price history (adjusted closes included) from the first available date."""
    p = {"period1": 0, "period2": int(time.time()), "interval": interval, "events": "div,split"}
    p.update(params)
    return get_json(f"{BASE}/v8/finance/chart/{symbol}", p, timeout=40)


def timeseries(symbol: str, types: list[str], start: str) -> dict:
    """Fundamentals series: {type: [{"date", "cur", "val"}, ...]} oldest first."""
    p1 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    j = get_json(f"{BASE}/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}",
                 {"type": ",".join(types), "period1": p1, "period2": int(time.time())})
    out = {}
    try:
        results = j["timeseries"]["result"]
    except (TypeError, KeyError):
        return out
    for res in results:
        k = res["meta"]["type"][0]
        pts = [{"date": p["asOfDate"], "cur": p.get("currencyCode"), "val": p["reportedValue"]["raw"]}
               for p in (res.get(k) or []) if p]
        if pts:
            out[k] = pts
    return out


def minor_unit(code: str):
    """For a minor-unit currency (Yahoo's GBp or the Sheet's GBX): (sheet code, major code, units per major)."""
    for yc, v in settings()["yahoo"]["minor_units"].items():
        if code in (yc, v["code"]):
            return v["code"], v["major"], v["per_major"]
    return None


def sheet_code(code: str | None) -> str | None:
    """Yahoo currency code -> the code used in the Sheet's FX table (GBp -> GBX, ZAc -> ZAC)."""
    m = minor_unit(code) if code else None
    return m[0] if m else code


def usd_per_unit(code: str):
    """US$ per one unit of a currency (minor units included), at full precision.

    Yahoo rounds "XXXUSD=X" quotes to 4 decimals (IDR would be ~80% off), so this fetches
    "XXX=X" (units per US$) and inverts it.
    Returns (rate, source) or (None, source) when Yahoo has no quote.
    """
    if code == "USD":
        return 1.0, "Fixed"
    m = minor_unit(code)
    major, div = (m[1], m[2]) if m else (code, 1)
    q = quote(f"{major}=X")
    src = f"Yahoo {major}=X, inverted" + (f", /{div}" if div != 1 else "")
    if not q or not q["price"]:
        return None, src
    return 1.0 / q["price"] / div, src
