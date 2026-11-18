"""Signal backtest: when a signal said "lean in", did its tier do better over the next months than when it didn't?

fetch()        downloads full daily histories (signal inputs and outcome series) into cache/signals/backtest/.
month_ends()   the last trading day of each month in the gold series.
signal_table() runs signals.compute() at each month-end on the series cut at that date (no lookahead), with
               the industry AISC that was published by then.
forward()      forward returns from each month-end over 3, 6 and 12 months.
bucket_stats() per status: months, independent (non-overlapping) months, mean, median, hit rate, a t-like
               score on the non-overlapping sample, and a "too few to judge" flag.
run()          writes out/backtest-signals/: report.txt, signals_history.csv, outcomes.csv.

The code reports; it never changes thresholds. Thresholds are the record in settings.toml [signals.thresholds]
and Signals G:H.
"""
import json
import math
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from . import yahoo
from .config import OUT, ensure, settings
from .history import truncate
from .signals import BY_KEY, SIG_CACHE, aisc_at, compute, load_cache, parse_fred, status

BT_CACHE = SIG_CACHE / "backtest"
DEST = OUT / "backtest-signals"
HORIZONS = (3, 6, 12)
TOO_FEW = 12                  # independent observations below this: "too few to judge"
ROYALTY = ("RGLD", "FNV", "WPM")
PCTILE_ETF = {"gdx_gold_pctile10y": "GDX", "sil_silver_pctile10y": "SIL", "copx_copper_pctile10y": "COPX"}


@dataclass(frozen=True)
class Test:
    key: str                  # signal key
    outcomes: tuple           # names from outcome_series(): "GC=F", "SI=F-GC=F" (first minus second), ...
    lean_in: str              # the status that means "lean in"


def tests() -> list[Test]:
    t = lambda k: BY_KEY[k].texts  # noqa: E731
    return [
        Test("gold_silver_ratio", ("SI=F-GC=F",), t("gold_silver_ratio")[0]),
        Test("real_yield_10y", ("GC=F",), t("real_yield_10y")[0]),
        Test("usd_12m", ("GC=F",), t("usd_12m")[0]),
        Test("spy_drawdown", ("GC=F", "ROYALTY"), t("spy_drawdown")[0]),
        Test("gold_vs_diesel_12m", ("GDX-GC=F",), t("gold_vs_diesel_12m")[0]),
        Test("silver_vs_diesel_12m", ("SIL-SI=F",), t("silver_vs_diesel_12m")[0]),
        Test("copper_vs_diesel_12m", ("COPX-HG=F",), t("copper_vs_diesel_12m")[0]),
        Test("gdx_gold_pctile10y", ("GDX-GC=F",), t("gdx_gold_pctile10y")[0]),
        Test("sil_silver_pctile10y", ("SIL-SI=F",), t("sil_silver_pctile10y")[0]),
        Test("copx_copper_pctile10y", ("COPX-HG=F",), t("copx_copper_pctile10y")[0]),
        Test("aisc_margin_share", ("GDX-GC=F",), "Wide margin"),
        Test("uptrend_gold", ("GDXJ", "SILJ", "GDXJ-GDX"), t("uptrend_gold")[0]),
        Test("uptrend_gdx", ("GDXJ", "SILJ", "GDXJ-GDX"), t("uptrend_gdx")[0]),
        Test("uptrend_silver", ("SILJ",), t("uptrend_silver")[0]),
        Test("uptrend_sil", ("SILJ",), t("uptrend_sil")[0]),
        Test("junior_timing", ("GDXJ", "SILJ", "GDXJ-GDX"), "Uptrend confirmed"),
    ]


# The AISC margin's status is descriptive text, so the backtest buckets the margin as a share of the gold price.
AISC_TEXTS = ("Wide margin", "Thin margin", "Middling margin")


def aisc_share_status(share, g, h) -> str:
    if share is None or (isinstance(share, float) and math.isnan(share)):
        return ""
    return AISC_TEXTS[0] if share >= g else AISC_TEXTS[1] if share <= h else AISC_TEXTS[2]


def cfg() -> dict:
    return settings()["signal_backtest"]


