"""Sustaining capital spending per company, trailing 12 months (roadmap 6, Part 2).

The record is `data/research/capex_periods.csv`: one row per figure a filing reports for its own period (a fiscal
year, or the year to date in a quarterly MD&A), in the filing's currency and basis, with its source. Nothing in it
is estimated: a figure a filing doesn't publish stays blank.

`research sustaining` builds the trailing 12 months ending on each company's financials date (the date its
trailing operating cash flow runs to, data/derived/holdings_detail.csv `fin_date`), so sustaining spending covers
the same months as the cash flow it is subtracted from:

    TTM = fiscal year + year to date now − the same year to date a year earlier

Each part is converted to US$ at the average month-end rate over its own period (as `royalty-ocf` does), and the
result goes to `pnav_companies.csv` (`sustaining_capex_usd_m`, `capitalized_stripping_usd_m`,
`sustaining_leases_usd_m`, `sustaining_period_end`, `sustaining_source`). `sustaining_capex_usd_m` is the total:
sustaining capital plus capitalized stripping (where a filing includes stripping in sustaining capital,
`stripping_in_sustaining` is "yes") plus sustaining lease payments, which IFRS 16 puts in financing cash flow, so
they are in neither operating cash flow nor capital spending (both counted, the user, Nov 21, 2026). The stripping
and lease columns show those parts; a lease figure is blank where no filing reports one.

When the next quarter's reports come out, add their year-to-date rows and rerun: the old rows stay, so every
figure can be recalculated. `research fetch` downloads the documents named in `data/research/sources.csv` (and in
the record) to cache/research/ as text, and `research find` searches them, so the figures can be found again.
"""
import hashlib
import re
import shutil
import subprocess

import numpy as np
import pandas as pd

from .config import CACHE, DATA, RESEARCH, ensure

RECORD = RESEARCH / "capex_periods.csv"
SOURCES = RESEARCH / "sources.csv"
COMPANIES = RESEARCH / "pnav_companies.csv"
DOCS = CACHE / "research"
COLS = ["ticker", "period", "period_start", "period_end", "basis", "currency", "sustaining",
        "capitalized_stripping", "stripping_in_sustaining", "sustaining_leases", "growth", "document", "url", "where", "published",
        "notes"]
PERIODS = {"FY": 12, "9M": 9, "6M": 6, "3M": 3}
OUT_COLS = ["sustaining_capex_usd_m", "capitalized_stripping_usd_m", "sustaining_leases_usd_m", "sustaining_period_end",
            "sustaining_source"]


def load_record(path=None) -> pd.DataFrame:
    R = pd.read_csv(path or RECORD, keep_default_na=False, na_values=[""], dtype={"ticker": str})
    for c in ("sustaining", "capitalized_stripping", "sustaining_leases", "growth"):
        R[c] = pd.to_numeric(R[c], errors="coerce")
    return R


def _year_before(d: str) -> str:
    t = pd.Timestamp(d)
    return (t - pd.DateOffset(years=1)).strftime("%Y-%m-%d")


def _year_to_date(C: pd.DataFrame, r, fy_end: str, end: str | None = None, period: str | None = None):
    """The rows making up the year to date after the fiscal year ending `fy_end`: one year-to-date row (9M, 6M), or
    the fiscal year's quarters (3M rows) where a company reports only quarters (Amerigo). ([rows], why)."""
    end = end or r.period_end
    period = period or r.period
    one = C[(C.period == period) & (C.period_end == end)]
    if period != "3M" or len(one) and pd.Timestamp(one.iloc[0].period_start) <= pd.Timestamp(fy_end) + pd.Timedelta(days=1):
        if one.empty:
            return [], f"no {period} figure for the period ending {end} (the prior-year comparative)"
        return [one.iloc[0]], ""
    q = C[(C.period == "3M") & (C.period_end > fy_end) & (C.period_end <= end)].sort_values("period_end")
    months = (pd.Timestamp(end).year - pd.Timestamp(fy_end).year) * 12 + pd.Timestamp(end).month - pd.Timestamp(fy_end).month
    if len(q) * 3 != months:
        return [], f"quarters to {end}: {len(q)} recorded, {months // 3} needed"
    return [x for _, x in q.iterrows()], ""


def _amount(r) -> tuple[float, float, float]:
    """(total sustaining spending, stripping, leases) for one record row, in its own currency."""
    strip = r.capitalized_stripping if r.capitalized_stripping == r.capitalized_stripping else 0.0
    lease = r.sustaining_leases if r.sustaining_leases == r.sustaining_leases else 0.0
    tot = r.sustaining + lease + (0.0 if str(r.stripping_in_sustaining).strip().lower() == "yes" else strip)
    return tot, strip, lease


