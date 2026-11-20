"""Royalty companies against their own history (roadmap 4c).

The framework's royalty band compares each company's independent P/NAV with fixed bands, and some companies sit
above them almost always. This adds a second view: each company against its own past valuation.

- P/OCF, from day one: month-end price of the US listing x shares outstanding / the latest annual operating cash
  flow the company had filed with the SEC by then (10-K, 40-F or 20-F, from EDGAR's XBRL facts). Royalty companies
  have few operating costs, so P/OCF tracks P/NAV reasonably well, but it isn't the same thing. Today's value uses
  the same basis as the history, so the percentile compares like with like. Months when the latest annual cash
  flow was zero or negative are left out.
- P/NAV, once recorded: today's independent P/NAV against the company's own rows on the Company history tab,
  blank until [royalty_history] pnav_min_days have been recorded.

The annual figures are the record in data/research/royalty_ocf.csv, written by `royalty-ocf` (run it after the
companies' annual filings, in February and March, and review the diff). `signals` writes PNAV inputs BY:CA on
every run; CB (the own-history band) and the Signals row `royalty_own_pctile_median` are formulas.
"""
import math
from datetime import date

import numpy as np
import pandas as pd

from . import yahoo
from .config import OUT, RESEARCH, ensure, settings

RECORD = RESEARCH / "royalty_ocf.csv"
COLS = ["symbol", "cik", "fiscal_start", "fiscal_end", "filed", "form", "accession", "currency", "ocf_m",
        "usd_per_unit", "ocf_usd_m", "shares_m", "shares_date", "source"]
