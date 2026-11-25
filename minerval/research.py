"""The research batch: what a company's record lacks, a proposal's checks, recording it, the agent's track record,
and the blind test (filing-research-agent spec, Parts 1-5).

The filing-researcher agent writes a batch to out/research/<TICKER>/proposal.json:

    ticker, kinds, made   the company, the kinds of input researched (KINDS), the date
    append                {record: [rows by column name]}
    cashflows             [{ticker, project, study_date, source, post: [...], pre, gold, silver, copper, lead, zinc,
                            prices, totals: {key: LOM total}, first}]: one entry per study, year 1 first
    set                   [{record, key, column, value, was, url}]: one cell of an existing row
    remove                [{record, key}]: a row to delete (a closed coverage gap)
    evidence              [{figure, value, unit, url, where, weight}]: published figures behind a derived value
                          (`weight` names the country_weights place a mine's production counts towards)

A figure that isn't printed in its document carries `derived` (how it was reached; a map by column when only some
of a row's figures are derived): reported for review, not recorded. `check` lists errors (which stop `record`) and review lines (for the user). `record --write` appends
rows by column name, keeps each file's line ending, and adds the batch to data/research/agent_log.csv, counting the
figures that differ from the agent's proposal.json beside it.
"""
import csv
import io
import json
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import coverage as COV
from . import documents as D
from . import jurisdiction as J
from . import studies as ST
from . import tables as TB
from .config import ROOT, settings
from .performance import MEASURES_RECORDED, UNITS
from .sustaining import PERIODS

RECORDS = {
    "capex_periods": ("data/research/capex_periods.csv", ("ticker", "period", "period_end")),
    "operations": ("data/research/operations.csv", ("ticker", "period_end", "measure", "category", "metal")),
    "projects": ("data/research/projects.csv", ("ticker", "project", "study_date")),
    "cashflows": ("data/research/project_cashflows.csv", ("ticker", "project", "study_date", "year")),
    "corrections": ("config/corrections.csv", ("ticker", "field")),
    "coverage": ("data/research/coverage.csv", ("ticker", "gap")),
    "sources": ("data/research/sources.csv", ("ticker", "url")),
    "companies": ("data/research/pnav_companies.csv", ("ticker",)),
    "agent_log": ("data/research/agent_log.csv", ("date", "ticker", "kind", "file")),
}
LOG_COLS = ["date", "ticker", "kind", "proposed", "changed", "added", "dropped", "file"]
APPENDABLE = ("capex_periods", "operations", "projects", "corrections", "coverage", "sources")
REWRITABLE = ("capex_periods", "operations", "projects", "cashflows", "coverage", "companies")   # round-trip exactly
CITED = {"capex_periods": "url", "operations": "url", "projects": "source", "corrections": "url"}
KINDS = ("sustaining", "study", "operations", "mine_production", "resources", "financing", "stage", "correction",
         "listing", "coverage")
APPEND_KIND = {"capex_periods": "sustaining", "operations": "operations", "projects": "study", "cashflows": "study",
               "corrections": "correction", "coverage": "coverage", "sources": None}
COMPANY_KIND = {
    **dict.fromkeys(("country_weights", "country_weights_source"), "mine_production"),
    **dict.fromkeys(("resource_amount", "resource_unit", "resource_category", "resource_source", "resource_date",
                     "resource_reserves", "resource_mi_excl_reserves", "resource_inferred", "resource_split_source"),
                    "resources"),
    **dict.fromkeys(("committed_funding_usd_m", "remaining_capex_usd_m", "funded_per_company", "financing_source"),
                    "financing"),
    **dict.fromkeys(("study_stage", "stage"), "stage"),
    **dict.fromkeys(("us_listing", "canada_listing", "us_otc_symbol", "listing_source"), "listing"),
}
PROJECT_STAGE = ("permits", "committed", "construction_start", "first_production", "remaining_capex_usd_m",
                 "superseded")
SUSTAINING_BUILT = ("sustaining_capex_usd_m", "capitalized_stripping_usd_m", "sustaining_leases_usd_m",
                    "sustaining_period_end", "sustaining_source")       # `research sustaining --write` builds these
CF_KEYS = {"pre": "pre_tax_fcf_usd_m", "post": "post_tax_fcf_usd_m", "gold": "payable_gold_koz",
           "silver": "payable_silver_koz", "copper": "payable_copper_mlb", "lead": "payable_lead_mlb",
           "zinc": "payable_zinc_mlb", "prices": "study_prices"}
CHECKED = {   # figures looked for in the cited document's text
    "capex_periods": ("sustaining", "capitalized_stripping", "sustaining_leases", "growth"),
    "operations": ("amount",),
    "projects": ("study_npv_usd_m", "initial_capex_usd_m", "remaining_capex_usd_m"),
    "cashflows": tuple(v for k, v in CF_KEYS.items() if k != "prices"),
    "corrections": ("value_usd_m",),
    "companies": ("committed_funding_usd_m", "remaining_capex_usd_m", "resource_amount", "resource_reserves",
                  "resource_mi_excl_reserves", "resource_inferred"),
}
COMPARED = {  # what the blind test scores (figures, and the facts the valuation reads)
    **CHECKED,
    "projects": CHECKED["projects"] + ("attributable_pct", "study_type", "study_discount_rate", "discounting",
                                       "marginal_tax_rate", "net_revenue_share", "permits", "committed",
                                       "construction_start", "first_production"),
    "coverage": ("status",),
    "companies": CHECKED["companies"] + ("country_weights", "resource_unit", "resource_category",
                                         "funded_per_company", "study_stage", "us_listing", "canada_listing",
                                         "us_otc_symbol"),
}
SCALES = (1.0, 1e-3, 1e3, 1e-6, 1e6)     # a table in thousands or units against a figure in millions, and back


