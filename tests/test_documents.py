"""Finding and downloading company documents (filing-research-agent spec A1-A3). Every page here is a recorded
layout with invented figures; downloads go through a fake `get`."""
import json

import pandas as pd
import pytest

from minerval import documents as D
from minerval import sustaining as SU

ASX_LIST = """<table><tr><th>Date</th><th>Price sens.</th><th>Headline</th></tr>
<tr> <td> 22/07/2026<br> <span class="dates-time">8:10 am</span> </td> <td class="pricesens"> </td> <td>
<a target="_blank" href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId=03100001">
June 2026 Quarterly Activities Report<br> <img src="/pdf_icon.png"> <span class="page">30 pages </span> </a> </td> </tr>
<tr> <td> 20/07/2026<br> </td> <td class="pricesens"> </td> <td>
<a target="_blank" href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId=03100002">
Appendix 3Y A Director<br> </a> </td> </tr>
</table>"""
ASX_PAGE = '<html><a href="https://announcements.asx.com.au/asxpdf/20260722/pdf/06abc123xyz.pdf">Click</a></html>'

INVESTEGATE = """<table class="table-investegate"><thead><tr><th>Date</th><th>Time</th><th>Source</th>
<th>Announcement</th></tr></thead><tbody>
<tr><td>25 Nov 2026</td><td>02:03 PM</td><td><a class="regulatory source-RNS" href="https://www.investegate.co.uk/source/RNS">RNS</a></td>
<td><a class="announcement-link" href="https://www.investegate.co.uk/announcement/rns/example-mining--exm/tr-1-notification/9000001">TR-1: Notification of major holdings </a></td></tr>
<tr><td>12 Aug 2026</td><td>07:00 AM</td><td><a href="https://www.investegate.co.uk/source/RNS">RNS</a></td>
<td><a class="announcement-link" href="https://www.investegate.co.uk/announcement/rns/example-mining--exm/interim-results-2026/9000002">Interim Results 2026 </a></td></tr>
</tbody></table>"""

EFTS = {"hits": {"total": {"value": 1}, "hits": [{
    "_id": "0001104659-25-090086:newp-20250630xex99d1.htm",
    "_source": {"ciks": ["0001369085"], "file_date": "2025-09-15", "form": "40-F", "file_type": "EX-99.1",
                "file_description": "EXHIBIT-99.1", "display_names": ["EXAMPLE METALS CORP (EXM) (CIK 0001369085)"]}}]}}

WP_MEDIA = [
    {"date": "2026-07-30T08:00:00", "title": {"rendered": "Interim Results Booklet 2026"},
     "source_url": "https://example-mining.com/wp-content/uploads/2026/07/interim-results-2026.pdf",
     "mime_type": "application/pdf"},
    {"date": "2026-07-30T08:00:00", "title": {"rendered": "Results banner"},
     "source_url": "https://example-mining.com/wp-content/uploads/2026/07/banner.jpg", "mime_type": "image/jpeg"},
]


def fake(pages: dict):
    """A `get` that serves each URL containing a key from `pages`, and refuses any other."""
    def get(u):
        for k, v in pages.items():
            if k in u:
                return v.encode() if isinstance(v, str) else v
        raise AssertionError(f"unexpected download {u}")
    return get


def test_sustaining_names_still_work(tmp_path, monkeypatch):
    """A1: the document code moved to minerval/documents.py; the names the skills use on `sustaining` are the same
    functions, and fetch + find still work end to end."""
    for name in ("doc_path", "to_text", "urls", "fetch", "find", "filings", "edgar_cik", "edgar_filings",
                 "us_symbol", "EDGAR_FORMS"):
        assert getattr(SU, name) is getattr(D, name), name
    monkeypatch.setattr(D, "DOCS", tmp_path)
    u = "https://example.com/mdna.htm"
    page = "<table><tr><td>Sustaining capital</td><td>10.5</td></tr></table>"
    lines = SU.fetch("EXM", get=fake({"mdna": page}), url=u)
    assert "1 lines" in lines[0] and SU.doc_path(u).parent == tmp_path
    assert any("Sustaining capital | 10.5" in x for x in SU.find("EXM", ["sustaining"], url=u))


def test_documents_are_offline_in_tests():
    """A3: tests/conftest.py blocks the downloader, so no test can reach a filing site."""
    with pytest.raises(AssertionError, match="network"):
        D._get("https://www.sec.gov/files/company_tickers.json")
    with pytest.raises(AssertionError, match="network"):
        SU._get("https://www.asx.com.au/")


