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


def test_country_risk_table():
    from minerval import jurisdiction as J
    T = pd.read_csv(J.TABLE, keep_default_na=False, na_values=[""])
    assert list(T.columns) == J.TABLE_COLS
    T["region"] = T.region.fillna("")
    assert not T.duplicated(["country", "region"]).any()
    assert T.source.notna().all() and T.basis.notna().all() and T.as_of.notna().all()
    assert T.rule.isin(J.RULES).all()
    filled = T.rule.isin(["score", "fixed"])
    assert (filled == T.addon_pct_points.notna()).all()          # top and median rows are worked out when loaded
    c = J.cfg()
    assert T.loc[filled, "addon_pct_points"].between(0, max(c["top_addon"], 4)).all()
    sc = T.loc[T.rule == "score", "addon_pct_points"]
    assert ((sc / c["step"]).round(9) % 1 == 0).all()             # only rounded add-ons are committed, not scores
    assert T.addon_pct_points.dropna().ge(0).all()


def test_country_weights():
    from minerval import jurisdiction as J
    R = pd.read_csv(DATA / "research" / "pnav_companies.csv")
    table = J.load_table()
    for _, r in R[R.country_weights.notna()].iterrows():
        assert J.check_weights(J.parse_weights(r.country_weights), table) == [], r.ticker
        assert isinstance(r.country_weights_source, str) and r.country_weights_source, r.ticker
    ov = R[R.addon_override.notna()]
    assert ov.addon_override.ge(0).all() and ov.addon_override_note.notna().all()


def test_royalty_ocf_record():
    """data/research/royalty_ocf.csv (written by `royalty-ocf`): one row per company and year, all sourced, and every
    company in [royalty_history] covered."""
    T = pd.read_csv(DATA / "research" / "royalty_ocf.csv")
    C = S["royalty_history"]
    assert not T.duplicated(["symbol", "fiscal_end"]).any()
    assert set(T.symbol) == set(C["companies"])
    assert T.source.str.startswith("SEC EDGAR").all() and T.shares_m.gt(0).all()
    assert (pd.to_datetime(T.filed) > pd.to_datetime(T.fiscal_end)).all()
    usd = T.currency == "USD"
    assert (T.usd_per_unit[usd] == 1).all() and T.usd_per_unit[~usd].between(0.5, 1.0).all()
    assert set(C["sheet_symbols"].values()) <= set(C["companies"])


def test_listing_columns():
    """pnav_companies.csv us_listing / canada_listing / us_otc_symbol (roadmap 5): well formed, all sourced."""
    R = pd.read_csv(DATA / "research" / "pnav_companies.csv", keep_default_na=False)
    us = R.us_listing[R.us_listing != ""]
    assert us.str.match(r"^(NYSE|NYSE American|Nasdaq|OTC ADR): [A-Z.\-]+$").all(), list(us)
    ca = R.canada_listing[R.canada_listing != ""]
    assert ca.str.match(r"^(TSX|TSX-V|CSE): [A-Z.\-]+$").all(), list(ca)
    otc = R.us_otc_symbol[R.us_otc_symbol != ""]
    assert otc.str.match(r"^[A-Z]{4,5}$").all(), list(otc)
    assert (R.listing_source != "").all()
    assert (R.ticker.str.endswith(" CN") <= (R.canada_listing != "")).all()   # every Canadian ticker has its listing


def test_screen_settings():
    C = S["portfolio_screen"]
    timing = {k.split("|")[0] for k in S["signals"]["timing"]}
    assert set(C["bucket_order"]) <= timing | {"Royalty"}
    assert set(C["buckets"].values()) <= set(C["bucket_order"])
    assert set(C["speculation"]) <= set(C["bucket_order"])
    from minerval.screen import MEASURES
    assert {m for ms in MEASURES.values() for m, _ in ms} <= set(C["score"])
    for k in ("financials_max_days", "price_max_days", "min_mcap_m", "min_mcap_developer_m"):
        assert C["filters"][k] > 0


