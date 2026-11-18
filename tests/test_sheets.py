"""Cell references, write blocks and the sheet back ends (in-memory and Claude payloads)."""
import json

import pytest

from minerval.sheets import (CLEAR, ClaudePayloads, MemorySheet, a1, blocks_by_row, col_to_num, column, count_cells,
                             load_claude_read, num_to_col, split_cell)


@pytest.mark.parametrize("col,n", [("A", 1), ("Z", 26), ("AA", 27), ("AB", 28), ("AP", 42), ("ZZ", 702), ("AAA", 703)])
def test_column_letters(col, n):
    assert col_to_num(col) == n
    assert num_to_col(n) == col
    assert col_to_num(col.lower()) == n


def test_column_letters_round_trip():
    assert all(col_to_num(num_to_col(n)) == n for n in range(1, 2000))


def test_split_cell():
    assert split_cell("ab12") == ("AB", 12)
    for bad in ("12", "A", "A1:B2", "'Tab'!A1"):
        with pytest.raises(ValueError):
            split_cell(bad)


def test_a1_ranges():
    assert a1("Holdings", "R2", 3, 3) == "'Holdings'!R2:T4"
    assert a1("Holdings", "Y2", 1, 4) == "'Holdings'!Y2:AB2"


def test_blocks_and_counts():
    blocks = blocks_by_row("T", "I", {7: [1, 2], 2: [3, 4], 3: [5, 6]})
    assert blocks == [("T", "I2", [[3, 4], [5, 6]]), ("T", "I7", [[1, 2]])]
    assert count_cells(blocks) == 6
    assert blocks_by_row("T", "I", {}) == []


def test_column_of_a_ragged_read():
    assert column([["a", "x"], [], ["c"]], 5) == {5: "a", 6: "", 7: "c"}
    assert column([["a", "x"], ["b"]], 5, 1) == {5: "x", 6: ""}


def test_memory_sheet_reads_like_google():
    sh = MemorySheet({"T": {"A1": 1, "B1": 2, "A2": 3, "A4": ""}})
    assert sh.read("T", "A1:B4") == [[1, 2], [3, ""]]          # trailing empty rows are dropped
    assert sh.read("T", "B1") == [[2]]
    assert sh.read("Missing", "A1:A3") == []


def test_memory_sheet_write_clears_and_skips():
    sh = MemorySheet({"T": {"A1": 1, "B1": 2}})
    n = sh.write([("T", "A1", [[CLEAR, None, 9]])])
    assert n == 3
    assert sh.cells["T"] == {"A1": "", "B1": 2, "C1": 9}       # None leaves a cell alone, CLEAR empties it


def test_claude_payloads_split_and_chain_revisions(tmp_path):
    (tmp_path / "payload_p_9.json").write_text("{}")           # left over from an earlier run
    w = ClaudePayloads(tmp_path, "p", base=40)
    blocks = [("T", f"A{1 + 500 * i}", [[1]] * 500) for i in range(3)]
    assert w.write(blocks) == 1500
    files = sorted(tmp_path.glob("payload_p_*.json"))
    assert [f.name for f in files] == ["payload_p_1.json", "payload_p_2.json", "payload_p_3.json"]
    packs = [json.loads(f.read_text()) for f in files]
    assert packs[0]["base"] == 40
    assert packs[1]["base"] == packs[2]["base"] == "SET_TO_PREVIOUS_RESULT_REVISION"
    assert all(sum(len(r) for e in p["edits"] for r in e["rows"]) <= ClaudePayloads.MAX_CELLS for p in packs)


def test_claude_payloads_cannot_read(tmp_path):
    with pytest.raises(RuntimeError):
        ClaudePayloads(tmp_path, "p").read("Holdings", "A1")


@pytest.mark.parametrize("saved", [
    {"2": "AEM.TO", "3": ["NEM"]},
    {"value": {"rows": {"2": [{"value": "AEM.TO"}], "3": [{"formula": "=X", "value": "NEM"}]}}},
    [{"type": "text", "text": json.dumps({"rows": {"2": ["AEM.TO"], "3": [{"spilledFrom": "A1", "value": "NEM"}]}})}],
])
def test_load_claude_read_formats(tmp_path, saved):
    f = tmp_path / "read.json"
    f.write_text(json.dumps(saved))
    assert load_claude_read(f) == {2: ["AEM.TO"], 3: ["NEM"]}


def test_load_claude_read_numbers(tmp_path):
    f = tmp_path / "read.json"
    f.write_text(json.dumps({"rows": {"2": [{"number": 12.5}], "3": [{"date": "2026-11-17"}]}}))
    assert load_claude_read(f) == {2: [12.5], 3: ["2026-11-17"]}
