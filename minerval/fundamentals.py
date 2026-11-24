"""Download financials for every fund holding (run after each earnings season).

Resolves each Sprott ticker to a Yahoo symbol, then fetches the price, the fundamentals series
used by the analysis, FX rates for every currency seen, and two years of daily metal prices.
Writes cache/fundamentals.json and cache/metals/<symbol>_daily.json.
"""
import json
import re
from datetime import date

import pandas as pd

from . import yahoo
from .config import CACHE, ROOT, ensure, settings, table

TYPES = [
    # latest values used for valuation
    "trailingOperatingCashFlow", "annualOperatingCashFlow",
    "trailingCashFlowFromContinuingOperatingActivities", "annualCashFlowFromContinuingOperatingActivities",
    "trailingFreeCashFlow", "annualFreeCashFlow",
    "trailingCapitalExpenditure", "annualCapitalExpenditure",
    "trailingEBITDA", "annualEBITDA",
    "trailingTotalRevenue", "annualTotalRevenue",
    "quarterlyStockholdersEquity", "annualStockholdersEquity",
    "quarterlyTotalDebt", "annualTotalDebt",
    "quarterlyMinorityInterest", "annualMinorityInterest",        # partners' stakes in consolidated mines
    "quarterlyCashCashEquivalentsAndShortTermInvestments", "annualCashCashEquivalentsAndShortTermInvestments",
    "quarterlyCashAndCashEquivalents", "annualCashAndCashEquivalents",
    # share counts (history is used for dilution) and working capital
    "quarterlyOrdinarySharesNumber", "annualOrdinarySharesNumber",
    "quarterlyShareIssued", "annualShareIssued",
    "quarterlyCurrentAssets", "annualCurrentAssets",
    "quarterlyCurrentLiabilities", "annualCurrentLiabilities",
    # the screen's developer measures (G&A against all spending; SG&A where G&A isn't reported)
    "annualGeneralAndAdministrativeExpense", "annualSellingGeneralAndAdministration",
]
STOP = {"ltd", "inc", "corp", "co", "the", "plc", "sa", "sab", "de", "cv", "nl", "pt", "ab", "saa", "corporation",
        "limited", "mining", "resources", "metals", "gold", "silver", "copper", "minerals", "mines", "and", "&", "us"}


def load_holdings() -> pd.DataFrame:
    return pd.read_csv(ROOT / settings()["holdings"]["file"])


def candidates(ticker: str, overrides: dict) -> list[str]:
    """Yahoo symbols to try for a Sprott ticker such as 'AEM CN' or '340 HK'."""
    if ticker in overrides:
        return [overrides[ticker]]
    if " " not in ticker:
        return [ticker.replace(".", "-")]
    base, ex = ticker.split(" ")
    if ex == "HK":
        return [base.zfill(4) + ".HK"]
    return [base.replace(".", "-") + s for s in settings()["yahoo"]["suffixes"].get(ex, [])]


def _tokens(s: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in STOP and len(t) > 1}


def resolve(ticker: str, name: str, overrides: dict) -> dict:
    """Try each candidate; take the first whose name shares a word with Sprott's name."""
    tried, best = [], None
    for y in candidates(ticker, overrides):
        tried.append(y)
        m = yahoo.meta(y)
        if not m:
            continue
        yname = m.get("longName") or m.get("shortName") or ""
        cand = {"yahoo": y, "yname": yname, "currency": m.get("currency"), "price": m["regularMarketPrice"],
                "time": m.get("regularMarketTime"), "match": bool(_tokens(name) & _tokens(yname)) or ticker in overrides}
        if cand["match"]:
            best = cand
            break
        best = best or cand
    return {"name": name, "tried": tried, **(best or {})}


def run(holdings_file=None):
    S = settings()
    ensure(CACHE / "metals")
    h = pd.read_csv(holdings_file) if holdings_file else load_holdings()
    names = dict(zip(h.ticker, h.holding))
    ov = dict(zip(*[table("symbol_overrides.csv")[c] for c in ("ticker", "yahoo")]))
    res = yahoo.pmap(lambda t: resolve(t, names[t], ov), list(names))
    start = S["yahoo"]["history_start"]
    series = yahoo.pmap(lambda t: yahoo.timeseries(res[t]["yahoo"], TYPES, start) if res[t].get("yahoo") else {},
                        list(names))
    for t in res:
        res[t]["series"] = series[t]
    curs = {v.get("currency") for v in res.values() if v.get("currency")}
    curs |= {p["cur"] for v in res.values() for pts in v["series"].values() for p in pts if p.get("cur")}
    fx = {c: r for c, (r, _) in yahoo.pmap(yahoo.usd_per_unit, sorted(curs)).items() if r}
    out = {"fetched": date.today().isoformat(), "fx": fx, "holdings": res}
    (CACHE / "fundamentals.json").write_text(json.dumps(out, indent=1))
    for metal, sym in S["yahoo"]["metals"].items():
        j = yahoo.chart(sym, range="2y", interval="1d")
        if j:
            (CACHE / "metals" / f"{sym}_daily.json").write_text(json.dumps(j))
    found = sum(1 for v in res.values() if v.get("yahoo"))
    unmatched = [f"{t} -> {v['yahoo']} ({v['yname']})" for t, v in res.items() if v.get("yahoo") and not v["match"]]
    lines = [f"Resolved {found} of {len(res)} holdings to Yahoo symbols.",
             "Not found: " + ", ".join(sorted(t for t, v in res.items() if not v.get("yahoo")))]
    if unmatched:
        lines.append("Found, but the name didn't match (check, and add to config/symbol_overrides.csv if right): "
                     + "; ".join(unmatched))
    missing_fx = sorted(curs - set(fx))
    if missing_fx:
        lines.append("No FX rate for: " + ", ".join(missing_fx))
    return lines
