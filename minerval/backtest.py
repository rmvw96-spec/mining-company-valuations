"""Backtests of the portfolio in private/portfolio.csv (config/portfolio.example.csv if absent).

fetch_history()  downloads monthly adjusted prices to cache/history/ (needs the network).
run()            computes, from that cache, into out/backtest/:
  prices_monthly.csv   US$ total-return price table (Toronto lines converted at the CAD rate)
  windows.json         last 1/3/5 years, the long cycle since 2010, named episodes, rolling returns
  cycle_2008.json      buy-and-hold over the 2008-2011 cycle
  since_2000.json      yearly-rebalanced test since August 2000
Settings: config/backtest.toml.
"""
import json
import tomllib

import numpy as np
import pandas as pd

from . import yahoo
from .config import CACHE, CONFIG, OUT, PRIVATE, ensure

HIST = CACHE / "history"
DEST = OUT / "backtest"


def cfg() -> dict:
    with open(CONFIG / "backtest.toml", "rb") as f:
        return tomllib.load(f)


def portfolio() -> pd.DataFrame:
    p = PRIVATE / "portfolio.csv"
    d = pd.read_csv(p if p.exists() else CONFIG / "portfolio.example.csv", keep_default_na=False)
    d["toronto_listing_in_cad"] = d.toronto_listing_in_cad.str.lower().eq("yes")
    d["already_held"] = d.already_held.str.lower().eq("yes")
    return d.set_index("key")


def _file(sym: str):
    return HIST / f"{sym.replace('=', '_').replace('^', '_')}_1mo.json"


def fetch_history() -> list[str]:
    ensure(HIST)
    c = cfg()
    syms = sorted(set(portfolio().yahoo) | set(c["benchmarks"]) | set(c["long_history"]))
    got = yahoo.pmap(lambda s: yahoo.history(s, "1mo"), syms, workers=3)
    bad = []
    for s, j in got.items():
        try:
            j["chart"]["result"][0]["timestamp"]
            _file(s).write_text(json.dumps(j))
        except (TypeError, KeyError, IndexError):
            bad.append(s)
    return [f"Downloaded {len(syms) - len(bad)} of {len(syms)} monthly histories."] + (
        ["Failed: " + ", ".join(bad)] if bad else [])


def load(sym: str) -> pd.Series:
    r = json.loads(_file(sym).read_text())["chart"]["result"][0]
    idx = pd.to_datetime(r["timestamp"], unit="s").to_period("M")
    adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose") or r["indicators"]["quote"][0]["close"]
    s = pd.Series(adj, index=idx, dtype=float).dropna()
    return s[~s.index.duplicated(keep="last")]


def splice(real: pd.Series, older: pd.Series) -> pd.Series:
    """Extend `real` back in time with `older`, scaled to meet it at real's first month."""
    real = real.dropna()
    t = real.index[0]
    pre = older[older.index <= t]
    if len(pre) < 2 or pre.index[-1] != t:
        return real
    return pd.concat([pre[:-1] * real.iloc[0] / pre.iloc[-1], real])


def table() -> pd.DataFrame:
    """Monthly US$ prices: portfolio keys plus benchmarks."""
    c, port = cfg(), portfolio()
    fx = load("CADUSD=X")
    px = {}
    for k, r in port.iterrows():
        s = load(r.yahoo)
        if r.toronto_listing_in_cad:
            s = (s * fx.reindex(s.index).ffill()).dropna()
        if r.first_month:
            s = s[s.index >= pd.Period(r.first_month, "M")]
        px[k] = s
    for k, proxy in c["proxies"].items():
        if k in px:
            px[k] = splice(px[k], load(proxy))
    for b in c["benchmarks"]:
        if b not in px:
            px[b] = load(b)
    return pd.DataFrame(px).sort_index()


def stats(v: pd.Series) -> dict:
    r = v.pct_change().dropna()
    n = len(r)
    dd = v / v.cummax() - 1
    r12 = v.pct_change(12).dropna()
    return {"total": float(v.iloc[-1] / v.iloc[0] - 1), "cagr": float((v.iloc[-1] / v.iloc[0]) ** (12 / n) - 1),
            "vol": float(r.std() * 12 ** .5), "maxdd": float(dd.min()), "dd_trough": str(dd.idxmin()),
            "worst12": float(r12.min()) if len(r12) else np.nan, "best12": float(r12.max()) if len(r12) else np.nan}


