"""Monte Carlo projection of the portfolio over 1, 3 and 5 years (settings: config/projection.toml).

Metals follow correlated monthly moves (20 years of history) around a median path set by three
interest-rate regimes. Each stock = beta x its main metal + its own moves, plus a slow catch-up
toward its peer-group valuation and, for the growth names, outcome trees (a project succeeds,
slips or fails). Physical trusts track their metal less a fee. Needs out/backtest/prices_monthly.csv
(run `backtest` first). Writes out/backtest/projection.json.
"""
import json
import tomllib

import numpy as np
import pandas as pd

from .backtest import DEST, portfolio
from .config import CONFIG

MET = ["GC=F", "SI=F", "HG=F"]
MI = {"gold": 0, "silver": 1, "copper": 2}


def cfg() -> dict:
    with open(CONFIG / "projection.toml", "rb") as f:
        return tomllib.load(f)


def q(x, v0):
    return {"p10": float(np.quantile(x, .1)), "p50": float(np.quantile(x, .5)), "p90": float(np.quantile(x, .9)),
            "ploss": float((x < v0).mean()), "mean": float(x.mean())}


def run(kappa: float | None = None) -> list[str]:
    c, port = cfg(), portfolio()
    K = c["kappa"] if kappa is None else kappa
    N, T = c["paths"], c["months"]
    rng = np.random.default_rng(c["seed"])
    amt = port.amount_usd.astype(float)
    P = pd.read_csv(DEST / "prices_monthly.csv", index_col=0)
    P.index = pd.PeriodIndex(P.index, freq="M")
    P = P.ffill()
    L = np.log(P).diff()
    cov_m = L[MET].loc[c["metals_from"]:].cov().values
    # rate regimes: median yearly growth for (gold, silver, copper) in years 1-2, then years 3-5
    names = list(c["regimes"])
    pr = np.array([c["regimes"][k]["probability"] for k in names])
    reg = rng.choice(len(names), size=N, p=pr)
    g12 = np.array([c["regimes"][k]["years_1_2"] for k in names])
    g35 = np.array([c["regimes"][k]["years_3_5"] for k in names])
    z = rng.standard_normal((N, T, 3)) @ np.linalg.cholesky(cov_m).T
    mu = np.where(np.arange(T)[None, :, None] < 24, np.log1p(g12)[reg][:, None, :], np.log1p(g35)[reg][:, None, :]) / 12
    mcum = np.cumsum(mu + z, axis=1)        # the drift is the median path, so no variance correction
    # equities: beta to the main metal plus correlated idiosyncratic moves
    EQ = [k for k in port.index if not port.loc[k, "already_held"] and port.loc[k, "group"] != "Physical metal"]
    BETA, RES = {}, {}
    for k in EQ:
        f = MET[MI[port.loc[k, "metal"]]]
        d = pd.concat([L[k], L[f]], axis=1).loc[c["beta_from"]:].dropna()
        X = np.column_stack([np.ones(len(d)), d[f]])
        b = np.linalg.lstsq(X, d[k], rcond=None)[0]
        BETA[k], RES[k] = b[1], d[k] - X @ b
    Rz = pd.DataFrame(RES)
    sd = Rz.std().values
    corr = Rz.loc[c["correlation_from"]:].corr().values
    corr = (1 - c["correlation_shrink"]) * corr + c["correlation_shrink"] * np.eye(len(EQ))
    eps = rng.standard_normal((N, T, len(EQ))) @ np.linalg.cholesky(corr).T
    TREE = c["outcomes"]
    t = np.arange(1, T + 1)
    val = {}
    for j, k in enumerate(EQ):
        s = sd[j] * (c["developer_volatility"] if k in TREE else 1.0)
        path = BETA[k] * mcum[:, :, MI[port.loc[k, "metal"]]] + np.cumsum(eps[:, :, j] * s, axis=1) - 0.5 * s * s * t[None, :]
        if k in c["valuation"] and K > 0:
            path = path + (-np.log(c["valuation"][k])) * (1 - np.exp(-K * t / 12))[None, :]
        for stage in TREE.get(k, []):
            a, b = stage["months"]
            when = rng.integers(a, b + 1, size=N)
            mult = rng.choice([m for _, m in stage["odds"]], size=N, p=[p for p, _ in stage["odds"]])
            path = path + np.where(t[None, :] >= when[:, None], np.log(mult)[:, None], 0.0)
        val[k] = amt[k] * np.exp(path)
    fee = -c["trust_fee"] * t / 12
    for k in port.index:
        if k in val:
            continue
        drift = mcum[:, :, MI[port.loc[k, "metal"]]]
        val[k] = amt[k] * np.exp(drift + (0 if port.loc[k, "already_held"] else fee[None, :]))
    held = [k for k in port.index if port.loc[k, "already_held"]]
    v_buy = sum(val[k] for k in val if k not in held)
    v_held = sum(val[k] for k in held) if held else 0
    tot = v_buy + v_held
    v0_tot, v0_buy = float(amt.sum()), float(amt.drop(held).sum())
    spot = c["checks"]["spot"]
    out = {"kappa": K, "betas": {k: float(v) for k, v in BETA.items()}, "idio": dict(zip(EQ, map(float, sd * 12 ** .5))),
           "metal_vol": dict(zip(MET, map(float, np.sqrt(np.diag(cov_m) * 12)))), "horizons": {}}
    for h, i in c["horizons"].items():
        o = {"total": q(tot[:, i], v0_tot), "purchases": q(v_buy[:, i], v0_buy)}
        if held:
            o["already_held"] = q(v_held[:, i], float(amt[held].sum()))
        o["metals"] = {m: {p: float(spot[m] * np.exp(np.quantile(mcum[:, i, MI[m]], pp)))
                           for p, pp in (("p10", .1), ("p50", .5), ("p90", .9))} for m in MI}
        o["by_regime"] = {names[r]: {"total": float(np.median(tot[reg == r, i])), "purchases": float(np.median(v_buy[reg == r, i])),
                                     "p10": float(np.quantile(tot[reg == r, i], .1)), "p90": float(np.quantile(tot[reg == r, i], .9)),
                                     "gold": float(spot["gold"] * np.exp(np.median(mcum[reg == r, i, 0])))}
                          for r in range(len(names))}
        grp = {}
        for k in val:
            g = port.loc[k, "group"]
            grp[g] = grp.get(g, 0) + val[k][:, i]
        o["by_group"] = {g: dict(q(x, 0), start=float(amt[port.group == g].sum())) for g, x in grp.items()}
        o["by_holding"] = {k: {"start": float(amt[k]), "p10": float(np.quantile(val[k][:, i], .1)),
                               "p50": float(np.median(val[k][:, i])), "p90": float(np.quantile(val[k][:, i], .9))} for k in val}
        out["horizons"][h] = o
    run_max = np.maximum.accumulate(np.concatenate([np.full((N, 1), v0_tot), tot], axis=1), axis=1)[:, 1:]
    dd = (tot / run_max - 1).min(axis=1)
    out["drawdown_5y"] = {"p50": float(np.median(dd)), "p10": float(np.quantile(dd, .1)), "p90": float(np.quantile(dd, .9))}
    ck = c["checks"]
    gp = spot["gold"] * np.exp(mcum[:, 12, 0])
    band = (gp > ck["gold_band"][0]) & (gp < ck["gold_band"][1])
    out["checks"] = {"share_of_paths": float(band.mean()), "total_p50": float(np.median(tot[band, 12])),
                     "purchases_p50": float(np.median(v_buy[band, 12])), "paths_above_4800": float((gp > ck["gold_above"]).mean()),
                     "argus": {k: {"target": float(tg / px - 1), "model_p50": float(np.median(val[k][:, 11]) / amt[k] - 1),
                                   "model_p90": float(np.quantile(val[k][:, 11], .9) / amt[k] - 1)}
                               for k, (tg, px) in ck["analyst_targets"].items() if k in val}}
    f = DEST / f"projection_k{int(round(K * 100))}.json"
    f.write_text(json.dumps(out, indent=1))
    lines = [f"Projection ({N:,} paths, catch-up speed {K}): {f}"]
    for h, o in out["horizons"].items():
        x = o["total"]
        lines.append(f"  {h}: low {x['p10']:,.0f}  mid {x['p50']:,.0f}  high {x['p90']:,.0f}  (today {v0_tot:,.0f})")
    return lines
