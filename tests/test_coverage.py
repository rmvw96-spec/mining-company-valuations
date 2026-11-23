"""Valuation coverage (roadmap 6b, docs/specs/valuation-coverage-spec.md): the completeness rule on fixture companies.
The checks on the real record are in tests/test_data_files.py."""
import numpy as np
import pandas as pd

from minerval import coverage as K


def companies():
    """A royalty, a producer with sustaining built, one on the fallback, a developer with a study's cash flows, one
    without, and an explorer."""
    return pd.DataFrame({
        "ticker": ["ROY", "PRD", "FBK", "DEV", "DNS", "EXP"],
        "basis": ["OCF", "FCF", "FCF", np.nan, np.nan, np.nan],
        "study_stage": [np.nan, np.nan, np.nan, "PFS", "PEA", np.nan],
        "sustaining_capex_usd_m": [np.nan, 100.0, np.nan, np.nan, np.nan, np.nan]})


def studies():
    P = pd.DataFrame({"ticker": ["DEV", "DNS"], "project": ["Big Pit", "Paper Pit"], "study_date": ["2025-01-01"] * 2,
                      "superseded": ["", ""]})
    C = pd.DataFrame({"ticker": ["DEV", "DEV"], "project": ["Big Pit"] * 2, "study_date": ["2025-01-01"] * 2,
                      "year": [1, 2]})
    return P, C


def record(*rows):
    return pd.DataFrame([dict(zip(K.COLS, r + ("",) * (len(K.COLS) - len(r)))) for r in rows], columns=K.COLS)


def test_every_company_is_valued_or_explained_and_closed_gaps_are_removed():
    P, C = studies()
    R = companies()
    full = record(("FBK", "sustaining", "to research", "record the Q3 MD&A rows"),
                  ("DNS", "study", "to research", "record the PEA's cash flows"),
                  ("EXP", "out_of_scope", "out of scope"))
    assert K.problems(R, P, C, full) == []
    assert K.problems(R, P, C, full.iloc[1:]) == ["FBK: on the free-cash-flow fallback with no sustaining row"]
    assert K.problems(R, P, C, full.drop(index=1)) == ["DNS: no study with cash flows recorded and no study row"]
    assert K.problems(R, P, C, full.iloc[:2]) == ["EXP: not valued and no coverage row"]
    stale = record(("PRD", "sustaining", "to research", "x"), ("DEV", "study", "to research", "x"),
                   ("ROY", "out_of_scope", "out of scope"))
    assert K.problems(R, P, C, pd.concat([full, stale])) == [
        "PRD: sustaining row, but its sustaining spending is built (remove the row)",
        "DEV: study row, but a study with cash flows is recorded (remove the row)",
        "ROY: out_of_scope row, but it has a basis or a study stage"]


def test_a_superseded_study_doesnt_close_a_study_gap():
    P, C = studies()
    P.loc[0, "superseded"] = "Big Pit FS, 2026"
    full = record(("FBK", "sustaining", "to research", "x"), ("DNS", "study", "to research", "x"),
                  ("EXP", "out_of_scope", "out of scope"))
    assert K.problems(companies(), P, C, full) == ["DEV: no study with cash flows recorded and no study row"]
