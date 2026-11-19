"""`snapshots`: rewrite the fund tables that don't follow the Sheet's formulas, from data/derived/.

  Summary                   A1 title; A4:K9 fund multiples (fund_multiples.csv)
  Metal prices reference    B2 title; B6:K11 multiples as reported and at today's prices, ranked by P/OCF today
                            (multiples_today.csv)
  Stress test & downside    B2 title; B6:E9 scenario prices; the EV/EBITDA, P/FCF and FCF-positive-weight tables
                            (C13:F18, C22:F27, C31:F36) and the downside table C40:L45 (stress_funds.csv)

Each table's header row is checked first; a table whose headers have moved is skipped and reported. The notes
below the tables are left alone. Run `compute` (or `refresh`) first: these are the figures it wrote.
"""
import json
import math
from datetime import date

import pandas as pd

from .config import DERIVED, OUT, ensure, settings
from .sheets import CLEAR, col_to_num, num_to_col

SUMMARY_HEADERS = ["Fund", "Focus", "P/B", "P/OCF", "P/FCF", "EV/EBITDA", "Weight with negative op. cash flow %",
                   "P/OCF, cash-positive holdings", "EV/EBITDA, EBITDA-positive holdings",
                   "Physical metal or other ETFs %", "Holdings without data %"]
TODAY_HEADERS = ["Fund", "Rank at today's prices", "P/OCF as reported", "P/OCF at today's prices",
                 "P/FCF as reported", "P/FCF at today's prices", "EV/EBITDA as reported",
                 "EV/EBITDA at today's prices", "Producers' revenue change at today's prices",
                 "P/OCF today, cash-positive holdings"]
SCENARIO_HEADERS = ["Scenario", "Gold $/oz", "Silver $/oz", "Copper $/lb"]
DOWNSIDE_HEADERS = ["Fund", "Free-cash-flow breakeven price", "Breakeven metal", "Breakeven as % of today's price",
                    "Net cash % of market value", "Working capital % of market value", "Weight burning cash %",
                    "Weight with under 2 years of cash %", "Share-count change, 1 yr % (median by fund weight)",
                    "Share-count change, 3 yrs % (median by fund weight)",
                    "Weight with share count up >20% in 3 yrs %"]
# Stress test & downside: (header row, the stress_funds.csv column prefix) for the three scenario tables
STRESS_TABLES = [(12, "EV/EBITDA "), (21, "P/FCF "), (30, "FCF+ weight ")]