def test_example_portfolio_is_neutral():
    """The committed example holds Sprott funds and a bullion trust only, never Model portfolio names."""
    E = pd.read_csv(CONFIG / "portfolio.example.csv")
    assert set(E.key) <= {"PHYS", "PSLV", "COP", "SGDM", "SGDJ", "COPP", "COPJ", "SLVR"}


def test_sources_log():
    """data/research/sources.csv: one row per document read, with where it is and what it held."""
    S = pd.read_csv(DATA / "research" / "sources.csv", keep_default_na=False)
    assert list(S.columns) == ["ticker", "company", "document", "period", "published", "url", "read", "found", "notes"]
    assert set(S.read) <= {"yes", "partial", "via search", "no"}
    assert S.url.str.startswith("https://").all()
    assert (S.document != "").all() and (S.company != "").all()


def test_docs_name_real_tests_and_links_resolve():
    """Spec acceptance criteria name their tests (`tests/test_x.py::test_y`): each must exist, so a criterion can't
    point at a renamed or deleted test. Relative links in README, CLAUDE.md and docs/ must resolve."""
    import re
    docs = [ROOT / "README.md", ROOT / "CLAUDE.md", *sorted((ROOT / "docs").rglob("*.md"))]
    for d in sorted((ROOT / "docs" / "specs").glob("*.md")):                  # the template's sections
        text = d.read_text()
        for section in ("## Goal", "## Scope", "## Design", "## Acceptance criteria"):
            assert f"\n{section}\n" in text, f"{d.name} has no '{section}' section (docs/specs/TEMPLATE.md)"
        assert re.search(r"^Roadmap\b.*· Status: ", text, re.M), f"{d.name} has no status line"
    for d in docs:
        text = d.read_text()
        for f, name in re.findall(r"(tests/test_\w+\.py)::(test_\w+)", text):
            if (d.name, name) == ("TEMPLATE.md", "test_y"):
                continue
            assert (ROOT / f).exists() and re.search(rf"^def {name}\(", (ROOT / f).read_text(), re.M), \
                f"{d.relative_to(ROOT)} names {f}::{name}, which doesn't exist"
        for link in re.findall(r"\]\(([^)\s]+)\)", text):
            if re.match(r"(https?:|mailto:|#)", link):
                continue
            assert (d.parent / link.split("#")[0]).exists(), f"{d.relative_to(ROOT)} links to missing {link}"


def _criteria(spec_text: str) -> dict:
    """{"A1": (ticked, text)} from a spec's acceptance criteria."""
    import re
    return {m[2]: (m[1] == "x", m[3]) for m in re.finditer(r"^- \[([ x])\] (A\d+)\. (.*)$", spec_text, re.M)}


def _ids(cell: str) -> list[str]:
    """"A1–A19" or "A2, A4" -> the criterion ids."""
    import re
    out = []
    for part in cell.split(","):
        m = re.fullmatch(r"\s*A(\d+)(?:\s*[–-]\s*A(\d+))?\s*", part)
        assert m, f"criteria '{cell}' should read like 'A1–A19' or 'A2, A4'"
        out += [f"A{i}" for i in range(int(m[1]), int(m[2] or m[1]) + 1)]
    return out


