"""Market signals for each tier: when the framework says to lean in (the Signals tab).

fetch()    downloads daily and monthly closes from Yahoo and the 10-year real yield (DFII10) from FRED
           into cache/signals/.
compute()  is a pure function of those series, the date, the thresholds and a few inputs: it returns each
           signal's value and status, using the same rules as the Sheet's status formulas (built here too,
           by status_formula, so the two can't drift apart).
run()      fetches, computes, writes values (E) and dates (F) to the Signals tab by key, reads the Sheet's
           statuses back and reports any that differ from Python's. Writes out/signals/.

These are signals from a framework, not advice.
"""
import io
import json
import os
from dataclasses import dataclass
from datetime import date

from functools import lru_cache

import pandas as pd

from . import yahoo
from .config import CACHE, DERIVED, OUT, RESEARCH, ensure, settings
from .sheets import blocks_by_row, col_to_num

SIG_CACHE = CACHE / "signals"


@dataclass(frozen=True)
class Signal:
    key: str
    tier: str
    label: str
    unit: str
    kind: str                   # the status rule: see status() and status_formula()
    texts: tuple = ()
    note: str = ""              # "What the framework says"
    source: str = ""
    fmt: str = "0.00"           # number format for E (and G:H)
    formula: bool = False       # E is a Sheet formula: Python never writes it


def _vs_diesel(metal):
    m = metal.capitalize()
    return Signal(f"{metal}_vs_diesel_12m", f"Producers ({metal})", f"{m} 12-month change minus diesel's",
                  "% points", "high_low",
                  (f"{m} outpacing fuel costs: margins widening", f"Fuel costs outpacing {metal}: margin squeeze",
                   "Neutral"),
                  "Margins widen when the metal rises faster than the costs of mining it; diesel is a large one.",
                  "Yahoo, COMEX futures and NYMEX heating oil (HO=F, the US diesel benchmark)", "0.0%")


def _pctile(key, etf, metal):
    return Signal(key, f"Producers ({metal})", f"{etf} ÷ {metal}: percentile of the last 10 years", "percentile",
                  "low_high", (f"Miners cheap against {metal}", f"Miners expensive against {metal}", "Mid-range"),
                  "Buy the miners when they are cheap against their metal, not after they have outrun it.",
                  "Yahoo, month-end closes; this month uses the latest price", "0")


def _fcf(fund):
    return Signal(f"fcf_yield_{fund}", "Producers", f"{fund} free-cash-flow yield (weighted)", "% a year",
                  "high_low", ("High free-cash-flow yield", "Low free-cash-flow yield", "Middling"),
                  "Producers are cheap when they earn a high free-cash-flow yield at today's prices.",
                  "Holdings tab: weight × free cash flow ÷ market value, companies only", "0.0%")


def _trend(key, name):
    return Signal(key, "Juniors", f"{name} against its 200-day average", "% above (below)", "trend",
                  ("Above its 200-day average", "Below its 200-day average"),
                  "Add to juniors once the uptrend is confirmed.", "Yahoo, daily closes", "0.0%")


