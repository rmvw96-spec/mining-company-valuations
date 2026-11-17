"""Daily update: share prices, FX rates, metal prices and the 10-year yield.

Writes, on the Holdings tab: R price (local currency), S currency, T price date for every row with
a Yahoo symbol in P; the FX table's rate, source and date (Z, AA, AB); and, with --shares, U shares
outstanding (millions). On the Metal prices reference tab: today's gold, silver and copper prices
(C15:C17) and the 10-year Treasury yield (C30). Everything else on the Sheet recalculates from these.
"""
import json
import time
from datetime import date, timedelta

from . import yahoo
from .config import OUT, settings
from .sheets import ClaudePayloads, blocks_by_row, column, load_claude_read


class LayoutError(RuntimeError):
    pass


def _check(actual, expected, where):
    a = [str(x).strip() if x is not None else "" for x in actual]
    a += [""] * (len(expected) - len(a))
    if a[:len(expected)] != list(expected):
        raise LayoutError(f"{where} should read {expected} but reads {a[:len(expected)]}. "
                          "The Sheet's layout has changed: update config/settings.toml before writing.")


def read_layout(sheet):
    """Check the headers and return ({row: symbol}, {row: currency for FX rows to fetch}, FX rows, old prices)."""
    S = settings()["sheet"]
    tab, last = S["holdings_tab"], S["last_row"]
    for rng, expected in (("R1:V1", S["price_headers"]), ("Y1:AB1", S["fx_headers"])):
        got = sheet.read(tab, rng)
        _check(got[0] if got else [], expected, f"{tab}!{rng}")
    syms = {r: str(v).strip() for r, v in column(sheet.read(tab, f"P2:P{last}"), 2).items() if str(v).strip()}
    old = {}
    for r, row in enumerate(sheet.read(tab, f"R2:U{last}"), start=2):
        row = list(row) + [""] * 4
        old[r] = {"price": row[0], "cur": row[1], "shares": row[3]}
    fx = sheet.read(tab, "Y2:Z60", formulas=True)
    fx_rows, fetch = {}, {}
    for i, row in enumerate(fx):
        code = str(row[0]).strip() if row else ""
        if not code:
            break
        r = 2 + i
        fx_rows[r] = code
        z = row[1] if len(row) > 1 else ""
        if code != "USD" and not (isinstance(z, str) and z.startswith("=")):
            fetch[r] = code
    return syms, fetch, fx_rows, old


def claude_layout(symbols_file):
    """The same as read_layout for a Claude Sheet, from a saved read of Holdings!P1:P<last>."""
    S = settings()["sheet"]
    syms = {r: str(v[0]).strip() for r, v in load_claude_read(symbols_file).items()
            if r >= 2 and v and isinstance(v[0], str) and v[0].strip()}
    fx_rows = {2 + i: c for i, c in enumerate(S["fx_rows"])}
    fetch = {r: c for r, c in fx_rows.items() if c != "USD" and c not in S["fx_derived"]}
    return syms, fetch, fx_rows, {}


def metal_quotes():
    Y = settings()["yahoo"]
    syms = list(Y["metals"].values()) + [Y["ten_year_yield"]]
    return yahoo.pmap(yahoo.quote, syms)


def latest_shares(symbol):
    types = ["quarterlyOrdinarySharesNumber", "annualOrdinarySharesNumber", "quarterlyShareIssued", "annualShareIssued"]
    start = (date.today() - timedelta(days=3 * 365)).isoformat()
    ts = yahoo.timeseries(symbol, types, start)
    for group in (types[:2], types[2:]):          # ordinary shares first, then shares issued
        pts = [p for k in group for p in ts.get(k, [])]
        if pts:
            p = max(pts, key=lambda p: p["date"])
            return {"shares_m": p["val"] / 1e6, "asof": p["date"]}
    return None