OCF_CONCEPTS = [("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
                ("us-gaap", "NetCashProvidedByUsedInOperatingActivities")]
SHARE_CONCEPTS = [("dei", "EntityCommonStockSharesOutstanding"), ("ifrs-full", "WeightedAverageShares"),
                  ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic")]
ROYALTY = "Royalty/streaming"
BANDS = ("Cheap for itself", "Normal for itself", "Expensive for itself")


def cfg() -> dict:
    return settings()["royalty_history"]


# ---------- the record: annual operating cash flow from SEC filings ----------

def _points(facts: dict, concepts, forms) -> list[dict]:
    out = []
    for tax, name in concepts:
        f = (facts.get("facts") or {}).get(tax, {}).get(name)
        if not f:
            continue
        for unit, pts in f["units"].items():
            out += [{**p, "unit": unit, "concept": name} for p in pts if p.get("form") in forms]
    return out


def _shares(facts: dict, forms, accn: str, start: str, end: str):
    """(shares, date) reported in one filing: the cover's shares outstanding, else that year's weighted average."""
    for concept in SHARE_CONCEPTS:
        pts = [p for p in _points(facts, [concept], forms) if p.get("accn") == accn and p["unit"] == "shares"]
        if concept[0] != "dei":
            pts = [p for p in pts if p.get("start") == start and p.get("end") == end]
        if pts:
            p = max(pts, key=lambda p: p["end"])
            return float(p["val"]), p["end"]
    return None, None


def annual_rows(facts: dict, symbol: str, cik: int, usd_rate) -> list[dict]:
    """One row per fiscal year (330-400 days), as first filed; a currency other than US$ is converted with
    usd_rate(currency, start, end) (US$ per unit)."""
    forms = set(cfg()["annual_forms"])
    pts = [p for p in _points(facts, OCF_CONCEPTS, forms) if p.get("start") and p.get("end")]
    pts = [p for p in pts if 330 <= (pd.Timestamp(p["end"]) - pd.Timestamp(p["start"])).days <= 400]
    by_year = {}                            # by year end: restatements sometimes move the start by a day
    for p in pts:
        by_year.setdefault(p["end"], []).append(p)
    rows = []
    for end, ps in sorted(by_year.items()):
        first = min(p["filed"] for p in ps)
        ps = sorted((p for p in ps if p["filed"] == first), key=lambda p: p["unit"] != "USD")
        p = ps[0]
        start = p["start"]
        shares, sdate = _shares(facts, forms, p["accn"], start, end)
        rate = 1.0 if p["unit"] == "USD" else usd_rate(p["unit"], start, end)
        if shares is None or rate is None:
            continue
        ocf = float(p["val"]) / 1e6
        rows.append({"symbol": symbol, "cik": cik, "fiscal_start": start, "fiscal_end": end, "filed": first,
                     "form": p["form"], "accession": p["accn"], "currency": p["unit"], "ocf_m": round(ocf, 3),
                     "usd_per_unit": round(rate, 6), "ocf_usd_m": round(ocf * rate, 3),
                     "shares_m": round(shares / 1e6, 4), "shares_date": sdate,
                     "source": f"SEC EDGAR XBRL, {p['concept']}, {p['form']} filed {first}"
                               + ("" if p["unit"] == "USD" else f"; converted at the fiscal year's average "
                                                                f"month-end {p['unit']}=X (Yahoo)")})
    return rows


def _fx_average():
    """usd_rate(currency, start, end): the average US$ per unit over the month-ends in the period (Yahoo <CUR>=X)."""
    cache = {}

    def rate(cur, start, end):
        if cur not in cache:
            j = yahoo.history(f"{cur}=X", "1mo")
            from .signals import closes
            cache[cur] = closes(j) if j else pd.Series(dtype=float)
        s = cache[cur]
        s = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
        return float((1 / s).mean()) if len(s) else None
    return rate


def fetch_record(path=None) -> list[str]:
    """The `royalty-ocf` command: rewrite data/research/royalty_ocf.csv from EDGAR and report what changed."""
    C = cfg()
    path = path or RECORD
    headers = {"User-Agent": C["edgar_user_agent"]}
    rate = _fx_average()
    rows, lines = [], []
    for sym, cik in C["companies"].items():
        j = yahoo.get_json(C["edgar_url"].format(cik=cik), headers=headers, tries=3)
        if not j:
            lines.append(f"{sym}: EDGAR didn't answer; its old rows are kept.")
            continue
        got = annual_rows(j, sym, cik, rate)
        rows += got
        lines.append(f"{sym}: {len(got)} fiscal years, {got[0]['fiscal_end'] if got else '-'} to "
                     f"{got[-1]['fiscal_end'] if got else '-'}.")
    new = pd.DataFrame(rows, columns=COLS)
    old = load_record(path) if path.exists() else pd.DataFrame(columns=COLS)
    kept = old[~old.symbol.isin(new.symbol.unique())]
    T = pd.concat([new, kept[COLS]], ignore_index=True).sort_values(["symbol", "fiscal_end"])
    T.to_csv(path, index=False)
    before = {(r.symbol, str(r.fiscal_end)[:10]) for r in old.itertuples()}
    added = [f"{r.symbol} {r.fiscal_end}" for r in new.itertuples() if (r.symbol, r.fiscal_end) not in before]
    shown = ", ".join(added) if len(added) <= 12 else f"{len(added)} fiscal years"
    lines.append(f"Wrote {len(T)} rows to {path}" + (f"; new: {shown}." if added else "; no new years."))
    ensure(OUT / "royalty-ocf")
    (OUT / "royalty-ocf" / "report.txt").write_text("\n".join(lines) + "\n")
    return lines


def load_record(path=None) -> pd.DataFrame:
    path = path or RECORD
    if not path.exists():
        return pd.DataFrame(columns=COLS)
    T = pd.read_csv(path, keep_default_na=False, na_values=[""])
    for c in ("fiscal_end", "filed"):
        T[c] = pd.to_datetime(T[c])
    return T


# ---------- P/OCF history and percentiles ----------

def _num(v) -> bool:
    return isinstance(v, (int, float, np.floating)) and not isinstance(v, bool) and math.isfinite(v)


def pocf_history(rec: pd.DataFrame, closes: pd.Series, today: date) -> pd.Series:
    """P/OCF at each monthly bar (Yahoo's bar for the current month is today's price): price x shares / the latest
    annual operating cash flow filed by the bar's month-end (or today). NaN where that cash flow is not positive."""
    rec = rec.sort_values(["fiscal_end", "filed"])
    out = {}
    for d, px in closes.items():
        asof = min(pd.Timestamp(d) + pd.offsets.MonthEnd(0), pd.Timestamp(today))
        known = rec[rec.filed <= asof]
        if known.empty or not _num(px):
            continue
        last = known.iloc[-1]
        ocf = float(last.ocf_usd_m)
        out[pd.Timestamp(d)] = px * float(last.shares_m) / ocf if ocf > 0 else np.nan
    return pd.Series(out, dtype=float)


def percentile(x, hist) -> float | None:
    """Share of the history at or below x, 0-100 (as signals.percentile)."""
    hist = pd.Series(hist, dtype=float).dropna()
    return None if not _num(x) or hist.empty else float(100 * (hist <= x).mean())


def own_pocf(rec: pd.DataFrame, closes: pd.Series, today: date, c: dict | None = None) -> dict:
    """{"pocf": today's P/OCF, "pctile": its percentile in the last `years` of month-ends, "months": how many}."""
    c = c or cfg()
    s = pocf_history(rec, closes, today)
    if s.empty:
        return {"pocf": None, "pctile": None, "months": 0}
    cur = s.iloc[-1]
    hist = s.iloc[:-1]
    hist = hist[hist.index > s.index[-1] - pd.DateOffset(years=c["years"])].dropna()
    ok = _num(cur) and len(hist) >= c["min_months"]
    return {"pocf": float(cur) if _num(cur) else None, "pctile": percentile(cur, hist) if ok else None,
            "months": len(hist)}


def own_pnav(history: list[tuple[str, float]], today_value, today: date, c: dict | None = None) -> float | None:
    """Today's independent P/NAV against the company's recorded days before today; None until pnav_min_days."""
    c = c or cfg()
    hist = [v for d, v in history if d < today.isoformat() and _num(v)]
    return percentile(today_value, hist) if len(hist) >= c["pnav_min_days"] else None


def band(pnav_pctile, pocf_pctile, lo: float, hi: float) -> str:
    """The own-history band, as PNAV inputs CB computes it: the P/NAV percentile when there is one, else P/OCF."""
    p, basis = (pnav_pctile, "P/NAV") if _num(pnav_pctile) else (pocf_pctile, "P/OCF")
    if not _num(p):
        return ""
    text = BANDS[0] if p <= lo else BANDS[2] if p >= hi else BANDS[1]
    return f"{text} ({basis} percentile {math.floor(p + 0.5)})"       # TEXT(p,"0") rounds half up


# ---------- the Sheet ----------

def _pnav_history(sheet) -> dict:
    """{yahoo symbol: [(date, independent P/NAV)]} from the Company history tab."""
    from .history import _iso
    tab = settings()["sheet"]["company_history_tab"]
    if not sheet.has_tab(tab):
        return {}
    out = {}
    for r in sheet.read(tab, f"A2:E{sheet.row_count(tab)}"):
        r = list(r) + [""] * 5
        d = _iso(r[0])
        if d and str(r[3]).strip() == "independent_pnav" and _num(r[4]):
            out.setdefault(str(r[2]).strip() or str(r[1]).strip(), []).append((d, float(r[4])))
    return out


def update_sheet(sheet, monthly: dict, today: date, dry_run: bool = False) -> tuple[list[str], list[float]]:
    """Write PNAV inputs BY:CA (P/OCF, its own percentile, the own P/NAV percentile) for the royalty rows and
    clear them elsewhere. Returns (report lines, the percentile each royalty row's band uses)."""
    from .sheets import CLEAR, col_to_num, num_to_col
    S = settings()["sheet"]
    P, a, b, tab = S["pnav_inputs"], S["pnav_first_row"], S["pnav_last_row"], S["pnav_inputs_tab"]
    C = cfg()
    ix = {k: col_to_num(P[k]) - 1 for k in ("holding", "yahoo", "peer_group", "independent_pnav")}
    grid = sheet.read(tab, f"A{a}:{num_to_col(max(ix.values()) + 1)}{b}")
    rec = load_record()
    hist = _pnav_history(sheet)
    cache, out, used, notes = {}, [], [], []
    for i in range(b - a + 1):
        r = list(grid[i]) if i < len(grid) else []
        r += [""] * (max(ix.values()) + 1 - len(r))
        y = str(r[ix["yahoo"]]).strip()
        if str(r[ix["peer_group"]]).strip() != ROYALTY:
            out.append([CLEAR] * 3)
            continue
        sym = C["sheet_symbols"].get(y, y)
        if sym not in C["companies"]:
            notes.append(f"{r[ix['holding']]} ({y}): not in [royalty_history] companies")
            out.append([CLEAR] * 3)
            continue
        if sym not in cache:
            closes = monthly.get(sym)
            cache[sym] = (own_pocf(rec[rec.symbol == sym], closes, today, C) if closes is not None and len(closes)
                          else {"pocf": None, "pctile": None, "months": 0})
        o = cache[sym]
        pp = own_pnav(hist.get(y, []), r[ix["independent_pnav"]], today, C)
        out.append([o["pocf"] if _num(o["pocf"]) else CLEAR, o["pctile"] if _num(o["pctile"]) else CLEAR,
                    pp if _num(pp) else CLEAR])
        p = pp if _num(pp) else o["pctile"]
        if _num(p):
            used.append(float(p))
    lines = []
    shown = [f"{s} {v['pctile']:.0f}" if _num(v["pctile"]) else f"{s} — ({v['months']} months)"
             for s, v in cache.items()]
    lines.append("Royalty P/OCF percentiles, own " + f"{C['years']} years: " + ", ".join(shown) + ".")
    if notes:
        lines.append("Royalty rows without an own-history figure: " + "; ".join(notes) + ".")
    if dry_run:
        lines.append(f"Dry run: PNAV inputs {P['pocf']}:{P['pnav_pctile']} not written.")
    else:
        sheet.write([(tab, f"{P['pocf']}{a}", out)])
    return lines, used