def ttm(R: pd.DataFrame, ticker: str, end: str, usd_rate) -> dict:
    """Trailing 12 months of sustaining spending to `end` for one company, in US$M.

    Returns {"sustaining": ..., "stripping": ..., "parts": [...], "why": ""}; when it can't be built, values are
    NaN and `why` says which filing is missing."""
    C = R[R.ticker == ticker]
    out = {"sustaining": np.nan, "stripping": np.nan, "leases": np.nan, "parts": [], "why": ""}
    now = C[C.period_end == end]
    if now.empty:
        last = C.period_end.max() if len(C) else "none"
        out["why"] = f"no filing for the period ending {end} (latest recorded: {last})"
        return out
    r = now.sort_values("period", key=lambda p: p.map(PERIODS), ascending=False).iloc[0]
    parts = [(r, 1)]
    if r.period != "FY":
        fy = C[(C.period == "FY") & (C.period_end < end)].sort_values("period_end")
        if fy.empty:
            out["why"] = f"no fiscal year before {end}"
            return out
        f = fy.iloc[-1]
        cur, why = _year_to_date(C, r, f.period_end)
        prior, why2 = _year_to_date(C, None, _year_before(f.period_end), _year_before(end), r.period)
        if why or why2:
            out["why"] = why or why2
            return out
        parts = [(f, 1)] + [(x, 1) for x in cur] + [(x, -1) for x in prior]
    bases = {p.basis for p, _ in parts}
    if len(bases) > 1:
        out["why"] = f"parts on different bases ({', '.join(sorted(bases))})"
        return out
    tot = strip = lease = 0.0
    for p, sign in parts:
        if p.sustaining != p.sustaining:
            out["why"] = f"{p.period} to {p.period_end}: sustaining not published"
            return out
        rate = 1.0 if p.currency == "USD" else usd_rate(p.currency, p.period_start, p.period_end)
        if rate is None:
            out["why"] = f"no {p.currency} rate for {p.period_start} to {p.period_end}"
            return out
        s, st, le = _amount(p)
        tot += sign * s * rate
        strip += sign * st * rate
        lease += sign * le * rate
        out["parts"].append(f"{'+' if sign > 0 else '-'}{p.period} to {p.period_end} ({p.document})")
    has_lease = any(p.sustaining_leases == p.sustaining_leases for p, _ in parts)
    out.update(sustaining=round(tot, 1), stripping=round(strip, 1), leases=round(lease, 1) if has_lease else np.nan,
               basis=bases.pop())
    return out


def financials_dates(path=None) -> dict:
    """{ticker: fin_date}: the date each company's trailing operating cash flow runs to."""
    D = pd.read_csv(path or DATA / "derived" / "holdings_detail.csv", dtype={"ticker": str})
    D = D[D.fin_date.notna()].drop_duplicates("ticker")
    return dict(zip(D.ticker, D.fin_date.astype(str).str[:10]))


def build(R: pd.DataFrame, dates: dict, usd_rate) -> tuple[pd.DataFrame, list[str]]:
    """One row per recorded company: the TTM figures and their source text, plus report lines."""
    rows, lines = [], []
    for t in sorted(R.ticker.unique()):
        end = dates.get(t)
        if not end:
            lines.append(f"{t}: no financials date in data/derived (run `compute`)")
            continue
        x = ttm(R, t, end, usd_rate)
        if x["why"]:
            lines.append(f"{t}: not built: {x['why']}")
            rows.append({"ticker": t, **{c: np.nan for c in OUT_COLS}})
            continue
        src = (f"TTM to {end}, {x['basis']} basis, US$ at period-average month-end rates (Yahoo): "
               + " ".join(x["parts"]) + "; record: data/research/capex_periods.csv")
        rows.append({"ticker": t, "sustaining_capex_usd_m": x["sustaining"],
                     "capitalized_stripping_usd_m": x["stripping"], "sustaining_leases_usd_m": x["leases"],
                     "sustaining_period_end": end,
                     "sustaining_source": src})
        le = "" if x["leases"] != x["leases"] else f", leases {x['leases']:,.1f}"
        lines.append(f"{t}: {x['sustaining']:,.1f} US$M to {end} (stripping {x['stripping']:,.1f}{le})")
    return pd.DataFrame(rows), lines