def _d(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def _v(x, nd=1, neg="negative"):
    """A rounded figure; a missing multiple is "negative" (the holdings' total is ≤ 0)."""
    if x is None or (isinstance(x, float) and math.isnan(x)) or pd.isna(x):
        return neg
    return round(float(x), nd)


def summary_rows(F: pd.DataFrame) -> list[list]:
    out = []
    for f in settings()["holdings"]["fund_order"]:
        r = F.loc[f]
        out.append([f, r.focus, _v(r["P/book"]), _v(r["P/ocf"]), _v(r["P/fcf"]), _v(r["EV/EBITDA"]),
                    _v(r["neg_ocf_%"]), _v(r["P/ocf (positive only)"]), _v(r["EV/EBITDA (positive only)"]),
                    _v(r["physical_metal_%"] + r["other_%"]), _v(r["uncovered_company_%"])])
    return out


def today_rows(T: pd.DataFrame) -> list[list]:
    """Ranked by P/OCF at today's prices (cheapest first; a negative total last)."""
    T = T.loc[settings()["holdings"]["fund_order"]]
    order = T["P/OCF today"].fillna(math.inf).rank(method="first").astype(int)
    out = []
    for f in order.sort_values().index:
        r = T.loc[f]
        out.append([f, int(order[f]), _v(r["P/OCF"]), _v(r["P/OCF today"]), _v(r["P/FCF"]), _v(r["P/FCF today"]),
                    _v(r["EV/EBITDA"]), _v(r["EV/EBITDA today"]), _v(r["revenue change %"] / 100, 3, CLEAR),
                    _v(r["P/OCF today (positive only)"])])
    return out


def scenario_rows(spot: dict) -> list[list]:
    sc = settings()["scenarios"]
    out = []
    for name in settings()["stress"]["scenarios"]:
        p = spot if name == "Today" else sc[name]
        out.append([name, round(p["gold"]), round(p["silver"], 2), round(p["copper"], 2)])
    return out


def stress_rows(S: pd.DataFrame, prefix: str, nd: int = 1) -> list[list]:
    out = []
    for f in settings()["holdings"]["fund_order"]:
        r = S.loc[f]
        vals = [_v(r[prefix + n], nd, 0.0 if prefix.startswith("FCF+") else "negative")
                for n in settings()["stress"]["scenarios"]]
        out.append([f] + vals)
    return out


def downside_rows(S: pd.DataFrame) -> list[list]:
    out = []
    for f in settings()["holdings"]["fund_order"]:
        r = S.loc[f]
        out.append([f, _v(r["breakeven price"], 2, CLEAR), r["breakeven metal"], _v(r["breakeven % of today"], 1, CLEAR)]
                   + [_v(r[c], 1, CLEAR) for c in ("net cash %", "working capital %", "burning cash %",
                                                    "runway < 2 yrs %", "dil1 median", "dil3 median",
                                                    "dil3 >20% weight")])
    return out


def tables(derived=None) -> list[dict]:
    """[{tab, title_cell, title, header_cell, headers, cell, rows}] from data/derived/."""
    d = derived or DERIVED
    F = pd.read_csv(d / "fund_multiples.csv", index_col="fund")
    T = pd.read_csv(d / "multiples_today.csv", index_col="fund")
    S = pd.read_csv(d / "stress_funds.csv", index_col="fund")
    m = json.loads((d / "metals_today.json").read_text())
    held, px = _d(settings()["holdings"]["as_of"]), _d(m["date"])
    out = [
        {"tab": "Summary", "title_cell": "A1",
         "title": f"Look-through valuation of Sprott miner ETFs (holdings as of {held}; prices as of {px} close)",
         "header_cell": "A3", "headers": SUMMARY_HEADERS, "cell": "A4", "rows": summary_rows(F)},
        {"tab": "Metal prices reference", "title_cell": "B2",
         "title": f"Multiples re-estimated at today's metal prices (COMEX close {px}; holdings as of {held})",
         "header_cell": "B5", "headers": TODAY_HEADERS, "cell": "B6", "rows": today_rows(T)},
        {"tab": "Stress test & downside", "title_cell": "B2",
         "title": f"Rick Rule-style checks: metal-price stress test, downside and dilution (share prices {px}; "
                  f"holdings {held})",
         "header_cell": "B5", "headers": SCENARIO_HEADERS, "cell": "B6", "rows": scenario_rows(m)},
    ]
    scen = settings()["stress"]["scenarios"]
    for hrow, prefix in STRESS_TABLES:
        out.append({"tab": "Stress test & downside", "header_cell": f"B{hrow}", "headers": ["Fund"] + scen,
                    "cell": f"B{hrow + 1}", "rows": stress_rows(S, prefix)})
    out.append({"tab": "Stress test & downside", "header_cell": "B39", "headers": DOWNSIDE_HEADERS,
                "cell": "B40", "rows": downside_rows(S)})
    return out


def tables_layout() -> list[dict]:
    """Each table's tab, header cell and headers (no data needed)."""
    scen = ["Fund"] + settings()["stress"]["scenarios"]
    return ([{"tab": "Summary", "header_cell": "A3", "headers": SUMMARY_HEADERS},
             {"tab": "Metal prices reference", "header_cell": "B5", "headers": TODAY_HEADERS},
             {"tab": "Stress test & downside", "header_cell": "B5", "headers": SCENARIO_HEADERS}]
            + [{"tab": "Stress test & downside", "header_cell": f"B{h}", "headers": scen} for h, _ in STRESS_TABLES]
            + [{"tab": "Stress test & downside", "header_cell": "B39", "headers": DOWNSIDE_HEADERS}])


def _rng(cell: str, nrows: int, ncols: int) -> str:
    from .sheets import split_cell
    c, r = split_cell(cell)
    return f"{cell}:{num_to_col(col_to_num(c) + ncols - 1)}{r + nrows - 1}"


def _same(a, b) -> bool:
    if b == CLEAR:
        return a in ("", None)
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def run(sheet, dry_run=False, out_dir=None, derived=None) -> list[str]:
    out_dir = out_dir or OUT / "snapshots"
    ensure(out_dir)
    rep, blocks = [], []
    for t in tables(derived):
        name = f"{t['tab']}!{_rng(t['cell'], len(t['rows']), len(t['headers']))}"
        got = sheet.read(t["tab"], _rng(t["header_cell"], 1, len(t["headers"])))
        have = [str(x).strip() for x in (got[0] if got else [])]
        if have[:len(t["headers"])] != t["headers"]:
            rep.append(f"{name}: skipped, the headers in {t['tab']}!{t['header_cell']} don't match "
                       f"(found {have}). Find out what moved before changing the code.")
            continue
        rng = _rng(t["cell"], len(t["rows"]), len(t["headers"]))
        cur = sheet.read(t["tab"], rng)
        n = sum(not _same(cur[i][j] if i < len(cur) and j < len(cur[i]) else "", v)
                for i, row in enumerate(t["rows"]) for j, v in enumerate(row))
        if t.get("title_cell"):
            ct = sheet.read(t["tab"], t["title_cell"])
            if not ct or not ct[0] or str(ct[0][0]) != t["title"]:
                n += 1
                blocks.append((t["tab"], t["title_cell"], [[t["title"]]]))
        blocks.append((t["tab"], t["cell"], t["rows"]))
        rep.append(f"{name}: {n} cells change.")
    if dry_run:
        (out_dir / "dry_run.json").write_text(json.dumps(
            [{"tab": t, "cell": c, "values": v} for t, c, v in blocks], indent=1, default=str))
        rep.append(f"Dry run: nothing written. The tables are in {out_dir / 'dry_run.json'}.")
    else:
        rep.append(f"Wrote {sheet.write(blocks)} cells.")
    (out_dir / "report.txt").write_text("\n".join(rep) + "\n")
    return rep
