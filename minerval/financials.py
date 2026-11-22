"""Write refreshed company data to the Sheet (after `refresh`, i.e. after each earnings season).

Rows are matched by key, not by position, so added or re-sorted rows are fine:
  Holdings            columns I:N and Q, matched on fund (A) + Sprott ticker (O)
  Holdings downside   columns D:J and M:Q, matched on fund (A) + Sprott ticker (L); K is a formula
  PNAV inputs         columns E:H and M:O, matched on the Yahoo symbol (AP). Rows with a fixed price
                      (AQ, the physical trusts) are skipped, and F:H and M:O are written only where
                      column I names a cash-flow basis, since I:L and P:S are research inputs.
                      Once `setup-sheet` has added them: AX:AY (cash, 12-month free cash flow) on every
                      row, and Holdings downside R (cost base, revenue - FCF); CC:CG, CM:CO and CQ:CS
                      (valuation by tier) from data/derived/valuation.csv, written by `valuation`, which must
                      be newer than pnav.csv. The formula columns CH:CL and CP are never written.
Cells whose new value is missing are cleared, so stale figures don't linger.
"""
import math

import pandas as pd

from .config import DERIVED, OUT, settings
from .sheets import CLEAR, blocks_by_row, col_to_num, column, split_cell

ADDON_HEADER = "Jurisdiction add-on"
UNIT = {"gold": "gold $/oz", "silver": "silver $/oz", "copper": "copper $/lb"}


def _num(v, nd):
    if v is None or (isinstance(v, float) and math.isnan(v)) or pd.isna(v):
        return CLEAR
    return round(float(v), nd)


def _m(v, nd=1):
    return CLEAR if v is None or pd.isna(v) else round(float(v) / 1e6, nd)


def holdings_rows(X: pd.DataFrame) -> dict:
    """{(fund, ticker): [I, J, K, L, M, N] values} and notes."""
    out = {}
    for _, r in X.iterrows():
        net_debt = _m(r.debt - r.cash) if pd.notna(r.mcap) else CLEAR
        out[(r.fund, r.ticker)] = ([_m(r.ocf), _m(r.fcf), _m(r.ebitda), _m(r.book), net_debt,
                                    r.fin_date if isinstance(r.fin_date, str) else CLEAR],
                                   r.note if isinstance(r.note, str) and r.note else CLEAR)
    return out


def downside_rows(M: pd.DataFrame) -> dict:
    """{(fund, ticker): ([D..J], [M..Q])}."""
    out = {}
    for _, r in M.iterrows():
        co = r.kind == "company"
        be, bm = CLEAR, CLEAR
        if co and pd.notna(r.get("be_k")):
            bm = UNIT[r.be_metal]
            be = round(float(r.be_price), 2) if 0 < r.be_k <= 3 else ("below zero" if r.be_k <= 0 else "over 3x today")
        left = [_num(r.netcash_pct, 1) if co else CLEAR, _num(r.get("wc_pct"), 1) if co else CLEAR,
                _num(r.get("runway"), 1), _num(r.get("dil1"), 1) if co else CLEAR,
                _num(r.get("dil3"), 1) if co else CLEAR, be, bm]
        if co and pd.notna(r.get("fcf_intercept_m")):
            right = [r.ticker, round(r.fcf_intercept_m, 4), round(r.fcf_per_gold_m, 8),
                     round(r.fcf_per_silver_m, 6), round(r.fcf_per_copper_m, 4)]
        else:
            right = [r.ticker, CLEAR, CLEAR, CLEAR, CLEAR]
        right.append(_num(r.get("cost_base_m"), 4) if co else CLEAR)          # R, once setup-sheet has added it
        out[(r.fund, r.ticker)] = (left, right)
    return out


def pnav_rows(I: pd.DataFrame) -> dict:
    """{yahoo symbol: ([E], [F, G, H], [M, N, O], [AX, AY], [P] or None)}. P (the jurisdiction add-on, as a fraction)
    only for rows whose add-on comes from the country table or an override; manual rows keep the Sheet's value."""
    out = {}
    for _, r in I.iterrows():
        if not isinstance(r.yahoo, str):
            continue
        e = [_num(r.get("net_cash_m"), 2)]
        fgh = [_num(r.get(k), 2) for k in ("revenue_m", "fcf_m", "ocf_m")]
        mno = [_num(r.get(f"avg_{m}"), 4) for m in ("gold", "silver", "copper")]
        cash = [_num(r.get("cash_m"), 2), _num(r.get("fcf_12m_m"), 2)]
        addon = None
        if str(r.get("addon_basis", "")) in ("table", "override") and pd.notna(r.get("addon_pct_points")):
            addon = [round(float(r.addon_pct_points) / 100, 6)]
        out.setdefault(r.yahoo, (e, fgh, mno, cash, addon))
    return out


def _text(v):
    return CLEAR if v is None or (isinstance(v, float) and math.isnan(v)) or str(v).strip() == "" else str(v)