def groups(port):
    keys = list(port.index)
    bought = [k for k in keys if not port.loc[k, "already_held"]]
    held = [k for k in keys if port.loc[k, "already_held"]]
    out = [("Whole mix (purchases + metal already held)", keys), ("Purchases only", bought)]
    if held:
        out.append(("Metal already held only", held))
    return out if held else out[1:]


def windows(P: pd.DataFrame) -> dict:
    """Recent 1/3/5-year windows, the long cycle, episodes and rolling returns."""
    c, port = cfg(), portfolio()
    amt = port.amount_usd.astype(float)
    keys = list(port.index)
    bought = [k for k in keys if not port.loc[k, "already_held"]]
    R = P.pct_change()

    def hold(start, ks):
        sub = P.loc[start:, ks]
        missing = list(sub.columns[sub.iloc[0].isna()])
        if missing:
            raise ValueError(f"no price at {start} for {missing}")
        return (sub / sub.iloc[0] * amt[ks]).sum(axis=1)

    def rebal(start, ks, every=c["rebalance_months"]):
        sub = R.loc[start:, ks].iloc[1:]
        v, idx, w = [amt[ks].sum()], [pd.Period(start, "M")], None
        for i, (t, r) in enumerate(sub.iterrows()):
            if i % every == 0:
                ok = r.notna()
                w = amt[ks] * ok
                w = w / w.sum() * v[-1]
            w = w * (1 + r.fillna(0))
            v.append(w.sum())
            idx.append(t)
        return pd.Series(v, index=idx)

    end = P.index[-1]
    bench = c["benchmark_labels"]
    res = {}
    for yrs in c["window_years"]:
        st = str(end - 12 * yrs)
        row = {}
        for nm, ks in groups(port):
            v = hold(st, ks)
            row[nm] = dict(stats(v), start_value=float(v.iloc[0]), end_value=float(v.iloc[-1]))
            if nm.startswith("Whole"):
                vr = rebal(st, ks)
                row["Whole mix, rebalanced yearly"] = dict(stats(vr), start_value=float(vr.iloc[0]), end_value=float(vr.iloc[-1]))
        for b, bl in bench.items():
            row[bl] = stats(P.loc[st:, b].dropna())
        res[f"{yrs} year" + ("s" if yrs > 1 else "")] = {"start": st, "rows": row}
    per = {}
    for k in keys:
        per[k] = {f"{y}y": float(P[k].iloc[-1] / P.loc[str(end - 12 * y), k] - 1) for y in c["window_years"]}
        per[k]["from_peak"] = float(P[k].iloc[-1] / P[k].iloc[-24:].max() - 1)
    st = c["long_cycle_start"]
    vl, vr = rebal(st, keys), rebal(st, bought)
    long = {"Whole mix, rebalanced yearly": stats(vl), "Purchases only, rebalanced yearly": stats(vr)}
    for b, bl in bench.items():
        long[bl] = stats(P.loc[st:, b].dropna())
    ep = {}
    for nm, a, b in c["episodes"]:
        if pd.Period(b, "M") > end:
            continue
        ep[nm] = {"mix": float(vl[b] / vl[a] - 1), "purchases": float(vr[b] / vr[a] - 1),
                  "gdx": float(P.loc[b, "GDX"] / P.loc[a, "GDX"] - 1), "gold": float(P.loc[b, "GC=F"] / P.loc[a, "GC=F"] - 1),
                  "silver": float(P.loc[b, "SI=F"] / P.loc[a, "SI=F"] - 1), "spy": float(P.loc[b, "SPY"] / P.loc[a, "SPY"] - 1)}
    roll = {}
    for y in c["window_years"]:
        x = (vl / vl.shift(12 * y) - 1).dropna()
        roll[y] = {"p10": float(x.quantile(.1)), "p50": float(x.quantile(.5)), "p90": float(x.quantile(.9)),
                   "min": float(x.min()), "max": float(x.max()), "neg": float((x < 0).mean()), "n": int(len(x))}
    ye = vl.groupby(vl.index.year).last()
    cal = (ye / ye.shift(1) - 1).dropna()
    return {"windows": res, "per_holding": per, "long": long, "episodes": ep, "rolling": roll,
            "calendar": {int(k): float(v) for k, v in cal.items()},
            "curve": {str(k): float(v) for k, v in (vl / vl.iloc[0] * 100).items()},
            "curve_gdx": {str(k): float(v) for k, v in (P.loc[st:, "GDX"] / P.loc[st, "GDX"] * 100).items()},
            "curve_spy": {str(k): float(v) for k, v in (P.loc[st:, "SPY"] / P.loc[st, "SPY"] * 100).items()}}