def rule(key: str):
    """(signal with its status rule active, threshold 1, threshold 2). Context-only signals show "Info" on the
    Sheet; the backtest still tests their rule, with [signal_backtest.context_thresholds]."""
    sig = BY_KEY[key]
    if sig.context:
        return replace(sig, context=False), *cfg()["context_thresholds"][key]
    return sig, *settings()["signals"]["thresholds"][key]


# ---------- data ----------

def _file(sym):
    return BT_CACHE / f"{sym.replace('=', '_').replace('^', '_')}_1d_max.json"


def symbols() -> list[str]:
    S = settings()["signals"]
    return sorted(set(S["daily"]) | set(S["monthly"]) | set(ROYALTY))


def fetch() -> list[str]:
    """Full daily histories for every series the backtest uses, and the FRED real yield."""
    from .signals import fred_csv
    ensure(BT_CACHE)
    got = yahoo.pmap(lambda s: yahoo.history(s, "1d"), symbols())
    failed = []
    for sym, j in got.items():
        if j and (j.get("chart") or {}).get("result"):
            _file(sym).write_text(json.dumps(j))
        else:
            failed.append(sym)
    S = settings()["signals"]
    txt = fred_csv(S)
    if txt and txt.startswith("observation_date"):
        (BT_CACHE / f"{S['fred_series']}.csv").write_text(txt)
    else:
        failed.append(f"FRED {S['fred_series']}")
    return [f"Download failed (cached copy used if there is one): {', '.join(failed)}"] if failed else []


def _series(chart, adjusted: bool) -> pd.Series:
    r = chart["chart"]["result"][0]
    ind = r["indicators"]
    q = (ind.get("adjclose") or [{}])[0].get("adjclose") if adjusted else None
    q = q or ind["quote"][0]["close"]
    s = pd.Series(q, index=pd.to_datetime(r["timestamp"], unit="s").normalize(), dtype=float).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def load() -> tuple[dict, dict]:
    """(signal data in compute()'s shape, {symbol: total-return daily series} for outcomes)."""
    S = settings()["signals"]
    closes, total = {}, {}
    for sym in symbols():
        f = _file(sym)
        if f.exists():
            j = json.loads(f.read_text())
            closes[sym], total[sym] = _series(j, False), _series(j, True)
    start = {k: pd.Timestamp(v) for k, v in cfg().get("start", {}).items()}
    for sym, d in start.items():          # drop thin early prints before an ETF's first full month
        for D in (closes, total):
            if sym in D:
                D[sym] = D[sym][D[sym].index >= d]
    fred = BT_CACHE / f"{S['fred_series']}.csv"
    if not fred.exists():
        fred = SIG_CACHE / f"{S['fred_series']}.csv"
    data = {"daily": {s: closes[s] for s in S["daily"] if s in closes},
            "monthly": {s: closes[s] for s in S["monthly"] if s in closes},   # daily: month_end_ratio takes the last
            "real_yield": parse_fred(fred.read_text()) if fred.exists() else None}
    if not data["daily"]:                 # no backtest download yet: fall back to the daily signals cache
        data = load_cache()
    return data, total


def month_ends(gold: pd.Series, start=None) -> pd.DatetimeIndex:
    """The last trading day of each complete month."""
    s = gold if start is None else gold[gold.index >= pd.Timestamp(start)]
    last = s.groupby(s.index.to_period("M")).apply(lambda x: x.index[-1])
    idx = pd.DatetimeIndex(last.values)
    return idx[idx.to_period("M") < gold.index[-1].to_period("M")] if len(idx) else idx


# ---------- signal values at each month-end ----------

def signal_table(data: dict, dates) -> pd.DataFrame:
    """Month-end values and statuses: columns <key> and <key>__status, one row per date."""
    rows = []
    for ts in dates:
        d = ts.date()
        a = aisc_at(d)
        out = compute(truncate(data, ts), d, inputs={"industry_aisc": a["value"]} if a else None)
        rec = {"date": ts}
        for r in out:
            rec[r["key"]] = r["value"]
            rec[r["key"] + "__status"] = r["status"]
        for r in out:                                 # context-only signals: their rule, as backtest statuses
            if BY_KEY[r["key"]].context:
                sig, g, h = rule(r["key"])
                rec[r["key"] + "__status"] = status(sig, r["value"], g, h, rec)
        gold = data["daily"].get("GC=F")
        m = rec.get("aisc_margin")
        g = gold[gold.index <= ts] if gold is not None else pd.Series(dtype=float)
        rec["aisc_margin_share"] = m / float(g.iloc[-1]) if m is not None and a and not g.empty else None
        for key, etf in PCTILE_ETF.items():          # a percentile over a short history says little: blank it
            e = data["monthly"].get(etf)
            if e is None or e.empty or (pd.Period(ts, "M") - pd.Period(e.index[0], "M")).n < cfg()["percentile_min_months"]:
                rec[key], rec[key + "__status"] = None, ""
        rows.append(rec)
    T = pd.DataFrame(rows).set_index("date")
    g, h = cfg()["aisc_margin_share"]
    T["aisc_margin_share__status"] = [aisc_share_status(v, g, h) for v in T["aisc_margin_share"]]
    return T