SIGNALS = [
    Signal("gold_silver_ratio", "Physical metal", "Gold/silver ratio", "oz of silver per oz of gold", "high_low",
           ("Silver cheap against gold: favours silver", "Gold cheap against silver: favours gold", "Neutral"),
           "A high ratio favours buying silver; a low one favours gold.", "Yahoo, COMEX futures (GC=F ÷ SI=F)", "0.0"),
    Signal("gold_silver_ratio_pctile", "Physical metal", "Gold/silver ratio: percentile since Aug 2000", "percentile",
           "info", (), "Where today's ratio sits in its own history.", "Yahoo, month-end closes", "0"),
    Signal("real_yield_10y", "Physical metal", "10-year real yield (TIPS)", "%", "real_yield",
           ("Peaked and falling: the framework's signal to buy bullion more heavily",
            "Rising: keep accumulating steadily", "Flat: keep accumulating steadily"),
           "Gold does best when real yields peak and turn down. Threshold 1: drop from the 12-month high "
           "(% points); threshold 2: 3-month rise counted as rising.", "FRED DFII10", "0.00"),
    Signal("real_yield_12m_high", "Physical metal", "10-year real yield: 12-month high", "%", "info", (), "",
           "FRED DFII10", "0.00"),
    Signal("real_yield_3m_change", "Physical metal", "10-year real yield: change over ~3 months", "% points",
           "info", (), "", "FRED DFII10", "0.00"),
    Signal("usd_12m", "Physical metal", "US dollar index, 12-month change", "% change", "low_high",
           ("Dollar weakening: supportive for bullion", "Dollar strengthening: a headwind", "Neutral"),
           "A falling dollar lifts metal prices in US dollars.", "Yahoo, DX-Y.NYB", "0.0%"),
    Signal("spy_drawdown", "Physical metal and royalty", "S&P 500 (SPY) below its 12-month high", "% from high",
           "drawdown", ("Stock-market panic: framework's moment for bullion and royalties",
                        "Market pullback: watch royalty companies", "Calm"),
           "Panics are when the framework buys bullion and royalty companies.", "Yahoo, SPY", "0.0%"),
    Signal("royalty_pnav_median", "Royalty", "Royalty companies: median independent P/NAV", "× NAV", "band",
           ("Buy zone", "Normal range", "Rich"),
           "Buy royalty companies at 1.1-1.4× NAV; 1.5-2.2× is their normal range. Uses the independent model's "
           "NAV per share (PNAV inputs R), refreshed by hand.", "PNAV inputs AJ (formula)", "0.00", formula=True),
    _vs_diesel("gold"), _vs_diesel("copper"), _vs_diesel("silver"),
    Signal("gold_12m", "Producers", "Gold, 12-month change", "% change", "info", (), "", "Yahoo, GC=F", "0.0%"),
    Signal("silver_12m", "Producers", "Silver, 12-month change", "% change", "info", (), "", "Yahoo, SI=F", "0.0%"),
    Signal("copper_12m", "Producers", "Copper, 12-month change", "% change", "info", (), "", "Yahoo, HG=F", "0.0%"),
    Signal("diesel_12m", "Producers", "Diesel (heating oil), 12-month change", "% change", "info", (), "",
           "Yahoo, HO=F", "0.0%"),
    Signal("crude_12m", "Producers", "Crude oil, 12-month change", "% change", "info", (), "", "Yahoo, CL=F", "0.0%"),
    Signal("aisc_margin", "Producers (gold)", "Gold price minus industry all-in sustaining cost", "$/oz", "aisc", (),
           "The industry's margin at today's gold price (AISC is the industry_aisc input below).",
           "Yahoo GC=F; AISC input", "#,##0"),
    _pctile("gdx_gold_pctile10y", "GDX", "gold"),
    _pctile("sil_silver_pctile10y", "SIL", "silver"),
    _pctile("copx_copper_pctile10y", "COPX", "copper"),
    _fcf("SGDM"), _fcf("SGDJ"), _fcf("COPP"), _fcf("SLVR"),
    Signal("tax_loss_window", "Juniors", "In the tax-loss selling window", "1 = yes", "window",
           ("In the tax-loss selling window", "Outside the window"),
           "Juniors are sold for tax losses late in the year: a time to buy them cheaply.", "Calendar", "0"),
    _trend("uptrend_gold", "Gold"), _trend("uptrend_gdx", "GDX (gold miners)"),
    _trend("uptrend_silver", "Silver"), _trend("uptrend_sil", "SIL (silver miners)"),
    Signal("junior_timing", "Juniors", "Junior buy conditions met (tax-loss window; gold and GDX uptrend)",
           "of 2", "junior",
           ("Both buy conditions met", "Tax-loss window open; uptrend not confirmed", "Uptrend confirmed", "Wait"),
           "Buy juniors in the tax-loss window, or once gold and the miners are in a confirmed uptrend.",
           "Signals rows above (formula)", "0", formula=True),
    Signal("gdxj_drawdown", "Juniors", "GDXJ below its 12-month high", "% from high", "info", (),
           "Depth of the junior gold sell-off.", "Yahoo, GDXJ", "0.0%"),
    Signal("silj_drawdown", "Juniors", "SILJ below its 12-month high", "% from high", "info", (),
           "Depth of the junior silver sell-off.", "Yahoo, SILJ", "0.0%"),
]
BY_KEY = {s.key: s for s in SIGNALS}


# ---------- series ----------