def test_asx_announcements_from_the_year_list():
    """A2: the ASX year list gives each announcement's date and headline; a matching one's page gives its PDF."""
    get = fake({"announcements.do": ASX_LIST, "idsId=03100001": ASX_PAGE})
    A = D.asx_announcements("exm", 2026, "quarterly", get=get)
    assert A == [{"date": "2026-07-22", "headline": "June 2026 Quarterly Activities Report", "ids_id": "03100001",
                  "url": "https://announcements.asx.com.au/asxpdf/20260722/pdf/06abc123xyz.pdf"}]


def test_investegate_results_list():
    """A2: Investegate's company list (London and Johannesburg announcements), newest first, filtered by headline."""
    get = fake({"/company/EXM?page=": "<html></html>", "/company/EXM": INVESTEGATE})
    A = D.investegate("EXM", "result|interim", get=get)
    assert A == [{"date": "2026-08-12", "headline": "Interim Results 2026",
                  "url": "https://www.investegate.co.uk/announcement/rns/example-mining--exm/interim-results-2026/9000002"}]


def test_investegate_pages_back_to_a_year():
    """A2: with `since`, Investegate's list is paged back until it reaches that date (a busy company's results for
    last year sit several pages down)."""
    def page(day, head, n):
        return (f'<tr><td>{day}</td><td>07:00 AM</td><td>RNS</td><td><a class="announcement-link" '
                f'href="https://www.investegate.co.uk/announcement/rns/exm/{n}">{head}</a></td></tr>')
    pages = {"?page=2": page("10 Sep 2025", "Interim Results 2025", 2), "?page=3": page("19 Mar 2025", "2024 Full-Year Results", 3),
             "?page=4": page("20 Sep 2024", "Interim Results 2024", 4), "/company/EXM": page("26 Aug 2026", "Interim Results 2026", 1)}
    seen = []
    get = fake(pages)
    A = D.investegate("EXM", "result", since="2025-01-01", get=lambda u: seen.append(u) or get(u))
    assert [a["date"] for a in A] == ["2026-08-26", "2025-09-10", "2025-03-19"]           # 2024 seen, then dropped
    assert any("page=4" in u for u in seen) and not any("page=5" in u for u in seen)
    assert len(D.investegate("EXM", "result", get=get)) == 3                        # three pages by default


def test_edgar_full_text_search_hits():
    """A2: EDGAR full-text search finds exhibits the submissions list misses (technical reports, older years)."""
    seen = []
    get = fake({"efts.sec.gov": json.dumps(EFTS)})
    H = D.edgar_search('"technical report" "Carangas"', cik=1369085, get=lambda u: seen.append(u) or get(u))
    assert "ciks=0001369085" in seen[0] and "%22technical%20report%22" in seen[0]
    assert H == [{"date": "2025-09-15", "form": "40-F", "type": "EX-99.1", "description": "EXHIBIT-99.1",
                  "url": "https://www.sec.gov/Archives/edgar/data/1369085/000110465925090086/newp-20250630xex99d1.htm"}]


def test_wordpress_media_search():
    """A2: a WordPress company site lists its uploads (results booklets behind a 403 exchange link); PDFs only."""
    get = fake({"wp-json/wp/v2/media": json.dumps(WP_MEDIA)})
    M = D.wordpress_media("https://example-mining.com/", "interim results", get=get)
    assert M == [{"date": "2026-07-30", "title": "Interim Results Booklet 2026",
                  "url": "https://example-mining.com/wp-content/uploads/2026/07/interim-results-2026.pdf"}]


def test_locate_picks_venues_from_the_listing():
    """A2: EDGAR for a US listing, the ASX for an ` AU` ticker, Investegate for ` LN` and ` SJ`, and the company's
    own site always (where the rest of the documents are)."""
    C = pd.DataFrame({"ticker": ["EXM AU", "EXM LN", "EXM CN", "EXM"],
                      "us_listing": ["", "", "NYSE: EXM", "OTC: EXMXF"]})
    assert D.venues("EXM AU", C) == ["asx", "site"]
    assert D.venues("EXM LN", C) == ["investegate", "site"]
    assert D.venues("EXM CN", C) == ["edgar", "site"]
    assert D.venues("EXM", C) == ["edgar", "site"]
