"""Company documents: where to find them, downloading, text and search (filing-research-agent spec, Part 3).

Each venue a company files on has its own way to list documents:

    EDGAR        the submissions list (`edgar_filings`) and full-text search (`edgar_search`), for US listings
    ASX          the year's announcement list, then each announcement's page for its PDF (`asx_announcements`)
    Investegate  London (and Johannesburg) announcements; LSE pages refuse scripts (`investegate`)
    company site a WordPress site's media library (`wordpress_media`); other sites by web search

SEDAR+ answers scripts with a bot challenge, so its documents are always the user's to save to `private/`.
`fetch` downloads a document once to cache/research/ as text and `find` searches it. Every download goes through
`_get`, which tests/conftest.py blocks. Downloads say what they are: the SEC's contact User-Agent for sec.gov,
`[research] user_agent` elsewhere.
"""
import hashlib
import html
import json
import re
import shutil
import subprocess
from urllib.parse import quote

import pandas as pd

from .config import CACHE, RESEARCH, ensure

DOCS = CACHE / "research"
SOURCES = RESEARCH / "sources.csv"
COMPANIES = RESEARCH / "pnav_companies.csv"
RECORDS_WITH_URLS = ("capex_periods.csv", "operations.csv")


# ---------- download, text, search ----------

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
    t = raw.decode("utf-8", "replace")
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", t)
    t = re.sub(r"\s+", " ", t)                                   # source line breaks mean nothing in HTML
    t = re.sub(r"(?i)</t[dh]>", " | ", t)                       # keep a table row on one line, cells apart
    t = re.sub(r"(?i)</tr>|<br\s*/?>|</p>|</div>|</h\d>|</li>", "\n", t)
    t = html.unescape(re.sub(r"(?s)<[^>]+>", " ", t)).replace("\xa0", " ").replace("​", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"(\|\s*)+\|", "|", t)                           # empty cells
    return "\n".join(x.strip(" |") for x in t.splitlines() if x.strip(" |"))


def urls(ticker: str | None = None) -> list[tuple[str, str]]:
    """(ticker, url) for every document in sources.csv and the record files that cite one by URL."""
    out = []
    for p in (SOURCES, *(RESEARCH / f for f in RECORDS_WITH_URLS)):
        if p.exists():
            T = pd.read_csv(p, keep_default_na=False, dtype=str)
            out += [(t, u) for t, u in zip(T.ticker, T.url) if u.startswith("http")]
    seen, res = set(), []
    for t, u in out:
        if (ticker is None or t == ticker) and u not in seen:
            seen.add(u)
            res.append((t, u))
    return res


def _get(u: str) -> bytes:
    """Download a document. The SEC asks automated clients for a contact User-Agent ([royalty_history])."""
    import time

    import requests

    from .config import settings
    S = settings()
    sec = "sec.gov" in u
    ua = S["royalty_history"]["edgar_user_agent"] if sec else S["research"]["user_agent"]
    for attempt in range(6):
        if sec:
            time.sleep(0.15)                 # the SEC allows about 10 requests a second
        r = requests.get(u, timeout=180, headers={"User-Agent": ua})
        if r.status_code not in (429, 503) or attempt == 5:
            break
        time.sleep(2 ** attempt)             # rate-limited: back off and try again
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


# ---------- EDGAR: which filings a company has made (for the US-listed and 40-F/6-K filers) ----------

EDGAR_FORMS = ("10-K", "10-Q", "6-K", "40-F", "20-F", "8-K", "40FR12B", "40-F/A", "20-F/A")   # 40FR12B: a 40-F registration (a new US listing)


def _edgar_json(url: str, get=None):
    return json.loads((get or _get)(url))


def us_symbol(ticker: str, path=None) -> str:
    """The US exchange symbol from pnav_companies.csv `us_listing` ("NYSE: KGC" -> "KGC"; OTC ADRs too)."""
    C = pd.read_csv(path or COMPANIES, dtype=str, keep_default_na=False)
    u = C.loc[C.ticker == ticker, "us_listing"]
    u = u.iloc[0] if len(u) else ""
    return u.split(":", 1)[1].strip() if ":" in u else ""


def edgar_cik(symbol: str, get=None) -> int | None:
    j = _edgar_json("https://www.sec.gov/files/company_tickers.json", get)
    return next((int(v["cik_str"]) for v in j.values() if v["ticker"].upper() == symbol.upper()), None)