def closes(chart) -> pd.Series:
    """Closes from a Yahoo chart response, by date."""
    r = chart["chart"]["result"][0]
    q = r["indicators"]["quote"][0]["close"]
    s = pd.Series(q, index=pd.to_datetime(r["timestamp"], unit="s").normalize(), dtype=float).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def parse_fred(text: str) -> pd.Series:
    """FRED's graph CSV (observation_date,SERIES); holidays are "." and are skipped."""
    d = pd.read_csv(io.StringIO(text), dtype=str)
    v = pd.to_numeric(d.iloc[:, 1], errors="coerce")
    return pd.Series(v.values, index=pd.to_datetime(d.iloc[:, 0])).dropna().sort_index()


def _cache_name(sym, interval):
    return SIG_CACHE / f"{sym.replace('=', '_').replace('^', '_')}_{interval}.json"


def fetch() -> list[str]:
    """Download everything compute() needs into cache/signals/. Returns lines naming what failed."""
    S = settings()["signals"]
    ensure(SIG_CACHE)
    failed = []
    daily = yahoo.pmap(lambda s: yahoo.chart(s, range=S.get("daily_range", "2y"), interval="1d"), S["daily"])
    monthly = yahoo.pmap(lambda s: yahoo.history(s, "1mo"), S["monthly"])
    for interval, got in (("1d", daily), ("1mo", monthly)):
        for sym, j in got.items():
            if j and (j.get("chart") or {}).get("result"):
                _cache_name(sym, interval).write_text(json.dumps(j))
            else:
                failed.append(f"{sym} ({interval})")
    txt = fred_csv(S)
    if txt and txt.startswith("observation_date"):
        (SIG_CACHE / f"{S['fred_series']}.csv").write_text(txt)
    else:
        failed.append(f"FRED {S['fred_series']}")
    return [f"Download failed (cached copy used if there is one): {', '.join(failed)}"] if failed else []


def fred_csv(S) -> str | None:
    """The FRED series as graph CSV text. With FRED_API_KEY set, FRED's API is tried first (it answers
    from cloud servers, where the graph CSV sometimes doesn't); its JSON is turned into the same CSV."""
    key = os.environ.get("FRED_API_KEY")
    if key:
        j = yahoo.get_json(S["fred_api_url"], {"series_id": S["fred_series"], "api_key": key, "file_type": "json"},
                           tries=3)
        obs = (j or {}).get("observations")
        if obs:
            return "observation_date," + S["fred_series"] + "\n" + "".join(
                f"{o['date']},{o['value']}\n" for o in obs)
    return yahoo.get_text(S["fred_url"].format(series=S["fred_series"]))


def load_cache() -> dict:
    S = settings()["signals"]
    out = {"daily": {}, "monthly": {}, "real_yield": None}
    for interval, key in (("1d", "daily"), ("1mo", "monthly")):
        for sym in S[key]:
            f = _cache_name(sym, interval)
            if f.exists():
                out[key][sym] = closes(json.loads(f.read_text()))
    f = SIG_CACHE / f"{S['fred_series']}.csv"
    if f.exists():
        out["real_yield"] = parse_fred(f.read_text())
    return out


# ---------- calculations ----------

def _year_back(s: pd.Series) -> pd.Series:
    return s[s.index > s.index[-1] - pd.DateOffset(years=1)]


def change_12m(s):
    """Latest close against the last close at least 12 months earlier."""
    if s is None or s.empty:
        return None
    base = s[s.index <= s.index[-1] - pd.DateOffset(years=1)]
    return None if base.empty else float(s.iloc[-1] / base.iloc[-1] - 1)


def high_12m(s):
    return None if s is None or s.empty else float(_year_back(s).max())


def drawdown(s):
    return None if s is None or s.empty else float(s.iloc[-1] / _year_back(s).max() - 1)


def vs_average(s, days):
    if s is None or len(s) < days:
        return None
    return float(s.iloc[-1] / s.iloc[-days:].mean() - 1)


def percentile(x, hist) -> float | None:
    """Share of the history at or below x, 0-100."""
    hist = pd.Series(hist).dropna()
    return None if x is None or hist.empty else float(100 * (hist <= x).mean())