def run(sheet=None, symbols_file=None, payload_dir=None, base=None, shares=False, old_shares=None,
        metals=True, dry_run=False, out_dir=None):
    """Fetch everything and write it. Returns the report lines."""
    S, R = settings()["sheet"], settings()["report"]
    out_dir = out_dir or OUT / "prices"
    out_dir.mkdir(parents=True, exist_ok=True)
    claude = sheet is None
    if claude:
        syms, fetch, fx_rows, old = claude_layout(symbols_file)
    else:
        syms, fetch, fx_rows, old = read_layout(sheet)
        if metals:
            m = S["metals_tab"]
            labels = [r[0] if r else "" for r in sheet.read(m, "B15:B17")]
            _check(labels, list(S["metal_labels"].values()), f"{m}!B15:B17")
            _check([(sheet.read(m, "B30") or [[""]])[0][0]], [S["yield_label"]], f"{m}!B30")
    today = date.today().isoformat()
    tab = S["holdings_tab"]
    Q = yahoo.pmap(yahoo.quote, sorted(set(syms.values())))
    blocks, rep = [], []

    # Prices: R price, S currency (sheet code), T date
    ok = {r: [Q[s]["price"], yahoo.sheet_code(Q[s]["currency"]), Q[s]["date"]] for r, s in syms.items() if Q.get(s)}
    blocks += blocks_by_row(tab, "R", ok)
    rep.append(f"Prices: {len(ok)} of {len(syms)} rows updated ({len(Q)} symbols).")
    fail = sorted({s for s in syms.values() if not Q.get(s)})
    if fail:
        rep.append("No price from Yahoo (left as they were; check for a renamed, delisted or taken-over company): "
                   + ", ".join(fail))

    # FX table: Z rate, AA source, AB date. Formula rows (pence, cents) follow their parent row.
    F = yahoo.pmap(yahoo.usd_per_unit, sorted(set(fetch.values())))
    fx_vals, fx_fail = {}, []
    for r, c in fetch.items():
        rate, src = F[c]
        if rate:
            fx_vals[r] = [rate, src]
        else:
            fx_fail.append(c)
    blocks += blocks_by_row(tab, "Z", fx_vals)
    blocks += blocks_by_row(tab, "AB", {r: [today] for r in fx_rows if r not in fetch or r in fx_vals})
    if fx_fail:
        rep.append("No FX rate from Yahoo (left as they were): " + ", ".join(sorted(fx_fail)))
    used = {v[1] for v in ok.values() if v[1]}
    missing = sorted(used - set(fx_rows.values()))
    if missing:
        rep.append("Currencies not in the FX table (add a row at the bottom of Holdings!Y:AB): " + ", ".join(missing))

    # Checks a person should look at
    cutoff = (date.today() - timedelta(days=R["stale_days"])).isoformat()
    stale = sorted({(s, q["date"]) for s, q in Q.items() if q and q["date"] < cutoff})
    if stale:
        rep.append(f"Price older than {R['stale_days']} days (thinly traded or suspended?): "
                   + ", ".join(f"{s} {d}" for s, d in stale))
    moves = sorted(((q["price"] / q["prev"] - 1, s) for s, q in Q.items() if q and q.get("prev")),
                   key=lambda x: -abs(x[0]))
    big = [f"{s} {m:+.0%}" for m, s in moves if abs(m) > R["big_move"]]
    if big:
        rep.append(f"Moved more than {R['big_move']:.0%} over the last 5 trading days (check for a share split or "
                   "consolidation; a split changes the share count too): " + ", ".join(big))
    since = []
    for r, v in ok.items():
        o = old.get(r, {})
        if isinstance(o.get("price"), (int, float)) and o["price"] > 0 and o.get("cur") == v[1]:
            since.append((v[0] / o["price"] - 1, syms[r]))
    if since:
        since = sorted(set(since), key=lambda x: -abs(x[0]))[:8]
        rep.append("Biggest moves since the last update: " + ", ".join(f"{s} {m:+.1%}" for m, s in since))

    # Metal prices and the 10-year yield
    if metals:
        Y = settings()["yahoo"]
        MQ = metal_quotes()
        m = S["metals_tab"]
        got = []
        for metal, sym in Y["metals"].items():
            q = MQ.get(sym)
            if q:
                blocks.append((m, S["metal_cells"][metal], [[q["price"]]]))
                got.append(f"{metal} {q['price']:,.2f} ({q['date']})")
            else:
                rep.append(f"No price for {sym} ({metal}); left as it was.")
        q = MQ.get(Y["ten_year_yield"])
        if q and 0.1 < q["price"] < 30:            # ^TNX is in percent
            blocks.append((m, S["yield_cell"], [[round(q["price"] / 100, 5)]]))
            got.append(f"10-yr yield {q['price']:.2f}% ({q['date']})")
        else:
            rep.append(f"No usable 10-year yield from {Y['ten_year_yield']}; left as it was.")
        if got:
            rep.append("Metals: " + ", ".join(got))

    # Share counts (after earnings season)
    share_blocks = []
    if shares:
        SH = yahoo.pmap(latest_shares, sorted(set(syms.values())))
        old_u = {r: v.get("shares") for r, v in old.items()}
        if old_shares:
            old_u.update({r: v[0] for r, v in load_claude_read(old_shares).items() if v})
        vals, flags = {}, []
        for r, s in syms.items():
            if SH.get(s):
                vals[r] = [SH[s]["shares_m"]]
                o = old_u.get(r)
                if isinstance(o, (int, float)) and o > 0 and abs(SH[s]["shares_m"] / o - 1) > R["share_change"]:
                    flags.append(f"row {r} {s}: {o:,.1f}M -> {SH[s]['shares_m']:,.1f}M (as of {SH[s]['asof']})")
        share_blocks = blocks_by_row(tab, "U", vals)
        rep.append(f"Shares: {len(vals)} rows.")
        nos = sorted({s for s in syms.values() if not SH.get(s)})
        if nos:
            rep.append("No share count from Yahoo (left as they were): " + ", ".join(nos))
        if flags:
            rep.append(f"Share count changed more than {R['share_change']:.0%} (check: acquisitions paid in shares, "
                       "financings, consolidations, or a US listing quoted in a different unit):\n  " + "\n  ".join(flags))

    # Write
    if claude:
        w = ClaudePayloads(payload_dir or out_dir, "prices", base)
        w.write(blocks)
        rep.append(f"Wrote {len(w.files)} price payload(s) to {w.out}.")
        if share_blocks:
            ws = ClaudePayloads(payload_dir or out_dir, "shares")
            ws.write(share_blocks)
            rep.append(f"Wrote {len(ws.files)} share payload(s); review the flags above before sending them.")
    elif dry_run:
        (out_dir / "dry_run.json").write_text(json.dumps(blocks + share_blocks, indent=1, default=str))
        rep.append(f"Dry run: nothing written. The {len(blocks + share_blocks)} blocks are in {out_dir / 'dry_run.json'}.")
    else:
        n = sheet.write(blocks + share_blocks)
        rep.append(f"Wrote {n} cells to the Sheet.")
    (out_dir / "report.txt").write_text(f"Price update {time.strftime('%Y-%m-%d %H:%M')}\n" + "\n".join(rep) + "\n")
    (out_dir / "quotes.json").write_text(json.dumps({"quotes": Q, "fx": F}, indent=1))
    return rep