def edgar_filings(cik: int, since: str, get=None, min_size: int = 100_000) -> list[dict]:
    """Filings since a date, each with its larger .htm documents (the MD&A and statements are exhibits of a 6-K)."""
    import requests
    j = _edgar_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", get)
    r = j["filings"]["recent"]
    out = []
    for i in range(len(r["form"])):
        if r["filingDate"][i] < since or r["form"][i] not in EDGAR_FORMS:
            continue
        acc = r["accessionNumber"][i].replace("-", "")
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"
        try:
            idx = _edgar_json(base + "index.json", get)
        except requests.HTTPError as e:              # some filings have no index.json (404): skip that one
            if e.response is None or e.response.status_code != 404:
                raise
            continue
        docs = [base + x["name"] for x in idx["directory"]["item"]
                if x["name"].endswith(".htm") and str(x.get("size") or "0").isdigit() and int(x["size"]) >= min_size]
        if docs:
            out.append({"date": r["filingDate"][i], "form": r["form"][i], "docs": docs})
    return out


def filings(ticker: str, since: str, get=None) -> list[str]:
    sym = us_symbol(ticker)
    if not sym:
        return [f"{ticker}: no US listing recorded, so no EDGAR filings; use the company's own site."]
    cik = edgar_cik(sym, get)
    if not cik:
        return [f"{ticker}: {sym} not in EDGAR's ticker list (OTC ADRs often aren't); use the company's own site."]
    lines = [f"{ticker}: {sym}, CIK {cik}"]
    for f in edgar_filings(cik, since, get):
        lines += [f"  {f['date']} {f['form']}"] + [f"      {d}" for d in f["docs"]]
    return lines


def edgar_search(query: str, cik: int | None = None, forms: str | None = None, get=None) -> list[dict]:
    """EDGAR full-text search (2001 on): each hit's filing date, form, exhibit type and document URL. It finds what
    the submissions list misses: technical-report exhibits, PDFs, filings older than the recent list."""
    u = f"https://efts.sec.gov/LATEST/search-index?q={quote(query)}"
    if cik:
        u += f"&ciks={int(cik):010d}"
    if forms:
        u += f"&forms={quote(forms)}"
    out = []
    for h in _edgar_json(u, get)["hits"]["hits"]:
        acc, name = h["_id"].split(":", 1)
        s = h["_source"]
        c = int(s["ciks"][0])
        out.append({"date": s["file_date"], "form": s["form"], "type": s.get("file_type", ""),
                    "description": s.get("file_description", ""),
                    "url": f"https://www.sec.gov/Archives/edgar/data/{c}/{acc.replace('-', '')}/{name}"})
    return out


# ---------- the ASX, Investegate, company sites ----------

def _text(get, u: str) -> str:
    return (get or _get)(u).decode("utf-8", "replace")


def asx_announcements(code: str, year: int, match: str = ".", get=None) -> list[dict]:
    """A year's ASX announcements whose headline matches, newest first, each with its PDF address (read from the
    announcement's page). The markitdigital JSON API returns only the latest five, so the HTML list is used."""
    t = _text(get, "https://www.asx.com.au/asx/v2/statistics/announcements.do?by=asxCode"
                   f"&asxCode={code.upper()}&timeframe=Y&year={year}")
    pat, out = re.compile(match, re.I), []
    for r in re.findall(r"<tr>(.*?)</tr>", t, re.S):
        d = re.search(r"(\d\d)/(\d\d)/(\d{4})", r)
        h = re.search(r"idsId=(\d+)[^>]*>\s*(.*?)\s*<", r, re.S)
        if not (d and h):
            continue
        head = html.unescape(re.sub(r"\s+", " ", h.group(2))).strip()
        if not pat.search(head):
            continue
        page = _text(get, "https://www.asx.com.au/asx/v2/statistics/displayAnnouncement.do?display=pdf"
                          f"&idsId={h.group(1)}")
        m = re.search(r"asxpdf/\d{8}/pdf/\w+\.pdf", page)
        out.append({"date": f"{d.group(3)}-{d.group(2)}-{d.group(1)}", "headline": head, "ids_id": h.group(1),
                    "url": f"https://announcements.asx.com.au/{m.group(0)}" if m else ""})
    return out