def month_end_values(s: pd.Series, dates) -> pd.Series:
    """The last value on or before each date."""
    return s.reindex(s.index.union(dates)).ffill().reindex(dates)


def outcome_series(total: dict) -> dict:
    """{name: total-return index}: each symbol, plus ROYALTY (equal weight of RGLD, FNV and WPM, monthly)."""
    out = dict(total)
    have = [s for s in ROYALTY if s in total]
    if have:
        m = pd.concat({s: total[s].groupby(total[s].index.to_period("M")).last() for s in have}, axis=1)
        r = m.pct_change().mean(axis=1, skipna=True).fillna(0)
        idx = (1 + r).cumprod()
        idx = idx[m.notna().any(axis=1)]
        idx.index = idx.index.to_timestamp("M")
        out["ROYALTY"] = idx
    return out


def forward(series: dict, name: str, dates, h: int) -> pd.Series:
    """Return over the next h months from each date; "A-B" is A's return minus B's."""
    def one(sym):
        s = series.get(sym)
        if s is None or s.empty:
            return pd.Series(np.nan, index=dates)
        m = s.groupby(s.index.to_period("M")).last()
        p = dates.to_period("M")
        start = m.reindex(p)
        end = m.reindex(p + h)
        # only months whose start falls inside the series
        first = m.index[0]
        start[p < first] = np.nan
        return pd.Series((end.values / start.values - 1), index=dates)
    if "-" in name and name not in series:
        a, b = name.split("-", 1)
        return one(a) - one(b)
    return one(name)


# ---------- statistics ----------

def non_overlapping(idx: pd.DatetimeIndex, h: int) -> pd.DatetimeIndex:
    """Greedy pick of dates at least h months apart."""
    picked, last = [], None
    for d in sorted(idx):
        p = pd.Period(d, "M")
        if last is None or (p - last).n >= h:
            picked.append(d)
            last = p
    return pd.DatetimeIndex(picked)


def stats(v: pd.Series, h: int) -> dict:
    v = v.dropna()
    ind = v.reindex(non_overlapping(v.index, h)) if len(v) else v
    return {"months": len(v), "independent": len(ind),
            "mean": float(v.mean()) if len(v) else None, "median": float(v.median()) if len(v) else None,
            "hit_rate": float((v > 0).mean()) if len(v) else None,
            "mean_independent": float(ind.mean()) if len(ind) else None,
            "too_few": len(ind) < TOO_FEW}


def score(a: pd.Series, b: pd.Series, h: int) -> float | None:
    """Difference in means over its standard error, on non-overlapping samples of each group (Welch)."""
    a = a.dropna()
    b = b.dropna()
    a, b = a.reindex(non_overlapping(a.index, h)), b.reindex(non_overlapping(b.index, h))
    if len(a) < 2 or len(b) < 2:
        return None
    se = math.sqrt(a.var() / len(a) + b.var() / len(b))
    return None if se < 1e-12 else float((a.mean() - b.mean()) / se)


def bucket_stats(statuses: pd.Series, outcome: pd.Series, h: int) -> list[dict]:
    """One row per status present, then "All months" (the baseline)."""
    ok = statuses.astype(str).str.len() > 0
    o = outcome[ok]
    st = statuses[ok]
    out = []
    for b in sorted(st.unique()):
        inb = o[st == b]
        rest = o[st != b]
        out.append({"bucket": b, **stats(inb, h), "score": score(inb, rest, h)})
    out.append({"bucket": "All months", **stats(o, h), "score": None})
    return out