def month_end_ratio(num: pd.Series, den: pd.Series, before: pd.Period, since: pd.Period | None = None):
    """Month-end num ÷ den for the months before `before` (the current month uses the latest quote instead)."""
    a = num.groupby(num.index.to_period("M")).last()
    b = den.groupby(den.index.to_period("M")).last()
    r = (a / b).dropna()
    r = r[r.index < before]
    return r[r.index >= since] if since is not None else r


def in_window(d: date, window) -> bool:
    start, end = (date(d.year, *map(int, w.split("-"))) for w in window)
    return start <= d <= end if start <= end else (d >= start or d <= end)


def fcf_yield(rows, fund, exclude) -> float | None:
    """Σ(weight × FCF ÷ market cap) ÷ Σ weight over a fund's companies with a market cap and an FCF figure.

    rows: dicts with fund, ticker, weight, mcap, fcf (as read from the Holdings tab)."""
    num = den = 0.0
    for r in rows:
        if r["fund"] != fund or r["ticker"] in exclude:
            continue
        w, m, f = r["weight"], r["mcap"], r["fcf"]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (w, m, f)) and m > 0:
            num += w * f / m
            den += w
    return num / den if den else None


@lru_cache(maxsize=1)
def industry_aisc_table() -> pd.DataFrame:
    """data/research/industry_aisc.csv: the World Gold Council's quarterly industry AISC, with publication dates."""
    T = pd.read_csv(RESEARCH / "industry_aisc.csv", dtype={"quarter": str})
    T["published"] = pd.to_datetime(T["published"])
    return T.sort_values("published").reset_index(drop=True)


def aisc_at(d) -> dict | None:
    """The latest industry AISC that was public on date d: {"value", "quarter", "published", "source"}, or None.
    A backtest on a past date uses the figure known then, not a later one."""
    T = industry_aisc_table()
    T = T[T["published"] <= pd.Timestamp(d)]
    if T.empty:
        return None
    r = T.iloc[-1]
    return {"value": float(r["aisc_usd_oz"]), "quarter": r["quarter"],
            "published": r["published"].date().isoformat(), "source": r["source"]}


def aisc_label(a: dict) -> str:
    """Column F text for the industry_aisc input row, e.g. "2026Q2, published 2026-11-03 (World Gold Council)"."""
    return f"{a['quarter']}, published {a['published']} ({a['source'].split(',')[0]})"


def royalty_pnavs_from_sheet(sheet) -> list[float]:
    """Independent P/NAVs of the royalty/streaming rows on PNAV inputs, picked as the Sheet's median formula
    picks them (peer group "Royalty/streaming", a NAV per share). Works where data/derived/ doesn't exist."""
    S = settings()["sheet"]
    P, a, b = S["pnav_inputs"], S["pnav_first_row"], S["pnav_last_row"]
    rows = sheet.read(S["pnav_inputs_tab"], f"A{a}:{P['peer_group']}{b}")
    ip, pg, nav = (col_to_num(P[k]) - 1 for k in ("independent_pnav", "peer_group", "nav_per_share"))
    out = []
    for r in rows:
        r = list(r) + [""] * (pg + 1)
        if str(r[pg]).strip() == "Royalty/streaming" and r[nav] not in ("", None) and _num(r[ip]):
            out.append(float(r[ip]))
    return out


def royalty_pnavs_from_derived() -> list[float]:
    """Independent P/NAVs of royalty/streaming companies (basis OCF) from data/derived/pnav.csv."""
    p = DERIVED / "pnav.csv"
    if not p.exists():
        return []
    T = pd.read_csv(p)
    m = T[(T.basis == "OCF") & T.model_nav_per_share_usd.notna()]
    return [float(v) for v in m["independent or study pnav"].dropna()]


# ---------- status rules (Python) and the matching Sheet formulas ----------