def test_roadmap_status_matches_the_specs():
    """The roadmap's status table ties each item to its spec: the criteria it names exist, the counts match what's
    ticked, the status follows from them ("(user)" and "(data)" follow-ups may stay open on a Built item), and the
    spec's status line names the item and its status. Every spec is on the roadmap, and every phase row is in the
    status table."""
    import re
    road = (ROOT / "docs" / "roadmap.md").read_text()
    table = road.split("\n## Status\n", 1)[1].split("\n## ", 1)[0]
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in table.split("\n")
            if line.startswith("| ") and not line.startswith("| # ")]
    assert rows, "no status table under '## Status' in docs/roadmap.md"
    linked = set()
    for item, _, spec_cell, status, crit_cell, checked, _ in rows:
        name = re.search(r"\(specs/([\w-]+\.md)\)", spec_cell)[1]
        linked.add(name)
        text = (ROOT / "docs" / "specs" / name).read_text()
        C, ids = _criteria(text), _ids(crit_cell)
        assert set(ids) <= set(C), f"roadmap {item}: {name} has no {sorted(set(ids) - set(C))}"
        n = sum(C[i][0] for i in ids)
        assert checked == f"{n} of {len(ids)}", f"roadmap {item}: {name} has {n} of {len(ids)} ticked in {crit_cell}"
        open_ = [i for i in ids if not C[i][0]]
        work = [i for i in open_ if not C[i][1].startswith(("(user)", "(data)"))]
        want = "Outstanding" if n == 0 else "In progress" if work else "Built"
        assert status == want, f"roadmap {item} says {status}; from {name}'s criteria it is {want} (open: {work})"
        line = next(x for x in text.split("\n") if x.startswith("Roadmap"))
        assert re.search(rf"\b{re.escape(item)}\b", line) and status in line, \
            f"{name}'s status line should name roadmap {item} and '{status}': {line}"
    specs = {p.name for p in (ROOT / "docs" / "specs").glob("*.md")} - {"TEMPLATE.md"}
    assert specs <= linked, f"specs not on the roadmap's status table: {sorted(specs - linked)}"
    phase = {line.split("|")[1].strip() for line in road.split("\n## Status\n", 1)[1].split("\n")
             if re.match(r"\| \d+[a-z]? \| \*\*", line)}
    assert phase <= {r[0] for r in rows}, f"phase rows missing from the status table: {sorted(phase - {r[0] for r in rows})}"


def test_coverage_record_is_well_formed():
    """data/research/coverage.csv (valuation-coverage A1): the fixed columns, a gap and status from the allowed sets
    (an out_of_scope gap is "out of scope" and nothing else is), one row per company and gap, a next step on every
    open row, `due` as YYYY-MM on `waiting` rows only, and an https source on `not published` and `waiting` rows."""
    from minerval import coverage
    K = coverage.load()
    R = pd.read_csv(DATA / "research" / "pnav_companies.csv")
    assert list(K.columns) == coverage.COLS
    assert set(K.gap) <= set(coverage.GAPS) and set(K.status) <= set(coverage.STATUSES)
    assert (K.gap.eq("out_of_scope") == K.status.eq("out of scope")).all()
    assert set(K.ticker) <= set(R.ticker), sorted(set(K.ticker) - set(R.ticker))
    assert not K.duplicated(["ticker", "gap"]).any(), K[K.duplicated(["ticker", "gap"])].ticker.tolist()
    open_ = K[K.status.ne("out of scope")]
    assert open_.next_step.ne("").all(), open_[open_.next_step.eq("")].ticker.tolist()
    waiting = K.status.eq("waiting")
    assert K.loc[waiting, "due"].str.fullmatch(r"20\d\d-(0[1-9]|1[0-2])").all()
    assert K.loc[~waiting, "due"].eq("").all()
    cited = K[K.status.isin(["not published", "waiting"])]
    assert cited.source.str.startswith("https://").all(), cited[~cited.source.str.startswith("https://")].ticker.tolist()


def test_every_valuation_gap_has_a_coverage_row():
    """valuation-coverage A2: every company in pnav_companies.csv is valued from its research (a royalty, a producer
    with sustaining built, a developer with a study's cash flows) or has a coverage row (a producer on the fallback a
    `sustaining` one, a developer without a study's cash flows a `study` one), and no row stays after its gap
    closes."""
    from minerval import coverage
    from minerval import studies as S
    P, C = S.load()
    assert coverage.problems(pd.read_csv(DATA / "research" / "pnav_companies.csv"), P, C, coverage.load()) == []


STUDY_STAGES = {"PEA", "PFS", "FS", "permitted", "construction", "none"}


def test_study_stage_holds_the_six_values_and_agrees_with_the_latest_study():
    """pnav_companies.csv `study_stage` (tier-valuation A20): every developer valued on studies (`stage` names a
    developer, no FCF/OCF basis) has one of the six values, nothing else has one, and where the company has a study
    on record its stage is the latest unsuperseded study's (studies.stage)."""
    from minerval import studies as S
    C = pd.read_csv(DATA / "research" / "pnav_companies.csv", keep_default_na=False, dtype=str)
    dev = C.stage.str.contains("eveloper") & C.basis.eq("")
    assert set(C.loc[dev, "study_stage"]) <= STUDY_STAGES, C.loc[dev & ~C.study_stage.isin(STUDY_STAGES), "ticker"]
    assert C.loc[~dev, "study_stage"].eq("").all(), C.loc[~dev & C.study_stage.ne(""), "ticker"].tolist()
    P, _ = S.load()
    P = P[P.superseded.str.strip().eq("")]
    for _, r in C[dev].iterrows():
        mine = P[P.ticker.eq(r.ticker)].sort_values("study_date")
        if len(mine):
            assert r.study_stage == S.stage(mine.iloc[-1]), (r.ticker, r.study_stage, S.stage(mine.iloc[-1]))


