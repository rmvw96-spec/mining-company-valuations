"""Valuation coverage (roadmap 6b, docs/specs/valuation-coverage-spec.md): data/research/coverage.csv records each
company the valuation doesn't fully cover, why, and what closes it. It is written by hand (a CSV writer, by column
name). `problems` is the completeness rule its test checks against the research files; `summary` is the `valuation`
report's Coverage section."""
import pandas as pd

from .config import RESEARCH

PATH = RESEARCH / "coverage.csv"
COLS = ["ticker", "gap", "status", "next_step", "due", "source", "notes"]
GAPS = ("sustaining", "study", "growth_project", "out_of_scope")
STATUSES = ("to research", "not published", "waiting", "out of scope")
EXPLAINS_A_FLAG = ("growth_project", "sustaining")


def load(path=None) -> pd.DataFrame:
    return pd.read_csv(path or PATH, keep_default_na=False, dtype=str)


def _text(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip()


def studied(P: pd.DataFrame, C: pd.DataFrame) -> set[str]:
    """Tickers with an unsuperseded study row that has cash flows (projects.csv, project_cashflows.csv)."""
    from . import studies as S
    live = P[_text(P.superseded).eq("")]
    return {p.ticker for _, p in live.iterrows() if len(S.flows(C, p))}


def problems(R: pd.DataFrame, P: pd.DataFrame, C: pd.DataFrame, K: pd.DataFrame) -> list[str]:
    """Where the record breaks the completeness rule. Every company in pnav_companies.csv (`R`) is valued from its
    research (a royalty, basis OCF; a producer, basis FCF, with sustaining built; a developer with a study's cash
    flows) or has a row in the coverage record `K`: a producer on the fallback a `sustaining` row, a company with a
    study stage but no study's cash flows a `study` row, anything else not valued any row. A `sustaining` or `study`
    row whose gap has closed, and an `out_of_scope` row for a company with a basis or study stage, must go."""
    basis, stage = _text(R.basis), _text(R.study_stage)
    built = pd.to_numeric(R.sustaining_capex_usd_m, errors="coerce").notna()
    has_study = R.ticker.isin(studied(P, C))
    fallback = basis.eq("FCF") & ~built
    no_study = stage.ne("") & ~has_study
    valued = basis.eq("OCF") | (basis.eq("FCF") & built) | (basis.eq("") & has_study)
    rows = {g: set(K.ticker[K.gap.eq(g)]) for g in GAPS}
    out = []
    for t, fb, ns, v in zip(R.ticker, fallback, no_study, valued):
        if fb and t not in rows["sustaining"]:
            out.append(f"{t}: on the free-cash-flow fallback with no sustaining row")
        elif ns and t not in rows["study"]:
            out.append(f"{t}: no study with cash flows recorded and no study row")
        elif not (v or fb or ns) and t not in set(K.ticker):
            out.append(f"{t}: not valued and no coverage row")
    on = dict(zip(R.ticker, zip(basis, built, has_study, stage)))
    for t, g in zip(K.ticker, K.gap):
        b, s, h, st = on.get(t, ("", False, False, ""))
        if g == "sustaining" and b == "FCF" and s:
            out.append(f"{t}: sustaining row, but its sustaining spending is built (remove the row)")
        elif g == "sustaining" and b != "FCF":
            out.append(f"{t}: sustaining row, but it isn't a producer on the free-cash-flow fallback (remove the row)")
        elif g == "study" and h:
            out.append(f"{t}: study row, but a study with cash flows is recorded (remove the row)")
        elif g == "out_of_scope" and (b or st):
            out.append(f"{t}: out_of_scope row, but it has a basis or a study stage")
    return out


def summary(K: pd.DataFrame, T: pd.DataFrame, today) -> list[str]:
    """The `valuation` report's Coverage section: rows by gap and status, `waiting` rows past their due month, and
    the companies flagged against outside views (valuation.csv `flags`) with no growth_project or sustaining row."""
    out = [f"Coverage (data/research/coverage.csv): {len(K)} rows"]
    for g in GAPS:
        X = K[K.gap.eq(g)]
        if len(X):
            out.append(f"  {g}: {len(X)} (" + ", ".join(f"{s} {n}" for s, n in X.groupby("status").size().items())
                       + ")")
    month = today.strftime("%Y-%m")
    late = K[K.status.eq("waiting") & K.due.ne("") & (K.due < month)]
    out += [f"  Waiting past due: {r.ticker} ({r.gap}, due {r.due}): {r.next_step}" for r in late.itertuples()] \
        or ["  Waiting past due: none"]
    explained = set(K.ticker[K.gap.isin(EXPLAINS_A_FLAG)])
    F = T[T["flags"].fillna("").astype(str).str.len().gt(0) & ~T.ticker.isin(explained)].drop_duplicates("ticker")
    out.append("  Flagged with no growth_project or sustaining row: "
               + ("; ".join(f"{r.holding} ({r.ticker})" for r in F.itertuples()) or "none"))
    return out