def cycle_2008(P: pd.DataFrame) -> dict:
    """Buy and hold through the 2008-2011 cycle; holdings not yet listed give their weight to the rest."""
    c, port = cfg(), portfolio()
    P = P.ffill()
    amt = port.amount_usd.astype(float)

    def run(a, b, ks):
        sub = P.loc[a:b, ks]
        ok = sub.iloc[0].notna()
        w = amt[ks] * ok
        w = w / w.sum() * amt[ks].sum()
        live = ok[ok].index
        v = (sub.loc[:, live] / sub.loc[:, live].iloc[0] * w[ok]).sum(axis=1)
        return v, list(ok[~ok].index), w

    def st(v):
        dd = v / v.cummax() - 1
        n = len(v) - 1
        back = v[(v.index > dd.idxmin()) & (v >= v.cummax().loc[dd.idxmin()])]
        return {"start": float(v.iloc[0]), "end": float(v.iloc[-1]), "total": float(v.iloc[-1] / v.iloc[0] - 1),
                "cagr": float((v.iloc[-1] / v.iloc[0]) ** (12 / n) - 1), "maxdd": float(dd.min()),
                "low": str(dd.idxmin()), "low_value": float(v.loc[dd.idxmin()]),
                "recovered": str(back.index[0]) if len(back) else "not by the end"}

    out = {}
    keys = list(port.index)
    for a, b in c["cycle_2008"]:
        res = {}
        for nm, ks in groups(port):
            v, miss, w = run(a, b, ks)
            res[nm] = st(v)
            if nm.startswith("Whole") or len(groups(port)) == 1:
                res["_missing"], wm = miss, w
        for bcol, bl in (("GDX", "Gold miners fund (GDX)"), ("GC=F", "Gold"), ("HG=F", "Copper"), ("SPY", "S&P 500 (SPY)")):
            res[bl] = st(P.loc[a:b, bcol])
        res["per_holding"] = {k: {"w": float(wm[k]), "total": float(P.loc[b, k] / P.loc[a, k] - 1),
                                  "to_low": float(P.loc[c["cycle_2008_low"], k] / P.loc[a, k] - 1)}
                              for k in keys if pd.notna(P.loc[a, k]) and a < c["cycle_2008_low"]}
        out[f"{a}|{b}"] = res
    return out


