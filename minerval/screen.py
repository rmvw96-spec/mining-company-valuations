"""Model portfolio from a screen (roadmap 5 and 5b).

Ranks the companies on PNAV inputs within each bucket on business performance (never on price) and proposes the
Model portfolio's holdings and target weights (A-F), buy multiples (S) and notes (U-V). Value only sets each row's
buy signal: the buy-below price at S and the status in T (tier-valuation spec, Part 5). Physical metal rows are the
user's and are kept as typed.

- The rules are public: [portfolio_screen] in config/settings.toml (buckets, markets, filters, score, sizing limits)
  and [valuation.buy] (the buy multiples). Each bucket's total weight and number of names are private:
  private/screen.toml.
- By default only companies buyable on a US or Canadian market are proposed (`--all-markets` adds the rest):
  pnav_companies.csv us_listing / canada_listing, and the fee reasons in settings. An OTC ADR with no Canadian
  listing also needs a median daily dollar volume over 3 months of at least `otc_adr_min_dollar_volume`.
- Holding names, weights and statuses never go into the repo, a log or the step summary: the report is
  out/screen/ (local), the Sheet and, with --email, a private email. The command never runs on GitHub.
- A buy multiple the user typed in S is kept: private/screen_state.json records the levels the screen wrote.

`portfolio-file` (Part 3) writes private/portfolio.csv from the tab for `backtest` and `project`.
"""
import json
import math
import time
import tomllib
from datetime import date

import numpy as np
import pandas as pd

from .config import DERIVED, OUT, PRIVATE, RESEARCH, ensure, settings
from .sheets import CLEAR, col_to_num, num_to_col, split_cell

DEST = OUT / "screen"
PRIVATE_CFG = PRIVATE / "screen.toml"
STATE = PRIVATE / "screen_state.json"
PORTFOLIO_FILE = PRIVATE / "portfolio.csv"
PHYSICAL = "Physical metal"
ROYALTY = "Royalty"
DEVELOPERS = "Growth: developers"
MEASURES = {        # measure, higher is better: business performance per share at constant prices, never price
    "producer": [("cf_ps_growth", True), ("margin_avg", True), ("margin_min", True), ("share_change_3y", False),
                 ("net_cash_pct", True), ("aisc_margin", True)],
    "developer": [("share_change_3y", False)],
    "royalty": [("ocf_ps_growth", True), ("margin_avg", True), ("margin_min", True), ("share_change_3y", False)],
}
ALL_MEASURES = sorted({m for ms in MEASURES.values() for m, _ in ms})
STUDY_BASIS, ROYALTY_BASIS = "study (risk-adjusted)", "OCF (royalty)"     # valuation.py's labels (PNAV inputs CC)
DOWNSIDE_FAILS = ("fails the downside test at any price", "negative value per share after a +30% overrun")
HOME = {".AX": "ASX", ".L": "LSE", ".JO": "JSE", ".HK": "HKEX", ".IS": "Borsa Istanbul", ".WA": "Warsaw",
        ".JK": "IDX", ".PS": "PSE", ".HE": "Helsinki", ".ST": "Stockholm", ".SN": "Santiago", ".LM": "Lima",
        ".MX": "Mexico"}
PORTFOLIO_COLS = ["key", "label", "group", "metal", "amount_usd", "already_held", "yahoo", "toronto_listing_in_cad",
                  "first_month"]


def cfg() -> dict:
    return settings()["portfolio_screen"]


