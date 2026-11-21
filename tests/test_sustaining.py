"""Trailing-12-month sustaining spending from the per-period record (roadmap 6). Offline; made-up figures."""
import numpy as np
import pandas as pd

from minerval import sustaining as SU


def rec(*rows):
    base = {"ticker": "ALP", "period": "FY", "period_start": "2025-01-01", "period_end": "2025-12-31",
            "basis": "attributable", "currency": "USD", "sustaining": 100.0, "capitalized_stripping": np.nan, "sustaining_leases": np.nan,
            "stripping_in_sustaining": "", "growth": np.nan, "document": "FY2025 MD&A", "url": "https://x/fy",
            "where": "", "published": "", "notes": ""}
    return pd.DataFrame([{**base, **r} for r in rows])


def flat(cur, start, end):
    return {"CAD": 0.7}.get(cur)


def test_fiscal_year_ending_on_the_financials_date():
    x = SU.ttm(rec({}), "ALP", "2025-12-31", flat)
    assert x["why"] == "" and x["sustaining"] == 100.0


def test_ttm_from_fiscal_year_and_year_to_date():
    R = rec({}, {"period": "9M", "period_start": "2026-01-01", "period_end": "2026-09-30", "sustaining": 90.0,
                 "document": "Q3 2026 MD&A"},
            {"period": "9M", "period_start": "2025-01-01", "period_end": "2025-09-30", "sustaining": 70.0,
             "document": "Q3 2026 MD&A"})
    x = SU.ttm(R, "ALP", "2026-09-30", flat)
    assert x["sustaining"] == 120.0                     # 100 + 90 - 70
    assert len(x["parts"]) == 3 and x["parts"][2].startswith("-9M")


def test_missing_prior_year_comparative_says_so():
    R = rec({}, {"period": "9M", "period_start": "2026-01-01", "period_end": "2026-09-30", "sustaining": 90.0})
    x = SU.ttm(R, "ALP", "2026-09-30", flat)
    assert np.isnan(x["sustaining"]) and "prior-year comparative" in x["why"]


def test_no_filing_for_the_date():
    x = SU.ttm(rec({}), "ALP", "2026-06-30", flat)
    assert "no filing for the period ending 2026-06-30" in x["why"]


def test_stripping_added_unless_included_and_currency_converted():
    x = SU.ttm(rec({"currency": "CAD", "capitalized_stripping": 20.0}), "ALP", "2025-12-31", flat)
    assert x["sustaining"] == 84.0 and x["stripping"] == 14.0          # (100 + 20) x 0.7
    y = SU.ttm(rec({"capitalized_stripping": 20.0, "stripping_in_sustaining": "yes"}), "ALP", "2025-12-31", flat)
    assert y["sustaining"] == 100.0 and y["stripping"] == 20.0


def test_unpublished_figure_and_mixed_bases_are_not_built():
    assert "not published" in SU.ttm(rec({"sustaining": np.nan}), "ALP", "2025-12-31", flat)["why"]
    R = rec({}, {"period": "9M", "period_start": "2026-01-01", "period_end": "2026-09-30", "basis": "100%"},
            {"period": "9M", "period_start": "2025-01-01", "period_end": "2025-09-30"})
    assert "different bases" in SU.ttm(R, "ALP", "2026-09-30", flat)["why"]


def test_write_companies_fills_only_recorded_tickers(tmp_path):
    p = tmp_path / "c.csv"
    pd.DataFrame({"ticker": ["ALP", "BET"], "holding": ["Alpha", "Beta"]}).to_csv(p, index=False)
    T, _ = SU.build(rec({}), {"ALP": "2025-12-31"}, flat)
    SU.write_companies(T, p)
    C = pd.read_csv(p, keep_default_na=False)
    assert C.loc[0, "sustaining_capex_usd_m"] == "100.0" and C.loc[1, "sustaining_capex_usd_m"] == ""
    assert C.loc[0, "sustaining_period_end"] == "2025-12-31" and "capex_periods.csv" in C.loc[0, "sustaining_source"]


def test_to_text_strips_html():
    assert "Sustaining capital | 10" in SU.to_text(b"<html><script>x</script><td>Sustaining capital</td> <td>10</td>")


def test_record_file_columns():
    R = pd.read_csv(SU.RECORD, keep_default_na=False)
    assert list(R.columns) == SU.COLS
    assert set(R.period) <= set(SU.PERIODS)
    assert set(R.basis) <= {"attributable", "100%", "consolidated"}
    assert R.url.str.startswith("https://").all() and (R.document != "").all()


def test_ttm_from_quarters_when_no_year_to_date_is_published():
    q = [("2026-01-01", "2026-03-31", 50.0), ("2026-04-01", "2026-06-30", 30.0), ("2026-07-01", "2026-09-30", 10.0),
         ("2025-01-01", "2025-03-31", 40.0), ("2025-04-01", "2025-06-30", 10.0), ("2025-07-01", "2025-09-30", 5.0)]
    R = rec({}, *[{"period": "3M", "period_start": a, "period_end": b, "sustaining": v} for a, b, v in q])
    x = SU.ttm(R, "ALP", "2026-09-30", flat)
    assert x["why"] == "" and x["sustaining"] == 135.0             # 100 + (50 + 30 + 10) - (40 + 10 + 5)
    y = SU.ttm(R[R.period_end != "2026-06-30"], "ALP", "2026-09-30", flat)
    assert "2 recorded, 3 needed" in y["why"]


def test_sustaining_leases_are_added_and_shown():
    R = rec({"sustaining_leases": 10.0},
            {"period": "9M", "period_start": "2026-01-01", "period_end": "2026-09-30", "sustaining": 90.0,
             "sustaining_leases": 6.0},
            {"period": "9M", "period_start": "2025-01-01", "period_end": "2025-09-30", "sustaining": 70.0,
             "sustaining_leases": 4.0})
    x = SU.ttm(R, "ALP", "2026-09-30", flat)
    assert x["sustaining"] == 132.0 and x["leases"] == 12.0           # 120 capital + 12 leases
    assert np.isnan(SU.ttm(rec({}), "ALP", "2025-12-31", flat)["leases"])   # none reported: blank, not 0


def test_edgar_filings_lists_large_documents():
    import json
    pages = {
        "https://data.sec.gov/submissions/CIK0000000042.json": {"filings": {"recent": {
            "form": ["6-K", "6-K", "S-8"], "filingDate": ["2026-10-29", "2025-01-01", "2026-11-01"],
            "accessionNumber": ["0001-26-000001", "0001-25-000001", "0001-26-000002"]}}},
        "https://www.sec.gov/Archives/edgar/data/42/000126000001/index.json": {"directory": {"item": [
            {"name": "ex991.htm", "size": "500000"}, {"name": "cover.htm", "size": "9000"}, {"name": "x.jpg", "size": "9"}]}},
    }
    F = SU.edgar_filings(42, "2026-01-01", get=lambda u: json.dumps(pages[u]).encode())
    assert F == [{"date": "2026-10-29", "form": "6-K",
                  "docs": ["https://www.sec.gov/Archives/edgar/data/42/000126000001/ex991.htm"]}]
