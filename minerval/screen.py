"""Model portfolio from a screen (roadmap 5).

Ranks the companies on PNAV inputs within each bucket and proposes the Model portfolio's holdings and target
weights (A-F), review levels (S) and notes (U-V). Physical metal rows are the user's and are kept as typed.

- The rules are public: [portfolio_screen] in config/settings.toml (buckets, markets, filters, score, review
  levels, sizing limits). Each bucket's total weight and number of names are private: private/screen.toml.
- By default only companies buyable on a US or Canadian market are proposed (`--all-markets` adds the rest):
  pnav_companies.csv us_listing / canada_listing, and the fee reasons in settings.
- Holding names, weights and statuses never go into the repo, a log or the step summary: the report is
  out/screen/ (local), the Sheet and, with --email, a private email. The command never runs on GitHub.
- A review level the user typed in S is kept: private/screen_state.json records the levels the screen wrote.

`portfolio-file` (Part 3) writes private/portfolio.csv from the tab for `backtest` and `project`.
"""
import json
import math
import time
import tomllib
from datetime import date

import numpy as np
import pandas as pd

from .config import OUT, PRIVATE, RESEARCH, ensure, settings
from .sheets import CLEAR, col_to_num, num_to_col, split_cell

DEST = OUT / "screen"
PRIVATE_CFG = PRIVATE / "screen.toml"
STATE = PRIVATE / "screen_state.json"
PORTFOLIO_FILE = PRIVATE / "portfolio.csv"
PHYSICAL = "Physical metal"
ROYALTY = "Royalty"
DEVELOPERS = "Growth: developers"
FUNDED = ("Fully funded", "Funded (company says)")
MEASURES = {        # measure, higher is better
    "producer": [("peer_norm", False), ("pnav_low", False), ("breakeven_gap", False), ("net_cash_pct", True),
                 ("share_change_3y", False), ("addon", False), ("addon_reliance", False)],
    "developer": [("pnav_after", False), ("peer_ev_ratio", False), ("months_of_cash", True), ("addon", False)],
    "royalty": [("independent_pnav", False), ("own_pctile", False), ("peer_norm", False), ("addon", False)],
}
HOME = {".AX": "ASX", ".L": "LSE", ".JO": "JSE", ".HK": "HKEX", ".IS": "Borsa Istanbul", ".WA": "Warsaw",
        ".JK": "IDX", ".PS": "PSE", ".HE": "Helsinki", ".ST": "Stockholm", ".SN": "Santiago", ".LM": "Lima",
        ".MX": "Mexico"}
PORTFOLIO_COLS = ["key", "label", "group", "metal", "amount_usd", "already_held", "yahoo", "toronto_listing_in_cad",
                  "first_month"]


def cfg() -> dict:
    return settings()["portfolio_screen"]


