"""Signal history and company history on the Sheet, so each day's readings are kept.

Signal history (one row per date): A Date, B Source ("live" or "backfill"), then one column per signal key,
found by the key in row 1, so columns can be reordered and new signals get a new column at the right.
A second run on the same date replaces that date's row; a live row is never replaced by a backfilled one.

Company history (long format): Date, Holding, Yahoo, Metric, Value. Royalty companies' independent P/NAV and
price, and developers' EV per gold-equivalent ounce, months of cash and cash share. A second run on the same
date replaces that date's rows.

Both live on the Sheet rather than in out/, because the scheduled run is on GitHub, where out/ is thrown away.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .config import settings
from .sheets import CLEAR, col_to_num, num_to_col

NY = ZoneInfo("America/New_York")
FIRST = ["Date", "Source"]
COMPANY_HEADER = ["Date", "Holding", "Yahoo", "Metric", "Value"]
CHUNK = 1000                   # rows added to a tab at a time
ROYALTY = "Royalty/streaming"


def today_ny() -> date:
    """The run date in New York (GitHub's runners are on UTC)."""
    return datetime.now(NY).date()


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _iso(v) -> str:
    s = "" if v is None else str(v).strip()
    if not s:
        return ""
    try:
        return pd.Timestamp(s).date().isoformat()
    except (ValueError, TypeError):
        return s


def _cell(v):
    return v if _num(v) else CLEAR


def _read_all(sheet, tab: str, ncols: int) -> list[list]:
    return sheet.read(tab, f"A1:{num_to_col(ncols)}{sheet.row_count(tab)}")


def _width(sheet, tab: str, need: int) -> int:
    """Columns to read: the tab's width (capped; nothing here is that wide) or what we need, if more."""
    return max(min(sheet.col_count(tab), 300), need)


def _make_room(sheet, tab: str, last_row: int, formats) -> bool:
    """Lengthen the tab in chunks so the next writes fit; reapply number formats to the new rows."""
    if sheet.row_count(tab) >= last_row:
        return False
    sheet.ensure_rows(tab, (last_row // CHUNK + 1) * CHUNK)
    sheet.number_formats([(tab, f"{c}2:{c}{sheet.row_count(tab)}", p) for c, p in formats])
    return True


# ---------- Signal history ----------

def signal_formats(header: list[str]) -> list[tuple]:
    from .signals import BY_KEY
    out = [("A", "yyyy-mm-dd")]
    for i, k in enumerate(header):
        if k in BY_KEY:
            out.append((num_to_col(i + 1), BY_KEY[k].fmt))
    return out


def upsert_signals(sheet, entries: dict, keys: list[str], dry_run: bool = False) -> list[str]:
    """entries: {iso date: (source, {key: value})}. Writes or replaces those dates' rows. Returns report lines."""
    tab = settings()["sheet"]["signal_history_tab"]
    if not entries:
        return []
    if not sheet.has_tab(tab):
        if dry_run:
            return [f"Signal history: would create the {tab} tab and write {len(entries)} rows."]
        sheet.ensure_tab(tab, rows=CHUNK, cols=len(FIRST) + len(keys))
    grid = _read_all(sheet, tab, _width(sheet, tab, len(FIRST) + len(keys)))
    header = [str(x).strip() for x in (grid[0] if grid else [])]
    while header and not header[-1]:
        header.pop()
    if not header:
        header = list(FIRST)
    if header[:2] != FIRST:
        return [f"Signal history: not written: {tab}!A1:B1 should be {FIRST}, not {header[:2]}."]
    old_header = list(header)
    for k in keys:
        if k not in header:
            header.append(k)
    added_cols = header[len(old_header):]

    existing = {}                                   # date -> (row number, row)
    for i, row in enumerate(grid[1:], start=2):
        d = _iso(row[0] if row else "")
        if d:
            existing[d] = (i, list(row))
    last_row = max([i for i, _ in existing.values()], default=1)
    last_date = max(existing, default="")

    def build(d, source, vals):
        return [d, source] + [_cell(vals.get(k)) for k in header[2:]]

    todo = {}
    skipped = 0
    for d, (source, vals) in sorted(entries.items()):
        old_source = existing[d][1][1] if d in existing and len(existing[d][1]) > 1 else ""
        if source == "backfill" and old_source == "live":
            skipped += 1                            # a live row wins over a backfilled one
            continue
        todo[d] = build(d, source, vals)

    blocks, lines = [], []
    if header != old_header:
        blocks.append((tab, "A1", [header]))
    inserts = [d for d in todo if d not in existing and d < last_date]
    if inserts:                                     # older dates: rewrite everything in date order
        merged = {d: row + [CLEAR] * (len(header) - len(row)) for d, (_, row) in existing.items()}
        merged.update(todo)
        rows = [merged[d] for d in sorted(merged)]
        blocks.append((tab, "A2", rows))
        need = 1 + len(rows)
        lines.append(f"Signal history: {len(todo)} rows written ({len(inserts)} older dates, so the tab was "
                     f"rewritten in date order).")
    else:
        nxt = last_row + 1
        for d, row in todo.items():
            if d in existing:
                blocks.append((tab, f"A{existing[d][0]}", [row]))
            else:
                blocks.append((tab, f"A{nxt}", [row]))
                nxt += 1
        need = nxt - 1
        replaced = sum(d in existing for d in todo)
        lines.append(f"Signal history: {len(todo) - replaced} rows added, {replaced} replaced"
                     + (f" ({min(todo)} to {max(todo)})." if len(todo) > 1 else f" ({next(iter(todo))})."
                        if todo else "."))
    if skipped:
        lines.append(f"Signal history: {skipped} backfilled dates skipped (live rows kept).")
    if added_cols and existing:
        lines.append("Signal history: new columns: " + ", ".join(added_cols))
    if dry_run:
        return [ln.replace("Signal history: ", "Signal history (dry run): ") for ln in lines]

    sheet.ensure_cols(tab, len(header))
    fmts = signal_formats(header)
    fresh = not existing
    if not _make_room(sheet, tab, need, fmts):     # (which formats every column when it adds rows)
        todo_fmts = [(c, p) for c, p in fmts if fresh or col_to_num(c) > len(old_header)]
        sheet.number_formats([(tab, f"{c}2:{c}{sheet.row_count(tab)}", p) for c, p in todo_fmts])
    sheet.write(blocks)
    return lines


# ---------- Company history ----------

def company_rows(pnav_grid: list[list], d: str) -> list[list]:
    """[date, holding, yahoo, metric, value] for royalty and developer rows of PNAV inputs (read from column A)."""
    P = settings()["sheet"]["pnav_inputs"]
    ix = {k: col_to_num(P[k]) - 1 for k in ("holding", "yahoo", "price", "nav_per_share", "independent_pnav",
                                             "peer_group", "ev_per_aueq_oz", "months_of_cash", "cash_share",
                                             "developer_check")}
    width = max(ix.values()) + 1
    out, seen = [], set()
    for row in pnav_grid:
        r = list(row) + [""] * (width - len(row))
        holding, sym = str(r[ix["holding"]]).strip(), str(r[ix["yahoo"]]).strip()
        if not holding:
            continue
        royalty = str(r[ix["peer_group"]]).strip() == ROYALTY and r[ix["nav_per_share"]] not in ("", None)
        metrics = (("independent_pnav", "price") if royalty else
                   ("ev_per_aueq_oz", "months_of_cash", "cash_share") if str(r[ix["developer_check"]]).strip()
                   else ())
        for m in metrics:
            v = r[ix[m]]
            name = "price_usd" if m == "price" else m
            if _num(v) and (sym or holding, name) not in seen:
                seen.add((sym or holding, name))
                out.append([d, holding, sym, name, v])
    return out


def upsert_company(sheet, rows: list[list], d: str, dry_run: bool = False) -> list[str]:
    tab = settings()["sheet"]["company_history_tab"]
    if not rows:
        return ["Company history: no royalty or developer rows found on PNAV inputs."]
    if not sheet.has_tab(tab):
        if dry_run:
            return [f"Company history (dry run): would create the {tab} tab and write {len(rows)} rows for {d}."]
        sheet.ensure_tab(tab, rows=CHUNK, cols=len(COMPANY_HEADER))
    grid = _read_all(sheet, tab, len(COMPANY_HEADER))
    header = [str(x).strip() for x in (grid[0] if grid else [])]
    blocks = []
    if not any(header):
        blocks.append((tab, "A1", [COMPANY_HEADER]))
    elif header[:5] != COMPANY_HEADER:
        return [f"Company history: not written: {tab}!A1:E1 should be {COMPANY_HEADER}."]
    dates = [_iso(r[0] if r else "") for r in grid[1:]]
    last = max([i for i, x in enumerate(dates, start=2) if x], default=1)
    if any(x > d for x in dates if x):
        return [f"Company history: not written: the tab already has dates after {d}."]
    same = [i for i, x in enumerate(dates, start=2) if x == d]
    start = min(same) if same else last + 1
    blocks.append((tab, f"A{start}", rows))
    end = start + len(rows) - 1
    if last > end:                                  # fewer rows than this date had before: clear the rest
        blocks.append((tab, f"A{end + 1}", [[CLEAR] * 5 for _ in range(last - end)]))
    verb = "replaced" if same else "added"
    line = f"Company history: {len(rows)} rows {verb} for {d}."
    if dry_run:
        return [line.replace("Company history: ", "Company history (dry run): ")]
    _make_room(sheet, tab, max(end, last), [("A", "yyyy-mm-dd")])
    sheet.write(blocks)
    return [line]


# ---------- called by signals.run ----------

def record(sheet, rows: list[dict], today: date, dry_run: bool = False) -> list[str]:
    """Record today's signal values (stale ones left blank) and company metrics. Never raises."""
    from .signals import SIGNALS
    if today.weekday() >= 5:
        return [f"History: not recorded ({today} is a weekend)."]
    lines = []
    try:
        vals = {r["key"]: (None if r.get("stale") else r["value"]) for r in rows}
        lines += upsert_signals(sheet, {today.isoformat(): ("live", vals)}, [s.key for s in SIGNALS], dry_run)
    except Exception as e:                          # history must never fail the update
        lines.append(f"Signal history not written: {type(e).__name__}: {e}")
    try:
        S = settings()["sheet"]
        P = S["pnav_inputs"]
        last = max(col_to_num(P[k]) for k in ("developer_check", "yahoo"))
        grid = sheet.read(S["pnav_inputs_tab"], f"A{S['pnav_first_row']}:{num_to_col(last)}{S['pnav_last_row']}")
        lines += upsert_company(sheet, company_rows(grid, today.isoformat()), today.isoformat(), dry_run)
    except Exception as e:
        lines.append(f"Company history not written: {type(e).__name__}: {e}")
    return lines


# ---------- backfill ----------

def no_backfill(key: str) -> bool:
    """Signals that can't be recomputed for past dates: they need past fundamentals, past P/NAVs, or (the AISC
    margin) a dated industry cost that only the signal backtest adds."""
    return key.startswith("fcf_yield_") or key in ("royalty_pnav_median", "aisc_margin")


def truncate(data: dict, d) -> dict:
    """The cached series as they stood at the close on date d."""
    ts = pd.Timestamp(d)

    def cut(s):
        return None if s is None else s[s.index <= ts]
    return {"daily": {k: cut(s) for k, s in data.get("daily", {}).items()},
            "monthly": {k: cut(s) for k, s in data.get("monthly", {}).items()},
            "real_yield": cut(data.get("real_yield"))}


def backfill_entries(data: dict, start, end) -> dict:
    """{iso date: ("backfill", values)} for each day gold traded between start and end."""
    from .signals import compute
    gold = data.get("daily", {}).get("GC=F")
    if gold is None or gold.empty:
        return {}
    days = gold.index[(gold.index >= pd.Timestamp(start)) & (gold.index <= pd.Timestamp(end))]
    out = {}
    for ts in days:
        rows = compute(truncate(data, ts), ts.date())
        out[ts.date().isoformat()] = ("backfill", {r["key"]: r["value"] for r in rows if not no_backfill(r["key"])})
    return out


def backfill(sheet, start, end=None, dry_run: bool = False) -> list[str]:
    from .signals import SIGNALS, load_cache
    end = end or today_ny()
    entries = backfill_entries(load_cache(), start, end)
    if not entries:
        return ["Backfill: no cached daily gold prices in that range (run `signals` first to download them)."]
    first = min(entries)
    return ([f"Backfill: {len(entries)} trading days from {first} to {max(entries)} (from the cached series; "
             "12-month and 200-day signals are blank until a year of data precedes the date)."]
            + upsert_signals(sheet, entries, [s.key for s in SIGNALS], dry_run))