# ---------- files ----------

def _path(name: str, base=None) -> Path:
    return Path(base or ROOT) / RECORDS[name][0]


def _read(name: str, base=None) -> tuple[list[str], list[dict]]:
    p = _path(name, base)
    if not p.exists():
        return [], []
    with p.open(newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        return list(rd.fieldnames or []), list(rd)


def _term(p: Path) -> str:
    return "\r\n" if p.read_bytes().endswith(b"\r\n") else "\n"


def _append(name: str, rows: list[dict], base=None) -> None:
    p = _path(name, base)
    cols, _ = _read(name, base)
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator=_term(p))
        for r in rows:
            w.writerow({c: _s(r.get(c, "")) for c in cols})


def _rewrite(name: str, cols: list[str], rows: list[dict], base=None) -> None:
    p = _path(name, base)
    term = _term(p)
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=cols, lineterminator=term)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    p.write_bytes(out.getvalue().encode("utf-8"))


# ---------- values ----------

def _s(v) -> str:
    return "" if v is None else str(v)


def _num(v) -> float | None:
    try:
        x = float(str(v).replace(",", ""))
    except ValueError:
        return None
    return x if x == x else None


def _dp(v) -> int:
    """Decimal places as written ("55.10" has two)."""
    s = _s(v).strip().replace(",", "")
    if "e" in s.lower():
        return TB._decimals(float(s))
    return len(s.split(".", 1)[1]) if "." in s else 0


def _same(p, t) -> bool:
    """A proposed value equals the record's, at the record's precision (text: the same words)."""
    a, b = _num(p), _num(t)
    if a is not None and b is not None:
        return round(a, _dp(t)) == round(b, _dp(t))
    if ":" in _s(t) and ";" in _s(t) + ";":
        try:
            pa = {(c, r): w for c, r, w in J.parse_weights(_s(p))}
            ta = {(c, r): w for c, r, w in J.parse_weights(_s(t))}
            return pa.keys() == ta.keys() and all(abs(pa[k] - ta[k]) <= 0.0015 for k in ta)
        except ValueError:
            pass
    return _s(p).strip().lower() == _s(t).strip().lower()


def doc_numbers(text: str) -> list[float]:
    """Every figure in a document's text, both ways of reading single spaces."""
    return [abs(x) for x in TB.numbers(text) + TB.numbers(text, space_thousands=True)]


class _Numbers:
    """A document's figures, rounded at each precision and scale on demand (for fast lookups)."""

    def __init__(self, nums: list[float]):
        self.nums, self.sets = nums, {}

    def has(self, value) -> bool:
        f = _num(value)
        if f is None or f == 0:
            return True
        dp = _dp(value)
        target = round(abs(f), dp)
        for s in SCALES:
            k = (dp, s)
            if k not in self.sets:
                self.sets[k] = {round(n * s, dp) for n in self.nums}
            if target in self.sets[k]:
                return True
        return False


def found_in(value, text: str) -> bool:
    """Spec A9: the figure appears in the text at its own precision, as printed or in thousands or millions, with
    commas, spaces or parentheses (a zero always passes: tables print it as a dash)."""
    return _Numbers(doc_numbers(text)).has(value)


def _first_url(s) -> str:
    m = re.search(r"https?://\S+", _s(s))
    return m.group(0).rstrip(").,;") if m else ""


def _key(row: dict, cols) -> tuple:
    return tuple(_s(row.get(c, "")).strip() for c in cols)


def _find(rows: list[dict], key: dict):
    return next((r for r in rows if all(_s(r.get(k, "")).strip() == _s(v).strip() for k, v in key.items())), None)


def _set_kind(name: str, col: str):
    if name == "companies":
        return COMPANY_KIND.get(col)
    if name == "projects":
        return "stage" if col in PROJECT_STAGE else "study"
    return APPEND_KIND.get(name)


def _cash_rows(c: dict) -> list[dict]:
    first = int(c.get("first", 1))
    return [{"ticker": c.get("ticker", ""), "project": c.get("project", ""), "study_date": c.get("study_date", ""),
             "year": str(first + i), "source": c.get("source", ""),
             **{col: _s(c[k][i]) for k, col in CF_KEYS.items() if k in c and i < len(c[k])}}
            for i in range(len(c.get("post", [])))]


# ---------- the record's allowed values ----------