def tax_loss(series: dict, sym: str, window_end_month: int = 2) -> dict:
    """Per year: return from the end of November and of December to the end of February (sym's total return),
    against the same-length return from every month-end (the baseline)."""
    s = series.get(sym)
    if s is None or s.empty:
        return {}
    m = s.groupby(s.index.to_period("M")).last()
    out = {}
    for start_month, n in ((11, 3), (12, 2)):
        rets = []
        for p in m.index:
            if p.month == start_month and (p + n) in m.index:
                rets.append(m[p + n] / m[p] - 1)
        base = (m.shift(-n) / m - 1).dropna()
        out[f"{'Nov' if start_month == 11 else 'Dec'}-end to Feb-end"] = {
            "years": len(rets), "mean": float(np.mean(rets)) if rets else None,
            "median": float(np.median(rets)) if rets else None,
            "hit_rate": float(np.mean([r > 0 for r in rets])) if rets else None,
            "base_mean": float(base.mean()) if len(base) else None,
            "base_hit_rate": float((base > 0).mean()) if len(base) else None,
            "too_few": len(rets) < TOO_FEW}
    return out


# ---------- threshold sweep ----------

def sweep_statuses(T: pd.DataFrame, key: str, which: str, value: float) -> pd.Series:
    """Statuses for `key` with one threshold replaced (which: "g" or "h"); the other as in settings."""
    if key == "aisc_margin_share":
        g, h = cfg()["aisc_margin_share"]
        g, h = (value, h) if which == "g" else (g, value)
        return T[key].map(lambda v: aisc_share_status(v, g, h))
    sig, g, h = rule(key)
    g, h = (value, h) if which == "g" else (g, value)
    out = []
    for _, r in T.iterrows():
        v = r[key]
        out.append(status(sig, v if v is not None and not (isinstance(v, float) and math.isnan(v)) else None,
                          g, h, r.to_dict()))
    return pd.Series(out, index=T.index)


# ---------- report ----------

def _pct(v):
    return "    —" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:+6.1%}"


def _hit(v):
    return "  —" if v is None else f"{v:4.0%}"


def _score(v):
    return "    " if v is None else f"{v:+4.1f}"


