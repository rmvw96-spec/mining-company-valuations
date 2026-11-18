"""Matching Sprott tickers to Yahoo symbols."""
from minerval import fundamentals, yahoo
from minerval.fundamentals import _tokens, candidates, resolve


def test_candidates():
    assert candidates("AEM CN", {}) == ["AEM.TO", "AEM.V", "AEM.CN", "AEM.NE"]
    assert candidates("340 HK", {}) == ["0340.HK"]                # Hong Kong codes are zero-padded
    assert candidates("ANTO LN", {}) == ["ANTO.L"]
    assert candidates("BRK.B", {}) == ["BRK-B"]                   # US class shares use a hyphen
    assert candidates("TECK.B CN", {})[0] == "TECK-B.TO"
    assert candidates("XYZ QQ", {}) == []                         # unknown exchange code
    assert candidates("PEOLES*", {"PEOLES*": "PE&OLES.MX"}) == ["PE&OLES.MX"]


def test_name_tokens_ignore_common_words():
    assert _tokens("Agnico Eagle Mines Ltd.") == {"agnico", "eagle"}
    assert not _tokens("Gold Mining Corp") & _tokens("Silver Resources Inc")


def fake_meta(monkeypatch, names):
    def meta(sym):
        if sym not in names:
            return None
        return {"longName": names[sym], "currency": "CAD", "regularMarketPrice": 1.0, "regularMarketTime": 0}
    monkeypatch.setattr(yahoo, "meta", meta)


def test_resolve_takes_first_name_match(monkeypatch):
    fake_meta(monkeypatch, {"ABC.TO": "Unrelated Holdings", "ABC.V": "Abcde Gold Corp"})
    r = resolve("ABC CN", "Abcde Gold Corp.", {})
    assert r["yahoo"] == "ABC.V" and r["match"]
    assert r["tried"] == ["ABC.TO", "ABC.V"]


def test_resolve_falls_back_to_first_found(monkeypatch):
    fake_meta(monkeypatch, {"ABC.V": "Unrelated Holdings", "ABC.CN": "Another One"})
    r = resolve("ABC CN", "Abcde Gold Corp.", {})
    assert r["yahoo"] == "ABC.V" and not r["match"]
    assert len(r["tried"]) == 4


def test_resolve_override_counts_as_a_match(monkeypatch):
    fake_meta(monkeypatch, {"PE&OLES.MX": "Industrias Penoles"})
    r = resolve("PEOLES*", "Peñoles", {"PEOLES*": "PE&OLES.MX"})
    assert r["yahoo"] == "PE&OLES.MX" and r["match"]


def test_resolve_nothing_found(monkeypatch):
    fake_meta(monkeypatch, {})
    r = resolve("ABC CN", "Abcde", {})
    assert "yahoo" not in r and r["tried"]


def test_holdings_file_loads():
    h = fundamentals.load_holdings()
    assert list(h.columns) == ["fund", "holding", "ticker", "weight_pct"]