def valuation_rows(V: pd.DataFrame) -> dict:
    """{yahoo symbol: ([CC:CG], [CM:CO], [CQ:CS])} from data/derived/valuation.csv: the basis, NPV at each deck and
    base-deck cash flow; dilution at each overrun and the financing note; buy-below, fair value and why."""
    c = settings()["valuation"]
    out = {}
    for _, r in V.iterrows():
        y = r.get("yahoo")
        if not isinstance(y, str) or not y.strip():
            continue
        left = [_text(r.get("valuation_basis"))] + [_num(r.get(f"npv {d}"), 1) for d in c["decks"]] \
            + [_num(r.get("cf_base"), 1)]
        mid = [_num(r.get(f"dilution +{o:.0%}"), 4) for o in c["capex_overrun"]] + [_text(r.get("financing_note"))]
        right = [_num(r.get("buy_below"), 2), _num(r.get("fair_value"), 2), _text(r.get("why"))]
        out.setdefault(y.strip(), (left, mid, right))
    return out


def _has_header(sheet, tab, cell, header) -> bool:
    """True when the column exists and its header is in place (setup-sheet has run)."""
    col, row = split_cell(cell)
    if sheet.col_count(tab) < col_to_num(col):
        return False
    got = sheet.read(tab, cell)
    return bool(got and got[0] and str(got[0][0]).strip() == header)


def _keys(sheet, tab, first, last, key_cols):
    """{row: tuple of key values} from the given key columns."""
    cols = [column(sheet.read(tab, f"{c}{first}:{c}{last}"), first) for c in key_cols]
    out = {}
    for r in cols[0]:
        k = tuple(str(c.get(r, "")).strip() for c in cols)
        if all(k):
            out[r] = k if len(k) > 1 else k[0]
    return out


def _same(a, b) -> bool:
    if a in ("", None) and (b == CLEAR or b in ("", None)):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-9 + 1e-6 * abs(b)
    return str(a).lstrip("'") == str(b)


def _changes(sheet, tab, col, values: dict) -> int:
    """How many cells in `values` ({row: [cells]}) differ from what the sheet holds now."""
    if not values:
        return 0
    ncol = max(len(v) for v in values.values())
    lo, hi = min(values), max(values)
    from .sheets import col_to_num, num_to_col
    end = num_to_col(col_to_num(col) + ncol - 1)
    cur = sheet.read(tab, f"{col}{lo}:{end}{hi}")
    n = 0
    for r, vals in values.items():
        row = cur[r - lo] if r - lo < len(cur) else []
        for j, v in enumerate(vals):
            if not _same(row[j] if j < len(row) else "", v):
                n += 1
    return n