def _allowed(name: str, r: dict) -> list[str]:
    g, out = (lambda c: _s(r.get(c, "")).strip()), []
    if name == "capex_periods":
        p = g("period")
        if p not in PERIODS:
            out.append(f"period '{p}' is not one of {', '.join(PERIODS)}")
        else:
            try:
                s, e = pd.Timestamp(g("period_start")), pd.Timestamp(g("period_end"))
                if abs((e - s).days + 1 - PERIODS[p] * 30.44) > 12:
                    out.append(f"dates don't fit a {p} period ({g('period_start')} to {g('period_end')})")
            except ValueError:
                out.append("period_start and period_end must be dates (YYYY-MM-DD)")
        if g("basis") not in ("consolidated", "attributable", "100%"):
            out.append(f"basis '{g('basis')}' is not consolidated, attributable or 100%")
        if not re.fullmatch(r"[A-Z]{3}", g("currency")):
            out.append(f"currency '{g('currency')}' is not a three-letter code")
        if g("stripping_in_sustaining") not in ("", "yes", "no"):
            out.append("stripping_in_sustaining is yes, no or blank")
    elif name == "operations":
        if g("measure") not in MEASURES_RECORDED:
            out.append(f"measure '{g('measure')}' is not one of {', '.join(MEASURES_RECORDED)}")
        if g("measure") == "resources" and g("category") not in ("reserves", "mi", "inferred"):
            out.append("a resources row's category is reserves, mi (exclusive of reserves) or inferred")
        if g("measure") != "resources" and g("category"):
            out.append("only resources rows have a category")
        if g("unit") not in UNITS:
            out.append(f"unit '{g('unit')}' is not one of {', '.join(UNITS)}")
        if g("basis") not in ("attributable", "100%"):
            out.append(f"basis '{g('basis')}' is not attributable or 100%")
        if pd.to_datetime(g("period_end"), errors="coerce") is pd.NaT:
            out.append("period_end must be a date")
    elif name == "projects":
        if g("study_type") not in ST.STUDY_TYPES:
            out.append(f"study_type '{g('study_type')}' is not one of {', '.join(ST.STUDY_TYPES)}")
        if g("discounting") not in ("", "mid-year", "end-year", "start-year"):
            out.append("discounting is mid-year, end-year or start-year")
        for c in ("permits", "committed"):
            if g(c) not in ("", "yes", "no"):
                out.append(f"{c} is yes, no or blank")
    elif name == "coverage":
        if g("gap") not in COV.GAPS or g("status") not in COV.STATUSES:
            out.append(f"gap '{g('gap')}' and status '{g('status')}' must come from {COV.GAPS} and {COV.STATUSES}")
        if (g("gap") == "out_of_scope") != (g("status") == "out of scope"):
            out.append("an out_of_scope gap is 'out of scope', and nothing else is")
        if g("status") != "out of scope" and not g("next_step"):
            out.append("an open coverage row needs a next_step")
        if (g("status") == "waiting") != bool(re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", g("due"))):
            out.append("`due` (YYYY-MM) is set on waiting rows and only those")
        if g("status") in ("not published", "waiting") and not g("source").startswith("https://"):
            out.append("a not published or waiting row needs an https source")
    elif name == "sources":
        if not g("url").startswith("https://"):
            out.append("a sources row needs an https url")
        if g("read") not in ("yes", "partial", "via search", "no"):
            out.append("read is yes, partial, via search or no")
        if not (g("document") and g("company")):
            out.append("a sources row names the company and the document")
    if name in CITED and name != "corrections" and not (g("document") or name == "projects"):
        out.append("the row names its document")
    return out


# ---------- check (spec Part 2) ----------

def check(b: dict, base=None) -> tuple[list[str], list[str]]:
    """(errors, review lines) for a batch."""
    E, R = [], []
    kinds = set(b.get("kinds", []))
    E += [f"kind '{k}' is not one of {', '.join(KINDS)}" for k in sorted(kinds - set(KINDS))]
    recs = {n: _read(n, base) for n in RECORDS}
    appends = b.get("append", {}) or {}
    logged = {r["url"] for r in recs["sources"][1]} | {_s(r.get("url")) for r in appends.get("sources", [])}
    nums: dict[str, _Numbers] = {}

    def kind(k, what):
        if k and k not in kinds:
            E.append(f"{what}: kind '{k}' not in the batch's kinds ({', '.join(sorted(kinds)) or 'none'})")

    def cite(u, what) -> bool:
        u = _s(u)
        if not u.startswith("https://"):
            E.append(f"{what}: no https source")
            return False
        if u not in logged:
            E.append(f"{what}: {u} is not logged in sources.csv (add a sources row to the batch)")
        if not D.doc_path(u).exists():
            E.append(f"{what}: {u} not downloaded (research fetch --url)")
            return False
        if u not in nums:
            nums[u] = _Numbers(doc_numbers(D.doc_path(u).read_text()))
        return True

    def figure(v, u, what, derived) -> bool:
        """True when fine; False when the figure isn't in the document (the caller reports it)."""
        if _s(v).strip() == "":
            return True
        if _num(v) is None:
            E.append(f"{what}: {v!r} is not a number")
            return True
        if derived:
            R.append(f"{what} = {v}: derived: {derived}")
            return True
        return u is None or nums[u].has(v)

    # appended rows
    for name, rows in appends.items():
        if name not in APPENDABLE:
            E.append(f"append: '{name}' is not a record a batch appends to ({', '.join(APPENDABLE)})")
            continue
        cols, have = recs[name]
        key = RECORDS[name][1]
        keys = {_key(r, key) for r in have}
        for i, r in enumerate(rows):
            what = f"{name} row {i + 1} ({', '.join(_s(r.get(k, '')) for k in key)})"
            extra = set(r) - set(cols) - {"derived"} - ({"url"} if name == "corrections" else set())
            E += [f"{what}: {name} has no column '{c}'" for c in sorted(extra)]
            k = _key(r, key)
            if k in keys:
                E.append(f"{what}: already recorded (or twice in the batch)")
            keys.add(k)
            kind(APPEND_KIND[name], what)
            E += [f"{what}: {m}" for m in _allowed(name, r)]
            if name in CITED:
                u = _first_url(r.get(CITED[name])) if name == "projects" else _s(r.get(CITED[name]))
                ok = cite(u, what)
                der = r.get("derived")                     # a string for the whole row, or a map by column
                for c in CHECKED.get(name, ()):
                    how = _s(der.get(c, "")) if isinstance(der, dict) else _s(der)
                    if c in r and not figure(r[c], u if ok else None, f"{what} {c}", how):
                        E.append(f"{what} {c}: {r[c]} is not in {u} (if it isn't printed, say how in `derived`)")

    # study cash flows
    studies = {_key(r, ("ticker", "project", "study_date")) for r in recs["projects"][1] + appends.get("projects", [])}
    cash_have = {_key(r, RECORDS["cashflows"][1][:3]) for r in recs["cashflows"][1]}
    for c in b.get("cashflows", []) or []:
        sk = _key(c, ("ticker", "project", "study_date"))
        what = f"cashflows {' '.join(sk)}"
        kind("study", what)
        if sk not in studies:
            E.append(f"{what}: no projects row for this study (append one)")
        if sk in cash_have:
            E.append(f"{what}: already recorded")
        n = len(c.get("post", []))
        if not n:
            E.append(f"{what}: no after-tax cash flows ('post')")
        E += [f"{what}: {k} has {len(c[k])} years, post has {n}" for k in CF_KEYS if k in c and len(c[k]) != n]
        extra = set(c) - set(CF_KEYS) - {"ticker", "project", "study_date", "source", "first", "totals", "derived"}
        E += [f"{what}: unknown key '{k}'" for k in sorted(extra)]
        u = _first_url(c.get("source"))
        ok = cite(u, what)
        der = c.get("derived") or {}
        missing = []
        for k, col in CF_KEYS.items():
            if k == "prices" or k not in c:
                continue
            how = der.get(k, "") if isinstance(der, dict) else _s(der)
            if how:
                R.append(f"{what} {col}: derived: {how}")
                continue
            missing += [f"year {i + 1} {k} {v}" for i, v in enumerate(c[k])
                        if not figure(v, u if ok else None, what, "")]
        if missing:
            E.append(f"{what}: {len(missing)} figures not in {u}: {'; '.join(missing[:8])}"
                     + (" ..." if len(missing) > 8 else ""))
        for k, total in (c.get("totals") or {}).items():
            if k not in c:
                E.append(f"{what}: a total for '{k}', which has no years")
                continue
            try:
                TB.series([total, *c[k]], len(c[k]))
            except ValueError as e:
                E.append(f"{what} {k}: {e}")
        if not c.get("totals"):
            R.append(f"{what}: no totals given to check the years against (add the table's LOM totals)")

    # cells
    for s in b.get("set", []) or []:
        name, col = s.get("record"), s.get("column")
        what = f"set {name} {json.dumps(s.get('key'))} {col}"
        if name not in REWRITABLE or name not in recs:
            E.append(f"{what}: cells of '{name}' can't be set by a batch")
            continue
        cols, have = recs[name]
        if col not in cols:
            E.append(f"{what}: {name} has no column '{col}'")
            continue
        if name == "companies" and col not in COMPANY_KIND:
            E.append(f"{what}: {col} isn't a research column (another command writes it)")
            continue
        row = _find(have, s.get("key") or {})
        if row is None:
            E.append(f"{what}: no such row in {name}")
            continue
        kind(_set_kind(name, col), what)
        cur, was = _s(row.get(col, "")), _s(s.get("was", ""))
        if not (cur.strip() == was.strip() or (_num(cur) is not None and _num(cur) == _num(was))):
            E.append(f"{what}: was '{was}' but the record has '{cur}' (the batch is out of date)")
        if col in CHECKED.get(name, ()):
            ok = cite(s.get("url"), what)
            if not figure(s.get("value"), _s(s.get("url")) if ok else None, what, _s(s.get("derived"))):
                E.append(f"{what}: {s.get('value')} is not in {s.get('url')} (if it isn't printed, say how in `derived`)")
        elif s.get("url"):
            cite(s.get("url"), what)
        if col == "country_weights":
            try:
                parts = J.parse_weights(_s(s.get("value")))
                E += [f"{what}: {m}" for m in J.check_weights(parts, J.load_table())]
                R += _weights_vs_evidence(parts, b.get("evidence") or [], what)
            except ValueError as e:
                E.append(f"{what}: {e}")

    # removals
    for s in b.get("remove", []) or []:
        name = s.get("record")
        what = f"remove {name} {json.dumps(s.get('key'))}"
        if name not in REWRITABLE or name not in recs:
            E.append(f"{what}: rows of '{name}' can't be removed by a batch")
            continue
        if _find(recs[name][1], s.get("key") or {}) is None:
            E.append(f"{what}: no such row in {name}")
        kind(APPEND_KIND.get(name), what)

    # evidence
    for i, ev in enumerate(b.get("evidence", []) or []):
        what = f"evidence {i + 1} ({ev.get('figure', '')})"
        u = _s(ev.get("url"))
        ok = cite(u, what)
        if not figure(ev.get("value"), u if ok else None, what, _s(ev.get("derived"))):
            E.append(f"{what}: {ev.get('value')} is not in {u}")

    R += _tie_outs(b, recs) + _moves(b, recs) + _splits(b, recs) + _rebuilds(b, recs)
    return E, R


def _weights_vs_evidence(parts, evidence, what) -> list[str]:
    ev = [e for e in evidence if _s(e.get("weight")).strip()]
    if not ev:
        return [f"{what}: weights not tied to evidence (give each mine's figure with its `weight` place)"]
    total = sum(_num(e.get("value")) or 0 for e in ev)
    share = {}
    for e in ev:
        share[_s(e["weight"]).strip()] = share.get(_s(e["weight"]).strip(), 0) + (_num(e.get("value")) or 0) / total
    out = []
    for c, r, w in parts:
        place = c + (f"/{r}" if r else "")
        if abs(share.get(place, 0) - w) > 0.0015:
            out.append(f"{what}: {place} {w} vs {share.get(place, 0):.3f} from the evidence")
    return out


def _tie_outs(b, recs) -> list[str]:
    """FY = the periods inside it (9M + 3M, 6M + 6M, four quarters) for sustaining spending, where all are known."""
    new = (b.get("append") or {}).get("capex_periods", [])
    if not new:
        return []
    tick = {_s(r.get("ticker")) for r in new}
    rows = [r for r in recs["capex_periods"][1] + new if _s(r.get("ticker")) in tick and _num(r.get("sustaining")) is not None]
    out = []
    for fy in [r for r in rows if r.get("period") == "FY"]:
        S, E_ = pd.Timestamp(fy["period_start"]), pd.Timestamp(fy["period_end"])
        subs = [r for r in rows if r is not fy and r.get("ticker") == fy["ticker"] and r.get("period") != "FY"
                and pd.Timestamp(r["period_start"]) >= S and pd.Timestamp(r["period_end"]) <= E_]

        def walk(cur, chain):
            if cur == E_ + timedelta(days=1):
                yield chain
                return
            for r in subs:
                if pd.Timestamp(r["period_start"]) == cur and len(chain) < 4:
                    yield from walk(pd.Timestamp(r["period_end"]) + timedelta(days=1), chain + [r])

        for chain in walk(S, []):
            if not any(r in new for r in chain + [fy]):
                continue
            vals = [_s(r["sustaining"]) for r in chain]
            tot = sum(float(v) for v in vals)
            tol = (len(chain) + 1) * 0.5 * 10 ** -max(_dp(v) for v in vals + [_s(fy["sustaining"])])
            if abs(tot - float(fy["sustaining"])) > tol + 1e-9:
                out.append(f"tie-out {fy['ticker']} sustaining {fy['period_start']} to {fy['period_end']}: "
                           f"{' + '.join(vals)} = {tot:g}, not the FY {_s(fy['sustaining'])}")
    return out


def _moves(b, recs) -> list[str]:
    """A production, resource or GEO figure that moved more than 50% from the year before (basis? units?)."""
    new = (b.get("append") or {}).get("operations", [])
    rows = recs["operations"][1] + new
    out = []
    for r in new:
        same = [x for x in rows if x is not r and all(_s(x.get(c)) == _s(r.get(c))
                                                       for c in ("ticker", "measure", "category", "metal", "unit"))
                and _s(x.get("period_end")) < _s(r.get("period_end"))]
        if not same:
            continue
        prev = max(same, key=lambda x: x["period_end"])
        a, p = _num(r.get("amount")), _num(prev.get("amount"))
        if a is not None and p and abs(a / p - 1) > 0.5:
            cat = f" {r['category']}" if _s(r.get("category")) else ""
            out.append(f"{r['ticker']} {r['measure']}{cat} {r['metal']} {_s(r['amount'])} {r['unit']} vs "
                       f"{_s(prev['amount'])} at {prev['period_end']} ({a / p - 1:+.0%}): check the basis and units")
    return out


def _splits(b, recs) -> list[str]:
    """Reserves + M&I (exclusive) + inferred against the resource total, where a batch sets them."""
    sets = [s for s in b.get("set", []) or [] if s.get("record") == "companies"
            and _s(s.get("column")).startswith("resource_")]
    out = []
    for t in {_s((s.get("key") or {}).get("ticker")) for s in sets}:
        row = dict(_find(recs["companies"][1], {"ticker": t}) or {})
        row.update({s["column"]: s.get("value") for s in sets if _s((s.get("key") or {}).get("ticker")) == t})
        parts = [_num(row.get(c)) for c in ("resource_reserves", "resource_mi_excl_reserves", "resource_inferred")]
        tot = _num(row.get("resource_amount"))
        if tot is not None and all(p is not None for p in parts) and abs(sum(parts) - tot) > 0.0005 * abs(tot) + 0.05:
            out.append(f"{t} resources: reserves + M&I + inferred = {sum(parts):g}, not the total {tot:g} "
                       "(is the total a different category?)")
    return out


def _rebuilds(b, recs) -> list[str]:
    """Each new study rebuilt at its own prices and rate (studies.rebuild): off the published NPV means a wrong
    convention, tax share or parse."""
    new = (b.get("append") or {}).get("projects", [])
    if not new:
        return []
    rows = recs["cashflows"][1] + [r for c in b.get("cashflows", []) or [] for r in _cash_rows(c)]
    C = pd.DataFrame([{c: _s(r.get(c, "")) for c in ST.CASHFLOW_COLS} for r in rows], columns=ST.CASHFLOW_COLS)
    for c in ["year", "pre_tax_fcf_usd_m", "post_tax_fcf_usd_m", *ST.METALS.values()]:
        C[c] = pd.to_numeric(C[c], errors="coerce")
    out = []
    for r in new:
        p = pd.Series({c: _s(r.get(c, "")) for c in ST.PROJECT_COLS})
        try:
            res = ST.rebuild(p, ST.flows(C, p))
        except Exception as e:          # a malformed study reads as a review line, not a crash
            out.append(f"study {p.ticker} {p.project} {p.study_date}: rebuild failed: {e}")
            continue
        out += [f"study {p.ticker} {p.project} {p.study_date}: {f}" for f in res["flags"]]
    return out


# ---------- record (spec Part 2 and Part 4) ----------

def granted_kinds() -> list[str]:
    return list(settings().get("research", {}).get("agent", {}).get("write_kinds", []))


def figures(b: dict) -> dict:
    """{(kind, record, identity, column): value} for everything a batch records that the blind test and the track
    record count. A study is identified by ticker and date (the agent may name a project differently)."""
    out = {}

    def ident(name, r):
        cols = RECORDS[name][1]
        return _key(r, [c for c in cols if not (name in ("projects", "cashflows") and c == "project")])

    for name, rows in (b.get("append") or {}).items():          # a new row is one kind, as `check` treats it
        for r in rows if name in COMPARED else []:
            for c in COMPARED[name]:
                if _s(r.get(c, "")).strip():
                    out[(APPEND_KIND[name], name, ident(name, r), c)] = _s(r[c])
    for c in b.get("cashflows", []) or []:
        for r in _cash_rows(c):
            for col in COMPARED["cashflows"]:
                if _s(r.get(col, "")).strip():
                    out[("study", "cashflows", ident("cashflows", r), col)] = r[col]
    for s in b.get("set", []) or []:
        name, col = s.get("record"), s.get("column")
        if name in COMPARED and col in COMPARED[name] and _s(s.get("value")).strip():
            out[(_set_kind(name, col), name, ident(name, s.get("key") or {}), col)] = _s(s.get("value"))
    return out


def _changes(b: dict, base=None) -> dict:
    """{record: {"append": rows, "set": [...], "remove": [...]}} in the order they apply."""
    ch = {}
    for name, rows in (b.get("append") or {}).items():
        ch.setdefault(name, {"append": [], "set": [], "remove": []})["append"] += rows
    if b.get("cashflows"):
        ch.setdefault("cashflows", {"append": [], "set": [], "remove": []})["append"] += [
            r for c in b["cashflows"] for r in _cash_rows(c)]
    for s in b.get("set", []) or []:
        ch.setdefault(s["record"], {"append": [], "set": [], "remove": []})["set"].append(s)
    for s in b.get("remove", []) or []:
        ch.setdefault(s["record"], {"append": [], "set": [], "remove": []})["remove"].append(s)
    if "sources" in ch:                                           # a document already logged isn't logged twice
        have = {_key(r, ("ticker", "url")) for r in _read("sources", base)[1]}
        ch["sources"]["append"] = [r for r in ch["sources"]["append"] if _key(r, ("ticker", "url")) not in have]
    return ch


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


SHEET_COPY = {"financing": "PNAV inputs BF:BI", "resources": "PNAV inputs AT:AW and BP:BS",
              "mine_production": "nothing by hand: `jurisdiction`, then `compute` and `financials` write P"}
NEXT = {"sustaining": "research sustaining (dry run), then research sustaining --write",
        "study": "research studies, then compute and valuation",
        "operations": "screen (the performance measures read operations.csv)",
        "mine_production": "jurisdiction (review out/jurisdiction/comparison.csv), then compute and financials",
        "coverage": "valuation (its Coverage section)", "correction": "compute, then financials --dry-run",
        "stage": "valuation", "financing": "valuation", "resources": "compute", "listing": "screen"}


def record(path, write: bool = False, agent: bool = False, base=None, granted=None, today=None) -> list[str]:
    """Check a batch, show what it changes, and with `write` apply it and add it to the track record."""
    path = Path(path)
    b = json.loads(path.read_text())
    errors, reviews = check(b, base)
    kinds = list(b.get("kinds", []))
    lines = [f"Batch {path.name} for {b.get('ticker', '?')}: {', '.join(kinds) or 'no kinds'}"]
    if agent:
        allowed = set(granted_kinds() if granted is None else granted)
        if set(kinds) - allowed:
            errors.append(f"the agent may not record {', '.join(sorted(set(kinds) - allowed))} itself (not in "
                          "[research.agent] write_kinds)")
        if path.name != "proposal.json":
            errors.append("the agent records only its own proposal.json")
    if errors:
        return lines + ["Refused: fix these, run research check, and record again."] + [f"  {e}" for e in errors]
    ch = _changes(b, base)
    for name, c in ch.items():
        parts = [f"+{_plural(len(c['append']), 'row')}"] if c["append"] else []
        parts += [_plural(len(c["set"]), "cell")] if c["set"] else []
        parts += [f"-{_plural(len(c['remove']), 'row')}"] if c["remove"] else []
        if parts:
            lines.append(f"{name}: {', '.join(parts)}")
        for s in c["set"]:
            lines.append(f"    {json.dumps(s['key'])} {s['column']}: '{_s(s.get('was'))}' -> '{_s(s.get('value'))}'")
    if reviews:
        lines += ["Review:"] + [f"  {r}" for r in reviews]
    if not write:
        return lines + ["Dry run: nothing written (add --write)."]
    for name, c in ch.items():
        if c["set"] or c["remove"]:
            cols, rows = _read(name, base)
            for s in c["set"]:
                _find(rows, s["key"])[s["column"]] = _s(s.get("value"))
            for s in c["remove"]:
                rows.remove(_find(rows, s["key"]))
            _rewrite(name, cols, rows + [{k: _s(v) for k, v in r.items()} for r in c["append"]], base)
        elif c["append"]:
            _append(name, c["append"], base)
    lines += track(b, path, base, today, agent)
    lines += [f"Sheet working copy for {k}: {SHEET_COPY[k]}" for k in kinds if k in SHEET_COPY]
    lines += [f"Next for {k}: {NEXT[k]}" for k in kinds if k in NEXT]
    return lines


def track(b: dict, path: Path, base=None, today=None, agent: bool = False) -> list[str]:
    """Spec Part 4: one agent_log.csv row per kind: the figures the agent proposed, and how many of the recorded
    ones were changed, added or dropped against its proposal.json beside the recorded file."""
    rec = figures(b)
    prop_path = path.parent / "proposal.json"
    prop = figures(json.loads(prop_path.read_text())) if prop_path.exists() else {}
    p = _path("agent_log", base)
    if not p.exists():
        p.write_text(",".join(LOG_COLS) + "\n")
    rows = []
    for k in b.get("kinds", []):
        P = {x: v for x, v in prop.items() if x[0] == k}
        Rk = {x: v for x, v in rec.items() if x[0] == k}
        rows.append({"date": (today or date.today()).isoformat(), "ticker": b.get("ticker", ""), "kind": k,
                     "proposed": len(P), "changed": sum(1 for x in Rk if x in P and not _same(Rk[x], P[x])),
                     "added": sum(1 for x in Rk if x not in P), "dropped": sum(1 for x in P if x not in Rk),
                     "file": path.name + (" (agent)" if agent else "")})
    _append("agent_log", rows, base)
    return [f"Track record: {r['kind']} proposed {r['proposed']}, changed {r['changed']}, added {r['added']}, "
            f"dropped {r['dropped']} (data/research/agent_log.csv)" for r in rows]


# ---------- plan (spec Part 3) ----------

def _tier(c: dict) -> str:
    s = _s(c.get("stage"))
    if "oyalty" in s or "stream" in s:
        return "royalty"
    if "eveloper" in s and not _s(c.get("basis")).strip():
        return "developer"
    if "xplorer" in s:
        return "explorer"
    if "hysical" in s:
        return "physical metal"
    return "producer"


def _month_end(y: int, m: int) -> date:
    return (pd.Timestamp(year=y, month=m, day=1) + pd.offsets.MonthEnd(0)).date()


def _needed(fin: date, fy_month: int) -> list[tuple[str, date, date]]:
    """The capex periods the trailing 12 months to the financials date are built from (sustaining.ttm): the last
    fiscal year, then the year to date and the same months a year earlier."""
    fy_end = _month_end(fin.year, fy_month)
    if fy_end > fin:
        fy_end = _month_end(fin.year - 1, fy_month)
    fy_start = (pd.Timestamp(fy_end) - pd.DateOffset(years=1) + pd.Timedelta(days=1)).date()
    out = [("FY", fy_start, fy_end)]
    if fin == fy_end:
        return out
    m = (fin.month - fy_month) % 12
    start = fy_end + timedelta(days=1)
    return out + [(f"{m}M", start, fin),
                  (f"{m}M", date(start.year - 1, start.month, 1), _month_end(fin.year - 1, fin.month))]


def _fin_dates(base=None) -> dict:
    p = Path(base or ROOT) / "data" / "derived" / "holdings_detail.csv"
    if not p.exists():
        return {}
    from .sustaining import financials_dates
    return financials_dates(p)


def plan(ticker: str, base=None, fin_dates: dict | None = None, today: date | None = None) -> list[str]:
    """What the record holds and lacks for a company, by kind, and where to look (spec Part 3)."""
    today = today or date.today()
    cols, comp = _read("companies", base)
    c = _find(comp, {"ticker": ticker})
    if c is None:
        return [f"{ticker}: not in pnav_companies.csv (add the company first: README, 'When Sprott's holdings change')"]
    tier = _tier(c)
    fin = (_fin_dates(base) if fin_dates is None else fin_dates).get(ticker, "")
    where = D.venues(ticker, pd.DataFrame(comp, columns=cols))
    L = [f"{ticker} {c.get('holding', '')}: {c.get('stage', '')} ({tier}); venues: {', '.join(where)}; "
         f"financials to {fin or 'unknown (run compute)'}"]
    mine = lambda name: [r for r in _read(name, base)[1] if r.get("ticker") == ticker]   # noqa: E731

    if tier == "producer":
        R = mine("capex_periods")
        fys = sorted(r["period_end"] for r in R if r.get("period") == "FY")
        suffix = ticker.rsplit(" ", 1)[1] if " " in ticker else "US"
        fy_month, assumed = (int(fys[-1][5:7]), "") if fys else ((6 if suffix in ("AU", "SJ") else 12), " (assumed)")
        if fin:
            L.append(f"sustaining (trailing 12 months to {fin}; fiscal year ends month {fy_month}{assumed}):")
            have = {(r["period"], r["period_end"]) for r in R}
            for p, s, e in _needed(pd.Timestamp(fin).date(), fy_month):
                L.append(f"  {p} {s} to {e}: {'recorded' if (p, e.isoformat()) in have else 'missing'}")
            L.append(f"  (where the MD&A gives quarters only: FY + this year's 3M quarters - last year's, or the four 3M "
                     f"quarters to {fin})")
        else:
            L.append("sustaining: financials date unknown (run compute)")
        L += [f"  recorded: {r['period']} {r['period_start']} to {r['period_end']} {r['sustaining']} {r['currency']}"
              for r in R]

    P = mine("projects")
    if P or tier in ("developer", "explorer"):
        cf = {(r["project"], r["study_date"]) for r in mine("cashflows")}
        L.append("study:" + ("" if P else " none recorded"))
        for r in P:
            gaps = [x for x in PROJECT_STAGE[:4] if not _s(r.get(x)).strip()]
            L.append(f"  {r['project']} {r['study_type']} {r['study_date']}: "
                     f"{'cash flows' if (r['project'], r['study_date']) in cf else 'no cash flows'}"
                     + (f"; superseded {r['superseded']}" if _s(r.get('superseded')).strip() else "")
                     + (f"; blank {', '.join(gaps)}" if gaps else ""))

    O = mine("operations")
    want = {"royalty": ["geo_sold"], "producer": ["production", "resources"]}.get(tier, ["resources"])
    if tier != "physical metal":
        for y in range(2022, today.year):
            have = {(r["measure"], r["category"]) for r in O if r["period_end"][:4] == str(y)}
            miss = []
            for m in want:
                if m == "resources":
                    cats = [k for k in ("reserves", "mi", "inferred") if ("resources", k) not in have]
                    if cats:
                        miss.append(f"resources ({', '.join(cats)})")
                elif not any(h[0] == m for h in have):
                    miss.append(m)
            L.append(f"operations {y}: " + (f"missing {', '.join(miss)}" if miss else "recorded"))

    if tier in ("producer", "royalty") or _s(c.get("country_weights")).strip():
        cw = _s(c.get("country_weights")).strip()
        L.append(f"country_weights: {cw} ({_s(c.get('country_weights_source'))})" if cw else "country_weights: blank")
    if tier in ("developer", "explorer"):
        for k in ("resources", "financing"):
            blank = [x for x, kk in COMPANY_KIND.items() if kk == k and x in c and not _s(c[x]).strip()]
            L.append(f"{k}: " + (f"blank {', '.join(blank)}" if blank else "filled"))
        L.append(f"stage: study_stage {_s(c.get('study_stage')) or 'blank'}")
    blank = [x for x in ("us_listing", "canada_listing", "listing_source") if not _s(c.get(x)).strip()]
    if blank:
        L.append(f"listing: blank {', '.join(blank)}")
    L += [f"correction: {r['field']} {r['value_usd_m']} ({r['note']})" for r in mine("corrections")]
    for r in mine("coverage"):
        due = _s(r.get("due"))
        L.append(f"coverage {r['gap']}: {r['status']}"
                 + (f" (due {due}{', past due' if due and due < today.isoformat()[:7] else ''})" if due else "")
                 + f": {r['next_step']}")
    S = sorted(mine("sources"), key=lambda r: r.get("published", ""), reverse=True)
    if S:
        L.append(f"documents already read ({len(S)}; newest first):")
        L += [f"  {r['published']} {r['document']}: {r['url']}" for r in S[:20]]
    return L


# ---------- the blind test (spec Part 5) ----------

def _git(base, *args) -> str:
    return subprocess.run(["git", *args], cwd=base, check=True, capture_output=True, text=True).stdout.strip()


def blind(tickers: list[str], kinds: list[str], base=None) -> list[str]:
    """In a linked worktree only: take out what the record holds for these companies and kinds (and the documents
    logged for them), so the agent researches them from nothing."""
    base = Path(base or ROOT)
    gd = Path(_git(base, "rev-parse", "--absolute-git-dir")).resolve()
    common = (base / _git(base, "rev-parse", "--git-common-dir")).resolve()
    if gd == common:
        return ["Refused: run blind in a linked worktree (git worktree add ../blind main), never in the main checkout."]
    bad = set(kinds) - set(KINDS)
    if bad:
        return [f"Refused: unknown kinds {', '.join(sorted(bad))}"]
    T, lines = set(tickers), []
    drop = {"sources"} | {n for n, k in APPEND_KIND.items() if k in kinds}
    for name in drop:
        cols, rows = _read(name, base)
        keep = [r for r in rows if r.get("ticker") not in T]
        if len(keep) != len(rows):
            _rewrite(name, cols, keep, base)
            lines.append(f"{name}: -{_plural(len(rows) - len(keep), 'row')}")
    blank = {"companies": [c for c, k in COMPANY_KIND.items() if k in kinds and c != "stage"]
             + (list(SUSTAINING_BUILT) if "sustaining" in kinds else []),
             "projects": list(PROJECT_STAGE) if "stage" in kinds and "study" not in kinds else []}
    for name, cs in blank.items():
        cols, rows = _read(name, base)
        n = 0
        for r in rows:
            if r.get("ticker") in T:
                for c in cs:
                    if c in r and r[c]:
                        r[c], n = "", n + 1
        if n:
            _rewrite(name, cols, rows, base)
            lines.append(f"{name}: {_plural(n, 'cell')} blanked")
    src = common.parent / "data" / "derived" / "holdings_detail.csv"
    if src.exists():
        (base / "data" / "derived").mkdir(parents=True, exist_ok=True)
        (base / "data" / "derived" / "holdings_detail.csv").write_bytes(src.read_bytes())
        lines.append("data/derived/holdings_detail.csv copied (the financials dates)")
    return lines or ["Nothing to take out."]


def compare(path, ref: str = "main", base=None) -> dict:
    """Spec Part 5: the proposal against the record at a git ref, figure by figure."""
    path, base = Path(path), Path(base or ROOT)
    b = json.loads(path.read_text())
    t, kinds = b.get("ticker", ""), set(b.get("kinds", []))
    truth = {}
    for name in COMPARED:
        try:
            text = _git(base, "show", f"{ref}:{RECORDS[name][0]}")
        except subprocess.CalledProcessError:
            continue
        rows = [r for r in csv.DictReader(io.StringIO(text)) if r.get("ticker") == t]
        if name == "companies":
            figs = figures({"set": [{"record": "companies", "key": {"ticker": t}, "column": c, "value": r.get(c, "")}
                                    for r in rows for c in COMPARED["companies"]]})
        elif name == "cashflows":
            figs = {}
            for r in rows:
                for col in COMPARED["cashflows"]:
                    if _s(r.get(col)).strip():
                        figs[("study", "cashflows", _key(r, ("ticker", "study_date", "year")), col)] = r[col]
        else:
            figs = figures({"append": {name: rows}})
        truth.update({k: v for k, v in figs.items() if k[0] in kinds})
    prop = figures(b)
    unsourced = 0
    for name, rows in (b.get("append") or {}).items():
        for r in rows if name in CITED else []:
            u = _first_url(r.get(CITED[name])) if name == "projects" else _s(r.get(CITED[name]))
            if not u.startswith("https://"):
                unsourced += sum(1 for c in COMPARED.get(name, ()) if _s(r.get(c, "")).strip())
    matched = [k for k in truth if k in prop and _same(prop[k], truth[k])]
    missed = [k for k in truth if k not in matched]
    extra = [k for k in prop if k not in truth]
    share = len(matched) / len(truth) if truth else 1.0
    lines = [f"{t}: matched {len(matched)} of {len(truth)} record figures ({share:.0%}); {len(extra)} extra; "
             f"{unsourced} proposed without a source"]
    lines += [f"  missed: {k[1]} {' '.join(k[2])}: {k[3]} {prop.get(k, '(not proposed)')}, record {truth[k]}"
              for k in missed]
    lines += [f"  extra: {k[1]} {' '.join(k[2])}: {k[3]} {prop[k]}" for k in extra]
    return {"matched": len(matched), "missed": len(missed), "extra": len(extra), "unsourced": unsourced,
            "record": len(truth), "share": share, "lines": lines}