def num(v) -> float:
    """A Sheet value as a float (NaN for blanks and text)."""
    if isinstance(v, bool):
        return np.nan
    if isinstance(v, (int, float, np.floating)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except ValueError:
        return np.nan


def _text(v) -> str:
    return "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v).strip()


def kind(bucket: str) -> str:
    return "royalty" if bucket == ROYALTY else "developer" if bucket == DEVELOPERS else "producer"


# ---------- universe ----------

def main_metal(r) -> str:
    """Largest revenue share for producers; the resource unit for developers."""
    if _text(r.get("peer_group")) == "Developer":
        u = _text(r.get("resource_unit"))
        return "gold" if u in ("oz Au", "oz AuEq") else "silver" if u == "oz AgEq" else "copper" if u.startswith(
            "lb") else ""
    shares = {m: num(r.get(f"share_{m}")) for m in ("gold", "silver", "copper")}
    shares = {m: v for m, v in shares.items() if v == v and v > 0}
    return max(shares, key=shares.get) if shares else ""


def bucket_of(r, c: dict | None = None) -> str:
    """The bucket for a company: the `bucket` override, else by peer group and main metal ("" when none fits)."""
    c = c or cfg()
    over = _text(r.get("bucket"))
    if over:
        return over
    m, peer = c["buckets"], _text(r.get("peer_group"))
    if peer in m:
        return m[peer]
    metal = r.get("metal") or main_metal(r)
    if "producer" in peer.lower():
        return m.get(f"{peer}|{metal}") or m.get(f"producer|{metal}", "")
    return ""


def market(r, c: dict | None = None) -> tuple[bool, str]:
    """(buyable without a per-trade fee in the default mode, note)."""
    c = (c or cfg())["markets"]
    if _text(r.get("us_listing")):
        return True, ""
    if _text(r.get("canada_listing")):
        if _text(r.get("us_otc_symbol")):
            return True, ""
        return bool(c["canada_rep_assisted"]), c["canada_rep_note"]
    return False, c["foreign_fee_note"]


def where(r) -> str:
    """Model portfolio C: where it trades, US and Canadian listings first."""
    parts = [x for x in (_text(r.get("us_listing")), _text(r.get("canada_listing"))) if x]
    otc = _text(r.get("us_otc_symbol"))
    if parts:
        return "; ".join(parts) + (f"; US OTC: {otc}" if otc and not _text(r.get("us_listing")) else "")
    y = _text(r.get("yahoo"))
    home = next((v for k, v in HOME.items() if y.endswith(k)), "home market")
    return f"{home} only" + (f" (US OTC: {otc})" if otc else "") + ": about $50 a trade in an IRA"


def read_universe(sheet, research: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Every PNAV inputs company with the screen's raw fields and measures, and today's metal prices."""
    S = settings()["sheet"]
    P, a, b, tab = S["pnav_inputs"], S["pnav_first_row"], S["pnav_last_row"], S["pnav_inputs_tab"]
    T, D = S["pnav_tab_cols"], S["downside_cols"]
    fields = {"holding": P["holding"], "mcap": P["mcap"], "addon": P["addon"], "peer_group": P["peer_group"],
              "independent_pnav": P["independent_pnav"], "royalty_band": P["royalty_band"],
              "resource_unit": P["resource_unit"], "months_of_cash": P["months_of_cash"],
              "developer_check": P["developer_check"], "pnav_after_raw": P["pnav_after"],
              "peer_ev_ratio": P["peer_ev_ratio"], "pnav_addon_up": P["pnav_addon_up"],
              "pocf_pctile": P["pocf_pctile"], "pnav_pctile": P["pnav_pctile"], "yahoo": P["yahoo"],
              "share_gold": "J", "share_silver": "K", "share_copper": "L"}
    last = max(col_to_num(c) for c in fields.values())
    grid = sheet.read(tab, f"A{a}:{num_to_col(last)}{b}")
    tcols = {"pnav_today": T["pnav_today"], "pnav_peer": T["pnav_peer"], "pnav_low": T["pnav_low"]}
    tlast = max(col_to_num(c) for c in tcols.values())
    pa = S["pnav_tab_first_row"]
    tgrid = sheet.read(S["pnav_tab"], f"A{pa}:{num_to_col(tlast)}{S['pnav_tab_last_row']}")
    rows = []
    for i in range(b - a + 1):
        r = list(grid[i]) if i < len(grid) else []
        r += [""] * (last - len(r))
        d = {k: r[col_to_num(c) - 1] for k, c in fields.items()}
        j = (a + i) - 10 - pa                          # P/NAV tab row N is PNAV inputs row N+10
        t = list(tgrid[j]) if 0 <= j < len(tgrid) else []
        t += [""] * (tlast - len(t))
        d.update({k: t[col_to_num(c) - 1] for k, c in tcols.items()})
        d["sheet_row"] = a + i
        if _text(d["holding"]):
            rows.append(d)
    U = pd.DataFrame(rows)
    R = research if research is not None else pd.read_csv(RESEARCH / "pnav_companies.csv", keep_default_na=False,
                                                          na_values=[""])
    keep = [c for c in ("sheet_row", "ticker", "stage", "us_listing", "canada_listing", "us_otc_symbol", "bucket",
                        "bucket_note") if c in R.columns]
    U = U.merge(R[keep], on="sheet_row", how="left")
    # Holdings (financials date, price date, by Sprott ticker) and Holdings downside (by ticker)
    H = sheet.read(S["holdings_tab"], f"A2:V{S['last_row']}")
    hold, by_name = {}, {}
    for r in H:
        r = list(r) + [""] * 22
        t = _text(r[14])
        if t:
            by_name.setdefault(_text(r[1]), []).append(t)
        if t and t not in hold:
            hold[t] = {"financials_through": _text(r[13]), "price_date": _text(r[19]), "currency": _text(r[18]),
                       "yahoo_h": _text(r[15])}
    DG = sheet.read(S["downside_tab"], f"A{S['downside_first_row']}:{D['ticker']}{S['downside_last_row']}")
    down = {}
    for r in DG:
        r = list(r) + [""] * (col_to_num(D["ticker"]) + 1)
        t = _text(r[col_to_num(D["ticker"]) - 1])
        if t and t not in down:
            down[t] = {k: r[col_to_num(D[k]) - 1] for k in ("net_cash_pct", "share_change_3y", "breakeven",
                                                             "breakeven_metal")}
    for k in ("financials_through", "price_date", "currency", "yahoo_h"):
        U[k] = [hold.get(_text(t), {}).get(k, "") for t in U.ticker]
    for k in ("net_cash_pct", "share_change_3y", "breakeven", "breakeven_metal"):
        U[k] = [down.get(_text(t), {}).get(k, "") for t in U.ticker]
    # The ticker to write in Model portfolio D: a US one where Holdings and Holdings downside carry it (KGC for
    # Kinross, whose PNAV inputs row is K CN), else the PNAV inputs one
    U["ticker_buy"] = [next((x for x in by_name.get(_text(h), []) if " " not in x and x in down), _text(t))
                       for h, t in zip(U.holding, U.ticker)]
    # One row per company (Wheaton is held in two funds): prefer the US listing's Sprott ticker
    U["_us"] = U.ticker.map(lambda t: " " not in _text(t))
    U = U.sort_values(["_us", "sheet_row"], ascending=[False, True]).drop_duplicates("holding").drop(columns="_us")
    U = U.sort_values("sheet_row").reset_index(drop=True)
    mc = S["metal_cells"]
    metals = {m: num((sheet.read(S["metals_tab"], cell) or [[""]])[0][0]) for m, cell in mc.items()}
    return add_measures(U, metals), metals


def add_measures(U: pd.DataFrame, metals: dict) -> pd.DataFrame:
    U = U.copy()
    for c in ("mcap", "pnav_today", "pnav_peer", "pnav_low", "independent_pnav", "peer_ev_ratio", "pnav_addon_up",
              "pocf_pctile", "pnav_pctile", "net_cash_pct", "share_change_3y", "breakeven"):
        U[c] = U[c].map(num) if c in U else np.nan
    U["addon"] = U["addon"].map(num) * 100 if "addon" in U else np.nan     # P is a fraction (0.01 = 1 point)
    U["metal"] = [main_metal(r) for _, r in U.iterrows()]
    U["bucket"] = [bucket_of(r) for _, r in U.iterrows()]
    U["peer_norm"] = U.pnav_peer
    price = [metals.get(_text(m).split(" ")[0].lower(), np.nan) for m in U.get("breakeven_metal", [""] * len(U))]
    U["breakeven_gap"] = U.breakeven / pd.Series(price, index=U.index) - 1
    U["addon_reliance"] = U.pnav_addon_up / U.pnav_today
    U["pnav_after"] = [0.0 if _text(v) in FUNDED else num(v) for v in U.pnav_after_raw]
    U["months_of_cash"] = [1e9 if _text(v) == "Cash-generating" else num(v) for v in U.months_of_cash]
    U["own_pctile"] = U.pnav_pctile.where(U.pnav_pctile.notna(), U.pocf_pctile)
    mk = [market(r) for _, r in U.iterrows()]
    U["market_ok"], U["market_note"] = [m[0] for m in mk], [m[1] for m in mk]
    U["where"] = [where(r) for _, r in U.iterrows()]
    return U


# ---------- filters, score, selection, weights ----------

def review_level(bucket: str, c: dict | None = None) -> float:
    r = (c or cfg())["review"]
    return float(r.get("by_bucket", {}).get(bucket, r["review_multiple"]))


def _age(d: str, today: date) -> float:
    try:
        return (today - pd.Timestamp(d).date()).days
    except (ValueError, TypeError):
        return np.inf


def failure(r, today: date, level: float, all_markets: bool = False, c: dict | None = None) -> str:
    """The first hard filter a company fails ("" when it passes)."""
    c = c or cfg()
    F, k = c["filters"], kind(r["bucket"])
    if not all_markets and not r["market_ok"]:
        return f"market ({r['market_note']})"
    if _age(r.get("financials_through"), today) > F["financials_max_days"]:
        return f"financials stale or missing ({r.get('financials_through') or 'no date'})"
    if _age(r.get("price_date"), today) > F["price_max_days"]:
        return f"price stale ({r.get('price_date') or 'no date'})"
    floor = F["min_mcap_developer_m"] if k == "developer" else F["min_mcap_m"]
    if not r["mcap"] >= floor:
        return f"market cap under ${floor:,.0f}M"
    dil = F.get("max_share_change_3y_pct_by_bucket", {}).get(r["bucket"], F["max_share_change_3y_pct"])
    if k == "producer" and r["share_change_3y"] > dil:
        return f"dilution {r['share_change_3y']:.0f}% in 3 years"
    if r["addon"] > F["max_addon_points"]:
        return f"jurisdiction add-on {r['addon']:.2f} points"
    if k == "developer":
        if _text(r.get("developer_check")).startswith("Short of cash"):
            return "developer short of cash"
        if not (r["pnav_after"] == r["pnav_after"]):
            return "no P/NAV after a raise or funding statement"
        if r["peer_ev_ratio"] > F["max_peer_ev_ratio"]:
            return f"EV per unit {r['peer_ev_ratio']:.2f}× the peer median"
    if k == "royalty":
        band = _text(r.get("royalty_band"))
        if band in F["royalty_excluded_bands"]:
            return f"framework band: {band}"
        hi = settings()["signals"]["thresholds"]["royalty_own_pctile_median"][1]
        if r["own_pctile"] >= hi:
            return f"expensive for itself (own-history percentile {r['own_pctile']:.0f})"
        return ""
    if r["peer_norm"] >= level:
        return f"valuation {r['peer_norm']:.2f}× peer norm, at or above the review level {level:g}"
    return ""


def rank_pct(x: pd.Series, higher_better: bool) -> pd.Series:
    """0 (worst) to 1 (best) within the series; NaN stays NaN; a single value is 1."""
    v = x.astype(float)
    ok = v.notna()
    out = pd.Series(np.nan, index=v.index)
    n = int(ok.sum())
    if n == 0:
        return out
    r = (v[ok] if higher_better else -v[ok]).rank(method="average")
    out[ok] = (r - 1) / (n - 1) if n > 1 else 1.0
    return out


def score(B: pd.DataFrame, k: str, c: dict | None = None) -> pd.DataFrame:
    """Add `score` and `measures_used` to one bucket's eligible companies."""
    w = (c or cfg())["score"]
    B = B.copy()
    num_ = pd.Series(0.0, index=B.index)
    den = pd.Series(0.0, index=B.index)
    used = pd.Series(0, index=B.index)
    for m, hb in MEASURES[k]:
        wt = float(w.get(m, 0))
        if wt <= 0:
            continue
        p = rank_pct(B[m], hb)
        num_ += (p * wt).fillna(0)
        den += p.notna() * wt
        used += p.notna().astype(int)
    B["score"] = (num_ / den.replace(0, np.nan))
    B["measures_used"] = used
    return B.sort_values("score", ascending=False, na_position="last")


def select(ranked: list[str], existing: set, n: int, buffer: int) -> list[str]:
    """Top n, keeping a holding already on the tab while it ranks within n + buffer."""
    keep = [t for t in ranked[:n + buffer] if t in existing][:n]
    fill = [t for t in ranked if t not in keep][:max(0, n - len(keep))]
    chosen = set(keep + fill)
    return [t for t in ranked if t in chosen]


def weights(scores: list[float], total: float, cap: float, tilt: float = 0.0) -> tuple[list[float], float]:
    """Split `total` over the names (equal, or tilted by score), at most `cap` each. Returns (weights,
    unallocated)."""
    k = len(scores)
    if k == 0:
        return [], total
    w = np.full(k, total / k)
    s = np.array([x if x == x else 0.0 for x in scores], dtype=float)
    if tilt and k > 1 and np.ptp(s) > 0:
        dev = (s - s.mean()) / np.abs(s - s.mean()).max()
        w = w * (1 + tilt * dev)
        w = w / w.sum() * total
    for _ in range(k + 1):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = float((w[over] - cap).sum())
        w[over] = cap
        room = np.where(w < cap - 1e-12, cap - w, 0.0)
        if room.sum() <= 1e-12:
            break
        add = np.minimum(room, excess * (w * (room > 0)) / max((w * (room > 0)).sum(), 1e-12))
        w = w + add
    return [float(x) for x in w], float(total - w.sum())


# ---------- the private sizes and the state ----------

def load_sizes(path=None) -> dict:
    """{bucket: {"weight", "names"}} from private/screen.toml."""
    path = path or PRIVATE_CFG
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f).get("buckets", {})


def load_state(path=None) -> dict | None:
    path = path or STATE
    return json.loads(path.read_text()) if path.exists() else None


# ---------- the tab ----------

def read_tab(sheet) -> list[dict]:
    """Model portfolio rows 6-31 as dicts of A-V (values), with their row number."""
    S = settings()["sheet"]
    a, b = S["portfolio_first_row"], S["portfolio_last_row"]
    grid = sheet.read(S["portfolio_tab"], f"A{a}:V{b}")
    out = []
    for i in range(b - a + 1):
        r = list(grid[i]) if i < len(grid) else []
        r += [""] * (22 - len(r))
        out.append({"row": a + i, **{num_to_col(j + 1): r[j] for j in range(22)}})
    return out


def resolve(row: dict, U: pd.DataFrame) -> str:
    """The universe's name for a tab row: the same name (any case), else the same ticker; the tab's name if none."""
    name, t = _text(row["B"]), _text(row["D"])
    hit = U[U.holding.map(lambda h: _text(h).lower()) == name.lower()]
    if hit.empty and t:
        hit = U[(U.ticker.map(_text) == t) | (U.ticker_buy.map(_text) == t if "ticker_buy" in U else False)]
    return _text(hit.holding.iloc[0]) if len(hit) else name


def plan(U: pd.DataFrame, tab: list[dict], sizes: dict, today: date, state: dict | None,
         all_markets: bool = False, rule_levels: bool = False, c: dict | None = None) -> dict:
    """The proposal: rows to write, the ranked buckets, drops, warnings. Pure (no Sheet)."""
    c = c or cfg()
    L = c["limits"]
    physical = [r for r in tab if _text(r["A"]) == PHYSICAL]
    existing = {resolve(r, U): r for r in tab if _text(r["B"]) and _text(r["A"]) != PHYSICAL}   # by holding name
    phys_w = sum(num(r["F"]) for r in physical if num(r["F"]) == num(r["F"]))
    screened = [b for b in c["bucket_order"] if b != PHYSICAL and b in sizes and sizes[b].get("names", 0) > 0]
    cw = sum(float(sizes[b]["weight"]) for b in screened)
    factor = (1 - phys_w) / cw if cw > 0 else 0.0
    warn, notes = [], []
    if cw > 0 and abs(factor - 1) > 1e-3:
        notes.append(f"Bucket weights in private/screen.toml sum to {cw:.1%}; scaled ×{factor:.3f} to fill the "
                     f"{1 - phys_w:.1%} left after physical metal.")
    typed = {}
    recorded = (state or {}).get("review", {})
    for name, r in existing.items():
        s, t = num(r["S"]), _text(r["D"])
        if s == s and not rule_levels and (state is None or t not in recorded or abs(recorded[t] - s) > 1e-9):
            typed[name] = s
    rows, ranked_out, drops, fails, ranks = [], {}, [], {}, {}
    for b in screened:
        n = int(sizes[b]["names"])
        k = kind(b)
        B = U[U.bucket == b].copy()
        B["level"] = [typed.get(_text(h), review_level(b, c)) for h in B.holding]
        B["fail"] = [failure(r, today, r["level"], all_markets, c) for _, r in B.iterrows()]
        E = score(B[B.fail == ""], k, c)
        ranked = [_text(h) for h in E.holding]
        chosen = select(ranked, set(existing), n, int(c["buffer"]))
        if len(chosen) < n:
            warn.append(f"{b}: {len(chosen)} eligible names for {n} places.")
        cap = L["max_name_weight_speculation"] if b in c["speculation"] else L["max_name_weight"]
        Ec = E.set_index(E.holding.map(_text)).loc[chosen] if chosen else E.iloc[:0]
        ws, un = weights(list(Ec.score), float(sizes[b]["weight"]) * factor, cap, float(c["tilt"]))
        if un > 1e-6:
            warn.append(f"{b}: {un:.1%} unallocated (per-name cap {cap:.0%}).")
        for (t, r), w in zip(Ec.iterrows(), ws):
            rank = ranked.index(t) + 1
            level = typed.get(t, review_level(b, c))
            old = existing.get(t)
            why = _text(old["U"]) if old and _text(old["U"]) and not _text(old["U"]).startswith("Screen:") \
                else why_text(r, k, rank, len(ranked))
            change = _text(old["V"]) if old else f"Screen: review above {level:g}× peer norm, or if it fails a filter"
            rows.append({"A": b, "B": t, "C": r["where"], "D": _text(old["D"]) if old else r.ticker_buy,
                         "E": (r.metal or "").capitalize(),
                         "F": round(w, 6), "S": level, "U": why, "V": change, "typed_level": t in typed,
                         "rank": rank, "score": r.score, "new": old is None})
        ranked_out[b] = B.assign(score=E.score.reindex(B.index), measures_used=E.measures_used.reindex(B.index)) \
            .sort_values(["fail", "score"], ascending=[True, False])
        fails.update({_text(h): f for h, f in zip(B.holding, B.fail) if f})
        ranks.update({t: (b, i + 1, n) for i, t in enumerate(ranked)})
    chosen_all = {r["B"] for r in rows}
    for t, r in existing.items():
        if t in chosen_all:
            continue
        if t in fails:
            why = fails[t]
        elif t in ranks:
            b, i, n = ranks[t]
            why = f"rank {i} in {b}, below {n} + buffer {c['buffer']}"
        elif _text(r["A"]) not in screened:
            why = "bucket not in private/screen.toml"
        else:
            why = "not in the screened universe now (no bucket or no data)"
        drops.append((_text(r["A"]), _text(r["B"]), why))
    S_ = settings()["sheet"]
    room = S_["portfolio_last_row"] - S_["portfolio_first_row"] + 1
    if len(physical) + len(rows) > room:
        warn.append(f"{len(physical) + len(rows)} rows for {room} on the tab: reduce `names` in private/screen.toml "
                    f"by {len(physical) + len(rows) - room} (--write would stop).")
    spec = sum(r["F"] for r in rows if r["A"] in c["speculation"])
    if spec > L["max_speculation"] + 1e-9:
        warn.append(f"Speculation (developers and expanding producers) {spec:.1%}, above {L['max_speculation']:.0%}.")
    nd = sum(1 for r in rows if r["A"] == DEVELOPERS)
    if 0 < nd < L["min_developers"] or nd > L["max_developers"]:
        warn.append(f"Developers: {nd} names (research range {L['min_developers']}-{L['max_developers']}).")
    nr = sum(1 for r in rows if r["A"] == ROYALTY)
    lo, hi = L["royalty_names"]
    if nr and not lo <= nr <= hi:
        warn.append(f"Royalty: {nr} names (research range {lo}-{hi}).")
    return {"physical": physical, "rows": rows, "ranked": ranked_out, "drops": drops, "warnings": warn,
            "notes": notes, "typed": typed, "existing": existing}


def why_text(r, k: str, rank: int, of: int) -> str:
    def f(v, fmt):
        return format(v, fmt) if v == v else "—"
    if k == "royalty":
        body = (f"independent P/NAV {f(r.independent_pnav, '.2f')}; own-history percentile "
                f"{f(r.own_pctile, '.0f')}; valuation {f(r.peer_norm, '.2f')}× peer norm")
    elif k == "developer":
        after = "funded" if _text(r.pnav_after_raw) in FUNDED else f(r.pnav_after, ".2f")
        moc = "cash-generating" if r.months_of_cash >= 1e9 else f(r.months_of_cash, ".0f")
        body = (f"P/NAV after a raise {after}; EV per unit {f(r.peer_ev_ratio, '.2f')}× peers; "
                f"{moc} months of funding")
    else:
        body = (f"valuation {f(r.peer_norm, '.2f')}× peer norm; P/NAV at Low prices {f(r.pnav_low, '.2f')}; "
                f"breakeven {f(r.breakeven_gap, '+.0%')} vs today's {r.metal or 'metal'}; net cash "
                f"{f(r.net_cash_pct, '.0f')}% of market value")
    return f"Screen: rank {rank} of {of} (score {f(r.score, '.2f')}); {body}; add-on {f(r.addon, '.2f')}"


# ---------- report and write ----------

def report(P: dict, all_markets: bool) -> list[str]:
    L = [f"Model portfolio screen ({'all markets' if all_markets else 'US and Canadian listings only'})", ""]
    L += P["notes"]
    if P["warnings"]:
        L += ["Warnings:"] + [f"  {w}" for w in P["warnings"]]
    L.append("")
    L.append("Proposal (bucket, holding, where, weight, review level, rank):")
    for r in P["physical"]:
        L.append(f"  {r['A']}: {r['B']} (kept as typed), {num(r['F']):.1%}")
    for r in P["rows"]:
        tag = "new" if r["new"] else "kept"
        lvl = f"{r['S']:g}" + (" (typed, kept)" if r["typed_level"] else "")
        L.append(f"  {r['A']}: {r['B']} [{r['D']}; {r['C']}] {r['F']:.1%}, review {lvl}, rank {r['rank']} ({tag})")
    total = sum(num(r["F"]) for r in P["physical"] if num(r["F"]) == num(r["F"])) + sum(r["F"] for r in P["rows"])
    L.append(f"  Total {total:.1%} ({len(P['physical']) + len(P['rows'])} rows of 26)")
    if P["drops"]:
        L += ["", "Dropped from the tab:"] + [f"  {b}: {h}: {why}" for b, h, why in P["drops"]]
    for b, B in P["ranked"].items():
        L += ["", f"{b}: ranked"]
        for _, r in B.iterrows():
            s = f"{r.score:.2f}" if r.score == r.score else "—"
            L.append(f"  {r.holding} [{_text(r.ticker)}] score {s}" + (f"  EXCLUDED: {r.fail}" if r.fail else
                                                                        f" ({r.get('measures_used', 0):.0f} measures)"))
    return L


def write_rows(sheet, P: dict) -> list[tuple]:
    """Blocks for Model portfolio A-F, S and U-V, rows 6-31 (physical rows first, then the proposal)."""
    S = settings()["sheet"]
    tab, a, b = S["portfolio_tab"], S["portfolio_first_row"], S["portfolio_last_row"]
    rows = [{k: r[k] for k in ("A", "B", "C", "D", "E", "F", "S", "U", "V")} for r in P["physical"]] + P["rows"]
    if len(rows) > b - a + 1:
        raise ValueError(f"{len(rows)} rows proposed; the tab has {b - a + 1} (rows can't be added below {b}).")

    def cell(v):
        return CLEAR if v is None or _text(v) == "" else v
    af, s, uv = [], [], []
    for i in range(b - a + 1):
        r = rows[i] if i < len(rows) else {}
        af.append([cell(r.get(k)) for k in "ABCDEF"])
        s.append([cell(r.get("S"))])
        uv.append([cell(r.get("U")), cell(r.get("V"))])
    return [(tab, f"A{a}", af), (tab, f"S{a}", s), (tab, f"U{a}", uv)]


def check_lookups(sheet, P: dict) -> list[str]:
    """Holdings named as the P/NAV tab names them and tickers on Holdings downside (else H-R can't look them up)."""
    S = settings()["sheet"]
    names = {_text(r[0]) for r in sheet.read(S["pnav_tab"], f"B{S['pnav_tab_first_row']}:B{S['pnav_tab_last_row']}")
             if r}
    L = S["downside_cols"]["ticker"]
    ticks = {_text(r[0]) for r in sheet.read(S["downside_tab"], f"{L}{S['downside_first_row']}:"
                                                                 f"{L}{S['downside_last_row']}") if r}
    bad = [f"{r['B']} not on the P/NAV tab" for r in P["rows"] if _text(r["B"]) not in names]
    bad += [f"{r['D']} not on Holdings downside" for r in P["rows"] if _text(r["D"]) not in ticks]
    return bad


def email_body(P: dict) -> str:
    added = [f"+ {r['A']}: {r['B']} {r['F']:.1%}" for r in P["rows"] if r["new"]]
    kept = [f"  {r['A']}: {r['B']} {num(P['existing'][r['B']]['F']):.1%} -> {r['F']:.1%}" for r in P["rows"]
            if not r["new"]]
    drops = [f"- {b}: {h} ({why})" for b, h, why in P["drops"]]
    return "\n".join(["Model portfolio rewritten by the screen.", ""] + added + kept + drops + [""] + P["warnings"])


def init_sizes(sheet, path=None) -> list[str]:
    """`screen --init`: write private/screen.toml from the tab's current split (Royalty with 0 names)."""
    path = path or PRIVATE_CFG
    if path.exists():
        return [f"{path} exists; edit it by hand (not overwritten)."]
    tab = read_tab(sheet)
    w, n = {}, {}
    for r in tab:
        b = _text(r["A"])
        if b and b != PHYSICAL and num(r["F"]) == num(r["F"]):
            w[b] = w.get(b, 0) + num(r["F"])
            n[b] = n.get(b, 0) + 1
    lines = ["# Private: each bucket's total weight (share of the whole Model portfolio) and number of names.",
             "# Written by `screen --init` from the tab; edit freely. Physical metal keeps its typed weights.", ""]
    for b in cfg()["bucket_order"]:
        if b == PHYSICAL:
            continue
        lines += [f'[buckets."{b}"]', f"weight = {round(w.get(b, 0), 4)}", f"names = {n.get(b, 0)}", ""]
    ensure(path.parent)
    path.write_text("\n".join(lines))
    return [f"Wrote {path} from the tab ({len(w)} buckets; Royalty at 0 until you set it)."]


def run(sheet, write: bool = False, all_markets: bool = False, email: bool = False, rule_levels: bool = False,
        today: date | None = None, out_dir=None) -> list[str]:
    from .history import today_ny
    today = today or today_ny()
    out_dir = out_dir or DEST
    ensure(out_dir)
    sizes = load_sizes()
    if not sizes:
        return [f"No {PRIVATE_CFG}: run `screen --init` (writes it from the tab), then set the sizes."]
    U, _ = read_universe(sheet)
    tab = read_tab(sheet)
    state = load_state()
    P = plan(U, tab, sizes, today, state, all_markets, rule_levels)
    rep = report(P, all_markets)
    pd.DataFrame(P["rows"]).to_csv(out_dir / "proposal.csv", index=False)
    lines = [f"Screen: {len(P['rows'])} screened rows proposed, {len(P['drops'])} dropped, "
             f"{len(P['warnings'])} warnings. Report (local only): {out_dir / 'report.txt'}."]
    if write:
        bad = check_lookups(sheet, P)
        if bad:
            rep += ["", "NOT WRITTEN: lookups would fail:"] + [f"  {x}" for x in bad]
            lines.append(f"Not written: {len(bad)} names or tickers wouldn't look up (see the report).")
        else:
            S = settings()["sheet"]
            a, b = S["portfolio_first_row"], S["portfolio_last_row"]
            backup = out_dir / f"backup-{time.strftime('%Y%m%d-%H%M%S')}.json"
            backup.write_text(json.dumps(sheet.read(S["portfolio_tab"], f"A{a}:V{b}", formulas=True), default=str))
            blocks = write_rows(sheet, P)
            sheet.write(blocks)
            rec = (state or {}).get("review", {})
            for r in P["rows"]:
                if not r["typed_level"]:
                    rec[r["D"]] = r["S"]
            ensure(STATE.parent)
            STATE.write_text(json.dumps({"review": rec, "written": today.isoformat()}, indent=1))
            back = sheet.read(S["portfolio_tab"], f"H{a}:T{b}")
            n_phys = len(P["physical"])
            failed = [r["B"] for i, r in enumerate(P["rows"])
                      if not _text((list(back[n_phys + i]) + [""] * 13)[0] if n_phys + i < len(back) else "")]
            rep += ["", f"Written. Backup: {backup}."]
            if failed:
                rep += ["Lookups showing blank after the write:"] + [f"  {x}" for x in failed]
            lines.append(f"Written to the Model portfolio ({len(P['rows'])} screened rows); backup in {backup}"
                         + (f"; {len(failed)} rows show a blank lookup (see the report)." if failed else "."))
            lines += write_portfolio_file(sheet)
            if email:
                from .alerts import send_email
                sent = send_email("Model portfolio: screen applied", email_body(P))
                lines.append("Emailed the changes." if sent else "Email not sent (ALERT_SMTP_URL / ALERT_EMAIL_TO "
                                                                 "not set).")
    (out_dir / "report.txt").write_text("\n".join(rep) + "\n")
    return lines + P["warnings"]


# ---------- Part 3: private/portfolio.csv ----------

def portfolio_rows(tab: list[dict], total: float, silver_held: float, holdings: dict, old: dict) -> list[dict]:
    """The backtest file's rows from the tab. holdings: {Sprott ticker: (yahoo, currency)}; old: {key: first_month}."""
    phys = cfg()["physical_symbols"]
    out = []
    for r in tab:
        key, w = _text(r["D"]), num(r["F"])
        if not key or w != w:
            continue
        y, cur = holdings.get(key, ("", ""))
        y = phys.get(key, y)
        amt = w * total
        base = {"label": _text(r["B"]), "group": _text(r["A"]), "metal": _text(r["E"]).lower(), "yahoo": y,
                "toronto_listing_in_cad": "yes" if y.endswith((".TO", ".V")) and cur == "CAD" else "no"}
        if key == "PSLV" and silver_held > 0:
            held = min(silver_held, amt)
            out.append({"key": key, **base, "amount_usd": round(held, 2), "already_held": "yes",
                        "first_month": old.get(key, "")})
            if amt - held > 0.005:
                out.append({"key": f"{key}-NEW", **base, "amount_usd": round(amt - held, 2), "already_held": "no",
                            "first_month": old.get(f"{key}-NEW", "")})
            continue
        out.append({"key": key, **base, "amount_usd": round(amt, 2), "already_held": "no",
                    "first_month": old.get(key, "")})
    return out


def write_portfolio_file(sheet, path=None) -> list[str]:
    """`portfolio-file`: private/portfolio.csv from the Model portfolio (the old one kept with a date)."""
    path = path or PORTFOLIO_FILE
    S = settings()["sheet"]
    C = S["portfolio_cols"]
    tab = read_tab(sheet)

    def one(cell):
        c, r = split_cell(cell)
        got = sheet.read(S["portfolio_tab"], f"{c}{r}")
        return num(got[0][0]) if got and got[0] else np.nan
    new_money, silver = one(C["new_money_cell"]), one(C["silver_held_value_cell"])
    total = (new_money if new_money == new_money else 0) + (silver if silver == silver else 0)
    hold = {}
    for r in sheet.read(S["holdings_tab"], f"A2:V{S['last_row']}"):
        r = list(r) + [""] * 22
        if _text(r[14]) and _text(r[14]) not in hold:
            hold[_text(r[14])] = (_text(r[15]), _text(r[18]))
    old = {}
    if path.exists():
        O = pd.read_csv(path, keep_default_na=False, dtype=str)
        old = {k: v for k, v in zip(O.key, O.first_month) if v}
        path.with_name(f"portfolio.{date.today().isoformat()}.csv").write_text(path.read_text())
    rows = portfolio_rows(tab, total, silver if silver == silver else 0.0, hold, old)
    ensure(path.parent)
    pd.DataFrame(rows, columns=PORTFOLIO_COLS).to_csv(path, index=False)
    missing = sum(1 for r in rows if not r["yahoo"])
    return [f"Wrote {path.name} for the backtest: {len(rows)} rows" + (f", {missing} without a Yahoo symbol." if missing
                                                                      else ".")]
