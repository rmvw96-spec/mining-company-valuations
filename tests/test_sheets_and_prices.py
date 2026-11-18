"""The daily price update. Yahoo is replaced by fixed quotes, and the Sheet by an in-memory copy of
the cells the commands use."""
import json

from minerval import prices, yahoo
from minerval.config import settings
from minerval.sheets import CLEAR, ClaudePayloads, MemorySheet, a1, blocks_by_row, col_to_num, num_to_col, runs, split_cell

QUOTES = {
    "AEM.TO": {"price": 250.0, "currency": "CAD", "date": "2026-11-17", "prev": 240.0},
    "NEM": {"price": 112.0, "currency": "USD", "date": "2026-11-17", "prev": 110.0},
    "ANTO.L": {"price": 3000.0, "currency": "GBp", "date": "2026-11-17", "prev": 2900.0},
    "GC=F": {"price": 3900.0, "currency": "USD", "date": "2026-11-17", "prev": 3850.0},
    "SI=F": {"price": 48.0, "currency": "USD", "date": "2026-11-17", "prev": 47.0},
    "HG=F": {"price": 6.0, "currency": "USD", "date": "2026-11-17", "prev": 5.9},
    "^TNX": {"price": 5.05, "currency": "USD", "date": "2026-11-17", "prev": 5.1},
}
FX = {"CAD": (0.7, "Yahoo CAD=X, inverted"), "GBP": (1.3, "Yahoo GBP=X, inverted")}


def fake_yahoo(monkeypatch):
    def quote(s):
        return QUOTES.get(s)

    def usd(c):
        return FX.get(c, (None, "x"))

    def pmap(fn, items, workers=None):
        return {i: fn(i) for i in items}

    for name, fn in (("quote", quote), ("usd_per_unit", usd), ("pmap", pmap)):
        monkeypatch.setattr(yahoo, name, fn)


def sheet():
    S = settings()["sheet"]
    h = {"P1": "Yahoo symbol", "P2": "AEM.TO", "P3": "NEM", "P4": "ANTO.L", "P5": "GONE.V",
         "R2": 244.29, "S2": "CAD", "R3": 110.31, "S3": "USD", "R4": 2900.0, "S4": "GBX"}
    for i, v in enumerate(S["price_headers"]):
        h[f"{'RSTUV'[i]}1"] = v
    for i, v in enumerate(S["fx_headers"]):
        h[f"{['Y', 'Z', 'AA', 'AB'][i]}1"] = v
    for i, (code, z) in enumerate([("USD", 1.0), ("CAD", 0.69), ("GBP", 1.31), ("GBX", "=Z4/100")]):
        h[f"Y{2 + i}"], h[f"Z{2 + i}"] = code, z
    m = {"B15": "Gold ($/oz)", "B16": "Silver ($/oz)", "B17": "Copper ($/lb)", "B30": "10-year Treasury yield"}
    return MemorySheet({S["holdings_tab"]: h, S["metals_tab"]: m})


def test_helpers():
    assert a1("Metal prices reference", "C15", 3, 1) == "'Metal prices reference'!C15:C17"
    assert a1("Holdings", "Z2") == "'Holdings'!Z2"
    assert runs([5, 2, 3, 7, 8]) == [[2, 3], [5], [7, 8]]
    assert blocks_by_row("T", "R", {2: [1], 3: [2], 5: [3]}) == [("T", "R2", [[1], [2]]), ("T", "R5", [[3]])]


def test_prices_google_like(tmp_path, monkeypatch):
    fake_yahoo(monkeypatch)
    sh = sheet()
    rep = prices.run(sheet=sh, out_dir=tmp_path)
    h = sh.cells["Holdings"]
    assert (h["R2"], h["S2"], h["T2"]) == (250.0, "CAD", "2026-11-17")
    assert (h["R4"], h["S4"]) == (3000.0, "GBX")              # GBp is renamed so XLOOKUP can't confuse it with GBP
    assert h["Z3"] == 0.7 and h["Z4"] == 1.3 and h["Z5"] == "=Z4/100"   # the formula row is left alone
    assert "GONE.V" in " ".join(rep)                              # a symbol without a price is reported
    m = sh.cells["Metal prices reference"]
    assert (m["C15"], m["C16"], m["C17"], m["C30"]) == (3900.0, 48.0, 6.0, 0.0505)


def test_layout_change_stops_the_update(tmp_path, monkeypatch):
    fake_yahoo(monkeypatch)
    sh = sheet()
    sh.cells["Holdings"]["S1"] = "Currency"
    try:
        prices.run(sheet=sh, out_dir=tmp_path)
    except prices.LayoutError:
        assert not sh.blocks                                       # nothing was written
    else:
        raise AssertionError("a changed header should stop the update")


def test_claude_payloads(tmp_path, monkeypatch):
    fake_yahoo(monkeypatch)
    f = tmp_path / "symbols.json"
    f.write_text(json.dumps({"1": "Yahoo symbol", "2": "AEM.TO", "3": "NEM"}))
    prices.run(symbols_file=f, payload_dir=tmp_path, base=86, out_dir=tmp_path)
    p = json.loads((tmp_path / "payload_prices_1.json").read_text())
    assert p["base"] == 86 and p["edits"][0] == {"kind": "writeCells", "sheet": "Holdings", "topLeft": "R2",
                                                 "rows": [[250.0, "CAD", "2026-11-17"], [112.0, "USD", "2026-11-17"]]}
    w = ClaudePayloads(tmp_path, "x")
    w.write([("Holdings", "I2", [[1.0, CLEAR]])])
    assert json.loads((tmp_path / "payload_x_1.json").read_text())["edits"][0]["rows"] == [[1.0, None]]



def test_prices_write_only_their_own_cells(tmp_path, monkeypatch):
    """Holdings D:H and V are ARRAYFORMULAs: a value typed below them breaks the whole column."""
    fake_yahoo(monkeypatch)
    monkeypatch.setattr(prices, "latest_shares", lambda s: {"shares_m": 10.0, "asof": "2026-09-30"})
    sh = sheet()
    prices.run(sheet=sh, shares=True, out_dir=tmp_path)
    allowed = {"Holdings": {"R", "S", "T", "U", "Z", "AA", "AB"}, "Metal prices reference": {"C"}}
    for tab, cell, rows in sh.blocks:
        col, _ = split_cell(cell)
        cols = {num_to_col(col_to_num(col) + j) for row in rows for j in range(len(row))}
        assert cols <= allowed[tab], (tab, cell)
    assert sh.cells["Holdings"]["U2"] == 10.0
