"""Jurisdiction add-on for the P/NAV discount rate, from a country table (roadmap 4b).

Discount rate = 10-year Treasury yield + risk premium + jurisdiction add-on. The add-on comes from
data/research/country_risk.csv, weighted by where each company's value is (`country_weights` in
data/research/pnav_companies.csv, e.g. "Canada/Ontario:0.6;Mexico:0.4"):

- A row of the country table ranked in the Fraser Institute's Investment Attractiveness Index records the quartile
  of its rank (`iai_quartile`, 1 = top) and gets that quartile's add-on ([jurisdiction] quartile_addons in
  settings.toml). Only the quartile is kept: the survey's ranks and scores are copyright and the repo is public.
  A row with `addon_pct_points` filled (a place the survey doesn't rank) uses that figure, with its basis stated.
- A country named without a region uses its own row when there is one, else the median add-on of its ranked
  regions (Fraser ranks Canadian provinces, US and Australian states and Argentine provinces, not the countries).
- A company's add-on: `addon_override` when filled (with a reason in `addon_override_note`); else the weighted
  table figure; else the hand-set `addon_pct_points` ("manual").
"""
import math

import numpy as np
import pandas as pd

from .config import RESEARCH, settings

TABLE = RESEARCH / "country_risk.csv"
TABLE_COLS = ["country", "region", "iai_quartile", "addon_pct_points", "basis", "source", "as_of"]


def cfg() -> dict:
    return settings()["jurisdiction"]


def quartile(rank: int, ranked: int) -> int:
    """Quartile of an IAI rank among `ranked` places: 1 (top) to 4."""
    return min(max(math.ceil(4 * rank / ranked), 1), 4)


def quartile_addon(q: int, addons=None) -> float:
    """Add-on for an IAI quartile: top quartile addons[0] ... bottom quartile addons[3]."""
    addons = addons or cfg()["quartile_addons"]
    return float(addons[int(q) - 1])


def load_table(path=None) -> dict:
    """{(country, region): add-on in percentage points}; region "" for a whole country. Country rows that aren't
    in the file but have ranked regions get the regions' median."""
    path = path or TABLE
    if not path.exists():
        return {}
    T = pd.read_csv(path, keep_default_na=False, na_values=[""])
    out = {}
    for _, r in T.iterrows():
        region = r.region if isinstance(r.region, str) else ""
        if pd.notna(r.addon_pct_points):
            v = float(r.addon_pct_points)
        else:
            v = quartile_addon(int(r.iai_quartile))
        out[(r.country.strip(), region.strip())] = v
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


def run(out_dir=None) -> list[str]:
    """The `jurisdiction` command: out/jurisdiction/comparison.csv and a summary."""
    from .config import OUT, ensure
    out_dir = out_dir or OUT / "jurisdiction"
    ensure(out_dir)
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
    return lines