def write_companies(T: pd.DataFrame, path=None) -> list[str]:
    """Write the TTM columns into pnav_companies.csv (every row with that ticker; others left as they are)."""
    p = path or COMPANIES
    C = pd.read_csv(p, keep_default_na=False, dtype=str)
    for c in OUT_COLS:
        if c not in C.columns:
            C[c] = ""
    n = 0
    for _, r in T.iterrows():
        m = C.ticker == r.ticker
        for c in OUT_COLS:
            v = r[c]
            C.loc[m, c] = "" if v != v else (f"{v:.1f}" if isinstance(v, float) else str(v))
        n += int(m.sum())
    C.to_csv(p, index=False, lineterminator="\n")
    return [f"Wrote {len(T)} companies' sustaining spending to {n} rows of {p.name}."]


def run_sustaining(write: bool = False, usd_rate=None) -> list[str]:
    from .royalty_history import _fx_average
    R = load_record()
    T, lines = build(R, financials_dates(), usd_rate or _fx_average())
    if write:
        lines += write_companies(T)
    else:
        lines.append("Dry run: pnav_companies.csv not changed (add --write).")
    return lines


# ---------- documents: download, text, search ----------

def doc_path(url: str):
    h = hashlib.sha1(url.encode()).hexdigest()[:12]
    return DOCS / f"{h}.txt"


def to_text(raw: bytes) -> str:
    """Text of a downloaded PDF (pdftotext -layout) or HTML page (tags removed)."""
    if raw[:5] == b"%PDF-":
        if not shutil.which("pdftotext"):
            raise RuntimeError("pdftotext not found: install poppler-utils")
        r = subprocess.run(["pdftotext", "-layout", "-", "-"], input=raw, capture_output=True, timeout=300)
        return r.stdout.decode("utf-8", "replace")
    import html
    t = raw.decode("utf-8", "replace")
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", t)
    t = re.sub(r"\s+", " ", t)                                   # source line breaks mean nothing in HTML
    t = re.sub(r"(?i)</t[dh]>", " | ", t)                       # keep a table row on one line, cells apart
    t = re.sub(r"(?i)</tr>|<br\s*/?>|</p>|</div>|</h\d>|</li>", "\n", t)
    t = html.unescape(re.sub(r"(?s)<[^>]+>", " ", t)).replace("\xa0", " ").replace("\u200b", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"(\|\s*)+\|", "|", t)                           # empty cells
    return "\n".join(x.strip(" |") for x in t.splitlines() if x.strip(" |"))


def urls(ticker: str | None = None) -> list[tuple[str, str]]:
    """(ticker, url) for every document in sources.csv and the record."""
    out = []
    for p in (SOURCES, RECORD):
        if p.exists():
            D = pd.read_csv(p, keep_default_na=False, dtype=str)
            out += [(t, u) for t, u in zip(D.ticker, D.url) if u.startswith("http")]
    seen, res = set(), []
    for t, u in out:
        if (ticker is None or t == ticker) and u not in seen:
            seen.add(u)
            res.append((t, u))
    return res


def _get(u: str) -> bytes:
    """Download a document. The SEC asks automated clients for a contact User-Agent ([royalty_history])."""
    import requests
    from .config import settings
    S = settings()
    ua = S["royalty_history"]["edgar_user_agent"] if "sec.gov" in u else S["yahoo"]["user_agent"]
    r = requests.get(u, timeout=180, headers={"User-Agent": ua})
    r.raise_for_status()
    return r.content


def fetch(ticker: str | None = None, get=None, refresh: bool = False, url: str | None = None) -> list[str]:
    """Download each document once to cache/research/ as text (all of a ticker's, or one `url`)."""
    get = get or _get
    ensure(DOCS)
    lines = []
    for t, u in ([(ticker or "", url)] if url else urls(ticker)):
        p = doc_path(u)
        if p.exists() and not refresh:
            continue
        try:
            text = to_text(get(u))
        except Exception as e:      # one document failing shouldn't stop the rest
            lines.append(f"{t}: failed {u}: {e}")
            continue
        p.write_text(f"{u}\n{text}")
        lines.append(f"{t}: {len(text.splitlines())} lines from {u} -> {p}")
    return lines or ["Nothing new to fetch."]


def find(ticker: str, terms: list[str], context: int = 2, url: str | None = None) -> list[str]:
    """Lines matching any term in the ticker's cached documents (or one `url`'s), with a little context."""
    pat = re.compile("|".join(re.escape(x) for x in terms), re.I)
    out = []
    for _, u in ([(ticker, url)] if url else urls(ticker)):
        p = doc_path(u)
        if not p.exists():
            out.append(f"(not fetched: {u})")
            continue
        L = p.read_text().splitlines()
        hits = [i for i, x in enumerate(L) if pat.search(x)]
        if hits:
            out.append(f"== {u}")
        for i in hits[:40]:
            out += [f"{j:6d}: {L[j]}" for j in range(max(0, i - context), min(len(L), i + context + 1))] + ["--"]
    return out or ["No matches."]
