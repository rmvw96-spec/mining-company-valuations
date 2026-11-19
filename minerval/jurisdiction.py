"""Jurisdiction add-on for the P/NAV discount rate, from a country table (roadmap 4b).

Discount rate = 10-year Treasury yield + risk premium + jurisdiction add-on. The add-on comes from
data/research/country_risk.csv, weighted by where each company's value is (`country_weights` in
data/research/pnav_companies.csv, e.g. "Canada/Ontario:0.6;Mexico:0.4").

Each row of the country table has a `rule`:
  score   the add-on from the Fraser Institute's Policy Perception Index: the average of the latest
          [jurisdiction] years scores, mapped onto a straight line from 0 at `floor_score` (and above) to
          `top_addon` at a score of 0, rounded to `step`. `build_table` writes these rows from a scores file kept in
          private/ (the survey is copyright and the repo is public, so only the rounded add-ons are committed).
  fixed   a figure with its reason in `basis` (a place the survey doesn't rank).
  top     `top_addon` (places the survey ranks near the bottom in an earlier year, or under sanctions).
  median  the median add-on of the `score` rows (provisional, until a ranking is checked).
A country named without a region uses its own row when there is one, else the median add-on of its regions
(Fraser ranks Canadian provinces, US and Australian states and Argentine provinces, not the countries).

A company's add-on: `addon_override` when filled (with a reason in `addon_override_note`); else the weighted
table figure; else the hand-set `addon_pct_points` ("manual").
"""
import numpy as np
import pandas as pd

from .config import RESEARCH, settings

TABLE = RESEARCH / "country_risk.csv"
TABLE_COLS = ["country", "region", "rule", "addon_pct_points", "few_responses", "basis", "source", "as_of"]
RULES = ("score", "fixed", "top", "median")


def cfg() -> dict:
    return settings()["jurisdiction"]


def addon_from_score(score: float, c: dict | None = None) -> float:
    """0 at floor_score and above, rising in a straight line to top_addon at 0; rounded to step."""
    c = c or cfg()
    floor, top, step = c["floor_score"], c["top_addon"], c["step"]
    raw = 0.0 if score >= floor else top * (floor - score) / floor
    return round(round(raw / step) * step, 4)


def average_score(row, c: dict | None = None) -> float | None:
    """The average of a scores-file row's latest `years` policy scores (columns ppi_<year>; blanks skipped)."""
    c = c or cfg()
    cols = sorted((k for k in row.keys() if str(k).startswith("ppi_")), reverse=True)[:c["years"]]
    vals = [float(row[k]) for k in cols if row[k] is not None and pd.notna(row[k]) and str(row[k]).strip() != ""]
    return sum(vals) / len(vals) if vals else None


def build_table(scores_path, source: str, as_of: str, path=None, c: dict | None = None) -> list[str]:
    """Rewrite the `score` rows of country_risk.csv from a private scores file (country, region, few_responses,
    ppi_<year>...); rows with other rules are kept. Returns report lines."""
    c = c or cfg()
    path = path or TABLE
    S = pd.read_csv(scores_path, keep_default_na=False, na_values=[""])
    old = pd.read_csv(path, keep_default_na=False, na_values=[""]) if path.exists() else pd.DataFrame(columns=TABLE_COLS)
    keep = old[old["rule"] != "score"]
    years = sorted((k[4:] for k in S.columns if k.startswith("ppi_")), reverse=True)[:c["years"]]
    basis = (f"Policy Perception Index, average of {', '.join(sorted(years))} where scored: 0 at {c['floor_score']:g} "
             f"and above, {c['top_addon']:g} at 0, in steps of {c['step']:g}")
    rows = []
    for _, r in S.iterrows():
        avg = average_score(r, c)
        if avg is None:
            continue
        few = str(r.get("few_responses", "")).strip().lower() in ("true", "yes", "1")
        rows.append({"country": r.country, "region": r.region if isinstance(r.region, str) else "", "rule": "score",
                     "addon_pct_points": addon_from_score(avg, c), "few_responses": "yes" if few else "",
                     "basis": basis, "source": source, "as_of": as_of})
    T = pd.concat([pd.DataFrame(rows, columns=TABLE_COLS), keep[TABLE_COLS]], ignore_index=True)
    T.to_csv(path, index=False)
    return [f"Wrote {len(rows)} scored places and kept {len(keep)} other rows in {path}."]


def load_table(path=None, c: dict | None = None) -> dict:
    """{(country, region): add-on in percentage points}; region "" for a whole country. Country rows that aren't
    in the file but have regions get the regions' median."""
    path = path or TABLE
    if not path.exists():
        return {}
    c = c or cfg()
    T = pd.read_csv(path, keep_default_na=False, na_values=[""])
    T["region"] = T.region.fillna("").astype(str).str.strip()
    T["country"] = T.country.astype(str).str.strip()
    scored = T.loc[T.rule == "score", "addon_pct_points"].astype(float)
    med = float(np.median(scored)) if len(scored) else np.nan
    out = {}
    for _, r in T.iterrows():
        if r.rule == "top":
            v = float(c["top_addon"])
        elif r.rule == "median":
            v = med
        else:
            v = float(r.addon_pct_points)
        out[(r.country, r.region)] = v
    regions = {}
    for (c, reg), v in out.items():
        if reg:
            regions.setdefault(c, []).append(v)
    for c, vs in regions.items():
        out.setdefault((c, ""), float(np.median(vs)))
    return out