def since_2000(P: pd.DataFrame) -> dict:
    """Yearly-rebalanced test since 2000, with Toronto lines filling in before US listings."""
    c, port = cfg(), portfolio()
    end = P.index[-1]
    fx, f6 = load("CADUSD=X"), load("6C=F")
    t0 = fx.index[0]
    fxx = pd.concat([f6[f6.index < t0] * fx.iloc[0] / f6[f6.index <= t0].iloc[-1], fx])

    def cad(sym):
        s = load(sym)
        return (s * fxx.reindex(s.index).ffill()).dropna()

    ext = {k: cad(s) for k, s in c["since_2000_toronto"].items()}
    ext.update({k: splice(P[k], cad(s)) for k, s in c["since_2000_splice"].items()})
    st, en = c["since_2000_start"], str(end)
    P = P.reindex(pd.period_range(st, end, freq="M"))
    for k, s in ext.items():
        P[k] = s.reindex(P.index)
    P["XAU"] = load("^XAU").reindex(P.index)
    P = P.ffill()
    amt = port.amount_usd.astype(float)
    keys = list(port.index)
    held = [k for k in keys if port.loc[k, "already_held"]]
    bought = [k for k in keys if k not in held]
    R = P.pct_change()

    def rebal(ks, every=c["rebalance_months"]):
        # purchases and metal already held keep their starting split; within the purchases,
        # holdings not yet listed give their weight to the others
        sub = R.loc[st:en, ks].iloc[1:]
        v, idx, w = [amt[ks].sum()], [pd.Period(st, "M")], None
        rk = [k for k in ks if k not in held]
        hk = [k for k in ks if k in held]
        for i, (t, r) in enumerate(sub.iterrows()):
            if i % every == 0:
                ok, tot = r.notna(), v[-1]
                w = pd.Series(0.0, index=ks)
                share_r = amt[rk].sum() / amt[ks].sum()
                if rk:
                    wr = amt[rk] * ok[rk]
                    w[rk] = wr / wr.sum() * tot * share_r
                if hk:
                    w[hk] = amt[hk] / amt[hk].sum() * tot * (1 - share_r)
            w = w * (1 + r.fillna(0))
            v.append(w.sum())
            idx.append(t)
        return pd.Series(v, index=idx)

    def stats2(v):
        r = v.pct_change().dropna()
        n = len(r)
        dd = v / v.cummax() - 1
        r12 = v.pct_change(12).dropna()
        return {"total": float(v.iloc[-1] / v.iloc[0] - 1), "cagr": float((v.iloc[-1] / v.iloc[0]) ** (12 / n) - 1),
                "vol": float(r.std() * 12 ** .5), "maxdd": float(dd.min()), "low": str(dd.idxmin()),
                "peak": str(v.loc[:dd.idxmin()].idxmax()), "worst12": float(r12.min()), "best12": float(r12.max())}

    vm, vr = rebal(keys), rebal(bought)
    lines = {"Whole mix, reset yearly": vm, "Purchases only, reset yearly": vr}
    if held:
        vs = (P.loc[st:en, held] / P.loc[st, held] * amt[held]).sum(axis=1)
        lines["Metal already held only"] = vs
    lines.update({"Gold-miner index (XAU, price only)": P.loc[st:en, "XAU"], "Gold": P.loc[st:en, "GC=F"],
                  "Copper": P.loc[st:en, "HG=F"], "S&P 500 (SPY)": P.loc[st:en, "SPY"]})
    out = {"full": {k: stats2(v) for k, v in lines.items()}, "end_value": float(vm.iloc[-1])}
    out["episodes"] = [{"name": nm, **{k: float(v[b] / v[a] - 1) for k, v in lines.items()}}
                       for nm, a, b in c["since_2000_episodes"] if pd.Period(b, "M") <= end]
    out["rolling"] = {}
    for y in (1, 3, 5, 10):
        x = (vm / vm.shift(12 * y) - 1).dropna()
        out["rolling"][y] = {"p10": float(x.quantile(.1)), "p50": float(x.quantile(.5)), "p90": float(x.quantile(.9)),
                             "min": float(x.min()), "max": float(x.max()), "neg": float((x < 0).mean()), "n": int(len(x)),
                             "worst_end": str(x.idxmin()), "best_end": str(x.idxmax())}

    def yearly(v):
        ye = v.groupby(v.index.year).last()
        return (ye / ye.shift(1) - 1).dropna()

    cal = {k: yearly(v) for k, v in lines.items() if k in ("Whole mix, reset yearly", "Purchases only, reset yearly",
                                                           "Metal already held only", "S&P 500 (SPY)")}
    out["calendar"] = {int(y): {k: float(s[y]) for k, s in cal.items()} for y in cal["Whole mix, reset yearly"].index}
    out["halves"] = {nm: {k: float((v[b] / v[a]) ** (12 / (pd.Period(b, "M") - pd.Period(a, "M")).n) - 1)
                          for k, v in lines.items()} for nm, a, b in c["since_2000_halves"] if pd.Period(b, "M") <= end}
    out["first"] = {k: str(P[k].first_valid_index()) for k in keys}
    marks = [st] + [f"{y}-12" for y in range(int(st[:4]), end.year)] + [str(end)]
    out["curve"] = {n: [round(float(lines[n][k] / lines[n].iloc[0] * 100)) for k in marks]
                    for n in ("Whole mix, reset yearly", "Gold", "S&P 500 (SPY)")}
    out["curve_months"] = marks
    return out


def run() -> list[str]:
    ensure(DEST)
    P = table().ffill()
    P.to_csv(DEST / "prices_monthly.csv")
    end = P.index[-1]
    W = windows(P)
    (DEST / "windows.json").write_text(json.dumps(W, indent=1))
    C8 = cycle_2008(P)
    (DEST / "cycle_2008.json").write_text(json.dumps(C8, indent=1))
    S0 = since_2000(P)
    (DEST / "since_2000.json").write_text(json.dumps(S0, indent=1))
    w = W["windows"]
    lines = [f"Backtest to {end}: results in {DEST}."]
    for h, d in w.items():
        k = next(iter(d["rows"]))
        lines.append(f"  {h}: {k} {d['rows'][k]['total']:+.1%}")
    lines.append(f"  Since {cfg()['since_2000_start']}: whole mix {S0['full']['Whole mix, reset yearly']['cagr']:+.1%} a year")
    return lines