def num(v) -> float:
    """A Sheet value as a float (NaN for blanks and text)."""
    if isinstance(v, bool):
        return np.nan
    if isinstance(v, (int, float, np.floating)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except ValueError:
        return np.nan


def _text(v) -> str:
    return "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v).strip()


def kind(bucket: str) -> str:
    return "royalty" if bucket == ROYALTY else "developer" if bucket == DEVELOPERS else "producer"


# ---------- universe ----------

def main_metal(r) -> str:
    """Largest revenue share for producers; the resource unit for developers."""
    if _text(r.get("peer_group")) == "Developer":
        u = _text(r.get("resource_unit"))
        return "gold" if u in ("oz Au", "oz AuEq") else "silver" if u == "oz AgEq" else "copper" if u.startswith(
            "lb") else ""
    shares = {m: num(r.get(f"share_{m}")) for m in ("gold", "silver", "copper")}
    shares = {m: v for m, v in shares.items() if v == v and v > 0}
    return max(shares, key=shares.get) if shares else ""


def bucket_of(r, c: dict | None = None) -> str:
    """The bucket for a company: the `bucket` override, else by peer group and main metal ("" when none fits)."""
    c = c or cfg()
    over = _text(r.get("bucket"))
    if over:
        return over
    m, peer = c["buckets"], _text(r.get("peer_group"))
    if peer in m:
        return m[peer]
    metal = r.get("metal") or main_metal(r)
    if "producer" in peer.lower():
        return m.get(f"{peer}|{metal}") or m.get(f"producer|{metal}", "")
    return ""


def market(r, c: dict | None = None) -> tuple[bool, str]:
    """(buyable without a per-trade fee in the default mode, note)."""
    c = (c or cfg())["markets"]
    if _text(r.get("us_listing")):
        return True, ""
    if _text(r.get("canada_listing")):
        if _text(r.get("us_otc_symbol")):
            return True, ""
        return bool(c["canada_rep_assisted"]), c["canada_rep_note"]
    return False, c["foreign_fee_note"]


def otc_adr(r) -> str:
    """The ADR symbol when the US listing is an OTC ADR ("OTC ADR: ANFTY"), else ""."""
    u = _text(r.get("us_listing"))
    return u.split(":", 1)[1].strip() if u.upper().startswith("OTC ADR:") else ""


def dollar_volume(chart: dict | None, days: int = 63) -> float:
    """Median daily US$ volume from a Yahoo 3-month chart; days with no trade (or missing from the chart) count as 0.
    NaN when the chart is missing."""
    try:
        q = chart["chart"]["result"][0]["indicators"]["quote"][0]
    except (TypeError, KeyError, IndexError):
        return np.nan
    dv = [(c or 0) * (v or 0) for c, v in zip(q.get("close") or [], q.get("volume") or [])]
    dv += [0.0] * max(0, days - len(dv))
    return float(np.median(dv))


def otc_volumes(U: pd.DataFrame, fetch=None) -> dict:
    """{ADR symbol: median daily US$ volume} for the OTC ADRs without a Canadian listing (downloads from Yahoo)."""
    from . import yahoo
    fetch = fetch or (lambda s: yahoo.chart(s, range="3mo", interval="1d"))
    syms = sorted({otc_adr(r) for _, r in U.iterrows() if otc_adr(r) and not _text(r.get("canada_listing"))})
    return {s: dollar_volume(c) for s, c in yahoo.pmap(fetch, syms).items()} if syms else {}


def apply_liquidity(U: pd.DataFrame, vols: dict, c: dict | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Marks the thinly traded OTC ADRs as not buyable in the default mode (`--all-markets` keeps them)."""
    floor = (c or cfg())["markets"]["otc_adr_min_dollar_volume"]
    U, warn = U.copy(), []
    for i, r in U.iterrows():
        s = otc_adr(r)
        if not s or s not in vols:
            continue
        v = vols[s]
        if v != v:
            U.at[i, "market_ok"], U.at[i, "market_note"] = False, f"OTC ADR {s}: trading volume not available"
            warn.append(f"Couldn't download {s}'s trading volume: {r['holding']} is left out until it can be checked.")
        elif v < floor:
            U.at[i, "market_ok"] = False
            U.at[i, "market_note"] = (f"OTC ADR {s} thinly traded: median ${v:,.0f} a day over 3 months, "
                                      f"floor ${floor:,.0f}")
    return U, warn


def where(r) -> str:
    """Model portfolio C: where it trades, US and Canadian listings first."""
    parts = [x for x in (_text(r.get("us_listing")), _text(r.get("canada_listing"))) if x]
    otc = _text(r.get("us_otc_symbol"))
    if parts:
        return "; ".join(parts) + (f"; US OTC: {otc}" if otc and not _text(r.get("us_listing")) else "")
    y = _text(r.get("yahoo"))
    home = next((v for k, v in HOME.items() if y.endswith(k)), "home market")
    return f"{home} only" + (f" (US OTC: {otc})" if otc else "") + ": about $50 a trade in an IRA"


def read_universe(sheet, research: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Every PNAV inputs company with the screen's raw fields and measures, and today's metal prices."""
    S = settings()["sheet"]
    P, a, b, tab = S["pnav_inputs"], S["pnav_first_row"], S["pnav_last_row"], S["pnav_inputs_tab"]
    D = S["downside_cols"]
    fields = {"holding": P["holding"], "mcap": P["mcap"], "addon": P["addon"], "peer_group": P["peer_group"],
              "resource_unit": P["resource_unit"], "developer_check": P["developer_check"], "yahoo": P["yahoo"],
              "share_gold": "J", "share_silver": "K", "share_copper": "L",
              # the valuation (roadmap 6), for the buy signal only
              "price": P["price"], "net_cash": P["net_cash"], "valuation_basis": P["valuation_basis"],
              "npv_pess": P["npv_pessimistic"], "npv_base": P["npv_base"], "dilution_30": P["dilution_30"],
              "buy_below_value": P["buy_below_value"], "fair_value_price": P["fair_value_price"],
              "valuation_why": P["valuation_why"], "minority": P["minority"]}
    last = max(col_to_num(c) for c in fields.values())
    grid = sheet.read(tab, f"A{a}:{num_to_col(last)}{b}")
    rows = []
    for i in range(b - a + 1):
        r = list(grid[i]) if i < len(grid) else []
        r += [""] * (last - len(r))
        d = {k: r[col_to_num(c) - 1] for k, c in fields.items()}
        d["sheet_row"] = a + i
        if _text(d["holding"]):
            rows.append(d)
    U = pd.DataFrame(rows)
    R = research if research is not None else pd.read_csv(RESEARCH / "pnav_companies.csv", keep_default_na=False,
                                                          na_values=[""])
    keep = [c for c in ("sheet_row", "ticker", "stage", "us_listing", "canada_listing", "us_otc_symbol", "bucket",
                        "bucket_note") if c in R.columns]
    U = U.merge(R[keep], on="sheet_row", how="left")
    # Holdings (financials date, price date, by Sprott ticker) and Holdings downside (by ticker)
    H = sheet.read(S["holdings_tab"], f"A2:V{S['last_row']}")
    hold, by_name = {}, {}
    for r in H:
        r = list(r) + [""] * 22
        t = _text(r[14])
        if t:
            by_name.setdefault(_text(r[1]), []).append(t)
        if t and t not in hold:
            hold[t] = {"financials_through": _text(r[13]), "price_date": _text(r[19]), "currency": _text(r[18]),
                       "yahoo_h": _text(r[15]), "fx": r[21]}
    DG = sheet.read(S["downside_tab"], f"A{S['downside_first_row']}:{D['ticker']}{S['downside_last_row']}")
    down = {}
    for r in DG:
        r = list(r) + [""] * (col_to_num(D["ticker"]) + 1)
        t = _text(r[col_to_num(D["ticker"]) - 1])
        if t and t not in down:
            down[t] = {k: r[col_to_num(D[k]) - 1] for k in ("net_cash_pct", "share_change_3y", "breakeven",
                                                             "breakeven_metal")}
    for k in ("financials_through", "price_date", "currency", "yahoo_h"):
        U[k] = [hold.get(_text(t), {}).get(k, "") for t in U.ticker]
    for k in ("net_cash_pct", "share_change_3y", "breakeven", "breakeven_metal"):
        U[k] = [down.get(_text(t), {}).get(k, "") for t in U.ticker]
    # The ticker to write in Model portfolio D: a US one where Holdings and Holdings downside carry it (KGC for
    # Kinross, whose PNAV inputs row is K CN), else the PNAV inputs one
    U["ticker_buy"] = [next((x for x in by_name.get(_text(h), []) if " " not in x and x in down), _text(t))
                       for h, t in zip(U.holding, U.ticker)]
    U["currency_buy"] = [hold.get(t, {}).get("currency", "") for t in U.ticker_buy]   # T's listing-currency price
    U["fx_buy"] = [hold.get(t, {}).get("fx", "") for t in U.ticker_buy]
    # One row per company (Wheaton is held in two funds): prefer the US listing's Sprott ticker
    U["_us"] = U.ticker.map(lambda t: " " not in _text(t))
    U = U.sort_values(["_us", "sheet_row"], ascending=[False, True]).drop_duplicates("holding").drop(columns="_us")
    U = U.sort_values("sheet_row").reset_index(drop=True)
    mc = S["metal_cells"]
    metals = {m: num((sheet.read(S["metals_tab"], cell) or [[""]])[0][0]) for m, cell in mc.items()}
    return add_measures(U, metals), metals


def add_measures(U: pd.DataFrame, metals: dict | None = None) -> pd.DataFrame:
    U = U.copy()
    for c in ("mcap", "net_cash_pct", "share_change_3y", "breakeven", "price", "net_cash", "npv_pess", "npv_base",
              "dilution_30", "buy_below_value", "fair_value_price", "minority", "fx_buy", "history_years",
              *ALL_MEASURES):
        U[c] = U[c].map(num) if c in U else np.nan
    # AISC margin at the base deck: the FCF breakeven (Holdings downside I, J) until roadmap 4a records AISC
    base = settings()["scenarios"][settings()["valuation"]["base_deck"]]
    px = [base.get(_text(m).split(" ")[0].lower(), np.nan) for m in U.get("breakeven_metal", [""] * len(U))]
    px = pd.Series(px, index=U.index, dtype=float)
    U["aisc_margin"] = (px - U.breakeven) / px
    U["addon"] = U["addon"].map(num) * 100 if "addon" in U else np.nan     # P is a fraction (0.01 = 1 point)
    U["shares"] = U.mcap / U.price.where(U.price > 0)
    U["metal"] = [main_metal(r) for _, r in U.iterrows()]
    U["bucket"] = [bucket_of(r) for _, r in U.iterrows()]
    mk = [market(r) for _, r in U.iterrows()]
    U["market_ok"], U["market_note"] = [m[0] for m in mk], [m[1] for m in mk]
    U["where"] = [where(r) for _, r in U.iterrows()]
    return U


# ---------- the buy signal (revision 2; tier-valuation spec, Part 5) ----------

def tier(r) -> str:
    """The valuation's tier from its basis (PNAV inputs CC), else from the bucket."""
    b = _text(r.get("valuation_basis"))
    if b == STUDY_BASIS:
        return "developer"
    if b == ROYALTY_BASIS:
        return "royalty"
    return "producer" if b else kind(_text(r.get("bucket")))


def buy_multiple(r) -> float:
    """S from the rule: the tier's buy multiple in [valuation.buy]."""
    return float(settings()["valuation"]["buy"][tier(r)]["buy"])


def buy_below_at(r, level: float) -> float | None:
    """The buy-below price (US$/share) at buy multiple `level`. At the rule's multiple it is the valuation's own
    (PNAV inputs CQ). A typed level re-prices it: producers and royalties (min(level × base NPV, pessimistic NPV) +
    net cash − minority interest) ÷ shares; developers the +30% overrun case, the level's change in NPV spread over
    the shares after the raise (shares × (1 + CN)). None where there's no price (the status says why)."""
    k, rule = tier(r), buy_multiple(r)
    cq = num(r.get("buy_below_value"))
    if abs(level - rule) < 1e-9:
        return cq if cq == cq else None
    base, shares = num(r.get("npv_base")), num(r.get("shares"))
    if not (base == base and base > 0 and shares == shares and shares > 0):
        return None
    if k == "developer":
        if cq != cq:
            return None
        d = num(r.get("dilution_30"))
        price = cq + (level - rule) * base / (shares * (1 + (d if d == d else 0.0)))
    else:
        pess = num(r.get("npv_pess"))
        if pess != pess:
            return None
        nc, mi = num(r.get("net_cash")), num(r.get("minority"))
        price = (min(level * base, pess) + (nc if nc == nc else 0.0) - (mi if mi == mi else 0.0)) / shares
    return price if price > 0 else None


def status(r, level: float) -> str:
    """Model portfolio T, in order: "No NPV: <why>"; "Fails downside test"; "Buy: below US$<price>" (price at or
    below); "Above fair value: review" (at or above the fair value price); "Hold"."""
    bb = buy_below_at(r, level)
    if bb is None:
        why = _text(r.get("valuation_why"))
        return "Fails downside test" if why in DOWNSIDE_FAILS else f"No NPV: {why or 'not valued'}"
    price, fair = num(r.get("price")), num(r.get("fair_value_price"))
    if price == price and price <= bb:
        cur, fx = _text(r.get("currency_buy")), num(r.get("fx_buy"))
        local = f" ({cur} {bb / fx:,.2f})" if cur and cur != "USD" and fx == fx and fx > 0 else ""
        return f"Buy: below US${bb:,.2f}{local}"
    if price == price and fair == fair and price >= fair:
        return "Above fair value: review"
    return "Hold"


# ---------- filters, score, selection, weights ----------


def _age(d: str, today: date) -> float:
    try:
        return (today - pd.Timestamp(d).date()).days
    except (ValueError, TypeError):
        return np.inf


def failure(r, today: date, all_markets: bool = False, c: dict | None = None) -> str:
    """The first hard filter a company fails ("" when it passes). No filter on price or valuation."""
    c = c or cfg()
    F, k = c["filters"], kind(r["bucket"])
    if not all_markets and not r["market_ok"]:
        return f"market ({r['market_note']})"
    if _age(r.get("financials_through"), today) > F["financials_max_days"]:
        return f"financials stale or missing ({r.get('financials_through') or 'no date'})"
    if _age(r.get("price_date"), today) > F["price_max_days"]:
        return f"price stale ({r.get('price_date') or 'no date'})"
    floor = F["min_mcap_developer_m"] if k == "developer" else F["min_mcap_m"]
    if not r["mcap"] >= floor:
        return f"market cap under ${floor:,.0f}M"
    dil = F.get("max_share_change_3y_pct_by_bucket", {}).get(r["bucket"], F["max_share_change_3y_pct"])
    if k == "producer" and r["share_change_3y"] > dil:
        return f"dilution {r['share_change_3y']:.0f}% in 3 years"
    hy, need = num(r.get("history_years")), F["min_history_years"]
    if hy == hy and hy < need:
        return f"too little history ({hy:.0f} of {need} years)"
    if F.get("max_addon_points") is not None and r["addon"] > F["max_addon_points"]:
        return f"jurisdiction add-on {r['addon']:.2f} points"
    if k == "developer" and _text(r.get("developer_check")).startswith("Short of cash"):
        return "developer short of cash"
    return ""


def rank_pct(x: pd.Series, higher_better: bool) -> pd.Series:
    """0 (worst) to 1 (best) within the series; NaN stays NaN; a single value is 1."""
    v = x.astype(float)
    ok = v.notna()
    out = pd.Series(np.nan, index=v.index)
    n = int(ok.sum())
    if n == 0:
        return out
    r = (v[ok] if higher_better else -v[ok]).rank(method="average")
    out[ok] = (r - 1) / (n - 1) if n > 1 else 1.0
    return out


def score(B: pd.DataFrame, k: str, c: dict | None = None) -> pd.DataFrame:
    """Add `score` and `measures_used` to one bucket's eligible companies."""
    w = (c or cfg())["score"]
    B = B.copy()
    num_ = pd.Series(0.0, index=B.index)
    den = pd.Series(0.0, index=B.index)
    used = pd.Series(0, index=B.index)
    for m, hb in MEASURES[k]:
        wt = float(w.get(m, 0))
        if wt <= 0:
            continue
        p = rank_pct(B[m], hb)
        B[f"p_{m}"] = p
        num_ += (p * wt).fillna(0)
        den += p.notna() * wt
        used += p.notna().astype(int)
    B["score"] = (num_ / den.replace(0, np.nan))
    B["measures_used"] = used
    return B.sort_values("score", ascending=False, na_position="last")


def select(ranked: list[str], existing: set, n: int, buffer: int) -> list[str]:
    """Top n, keeping a holding already on the tab while it ranks within n + buffer."""
    keep = [t for t in ranked[:n + buffer] if t in existing][:n]
    fill = [t for t in ranked if t not in keep][:max(0, n - len(keep))]
    chosen = set(keep + fill)
    return [t for t in ranked if t in chosen]


def weights(scores: list[float], total: float, cap: float, tilt: float = 0.0) -> tuple[list[float], float]:
    """Split `total` over the names (equal, or tilted by score), at most `cap` each. Returns (weights,
    unallocated)."""
    k = len(scores)
    if k == 0:
        return [], total
    w = np.full(k, total / k)
    s = np.array([x if x == x else 0.0 for x in scores], dtype=float)
    if tilt and k > 1 and np.ptp(s) > 0:
        dev = (s - s.mean()) / np.abs(s - s.mean()).max()
        w = w * (1 + tilt * dev)
        w = w / w.sum() * total
    for _ in range(k + 1):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = float((w[over] - cap).sum())
        w[over] = cap
        room = np.where(w < cap - 1e-12, cap - w, 0.0)
        if room.sum() <= 1e-12:
            break
        add = np.minimum(room, excess * (w * (room > 0)) / max((w * (room > 0)).sum(), 1e-12))
        w = w + add
    return [float(x) for x in w], float(total - w.sum())


# ---------- the private sizes and the state ----------

def load_sizes(path=None) -> dict:
    """{bucket: {"weight", "names"}} from private/screen.toml."""
    path = path or PRIVATE_CFG
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f).get("buckets", {})


def load_state(path=None) -> dict | None:
    path = path or STATE
    return json.loads(path.read_text()) if path.exists() else None


# ---------- the tab ----------

def read_tab(sheet) -> list[dict]:
    """Model portfolio rows 6-31 as dicts of A to the buy-below column (values), with their row number."""
    S = settings()["sheet"]
    a, b = S["portfolio_first_row"], S["portfolio_last_row"]
    n = col_to_num(S["portfolio_cols"]["buy_below"])
    grid = sheet.read(S["portfolio_tab"], f"A{a}:{num_to_col(n)}{b}")
    out = []
    for i in range(b - a + 1):
        r = list(grid[i]) if i < len(grid) else []
        r += [""] * (n - len(r))
        out.append({"row": a + i, **{num_to_col(j + 1): r[j] for j in range(n)}})
    return out


def sheet_check(U: pd.DataFrame, tab: list[dict]) -> list[str]:
    """Model portfolio T (status) and AA (buy-below at S) against the same rule in Python, for the rows with a buy
    multiple in S: a difference means the Sheet's formula or a column it reads has changed."""
    C = settings()["sheet"]["portfolio_cols"]
    T, AA, S_ = C["status"], C["buy_below"], C["review_level"]
    rows, bad, names = 0, [], []
    for row in tab:
        lvl = num(row.get(S_))
        if not _text(row.get("B")) or lvl != lvl:
            continue
        hit = U[U.holding.map(_text) == resolve(row, U)]
        if hit.empty:
            continue
        if _text(hit.holding.iloc[0]).lower() != _text(row["B"]).lower():         # XLOOKUP ignores case
            names.append(f"  row {row['row']}: '{_text(row['B'])}' (PNAV inputs: '{_text(hit.holding.iloc[0])}')")
            continue
        r, rows = hit.iloc[0], rows + 1
        want_t, want_aa, got_aa = status(r, lvl), buy_below_at(r, lvl), num(row.get(AA))
        same_aa = (want_aa is None and got_aa != got_aa) or (want_aa is not None and got_aa == got_aa
                                                             and abs(got_aa - want_aa) <= 0.005 + 1e-6 * abs(want_aa))
        if _text(row.get(T)) != want_t or not same_aa:
            aa = "blank" if want_aa is None else f"{want_aa:.4f}"
            bad.append(f"  {_text(row['B'])} (row {row['row']}): Sheet '{_text(row.get(T))}', "
                       f"{_text(row.get(AA)) or 'blank'}; the rule '{want_t}', {aa}")
    out = [f"Model portfolio {T} and {AA} agree with the screen's rule ({rows} rows)."] if not bad else [
        f"Model portfolio {T} or {AA} differ from the screen's rule in {len(bad)} rows (a formula or a column it "
        f"reads changed):"] + bad
    if names:
        out += [f"Names in B that PNAV inputs doesn't have ({T}, {AA} and the other lookups stay blank; type the "
                f"PNAV inputs name):"] + names
    return out


def resolve(row: dict, U: pd.DataFrame) -> str:
    """The universe's name for a tab row: the same name (any case), else the same ticker; the tab's name if none."""
    name, t = _text(row["B"]), _text(row["D"])
    hit = U[U.holding.map(lambda h: _text(h).lower()) == name.lower()]
    if hit.empty and t:
        hit = U[(U.ticker.map(_text) == t) | (U.ticker_buy.map(_text) == t if "ticker_buy" in U else False)]
    return _text(hit.holding.iloc[0]) if len(hit) else name


def plan(U: pd.DataFrame, tab: list[dict], sizes: dict, today: date, state: dict | None,
         all_markets: bool = False, rule_levels: bool = False, c: dict | None = None) -> dict:
    """The proposal: rows to write, the ranked buckets, drops, warnings. Pure (no Sheet)."""
    c = c or cfg()
    L = c["limits"]
    physical = [r for r in tab if _text(r["A"]) == PHYSICAL]
    existing = {resolve(r, U): r for r in tab if _text(r["B"]) and _text(r["A"]) != PHYSICAL}   # by holding name
    phys_w = sum(num(r["F"]) for r in physical if num(r["F"]) == num(r["F"]))
    screened = [b for b in c["bucket_order"] if b != PHYSICAL and b in sizes and sizes[b].get("names", 0) > 0]
    cw = sum(float(sizes[b]["weight"]) for b in screened)
    factor = (1 - phys_w) / cw if cw > 0 else 0.0
    warn, notes = [], []
    if cw > 0 and abs(factor - 1) > 1e-3:
        notes.append(f"Bucket weights in private/screen.toml sum to {cw:.1%}; scaled ×{factor:.3f} to fill the "
                     f"{1 - phys_w:.1%} left after physical metal.")
    typed = {}
    recorded = (state or {}).get("review", {})
    for name, r in existing.items():
        s, t = num(r["S"]), _text(r["D"])
        if s == s and not rule_levels and (state is None or t not in recorded or abs(recorded[t] - s) > 1e-9):
            typed[name] = s
    rows, ranked_out, drops, fails, ranks = [], {}, [], {}, {}
    for b in screened:
        n = int(sizes[b]["names"])
        k = kind(b)
        B = U[U.bucket == b].copy()
        B["fail"] = [failure(r, today, all_markets, c) for _, r in B.iterrows()]
        E = score(B[B.fail == ""], k, c)
        ranked = [_text(h) for h in E.holding]
        chosen = select(ranked, set(existing), n, int(c["buffer"]))
        if len(chosen) < n:
            warn.append(f"{b}: {len(chosen)} eligible names for {n} places.")
        cap = L["max_name_weight_speculation"] if b in c["speculation"] else L["max_name_weight"]
        Ec = E.set_index(E.holding.map(_text)).loc[chosen] if chosen else E.iloc[:0]
        ws, un = weights(list(Ec.score), float(sizes[b]["weight"]) * factor, cap, float(c["tilt"]))
        if un > 1e-6:
            warn.append(f"{b}: {un:.1%} unallocated (per-name cap {cap:.0%}).")
        for (t, r), w in zip(Ec.iterrows(), ws):
            rank = ranked.index(t) + 1
            level = typed.get(t, buy_multiple(r))
            old = existing.get(t)
            why = _text(old["U"]) if old and _text(old["U"]) and not _text(old["U"]).startswith("Screen:") \
                else why_text(r, k, rank, len(ranked))
            change = _text(old["V"]) if old else "Screen: review above fair value, or if it fails a filter"
            rows.append({"A": b, "B": t, "C": r["where"], "D": _text(old["D"]) if old else r.ticker_buy,
                         "E": (r.metal or "").capitalize(),
                         "F": round(w, 6), "S": level, "U": why, "V": change, "typed_level": t in typed,
                         "rank": rank, "score": r.score, "new": old is None,
                         "buy_below": buy_below_at(r, level), "status": status(r, level)})
        pc = [f"p_{m}" for m, _ in MEASURES[k] if f"p_{m}" in E]
        ranked_out[b] = B.assign(score=E.score.reindex(B.index), measures_used=E.measures_used.reindex(B.index),
                                 rank=pd.Series(range(1, len(E) + 1), index=E.index).reindex(B.index),
                                 picked=B.holding.map(lambda h: _text(h) in chosen), **{x: E[x] for x in pc}) \
            .sort_values(["fail", "score"], ascending=[True, False])
        fails.update({_text(h): f for h, f in zip(B.holding, B.fail) if f})
        ranks.update({t: (b, i + 1, n) for i, t in enumerate(ranked)})
    chosen_all = {r["B"] for r in rows}
    for t, r in existing.items():
        if t in chosen_all:
            continue
        if t in fails:
            why = fails[t]
        elif t in ranks:
            b, i, n = ranks[t]
            why = f"rank {i} in {b}, below {n} + buffer {c['buffer']}"
        elif _text(r["A"]) not in screened:
            why = "bucket not in private/screen.toml"
        else:
            why = "not in the screened universe now (no bucket or no data)"
        drops.append((_text(r["A"]), _text(r["B"]), why))
    S_ = settings()["sheet"]
    room = S_["portfolio_last_row"] - S_["portfolio_first_row"] + 1
    if len(physical) + len(rows) > room:
        warn.append(f"{len(physical) + len(rows)} rows for {room} on the tab: reduce `names` in private/screen.toml "
                    f"by {len(physical) + len(rows) - room} (--write would stop).")
    spec = sum(r["F"] for r in rows if r["A"] in c["speculation"])
    if spec > L["max_speculation"] + 1e-9:
        warn.append(f"Speculation (developers and expanding producers) {spec:.1%}, above {L['max_speculation']:.0%}.")
    nd = sum(1 for r in rows if r["A"] == DEVELOPERS)
    if 0 < nd < L["min_developers"] or nd > L["max_developers"]:
        warn.append(f"Developers: {nd} names (research range {L['min_developers']}-{L['max_developers']}).")
    nr = sum(1 for r in rows if r["A"] == ROYALTY)
    lo, hi = L["royalty_names"]
    if nr and not lo <= nr <= hi:
        warn.append(f"Royalty: {nr} names (research range {lo}-{hi}).")
    return {"physical": physical, "rows": rows, "ranked": ranked_out, "drops": drops, "warnings": warn,
            "notes": notes, "typed": typed, "existing": existing}


def why_text(r, k: str, rank: int, of: int) -> str:
    """Model portfolio U for a screened row: its rank and the performance measures it was scored on."""
    def f(v, fmt):
        v = num(v)
        return format(v, fmt) if v == v else "—"
    parts = []
    for m, _ in MEASURES[k]:
        label, fmt, after = DESCRIBE.get(m, (m, ".2f", ""))
        if m in ("cf_ps_growth",) and _text(r.get("cf_basis")) == "FCF":
            after += " (FCF basis)"
        parts.append(f"{label} {f(r.get(m), fmt)}{after}")
    used = num(r.get("measures_used"))
    return (f"Screen: rank {rank} of {of} (score {f(r.get('score'), '.2f')}, {int(used) if used == used else 0} "
            f"of {len(MEASURES[k])} measures); " + "; ".join(parts))


DESCRIBE = {      # measure: (label, format, after) for Model portfolio U
    "cf_ps_growth": ("cash flow per share growth", "+.0%", " a year"),
    "ocf_ps_growth": ("OCF per share growth", "+.0%", " a year"),
    "margin_avg": ("cash margin", ".0%", " average"),
    "margin_min": ("lowest year", ".0%", ""),
    "share_change_3y": ("3-year share change", "+.0f", "%"),
    "net_cash_pct": ("net cash", ".0f", "% of market value"),
    "aisc_margin": ("margin at the base deck over the breakeven", ".0%", ""),
}


# ---------- report and write ----------

def valuation_gaps(ranked: dict, V: pd.DataFrame | None) -> list[tuple[str, str, str]]:
    """[(bucket, holding, why)] for the eligible candidates (no failed filter) without an NPV at every deck and a
    valuation basis in data/derived/valuation.csv (tier-valuation A25), matched by Sheet row."""
    decks = settings()["valuation"]["decks"]
    by_row = {} if V is None else {int(r.sheet_row): r for _, r in V.iterrows()}
    out = []
    for b, B in ranked.items():
        for _, r in B[B.fail == ""].iterrows():
            v = by_row.get(int(r.sheet_row))
            if v is None:
                out.append((b, r.holding, "not valued"))
                continue
            missing = [d for d in decks if num(v.get(f"npv {d}")) != num(v.get(f"npv {d}"))]
            if len(missing) == len(decks):
                out.append((b, r.holding, _text(v.get("why")) or "no NPV"))
            elif missing:
                out.append((b, r.holding, "no NPV at " + ", ".join(missing)))
            elif not _text(v.get("valuation_basis")):
                out.append((b, r.holding, "no valuation basis"))
    return out


def report(P: dict, all_markets: bool, V: pd.DataFrame | None = None) -> list[str]:
    L = [f"Model portfolio screen ({'all markets' if all_markets else 'US and Canadian listings only'})", ""]
    L += P["notes"]
    if P["warnings"]:
        L += ["Warnings:"] + [f"  {w}" for w in P["warnings"]]
    if V is not None:
        gaps = valuation_gaps(P["ranked"], V)
        n = sum(int((B.fail == "").sum()) for B in P["ranked"].values())
        k = len(settings()["valuation"]["decks"])
        L += ["", f"Valuation: {n - len(gaps)} of {n} candidates have an NPV at all "
                  f"{ {3: 'three'}.get(k, str(k)) } decks (roadmap 6)"] + [f"  {b}: {h}: {w}" for b, h, w in gaps]
    L.append("")
    L.append("Proposal (bucket, holding, where, weight, buy multiple, rank, status):")
    for r in P["physical"]:
        L.append(f"  {r['A']}: {r['B']} (kept as typed), {num(r['F']):.1%}")
    for r in P["rows"]:
        tag = "new to the tab" if r["new"] else "already on the tab"
        lvl = f"{r['S']:g}" + (" (typed, kept)" if r["typed_level"] else "")
        L.append(f"  {r['A']}: {r['B']} [{r['D']}; {r['C']}] {r['F']:.1%}, buy multiple {lvl}, rank {r['rank']} "
                 f"({tag}): {r.get('status', '')}")
    total = sum(num(r["F"]) for r in P["physical"] if num(r["F"]) == num(r["F"])) + sum(r["F"] for r in P["rows"])
    L.append(f"  Total {total:.1%} ({len(P['physical']) + len(P['rows'])} rows of 26)")
    if P["drops"]:
        L += ["", "Dropped from the tab:"] + [f"  {b}: {h}: {why}" for b, h, why in P["drops"]]
    for b, B in P["ranked"].items():
        L += ["", f"{b}: ranked"]
        for _, r in B.iterrows():
            s = f"{r.score:.2f}" if r.score == r.score else "—"
            L.append(f"  {r.holding} [{_text(r.ticker)}] score {s}" + (f"  EXCLUDED: {r.fail}" if r.fail else
                                                                        f" ({r.get('measures_used', 0):.0f} measures)"))
    return L


def ranking_table(P: dict) -> pd.DataFrame:
    """Every screened company: bucket, rank, score, each measure's value and its 0-1 rank in the bucket (p_), and
    why an excluded one failed. Written to out/screen/ranking.csv."""
    out = []
    for b, B in P["ranked"].items():
        cols = [m for m, _ in MEASURES[kind(b)]]
        T = pd.DataFrame({"bucket": b, "holding": B.holding.map(_text), "ticker": B.ticker,
                          "picked": B.get("picked", False), "rank": B.get("rank"), "score": B.score,
                          "measures_used": B.measures_used, "excluded": B.fail,
                          "cf_basis": B.get("cf_basis", ""), "history_years": B.get("history_years")})
        for m in cols:
            T[m] = B[m]
            T[f"p_{m}"] = B.get(f"p_{m}")
        out.append(T)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def write_rows(sheet, P: dict) -> list[tuple]:
    """Blocks for Model portfolio A-F, S and U-V, rows 6-31 (physical rows first, then the proposal)."""
    S = settings()["sheet"]
    tab, a, b = S["portfolio_tab"], S["portfolio_first_row"], S["portfolio_last_row"]
    rows = [{k: r[k] for k in ("A", "B", "C", "D", "E", "F", "S", "U", "V")} for r in P["physical"]] + P["rows"]
    if len(rows) > b - a + 1:
        raise ValueError(f"{len(rows)} rows proposed; the tab has {b - a + 1} (rows can't be added below {b}).")

    def cell(v):
        return CLEAR if v is None or _text(v) == "" else v
    af, s, uv = [], [], []
    for i in range(b - a + 1):
        r = rows[i] if i < len(rows) else {}
        af.append([cell(r.get(k)) for k in "ABCDEF"])
        s.append([cell(r.get("S"))])
        uv.append([cell(r.get("U")), cell(r.get("V"))])
    return [(tab, f"A{a}", af), (tab, f"S{a}", s), (tab, f"U{a}", uv)]


def check_lookups(sheet, P: dict) -> list[str]:
    """Holdings named as the P/NAV tab names them and tickers on Holdings downside (else H-R can't look them up)."""
    S = settings()["sheet"]
    names = {_text(r[0]) for r in sheet.read(S["pnav_tab"], f"B{S['pnav_tab_first_row']}:B{S['pnav_tab_last_row']}")
             if r}
    L = S["downside_cols"]["ticker"]
    ticks = {_text(r[0]) for r in sheet.read(S["downside_tab"], f"{L}{S['downside_first_row']}:"
                                                                 f"{L}{S['downside_last_row']}") if r}
    bad = [f"{r['B']} not on the P/NAV tab" for r in P["rows"] if _text(r["B"]) not in names]
    bad += [f"{r['D']} not on Holdings downside" for r in P["rows"] if _text(r["D"]) not in ticks]
    return bad


def email_body(P: dict) -> str:
    added = [f"+ {r['A']}: {r['B']} {r['F']:.1%}" for r in P["rows"] if r["new"]]
    kept = [f"  {r['A']}: {r['B']} {num(P['existing'][r['B']]['F']):.1%} -> {r['F']:.1%}" for r in P["rows"]
            if not r["new"]]
    drops = [f"- {b}: {h} ({why})" for b, h, why in P["drops"]]
    return "\n".join(["Model portfolio rewritten by the screen.", ""] + added + kept + drops + [""] + P["warnings"])


def init_sizes(sheet, path=None) -> list[str]:
    """`screen --init`: write private/screen.toml from the tab's current split (Royalty with 0 names)."""
    path = path or PRIVATE_CFG
    if path.exists():
        return [f"{path} exists; edit it by hand (not overwritten)."]
    tab = read_tab(sheet)
    w, n = {}, {}
    for r in tab:
        b = _text(r["A"])
        if b and b != PHYSICAL and num(r["F"]) == num(r["F"]):
            w[b] = w.get(b, 0) + num(r["F"])
            n[b] = n.get(b, 0) + 1
    lines = ["# Private: each bucket's total weight (share of the whole Model portfolio) and number of names.",
             "# Written by `screen --init` from the tab; edit freely. Physical metal keeps its typed weights.", ""]
    for b in cfg()["bucket_order"]:
        if b == PHYSICAL:
            continue
        lines += [f'[buckets."{b}"]', f"weight = {round(w.get(b, 0), 4)}", f"names = {n.get(b, 0)}", ""]
    ensure(path.parent)
    path.write_text("\n".join(lines))
    return [f"Wrote {path} from the tab ({len(w)} buckets; Royalty at 0 until you set it)."]


def run(sheet, write: bool = False, all_markets: bool = False, email: bool = False, rule_levels: bool = False,
        today: date | None = None, out_dir=None, fetch_volume=None) -> list[str]:
    from .history import today_ny
    today = today or today_ny()
    out_dir = out_dir or DEST
    ensure(out_dir)
    sizes = load_sizes()
    if not sizes:
        return [f"No {PRIVATE_CFG}: run `screen --init` (writes it from the tab), then set the sizes."]
    from . import performance
    U, _ = read_universe(sheet)
    U = add_measures(performance.add(U))
    U, liq_warn = apply_liquidity(U, otc_volumes(U, fetch_volume))
    tab = read_tab(sheet)
    state = load_state()
    P = plan(U, tab, sizes, today, state, all_markets, rule_levels)
    P["warnings"] = liq_warn + P["warnings"]
    vpath = DERIVED / "valuation.csv"
    rep = report(P, all_markets, pd.read_csv(vpath) if vpath.exists() else None)
    rep += [""] + sheet_check(U, tab)
    pd.DataFrame(P["rows"]).to_csv(out_dir / "proposal.csv", index=False)
    ranking_table(P).round(4).to_csv(out_dir / "ranking.csv", index=False)
    lines = [f"Screen: {len(P['rows'])} screened rows proposed, {len(P['drops'])} dropped, "
             f"{len(P['warnings'])} warnings. Report (local only): {out_dir / 'report.txt'}."]
    if write:
        bad = check_lookups(sheet, P)
        if bad:
            rep += ["", "NOT WRITTEN: lookups would fail:"] + [f"  {x}" for x in bad]
            lines.append(f"Not written: {len(bad)} names or tickers wouldn't look up (see the report).")
        else:
            S = settings()["sheet"]
            a, b = S["portfolio_first_row"], S["portfolio_last_row"]
            backup = out_dir / f"backup-{time.strftime('%Y%m%d-%H%M%S')}.json"
            backup.write_text(json.dumps(sheet.read(S["portfolio_tab"], f"A{a}:V{b}", formulas=True), default=str))
            blocks = write_rows(sheet, P)
            sheet.write(blocks)
            rec = (state or {}).get("review", {})
            for r in P["rows"]:
                if not r["typed_level"]:
                    rec[r["D"]] = r["S"]
            ensure(STATE.parent)
            STATE.write_text(json.dumps({"review": rec, "written": today.isoformat()}, indent=1))
            back = sheet.read(S["portfolio_tab"], f"H{a}:T{b}")
            n_phys = len(P["physical"])
            failed = [r["B"] for i, r in enumerate(P["rows"])
                      if not _text((list(back[n_phys + i]) + [""] * 13)[0] if n_phys + i < len(back) else "")]
            rep += ["", f"Written. Backup: {backup}."]
            if failed:
                rep += ["Lookups showing blank after the write:"] + [f"  {x}" for x in failed]
            lines.append(f"Written to the Model portfolio ({len(P['rows'])} screened rows); backup in {backup}"
                         + (f"; {len(failed)} rows show a blank lookup (see the report)." if failed else "."))
            lines += write_portfolio_file(sheet)
            if email:
                from .alerts import send_email
                sent = send_email("Model portfolio: screen applied", email_body(P))
                lines.append("Emailed the changes." if sent else "Email not sent (ALERT_SMTP_URL / ALERT_EMAIL_TO "
                                                                 "not set).")
    (out_dir / "report.txt").write_text("\n".join(rep) + "\n")
    return lines + P["warnings"]


# ---------- Part 3: private/portfolio.csv ----------

def portfolio_rows(tab: list[dict], total: float, silver_held: float, holdings: dict, old: dict) -> list[dict]:
    """The backtest file's rows from the tab. holdings: {Sprott ticker: (yahoo, currency)}; old: {key: first_month}."""
    phys = cfg()["physical_symbols"]
    out = []
    for r in tab:
        key, w = _text(r["D"]), num(r["F"])
        if not key or w != w:
            continue
        y, cur = holdings.get(key, ("", ""))
        y = phys.get(key, y)
        amt = w * total
        base = {"label": _text(r["B"]), "group": _text(r["A"]), "metal": _text(r["E"]).lower(), "yahoo": y,
                "toronto_listing_in_cad": "yes" if y.endswith((".TO", ".V")) and cur == "CAD" else "no"}
        if key == "PSLV" and silver_held > 0:
            held = min(silver_held, amt)
            out.append({"key": key, **base, "amount_usd": round(held, 2), "already_held": "yes",
                        "first_month": old.get(key, "")})
            if amt - held > 0.005:
                out.append({"key": f"{key}-NEW", **base, "amount_usd": round(amt - held, 2), "already_held": "no",
                            "first_month": old.get(f"{key}-NEW", "")})
            continue
        out.append({"key": key, **base, "amount_usd": round(amt, 2), "already_held": "no",
                    "first_month": old.get(key, "")})
    return out


def write_portfolio_file(sheet, path=None) -> list[str]:
    """`portfolio-file`: private/portfolio.csv from the Model portfolio (the old one kept with a date)."""
    path = path or PORTFOLIO_FILE
    S = settings()["sheet"]
    C = S["portfolio_cols"]
    tab = read_tab(sheet)

    def one(cell):
        c, r = split_cell(cell)
        got = sheet.read(S["portfolio_tab"], f"{c}{r}")
        return num(got[0][0]) if got and got[0] else np.nan
    new_money, silver = one(C["new_money_cell"]), one(C["silver_held_value_cell"])
    total = (new_money if new_money == new_money else 0) + (silver if silver == silver else 0)
    hold = {}
    for r in sheet.read(S["holdings_tab"], f"A2:V{S['last_row']}"):
        r = list(r) + [""] * 22
        if _text(r[14]) and _text(r[14]) not in hold:
            hold[_text(r[14])] = (_text(r[15]), _text(r[18]))
    old = {}
    if path.exists():
        O = pd.read_csv(path, keep_default_na=False, dtype=str)
        old = {k: v for k, v in zip(O.key, O.first_month) if v}
        path.with_name(f"portfolio.{date.today().isoformat()}.csv").write_text(path.read_text())
    rows = portfolio_rows(tab, total, silver if silver == silver else 0.0, hold, old)
    ensure(path.parent)
    pd.DataFrame(rows, columns=PORTFOLIO_COLS).to_csv(path, index=False)
    missing = sum(1 for r in rows if not r["yahoo"])
    return [f"Wrote {path.name} for the backtest: {len(rows)} rows" + (f", {missing} without a Yahoo symbol." if missing
                                                                      else ".")]