def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def status(sig: Signal, v, g, h, ctx: dict) -> str:
    """The status text for a value, as the Sheet's formula in column I computes it."""
    if not _num(v):
        return ""
    t, k = sig.texts, sig.kind
    if k == "info":
        return "Info"
    if k == "high_low":
        return t[0] if v >= g else t[1] if v <= h else t[2]
    if k == "low_high":
        return t[0] if v <= g else t[1] if v >= h else t[2]
    if k == "drawdown":
        return t[0] if v <= h else t[1] if v <= g else t[2]
    if k == "band":
        return t[0] if v <= g else t[1] if v <= h else t[2]
    if k == "real_yield":
        peak, chg = ctx.get("real_yield_12m_high"), ctx.get("real_yield_3m_change")
        if not (_num(peak) and _num(chg)):
            return ""
        return t[0] if v <= peak - g and chg < 0 else t[1] if chg >= h else t[2]
    if k == "window":
        return t[0] if v == 1 else t[1]
    if k == "trend":
        return t[0] if v > 0 else t[1]
    if k == "aisc":
        aisc = ctx.get("industry_aisc")
        if not _num(aisc) or v + aisc == 0:
            return ""
        return f"Margin ${v:,.0f}/oz ({v / (v + aisc):.0%} of the gold price)"
    if k == "junior":
        w, ug, ux = (ctx.get(x) for x in ("tax_loss_window", "uptrend_gold", "uptrend_gdx"))
        if not all(_num(x) for x in (w, ug, ux)):
            return ""
        up = ug > 0 and ux > 0
        return t[0] if w == 1 and up else t[1] if w == 1 else t[2] if up else t[3]
    raise ValueError(sig.kind)


def look(key: str, col: str = "E") -> str:
    """Sheet expression: the value in `col` of the Signals row whose key (column A) is `key`."""
    return f'XLOOKUP("{key}",$A:$A,${col}:${col},"")'