def run(refresh: bool = False) -> list[str]:
    ensure(DEST)
    rep = []
    if refresh or not any(BT_CACHE.glob("*_1d_max.json")):
        rep += fetch()
    data, total = load()
    gold = data["daily"].get("GC=F")
    if gold is None or gold.empty:
        return rep + ["No gold series: run `backtest-signals --refresh` with a network connection."]
    dates = month_ends(gold, cfg().get("first_month_end"))
    T = signal_table(data, dates)
    T.to_csv(DEST / "signals_history.csv")
    series = outcome_series(total)

    rows = []
    lines = []
    for t in tests():
        st = T[t.key + "__status"].fillna("")
        have = st[st.str.len() > 0]
        sig_name = BY_KEY[t.key].label if t.key in BY_KEY else "AISC margin as a share of the gold price"
        span = f"{have.index[0]:%b %Y} to {have.index[-1]:%b %Y}" if len(have) else "no history"
        ctx = " (context only on the Sheet: its old rule, tested)" if t.key in BY_KEY and BY_KEY[t.key].context else ""
        lines.append(f"\n{sig_name} [{t.key}]{ctx}, {span}. Lean-in status: \"{t.lean_in}\"")
        for name in t.outcomes:
            for h in HORIZONS:
                fwd = forward(series, name, T.index, h)
                bs = bucket_stats(st, fwd, h)
                lines.append(f"  {label(name)}, next {h} months")
                for b in bs:
                    rows.append({"signal": t.key, "outcome": name, "horizon_months": h, "threshold": "",
                                 **b})
                    flag = "  too few to judge" if b["too_few"] else ""
                    mark = "*" if b["bucket"] == t.lean_in else " "
                    lines.append(f"   {mark}{b['bucket'][:52]:<52} {b['months']:4d} mo ({b['independent']:3d} ind.)"
                                 f"  mean {_pct(b['mean'])}  median {_pct(b['median'])}  up {_hit(b['hit_rate'])}"
                                 f"  score {_score(b['score'])}{flag}")
    # tax-loss window
    lines.append("\nTax-loss window [tax_loss_window]: juniors bought at the end of November or December, "
                 "held to the end of February")
    for sym in ("GDXJ", "GDX"):
        for k, v in tax_loss(series, sym).items():
            flag = "  too few to judge" if v["too_few"] else ""
            lines.append(f"  {sym} {k}: {v['years']} years, mean {_pct(v['mean'])}, median {_pct(v['median'])}, "
                         f"up {_hit(v['hit_rate'])}; any month-end, same length: mean {_pct(v['base_mean'])}, "
                         f"up {_hit(v['base_hit_rate'])}{flag}")
            rows.append({"signal": "tax_loss_window", "outcome": sym, "horizon_months": k, "threshold": "",
                         "bucket": "In window", "months": v["years"], "independent": v["years"],
                         "mean": v["mean"], "median": v["median"], "hit_rate": v["hit_rate"],
                         "mean_independent": v["mean"], "too_few": v["too_few"], "score": None})

    # threshold sweep: the lean-in bucket at a few thresholds around the current one
    lines.append("\nThreshold sweep: the lean-in status at nearby thresholds (current marked *). Look for a plateau, "
                 "not the best number.")
    for key, spec in cfg()["sweep"].items():
        t = next(x for x in tests() if x.key == key)
        which, values = spec["threshold"], spec["values"]
        cur = (cfg()["aisc_margin_share"] if key == "aisc_margin_share"
               else rule(key)[1:])[0 if which == "g" else 1]
        name, h = t.outcomes[0], spec.get("horizon", 12)
        fwd = forward(series, name, T.index, h)
        lines.append(f"  {key}, threshold {1 if which == 'g' else 2}; {label(name)}, next {h} months")
        for v in values:
            st = sweep_statuses(T, key, which, v)
            b = next((x for x in bucket_stats(st, fwd, h) if x["bucket"] == t.lean_in), None)
            mark = "*" if math.isclose(v, cur) else " "
            if b is None:
                lines.append(f"   {mark}{v:>7}: never")
                continue
            rows.append({"signal": key, "outcome": name, "horizon_months": h, "threshold": v, **b})
            flag = "  too few to judge" if b["too_few"] else ""
            lines.append(f"   {mark}{v:>7}: {b['months']:4d} mo ({b['independent']:3d} ind.)  mean {_pct(b['mean'])}"
                         f"  up {_hit(b['hit_rate'])}  score {_score(b['score'])}{flag}")

    pd.DataFrame(rows).to_csv(DEST / "outcomes.csv", index=False)
    head = [
        f"Signal backtest: month-ends {T.index[0]:%b %Y} to {T.index[-1]:%b %Y} ({len(T)} months)",
        "Each signal is recomputed at every month-end from the series as they stood then (and the industry AISC "
        "published by then).",
        "Forward returns are total returns (dividends in) from that month-end. 'ind.' counts non-overlapping "
        "windows: overlapping 12-month windows share 11 months, so the month count overstates the evidence.",
        f"'score' = the bucket's mean minus the other months' mean, over its standard error, on non-overlapping "
        f"windows; about ±2 or more is unlikely to be chance. Fewer than {TOO_FEW} independent windows: too few to "
        "judge.",
        f"Miners-against-metal percentiles count from {cfg()['percentile_min_months']} months after the ETF "
        "starts (a percentile of a shorter history says little).",
        "Not tested (no history): fund FCF yields (need past fundamentals) and the royalty median P/NAV "
        "(needs past P/NAVs; Signal history records it from Nov 2026).",
        "Limits: one cycle-heavy period; ETFs hold today's survivors; Yahoo's futures series roll from contract "
        "to contract; ROYALTY = equal weight of RGLD, FNV and WPM (as listed then).",
        "The thresholds aren't changed by this report: change settings.toml [signals.thresholds] and Signals G:H "
        "together.",
    ]
    text = "\n".join(head + lines) + "\n"
    (DEST / "report.txt").write_text(text)
    return rep + [f"Wrote {DEST}/report.txt, signals_history.csv and outcomes.csv ({len(T)} month-ends)."]


def label(name: str) -> str:
    names = {"GC=F": "gold", "SI=F": "silver", "HG=F": "copper", "ROYALTY": "royalty companies"}
    if "-" in name and name not in names:
        a, b = name.split("-", 1)
        return f"{names.get(a, a)} minus {names.get(b, b)}"
    return names.get(name, name)