def run(sheet, dry_run=False, out_dir=None):
    S = settings()["sheet"]
    last = S["last_row"]
    out_dir = out_dir or OUT / "financials"
    out_dir.mkdir(parents=True, exist_ok=True)
    X = pd.read_csv(DERIVED / "holdings_detail.csv")
    M = pd.read_csv(DERIVED / "stress_holdings.csv")
    I = pd.read_csv(DERIVED / "pnav.csv")
    blocks, rep = [], []

    # Holdings
    tab = S["holdings_tab"]
    want = holdings_rows(X)
    keys = _keys(sheet, tab, 2, last, ["A", "O"])
    vals = {r: want[k][0] for r, k in keys.items() if k in want}
    notes = {r: [want[k][1]] for r, k in keys.items() if k in want}
    ch = _changes(sheet, tab, "I", vals) + _changes(sheet, tab, "Q", notes)
    blocks += blocks_by_row(tab, "I", vals) + blocks_by_row(tab, "Q", notes)
    rep.append(f"{tab}: {len(vals)} rows matched, {ch} cells change.")
    missing = sorted(set(want) - set(keys.values()))
    if missing:
        rep.append(f"  In the data but not on {tab} (add a row for each, then rerun): "
                   + ", ".join(f"{f} {t}" for f, t in missing))
    extra = sorted(r for r, k in keys.items() if k not in want)
    if extra:
        rep.append(f"  On {tab} but not in data/holdings.csv (left as they were): rows " + ", ".join(map(str, extra)))

    # Holdings downside
    tab = S["downside_tab"]
    want = downside_rows(M)
    from .layout import DOWNSIDE_COST_HEADER, PNAV_HEADERS
    D = S["downside_cols"]
    if not _has_header(sheet, tab, f"{D['cost_base']}{S['downside_first_row'] - 1}", DOWNSIDE_COST_HEADER):
        want = {k: (left, right[:-1]) for k, (left, right) in want.items()}
        rep.append(f"  {tab}!{D['cost_base']} (cost base) not set up yet: run `setup-sheet` to add it.")
    keys = _keys(sheet, tab, 2, last, ["A", "L"])
    left = {r: want[k][0] for r, k in keys.items() if k in want}
    right = {r: want[k][1] for r, k in keys.items() if k in want}
    ch = _changes(sheet, tab, "D", left) + _changes(sheet, tab, "M", right)
    blocks += blocks_by_row(tab, "D", left) + blocks_by_row(tab, "M", right)
    rep.append(f"{tab}: {len(left)} rows matched, {ch} cells change.")
    missing = sorted(set(want) - set(keys.values()))
    if missing:
        rep.append(f"  In the data but not on {tab}: " + ", ".join(f"{f} {t}" for f, t in missing))

    # PNAV inputs
    tab = S["pnav_inputs_tab"]
    a, b = S["pnav_first_row"], S["pnav_last_row"]
    want = pnav_rows(I)
    sym = column(sheet.read(tab, f"AP{a}:AQ{b}"), a)
    fixed = {r: v for r, v in column(sheet.read(tab, f"AP{a}:AQ{b}"), a, 1).items() if str(v).strip()}
    basis = column(sheet.read(tab, f"I{a}:I{b}"), a)
    P = S["pnav_inputs"]
    has_cash = _has_header(sheet, tab, f"{P['cash']}{a - 1}", PNAV_HEADERS["cash"])
    e, fgh, mno, cash, addon, unknown = {}, {}, {}, {}, {}, []
    for r, s in sym.items():
        s = str(s).strip()
        if not s or r in fixed:
            continue
        if s not in want:
            unknown.append(s)
            continue
        e[r] = want[s][0]
        cash[r] = want[s][3]
        if str(basis.get(r, "")).strip():
            fgh[r], mno[r] = want[s][1], want[s][2]
            if want[s][4] is not None:
                addon[r] = want[s][4]
    ch = _changes(sheet, tab, "E", e) + _changes(sheet, tab, "F", fgh) + _changes(sheet, tab, "M", mno)
    blocks += blocks_by_row(tab, "E", e) + blocks_by_row(tab, "F", fgh) + blocks_by_row(tab, "M", mno)
    if has_cash:
        ch += _changes(sheet, tab, P["cash"], cash)
        blocks += blocks_by_row(tab, P["cash"], cash)
    else:
        rep.append(f"  {tab}!{P['cash']}:{P['fcf_12m']} (cash, free cash flow) not set up yet: run `setup-sheet`.")
    if _has_header(sheet, tab, f"{P['addon']}{a - 1}", ADDON_HEADER):
        n_add = _changes(sheet, tab, P["addon"], addon)
        ch += n_add
        blocks += blocks_by_row(tab, P["addon"], addon)
        rep.append(f"  Jurisdiction add-on ({P['addon']}): {len(addon)} rows from the country table or an override "
                   f"({n_add} change); the other rows keep the Sheet's hand-set figure.")
    else:
        rep.append(f"  {tab}!{P['addon']}{a - 1} isn't headed {ADDON_HEADER!r}: the add-on was not written.")
    # Valuation by tier: CC:CG, CM:CO, CQ:CS (CH:CL and CP are formulas over today's EV)
    from .layout import valuation_headers
    span = f"{P['valuation_basis']}:{P['valuation_why']}"
    vpath = DERIVED / "valuation.csv"
    if not _has_header(sheet, tab, f"{P['valuation_basis']}{a - 1}", valuation_headers()["valuation_basis"]):
        rep.append(f"  {tab}!{span} (valuation) not set up yet: run `setup-sheet`.")
    elif not vpath.exists():
        rep.append(f"  Valuation ({span}): no {vpath.name}: run `valuation` first.")
    elif vpath.stat().st_mtime < (DERIVED / "pnav.csv").stat().st_mtime:
        rep.append(f"  Valuation ({span}): {vpath.name} is older than pnav.csv: run `valuation` first.")
    else:
        want_v = valuation_rows(pd.read_csv(vpath))
        vl, vm, vr = {}, {}, {}
        for r, s in sym.items():
            s = str(s).strip()
            if s and r not in fixed and s in want_v:
                vl[r], vm[r], vr[r] = want_v[s]
        n_v = (_changes(sheet, tab, P["valuation_basis"], vl) + _changes(sheet, tab, P["dilution_15"], vm)
               + _changes(sheet, tab, P["buy_below_value"], vr))
        ch += n_v
        blocks += (blocks_by_row(tab, P["valuation_basis"], vl) + blocks_by_row(tab, P["dilution_15"], vm)
                   + blocks_by_row(tab, P["buy_below_value"], vr))
        rep.append(f"  Valuation ({span}): {len(vl)} rows ({n_v} cells change).")
    rep.append(f"{tab}: {len(e)} rows matched, {ch} cells change.")
    if unknown:
        rep.append(f"  Yahoo symbols in {tab}!AP with no data (left as they were): " + ", ".join(unknown))

    if dry_run:
        rows = [{"tab": t, "cell": c, "values": v} for t, c, v in blocks]
        pd.DataFrame(rows).to_json(out_dir / "dry_run.json", orient="records", indent=1)
        rep.append(f"Dry run: nothing written. The blocks are in {out_dir / 'dry_run.json'}.")
    else:
        n = sheet.write(blocks)
        rep.append(f"Wrote {n} cells.")
    (out_dir / "report.txt").write_text("\n".join(rep) + "\n")
    return rep
