"""Rows and numbers out of filing text (filing-research-agent spec A4-A6). The layouts are the ones met in the
Nov 2026 research (the mine-study-rebuild and sustaining-research-batch skills), with invented figures."""
import pytest

from minerval import tables as T

# EDGAR HTML through documents.to_text: one table row per line, cells joined by " | "
PIPE = """Capital expenditures reconciliation
Three Months Ended September 30, | Nine Months Ended September 30,
(in millions) | 2026 | 2025 | 2026 | 2025
Sustaining capital expenditures (1) | $ | 41.2 | $ | 38.0 | $ | 120.5 | $ | 101.9
Non-sustaining capital | 12.0 | 9.5 | (3.1 | ) | 30.2
Total capital expenditures | 53.2 | 47.5 | 117.4 | -
Sustaining lease payments | (2) | 3.0 | 2.0 | 8.5 | 6.0"""

# pdftotext -layout: columns kept apart by runs of spaces
LAYOUT = """                                   Year ended December 31
US$ '000                              2025          2024
Sustaining capital                   60,412        55,190
Sustaining leases                     1,600            --
"""

# One cell per line (Perpetua, Skouries): the label, then each value on its own line
ONE_PER_LINE = """Table 22-4  Annual cash flow
Years ended
After-Tax Cash Flow
(234.4)
-
512.0
610.5
Payable gold (koz)
"""

# EDGAR HTML with one cell per line, blank cells as zero-width spaces and "$" in cells of their own (Kinross)
EDGAR_CELLS = "Years ended December 31, 2025\nUSA\nTotal\nSustaining capital expenditures\n\u200b\n$\n113.0\n\u200b\n$\n188.6\nLease payments - sustaining (k)\n\u200b\n6.3\n"


def test_numbers_layout_traps():
    """A5: parentheses and EDGAR's split negatives, dashes as zero, thousands by comma or space, unit tokens."""
    assert T.numbers("(234.4) | 1,182.7 | -45 | −3.5") == [-234.4, 1182.7, -45.0, -3.5]
    assert T.numbers("(3.1 | ) | 30.2") == [-3.1, 30.2]                 # EDGAR splits "(3.1)" across cells
    assert T.numbers("12.0 | - | -- | – | 7") == [12.0, 0.0, 0.0, 0.0, 7.0]
    assert T.numbers("53.2 | 47.5 | -") == [53.2, 47.5, 0.0]            # a trailing dash cell isn't lost
    assert T.numbers("US$ '000  60,412   55,190") == [60412.0, 55190.0]  # the unit token isn't a number
    assert T.numbers("$000s 1 | (US$M) 2") == [1.0, 2.0]
    assert T.numbers("35 645 576   1 200", space_thousands=True) == [35645576.0, 1200.0]
    assert T.numbers("35 645 576") == [35.0, 645.0, 576.0]              # single spaces separate cells by default
    assert T.numbers("12.5%  $ 4.20") == [12.5, 4.2]


def test_rows_in_pipe_tables():
    """A4: a label's row in an EDGAR table, its numbers (not the footnote marker in the label), and the nearest
    period header above it."""
    R = T.rows(PIPE, r"sustaining capital")
    assert [r["label"] for r in R] == ["Sustaining capital expenditures (1)", "Non-sustaining capital"]
    assert R[0]["values"] == [41.2, 38.0, 120.5, 101.9]
    assert R[0]["period"].startswith("Three Months Ended September 30, | Nine Months Ended")
    assert R[0]["columns"] == "(in millions) | 2026 | 2025 | 2026 | 2025"
    assert T.rows("(1) Figures for 2026 and 2025 are restated\nSustaining capital | 4.0", "sustaining")[0]["columns"] == ""
    assert R[1]["values"] == [12.0, 9.5, -3.1, 30.2]
    assert T.rows(PIPE, r"^total capital")[0]["values"] == [53.2, 47.5, 117.4, 0.0]
    L = T.rows(PIPE, r"lease payments")[0]                               # a footnote marker in its own cell
    assert (L["label"], L["values"]) == ("Sustaining lease payments (2)", [3.0, 2.0, 8.5, 6.0])


def test_rows_in_pdf_layout_text():
    """A4: pdftotext -layout rows, the label kept apart from its numbers by spaces; the header is 'Year ended'."""
    R = T.rows(LAYOUT, r"^\s*sustaining")
    assert [(r["label"], r["values"]) for r in R] == [("Sustaining capital", [60412.0, 55190.0]),
                                                       ("Sustaining leases", [1600.0, 0.0])]
    assert R[0]["period"] == "Year ended December 31" and R[0]["period_line"] == 0


def test_rows_with_period_header_one_cell_per_line():
    """A4: a label alone on its line takes the numbers on the lines that follow, up to the next text line."""
    R = T.rows(ONE_PER_LINE, r"after-tax cash flow")
    assert R[0]["values"] == [-234.4, 0.0, 512.0, 610.5]
    assert R[0]["period"] == "Years ended" and R[0]["line"] == 2
    E = T.rows(EDGAR_CELLS, r"^sustaining capital")
    assert E[0]["values"] == [113.0, 188.6] and E[0]["period"] == "Years ended December 31, 2025"
    assert T.rows(EDGAR_CELLS, r"lease payments")[0]["values"] == [6.3]


def test_series_checks_the_total():
    """A6: a total and N years; refused when the count is wrong or the years don't sum to the total beyond
    rounding (half the last decimal place per figure)."""
    assert T.series([10.0, 2.5, 3.5, 4.0], 3) == [2.5, 3.5, 4.0]
    assert T.series([2.5, 3.5, 4.0, 10.0], 3, total="last") == [2.5, 3.5, 4.0]
    assert T.series([10.1, 2.5, 3.5, 4.0], 3) == [2.5, 3.5, 4.0]        # within rounding: 4 figures x 0.05
    with pytest.raises(ValueError, match="sum"):
        T.series([10.5, 2.5, 3.5, 4.0], 3)
    with pytest.raises(ValueError, match="3 years"):
        T.series([10.0, 2.5, 7.5], 3)
    assert T.series([2.5, 3.5], 2, total=None) == [2.5, 3.5]