def parse_weights(text) -> list[tuple[str, str, float]]:
    """"Canada/Ontario:0.6;Mexico:0.4" -> [("Canada", "Ontario", 0.6), ("Mexico", "", 0.4)]; [] when blank."""
    if not isinstance(text, str) or not text.strip():
        return []
    out = []
    for part in text.split(";"):
        place, _, w = part.rpartition(":")
        if not place:
            raise ValueError(f"no weight in {part!r}")
        country, _, region = place.partition("/")
        out.append((country.strip(), region.strip(), float(w)))
    return out


def check_weights(parts, table: dict, tol=None) -> list[str]:
    """Problems with a parsed `country_weights`: weights not summing to 1, places not in the table."""
    tol = cfg()["weight_tolerance"] if tol is None else tol
    errs = []
    s = sum(w for _, _, w in parts)
    if parts and abs(s - 1) > tol:
        errs.append(f"weights sum to {s:.3f}")
    for c, reg, w in parts:
        if w < 0:
            errs.append(f"negative weight for {c}")
        if (c, reg) not in table:
            errs.append(f"{c + ('/' + reg if reg else '')} is not in country_risk.csv")
    return errs


def weighted_addon(parts, table: dict) -> float:
    return sum(w * table[(c, reg)] for c, reg, w in parts) / sum(w for _, _, w in parts)


def company_addon(row, table: dict) -> tuple[float, str]:
    """(add-on in percentage points, basis): "override", "table" or "manual" (the hand-set figure)."""
    ov = row.get("addon_override")
    if ov is not None and pd.notna(ov) and str(ov).strip() != "":
        return float(ov), "override"
    parts = parse_weights(row.get("country_weights"))
    if parts and not check_weights(parts, table):
        return round(weighted_addon(parts, table), 4), "table"
    manual = row.get("addon_pct_points")
    return (float(manual) if manual is not None and pd.notna(manual) else np.nan), "manual"


def apply(R: pd.DataFrame, table: dict | None = None) -> pd.DataFrame:
    """The research rows with `addon_manual` (the hand-set figure), `addon_pct_points` (the one used) and
    `addon_basis`."""
    table = load_table() if table is None else table
    R = R.copy()
    if "country_weights" not in R:
        R["addon_manual"], R["addon_basis"] = R["addon_pct_points"], "manual"
        return R
    got = [company_addon(r, table) for _, r in R.iterrows()]
    R["addon_manual"] = R["addon_pct_points"]
    R["addon_pct_points"] = [g[0] for g in got]
    R["addon_basis"] = [g[1] for g in got]
    return R


def comparison(R: pd.DataFrame, table: dict | None = None) -> pd.DataFrame:
    """Old (hand-set) and new add-on for every row with a cash-flow basis: the table the user reviews."""
    A = apply(R, table)
    A = A[A.basis.astype(str).isin(["FCF", "OCF"])]
    out = A[["ticker", "holding", "country_weights", "addon_manual", "addon_pct_points", "addon_basis"]].copy()
    out["change"] = out.addon_pct_points - out.addon_manual
    return out.rename(columns={"addon_manual": "old", "addon_pct_points": "new", "addon_basis": "basis"})


def run(out_dir=None, scores=None, source=None, as_of=None) -> list[str]:
    """The `jurisdiction` command: out/jurisdiction/comparison.csv and a summary. With `scores`, first rebuild the
    table's scored rows from that (private) file."""
    from .config import OUT, ensure
    out_dir = out_dir or OUT / "jurisdiction"
    ensure(out_dir)
    pre = []
    if scores:
        if not source or not as_of:
            return ["--build needs --source (the survey edition) and --as-of (its publication month)."]
        pre = build_table(scores, source, as_of)
    R = pd.read_csv(RESEARCH / "pnav_companies.csv")
    table = load_table()
    C = comparison(R, table)
    C.to_csv(out_dir / "comparison.csv", index=False)
    lines = [f"Country table: {len(table)} places. Companies with a cash-flow basis: {len(C)}; "
             + ", ".join(f"{k} {v}" for k, v in C.basis.value_counts().items()) + "."]
    bad = []
    for _, r in R.iterrows():
        try:
            errs = check_weights(parse_weights(r.get("country_weights")), table)
        except ValueError as e:
            errs = [str(e)]
        if errs:
            bad.append(f"  {r.ticker}: " + "; ".join(errs))
    if bad:
        lines += ["country_weights that can't be used (the hand-set add-on is kept):"] + bad
    big = C[C.change.abs() >= 1].sort_values("change")
    if len(big):
        lines.append("Add-ons moving 1 point or more:")
        lines += [f"  {r.ticker}: {r.old:g} -> {r.new:g}" for _, r in big.iterrows()]
    lines.append(f"Full table: {out_dir / 'comparison.csv'}.")
    return pre + lines