def test_agent_log_is_well_formed():
    """Filing-research-agent A11: the track record, one row per recorded batch and kind, counting the figures the
    agent proposed and how many the recorded file changed, added or dropped."""
    from minerval import research as RS
    L = pd.read_csv(DATA / "research" / "agent_log.csv", keep_default_na=False, dtype=str)
    assert list(L.columns) == RS.LOG_COLS
    assert set(L.kind) <= set(RS.KINDS)
    assert pd.to_datetime(L.date, format="%Y-%m-%d", errors="coerce").notna().all()
    for c in ("proposed", "changed", "added", "dropped"):
        assert L[c].str.fullmatch(r"\d+").all(), c
    assert (L.ticker != "").all() and L.file.str.endswith((".json", ".json (agent)")).all()


def test_agent_definition_names_real_commands():
    """Filing-research-agent A14: the subagent file loads (name, description, tools), holds the loop, the rules and
    the stop, covers every kind the batch knows, and names only `research` verbs the command line has."""
    import re
    from minerval import research as RS
    text = (ROOT / ".claude" / "agents" / "filing-researcher.md").read_text()
    front = text.split("---\n")[1]
    assert "name: filing-researcher\n" in front and "\ndescription: " in front
    tools = re.search(r"^tools: (.*)$", front, re.M)[1].split(", ")
    assert {"Bash", "Read", "Write"} <= set(tools)
    for section in ("## The loop", "## Rules", "## Where each kind is found", "## Stop"):
        assert f"\n{section}\n" in text, section
    assert "Don't run `research record`." in text and "never records" in front
    table = text.split("## Where each kind is found", 1)[1].split("\n\n", 2)[1]
    assert set(re.findall(r"^\| `(\w+)` \|", table, re.M)) == set(RS.KINDS)
    main = (ROOT / "minerval" / "__main__.py").read_text()
    verbs = set(re.findall(r'"(\w+)"', re.search(r'add_argument\("what", choices=\[(.*?)\]\)', main, re.S)[1]))
    named = set(re.findall(r"`research (\w+)", text))
    assert named and named <= verbs, named - verbs


def test_operations_record_is_well_formed():
    """Screen revision 2 (A26): annual production, reserves and resources, and royalty GEOs, one row per company, year
    end, measure, category and metal, with a source; M&I is recorded exclusive of reserves."""
    from minerval.performance import MEASURES_RECORDED, OPERATIONS_COLS, UNITS
    O = pd.read_csv(DATA / "research" / "operations.csv", keep_default_na=False)
    assert list(O.columns) == OPERATIONS_COLS
    assert set(O.measure) <= set(MEASURES_RECORDED)
    assert set(O[O.measure == "resources"].category) <= {"reserves", "mi", "inferred"}
    assert (O[O.measure != "resources"].category == "").all()
    assert set(O.unit) <= set(UNITS) and set(O.basis) <= {"attributable", "100%"}
    assert O.url.str.startswith("https://").all() and (O.document != "").all()
    assert not O.duplicated(["ticker", "period_end", "measure", "category", "metal"]).any()
    assert pd.to_datetime(O.period_end, errors="coerce").notna().all()
    assert pd.to_numeric(O.amount, errors="coerce").notna().all()


def test_fetch_downloads_the_series_the_screen_measures_read():
    """Screen revision 2: every annual series minerval/performance.py reads is in fundamentals.TYPES."""
    from minerval.fundamentals import TYPES
    from minerval.performance import SERIES
    assert set(SERIES.values()) <= set(TYPES)
