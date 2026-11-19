"""Checks on the hand-maintained inputs in config/ and data/, so a bad edit fails CI rather than a run."""
import pandas as pd
import pytest

from minerval.config import CONFIG, DATA, ROOT, settings
from minerval.price_model import METALS

S = settings()
FUNDS = S["holdings"]["fund_order"]


@pytest.fixture(scope="module")
def holdings():
    return pd.read_csv(ROOT / S["holdings"]["file"])


def test_settings_are_consistent():
    assert set(FUNDS) == set(S["funds"])
    assert {f["metal"] for f in S["funds"].values()} <= set(METALS)
    for name, prices in S["scenarios"].items():
        assert set(prices) == set(METALS), name
    for name in S["stress"]["scenarios"] + S["pnav"]["scenarios"]:
        assert name == "Today" or name in S["scenarios"], name
    assert set(S["sheet"]["metal_cells"]) == set(S["sheet"]["metal_labels"]) == set(METALS)
    assert S["sheet"]["pnav_first_row"] < S["sheet"]["pnav_last_row"] <= S["sheet"]["last_row"]
    assert set(S["sheet"]["fx_derived"]) <= set(S["sheet"]["fx_rows"])
    assert len(S["sheet"]["price_headers"]) == 5 and len(S["sheet"]["fx_headers"]) == 4


def test_holdings(holdings):
    assert list(holdings.columns) == ["fund", "holding", "ticker", "weight_pct"]
    assert holdings.notna().all().all()
    assert set(holdings.fund) <= set(FUNDS)
    assert not holdings.duplicated(["fund", "ticker"]).any()
    assert (holdings.weight_pct > 0).all()
    totals = holdings.groupby("fund").weight_pct.sum()
    assert totals.between(97, 101).all(), totals.to_dict()     # Sprott's page rounds, and leaves out cash


def test_pnav_research(holdings):
    R = pd.read_csv(DATA / "research" / "pnav_companies.csv")
    assert R.sheet_row.is_unique
    assert R.sheet_row.between(S["sheet"]["pnav_first_row"], S["sheet"]["pnav_last_row"]).all()
    assert set(R.ticker) <= set(holdings.ticker)
    assert set(R.mix_fund.dropna()) <= set(FUNDS)
    m = R[R.basis.notna()]
    assert set(m.basis) <= {"FCF", "OCF"}
    assert m.yahoo.notna().all() and m.reserve_life_years.gt(0).all() and m.addon_pct_points.ge(0).all()
    assert set(S["pnav"]["no_metal_adjustment"]) <= set(R.ticker)


def test_metal_mix(holdings):
    M = pd.read_csv(CONFIG / "metal_mix.csv")
    assert M.ticker.is_unique and set(M.ticker) <= set(holdings.ticker)
    shares = M[list(METALS)]
    assert shares.stack().dropna().between(0, 1).all()
    assert (shares.fillna(0).sum(axis=1) <= 1.0 + 1e-9).all()


def test_overrides_and_corrections(holdings):
    O = pd.read_csv(CONFIG / "symbol_overrides.csv")
    assert O.ticker.is_unique and O.yahoo.notna().all()
    C = pd.read_csv(CONFIG / "corrections.csv")
    assert set(C.ticker) <= set(holdings.ticker)
    assert set(C.field.dropna()) <= {"book", "ocf", "fcf", "ebitda", "revenue", "debt", "cash"}
    assert C.source.notna().all(), "every correction needs a source"


def test_resource_research_columns():
    from minerval.pnav import RESOURCE_CATEGORIES, RESOURCE_COLS, RESOURCE_UNITS
    R = pd.read_csv(DATA / "research" / "pnav_companies.csv")
    assert set(RESOURCE_COLS) <= set(R.columns)
    filled = R[R.resource_amount.notna()]
    assert (filled.resource_amount > 0).all()
    assert set(filled.resource_unit) <= set(RESOURCE_UNITS)
    assert set(filled.resource_category) <= set(RESOURCE_CATEGORIES)
    assert filled.resource_source.notna().all() and filled.resource_date.notna().all(), "a filled amount needs a source and date"
    blank = R[R.resource_amount.isna()]
    assert blank[["resource_unit", "resource_category", "resource_source"]].isna().all().all()


def test_financing_and_split_columns():
    from minerval.pnav import FINANCING_COLS, SPLIT_COLS
    R = pd.read_csv(DATA / "research" / "pnav_companies.csv")
    assert set(FINANCING_COLS + SPLIT_COLS) <= set(R.columns)
    for c in ("committed_funding_usd_m", "remaining_capex_usd_m", "resource_reserves", "resource_mi_excl_reserves",
              "resource_inferred"):
        assert (R[c].dropna() >= 0).all(), c
    money = R.committed_funding_usd_m.notna() | R.remaining_capex_usd_m.notna() | R.funded_per_company.notna()
    assert R.loc[money, "financing_source"].notna().all(), "a financing figure needs a source"
    assert set(R.funded_per_company.dropna()) <= {"Yes"}
    split = R.resource_reserves.notna() | R.resource_mi_excl_reserves.notna() | R.resource_inferred.notna()
    assert R.loc[split, "resource_split_source"].notna().all(), "a resource split needs a source"
    assert R.loc[split, "resource_amount"].notna().all(), "a split row keeps its total in resource_amount"


def test_industry_aisc_table():
    A = pd.read_csv(DATA / "research" / "industry_aisc.csv", dtype={"quarter": str})
    assert list(A.columns) == ["quarter", "aisc_usd_oz", "published", "source", "note"]
    assert A.quarter.is_unique and A.quarter.str.fullmatch(r"20\d\dQ[1-4]").all()
    assert list(A.quarter) == sorted(A.quarter)
    assert (A.aisc_usd_oz > 0).all()
    pub = pd.to_datetime(A.published)
    assert pub.is_monotonic_increasing
    quarter_end = pd.PeriodIndex(A.quarter, freq="Q").end_time
    assert (pub > quarter_end).all()                     # published after the quarter it reports
    assert A.source.str.contains("https://").all()