def _q(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def status_formula(sig: Signal, r: int) -> str:
    """The formula for column I on row r: the same rule as status()."""
    E, G, H = f"E{r}", f"G{r}", f"H{r}"
    t = [_q(x) for x in sig.texts]
    k = sig.kind
    if k == "info":
        body = '"Info"'
    elif k == "high_low":
        body = f"IF({E}>={G},{t[0]},IF({E}<={H},{t[1]},{t[2]}))"
    elif k == "low_high":
        body = f"IF({E}<={G},{t[0]},IF({E}>={H},{t[1]},{t[2]}))"
    elif k == "drawdown":
        body = f"IF({E}<={H},{t[0]},IF({E}<={G},{t[1]},{t[2]}))"
    elif k == "band":
        body = f"IF({E}<={G},{t[0]},IF({E}<={H},{t[1]},{t[2]}))"
    elif k == "real_yield":
        body = (f"LET(peak,{look('real_yield_12m_high')},change,{look('real_yield_3m_change')},"
                f'IF(OR(peak="",change=""),"",IF(AND({E}<=peak-{G},change<0),{t[0]},'
                f"IF(change>={H},{t[1]},{t[2]}))))")
    elif k == "window":
        body = f"IF({E}=1,{t[0]},{t[1]})"
    elif k == "trend":
        body = f"IF({E}>0,{t[0]},{t[1]})"
    elif k == "aisc":
        body = (f"LET(aisc,{look('industry_aisc')},IF(aisc=\"\",\"\",\"Margin $\"&TEXT({E},\"#,##0\")&\"/oz (\"&"
                f"TEXT({E}/({E}+aisc),\"0%\")&\" of the gold price)\"))")
    elif k == "junior":
        body = (f"LET(window,{look('tax_loss_window')},gold_up,{look('uptrend_gold')},gdx_up,{look('uptrend_gdx')},"
                f'IF(OR(window="",gold_up="",gdx_up=""),"",IF(AND(window=1,gold_up>0,gdx_up>0),{t[0]},'
                f"IF(window=1,{t[1]},IF(AND(gold_up>0,gdx_up>0),{t[2]},{t[3]})))))")
    else:
        raise ValueError(k)
    return f'=IF({E}="","",{body})'


def value_formula(sig: Signal) -> str:
    """Column E for the formula rows."""
    if sig.key == "royalty_pnav_median":
        S = settings()["sheet"]
        P, a, b, tab = S["pnav_inputs"], S["pnav_first_row"], S["pnav_last_row"], S["pnav_inputs_tab"]

        def rng(c):
            return f"'{tab}'!{P[c]}{a}:{P[c]}{b}"
        return (f'=IFERROR(MEDIAN(FILTER({rng("independent_pnav")},{rng("peer_group")}="Royalty/streaming",'
                f'{rng("nav_per_share")}<>"")),"")')
    if sig.key == "junior_timing":
        return (f"=LET(window,{look('tax_loss_window')},gold_up,{look('uptrend_gold')},gdx_up,{look('uptrend_gdx')},"
                f'IF(OR(window="",gold_up="",gdx_up=""),"",N(window=1)+N(AND(gold_up>0,gdx_up>0))))')
    raise ValueError(sig.key)


# ---------- compute ----------

def compute(data: dict, today: date, thresholds: dict | None = None, inputs: dict | None = None,
            fcf_yields: dict | None = None, royalty_pnavs: list | None = None,
            fallback: dict | None = None) -> list[dict]:
    """Every signal's value, as-of date and status. Pure: no network, no files, no Sheet.

    fallback: {key: (value, as-of date)} used, and marked stale, when a series is missing (the Sheet's last
    values, say, when FRED can't be reached and there's no cached copy)."""
    S = settings()["signals"]
    th = {k: list(v) for k, v in S["thresholds"].items()}
    th.update(thresholds or {})
    inp = dict(S["inputs"])
    inp.update({k: v for k, v in (inputs or {}).items() if _num(v)})
    if not _num(inp.get("industry_aisc")):          # the dated table is the record (published by `today`)
        a = aisc_at(today)
        inp["industry_aisc"] = a["value"] if a else None
    D, M, ry = data.get("daily", {}), data.get("monthly", {}), data.get("real_yield")
    vals, asof = {}, {}

    def put(key, v, s=None):
        vals[key] = v
        asof[key] = s.index[-1].date().isoformat() if s is not None and not s.empty and v is not None else ""

    def last(sym):
        s = D.get(sym)
        return (None, None) if s is None or s.empty else (float(s.iloc[-1]), s)

    gold, gs = last("GC=F")
    silver, ss = last("SI=F")
    if gold and silver:
        put("gold_silver_ratio", gold / silver, gs)
        if "GC=F" in M and "SI=F" in M:
            cur = gs.index[-1].to_period("M")
            hist = month_end_ratio(M["GC=F"], M["SI=F"], cur, pd.Period(S["ratio_history_start"], "M"))
            put("gold_silver_ratio_pctile", percentile(gold / silver, hist), gs)
    if ry is not None and not ry.empty:
        n = S["real_yield_change_days"]
        put("real_yield_10y", float(ry.iloc[-1]), ry)
        put("real_yield_12m_high", high_12m(ry), ry)
        put("real_yield_3m_change", float(ry.iloc[-1] - ry.iloc[-1 - n]) if len(ry) > n else None, ry)
    put("usd_12m", change_12m(D.get("DX-Y.NYB")), D.get("DX-Y.NYB"))
    put("spy_drawdown", drawdown(D.get("SPY")), D.get("SPY"))
    for key, sym in (("gold_12m", "GC=F"), ("silver_12m", "SI=F"), ("copper_12m", "HG=F"),
                     ("diesel_12m", "HO=F"), ("crude_12m", "CL=F")):
        put(key, change_12m(D.get(sym)), D.get(sym))
    for metal in ("gold", "silver", "copper"):
        m, dsl = vals.get(f"{metal}_12m"), vals.get("diesel_12m")
        sym = {"gold": "GC=F", "silver": "SI=F", "copper": "HG=F"}[metal]
        put(f"{metal}_vs_diesel_12m", m - dsl if m is not None and dsl is not None else None, D.get(sym))
    if gold and _num(inp["industry_aisc"]):
        put("aisc_margin", gold - inp["industry_aisc"], gs)
    years = S["percentile_years"]
    for key, etf, sym in (("gdx_gold_pctile10y", "GDX", "GC=F"), ("sil_silver_pctile10y", "SIL", "SI=F"),
                          ("copx_copper_pctile10y", "COPX", "HG=F")):
        e, es = last(etf)
        mtl, _ = last(sym)
        if e and mtl and etf in M and sym in M:
            cur = es.index[-1].to_period("M")
            hist = month_end_ratio(M[etf], M[sym], cur, cur - 12 * years)
            put(key, percentile(e / mtl, hist), es)
    for fund in S["fcf_yield_funds"]:
        v = (fcf_yields or {}).get(fund)
        vals[f"fcf_yield_{fund}"], asof[f"fcf_yield_{fund}"] = v, today.isoformat() if v is not None else ""
    vals["tax_loss_window"], asof["tax_loss_window"] = int(in_window(today, S["tax_loss_window"])), today.isoformat()
    for key, sym in (("uptrend_gold", "GC=F"), ("uptrend_gdx", "GDX"), ("uptrend_silver", "SI=F"),
                     ("uptrend_sil", "SIL")):
        put(key, vs_average(D.get(sym), S["uptrend_days"]), D.get(sym))
    put("gdxj_drawdown", drawdown(D.get("GDXJ")), D.get("GDXJ"))
    put("silj_drawdown", drawdown(D.get("SILJ")), D.get("SILJ"))
    stale = set()
    for key, (v, d) in (fallback or {}).items():
        if vals.get(key) is None and _num(v) and key in BY_KEY and not BY_KEY[key].formula:
            vals[key], asof[key] = float(v), str(d or "")
            stale.add(key)
    # Formula rows: the Sheet computes these; Python works out the same to check them.
    rp = [v for v in (royalty_pnavs or []) if _num(v)]
    vals["royalty_pnav_median"] = float(pd.Series(rp).median()) if rp else None
    w, ug, ux = vals.get("tax_loss_window"), vals.get("uptrend_gold"), vals.get("uptrend_gdx")
    vals["junior_timing"] = (int(w == 1) + int(ug > 0 and ux > 0)) if None not in (w, ug, ux) else None

    ctx = {**vals, "industry_aisc": inp["industry_aisc"]}
    out = []
    for sig in SIGNALS:
        g, h = (th.get(sig.key) or [None, None])[:2]
        v = vals.get(sig.key)
        out.append({"key": sig.key, "tier": sig.tier, "label": sig.label, "value": v,
                    "asof": asof.get(sig.key, ""), "threshold_1": g, "threshold_2": h,
                    "status": status(sig, v, g, h, ctx), "formula": sig.formula, "stale": sig.key in stale})
    return out


# ---------- the Sheet ----------

def read_tab(sheet) -> dict:
    """{key: {"row", "E", "G", "H", "I"}} from the Signals tab (keys in column A)."""
    S = settings()["sheet"]
    tab, last = S["signals_tab"], S["signals_last_row"]
    rows = sheet.read(tab, f"A1:I{last}")
    out = {}
    for i, r in enumerate(rows, start=1):
        r = list(r) + [""] * 9
        key = str(r[0]).strip()
        if key and i >= S["signals_first_row"]:
            out[key] = {"row": i, "E": r[4], "F": r[5], "G": r[6], "H": r[7], "I": r[8]}
    return out


def holdings_rows(sheet) -> list[dict]:
    S = settings()["sheet"]
    rows = sheet.read(S["holdings_tab"], f"A2:O{S['last_row']}")
    out = []
    for r in rows:
        r = list(r) + [""] * 15
        if r[0]:
            out.append({"fund": str(r[0]).strip(), "weight": r[2], "mcap": r[3], "fcf": r[9],
                        "ticker": str(r[14]).strip()})
    return out


def fcf_yields_from_sheet(sheet) -> dict:
    H = settings()["holdings"]
    rows = holdings_rows(sheet)
    exclude = set(H["physical_trusts"]) | set(H["non_operating"])
    return {f: fcf_yield(rows, f, exclude) for f in settings()["signals"]["fcf_yield_funds"]}


def _fmt(v, sig):
    if not _num(v):
        return "—"
    return f"{v:.1%}" if sig.fmt.endswith("%") else f"{v:,.2f}"


def run(sheet=None, dry_run=False, out_dir=None, fetch_data=True, today: date | None = None) -> list[str]:
    from .history import record, today_ny
    today = today or today_ny()
    out_dir = out_dir or OUT / "signals"
    ensure(out_dir)
    rep = fetch() if fetch_data else []
    data = load_cache()
    tabname = settings()["sheet"]["signals_tab"]
    tab = read_tab(sheet) if sheet is not None and sheet.has_tab(tabname) else None
    if sheet is not None and tab is None:
        rep.append(f"No {tabname} tab on the Sheet: run `setup-sheet` first. Statuses below use settings.toml.")
    thresholds, inputs = {}, {}
    for key, c in (tab or {}).items():
        if key in BY_KEY and _num(c["G"]) and _num(c["H"]):
            thresholds[key] = [c["G"], c["H"]]
        if key not in BY_KEY:
            inputs[key] = c["E"]
    aisc = aisc_at(today)                   # the record is data/research/industry_aisc.csv, not the Sheet
    inputs.pop("industry_aisc", None)
    if aisc:
        inputs["industry_aisc"] = aisc["value"]
    fy = fcf_yields_from_sheet(sheet) if sheet is not None else {}
    royalty = royalty_pnavs_from_sheet(sheet) if tab is not None else royalty_pnavs_from_derived()
    fallback = {k: (c["E"], c["F"]) for k, c in (tab or {}).items() if k in BY_KEY}
    rows = compute(data, today, thresholds, inputs, fy, royalty, fallback)
    stale = [f"{r['key']} ({r['asof'] or 'no date'})" for r in rows if r["stale"]]
    if stale:
        rep.append("No new data, so the Sheet's last values are kept: " + ", ".join(stale))

    # Write values and dates for the Python rows, by key
    blocks, missing_rows = [], []
    if tab is not None:
        vals = {}
        for r in rows:
            if r["formula"] or r["stale"]:
                continue
            if r["key"] not in tab:
                missing_rows.append(r["key"])
                continue
            if r["value"] is not None:
                vals[tab[r["key"]]["row"]] = [r["value"], r["asof"]]
        if aisc and "industry_aisc" in tab:
            vals[tab["industry_aisc"]["row"]] = [aisc["value"], aisc_label(aisc)]
        blocks = blocks_by_row(tabname, "E", vals)
        if missing_rows:
            rep.append(f"Rows missing on the {tabname} tab (not written): " + ", ".join(missing_rows))
        if not dry_run:
            sheet.write(blocks)
            rep.append(f"Wrote {sum(len(b[2]) for b in blocks)} signal values to the {tabname} tab.")
        else:
            rep.append(f"Dry run: {sum(len(b[2]) for b in blocks)} signal values would be written.")

    # Statuses
    lines = []
    tier = None
    for r in rows:
        if r["tier"] != tier:
            tier = r["tier"]
            lines.append(f"  {tier}")
        lines.append(f"    {r['label']}: {_fmt(r['value'], BY_KEY[r['key']])}  {r['status']}")
    rep.append("Signals:\n" + "\n".join(lines))
    nodata = [r["key"] for r in rows if r["value"] is None]
    if nodata:
        rep.append("No value (missing data): " + ", ".join(nodata))

    # Changed since the last run: the Sheet's statuses before this run's write (wherever the last run was:
    # here or on GitHub); without a Sheet, the statuses saved by the last run on this computer.
    last_f = out_dir / "last.json"
    # The AISC margin's status is the margin itself, so it changes every day: not a change worth reporting.
    now = {r["key"]: r["status"] for r in rows
           if r["status"] and r["status"] != "Info" and BY_KEY[r["key"]].kind != "aisc"}
    before = None
    if tab is not None:
        before = {k: str(c["I"]).strip() for k, c in tab.items() if k in BY_KEY}
    elif last_f.exists():
        before = json.loads(last_f.read_text())
    if before is not None:
        ch = [f"{BY_KEY[k].label}: {before.get(k) or '—'} -> {v}" for k, v in now.items()
              if k in BY_KEY and before.get(k) != v]
        rep.append("Changed since the last run:\n  " + "\n  ".join(ch) if ch else "No status changed since the last run.")

    # The Sheet's statuses against Python's (only meaningful once the values are written)
    if tab is not None and not dry_run:
        back = read_tab(sheet)
        mism = []
        for r in rows:
            c = back.get(r["key"])
            if c is None or (r["value"] is None and not c["I"]):
                continue
            if str(c["I"]).strip() != r["status"]:
                mism.append(f"{r['key']}: Sheet '{c['I']}', Python '{r['status']}'")
        rep.append("Sheet and Python statuses differ (a formula or threshold drifted):\n  " + "\n  ".join(mism)
                   if mism else "Sheet and Python statuses agree.")

    # Keep today's readings: Signal history and Company history tabs (never fails the run)
    if tab is not None:
        rep += record(sheet, rows, today, dry_run)

    (out_dir / "signals.json").write_text(json.dumps({"date": today.isoformat(), "signals": rows}, indent=1,
                                                     default=str))
    if not dry_run:
        last_f.write_text(json.dumps(now, indent=1))
    (out_dir / "report.txt").write_text(f"Signals {today.isoformat()}\n" + "\n".join(rep) + "\n")
    return rep