def investegate(code: str, match: str = ".", pages: int = 3, since: str | None = None, get=None) -> list[dict]:
    """A company's announcements on Investegate (London Stock Exchange pages refuse scripts), newest first: `pages`
    pages, or with `since` (YYYY-MM-DD) as many as it takes to reach that date (at most 15)."""
    pat, out = re.compile(match, re.I), []
    for n in range(1, (15 if since else pages) + 1):
        t = _text(get, f"https://www.investegate.co.uk/company/{code.upper()}" + (f"?page={n}" if n > 1 else ""))
        dates = []
        for r in re.findall(r"<tr>(.*?)</tr>", t, re.S):
            d = re.search(r"<td>\s*(\d{1,2} [A-Z][a-z]{2} \d{4})\s*</td>", r)
            a = re.search(r'href="(https://www\.investegate\.co\.uk/announcement/[^"]+)">([^<]*)<', r)
            if not (d and a):
                continue
            day = pd.to_datetime(d.group(1), format="%d %b %Y").strftime("%Y-%m-%d")
            dates.append(day)
            if pat.search(html.unescape(a.group(2))) and (since is None or day >= since):
                out.append({"date": day, "headline": html.unescape(a.group(2)).strip(), "url": a.group(1)})
        if since and (not dates or min(dates) < since):
            break
    return out


def wordpress_media(site: str, words: str, get=None) -> list[dict]:
    """PDFs in a WordPress site's media library matching the words (`/wp-json/wp/v2/media?search=`). JSE pages
    (senspdf.jse.co.za) refuse scripts, but the company's own site often carries the same booklet."""
    u = f"{site.rstrip('/')}/wp-json/wp/v2/media?search={quote(words)}&per_page=50"
    return [{"date": m.get("date", "")[:10], "title": html.unescape(m.get("title", {}).get("rendered", "")).strip(),
             "url": m["source_url"]}
            for m in _edgar_json(u, get) if str(m.get("mime_type", "")).endswith("pdf")]


# ---------- which venues to search for a company ----------

def venues(ticker: str, companies: pd.DataFrame | None = None) -> list[str]:
    """Where a company's documents are: EDGAR with a US listing (or a US ticker), the ASX for ` AU`, Investegate for
    London (` LN`) and Johannesburg (` SJ`), and its own site always."""
    C = companies if companies is not None else pd.read_csv(COMPANIES, dtype=str, keep_default_na=False)
    row = C[C.ticker == ticker]
    us = str(row.us_listing.iloc[0]).strip() if len(row) else ""
    suffix = ticker.rsplit(" ", 1)[1] if " " in ticker else "US"
    out = ["edgar"] if (us or suffix == "US") else []
    out += {"AU": ["asx"], "LN": ["investegate"], "SJ": ["investegate"]}.get(suffix, [])
    return out + ["site"]


def locate(ticker: str, match: str | None = None, year: int | None = None, site: str | None = None,
           since: str = "2025-01-01", get=None) -> list[str]:
    """Candidate documents for a company from every venue it files on (spec Part 3, `research locate`)."""
    code = ticker.split(" ")[0]
    where = venues(ticker)
    lines = [f"{ticker}: venues {', '.join(where)}"]
    for v in where:
        try:
            if v == "edgar":
                lines += filings(ticker, since, get)
                cik = edgar_cik(us_symbol(ticker) or code, get) if match else None
                if cik:
                    lines += [f"  full-text search {match!r}:"] + [
                        f"    {h['date']} {h['form']} {h['type']} {h['url']}" for h in edgar_search(match, cik, get=get)]
            elif v == "asx":
                y = year or pd.Timestamp.today().year
                lines += [f"  ASX {code} {y}:"] + [f"    {a['date']} {a['headline'][:70]} {a['url'] or '(no PDF)'}"
                                                   for a in asx_announcements(code, y, match or ".", get)]
            elif v == "investegate":
                lines += [f"  Investegate {code}:"] + [f"    {a['date']} {a['headline'][:70]} {a['url']}" for a in
                                                       investegate(code, match or ".", since=f"{year}-01-01" if year
                                                                   else None, get=get)]
            elif site:
                lines += [f"  {site} media {match!r}:"] + [f"    {m['date']} {m['title'][:70]} {m['url']}"
                                                          for m in wordpress_media(site, match or "", get)]
            else:
                lines.append("  company site: give --site for a WordPress media search, or search the web for "
                             "the company and the document (\"MD&A pdf\"); SEDAR+ documents are the user's to save")
        except Exception as e:          # one venue failing shouldn't stop the rest
            lines.append(f"  {v}: failed: {e}")
    return lines
