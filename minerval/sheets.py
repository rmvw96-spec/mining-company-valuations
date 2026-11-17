"""Reading and writing the spreadsheet.

Two back ends share one interface:
  GoogleSheet     reads and writes a Google Sheet through the Sheets API (gspread).
  ClaudePayloads  writes "applyEdits" payload files for a Claude Sheet; Claude sends them.
                  It can't read the sheet, so the caller passes in what was read separately.

A write is a list of (tab, top-left cell, rows) blocks. CLEAR empties a cell.
"""
import json
import re
from pathlib import Path

CLEAR = "__CLEAR__"


def _is_clear(v) -> bool:
    return isinstance(v, str) and v == CLEAR


def col_to_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch.upper()) - 64
    return n


def num_to_col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_cell(cell: str):
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", cell)
    if not m:
        raise ValueError(f"not a cell reference: {cell}")
    return m.group(1).upper(), int(m.group(2))


def a1(tab: str, cell: str, nrows: int = 1, ncols: int = 1) -> str:
    """'Tab'!C15:E17 style range for a block starting at cell."""
    col, row = split_cell(cell)
    end = f"{num_to_col(col_to_num(col) + ncols - 1)}{row + nrows - 1}"
    rng = cell if (nrows, ncols) == (1, 1) else f"{cell}:{end}"
    return f"'{tab}'!{rng}"


def runs(rows: list[int]) -> list[list[int]]:
    """Split row numbers into runs of consecutive rows."""
    out, cur = [], []
    for r in sorted(rows):
        if cur and r != cur[-1] + 1:
            out.append(cur)
            cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    return out


def blocks_by_row(tab: str, col: str, values: dict[int, list]) -> list:
    """{row: [values across columns from col]} -> write blocks, one per run of consecutive rows."""
    return [(tab, f"{col}{run[0]}", [values[r] for r in run]) for run in runs(list(values))]


def count_cells(blocks) -> int:
    return sum(len(r) for _, _, rows in blocks for r in rows)


class GoogleSheet:
    """A Google Sheet opened with a service account (default) or your own Google sign-in (oauth=True)."""

    def __init__(self, sheet_id: str, credentials: str | None = None, oauth: bool = False):
        import gspread
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        if oauth:
            gc = gspread.oauth(credentials_filename=credentials, scopes=scopes) if credentials else gspread.oauth(scopes)
        else:
            gc = gspread.service_account(filename=credentials, scopes=scopes) if credentials else gspread.service_account(scopes)
        self.book = gc.open_by_key(sheet_id)

    def read(self, tab: str, rng: str, formulas: bool = False) -> list[list]:
        """Values of a range as a list of rows (ragged: Google drops trailing empty cells)."""
        r = self.book.values_get(f"'{tab}'!{rng}", params={
            "valueRenderOption": "FORMULA" if formulas else "UNFORMATTED_VALUE",
            "dateTimeRenderOption": "FORMATTED_STRING"})
        return r.get("values", [])

    def write(self, blocks) -> int:
        data = []
        for tab, cell, rows in blocks:
            vals = [["" if _is_clear(v) else v for v in row] for row in rows]
            data.append({"range": a1(tab, cell, len(rows), max(len(r) for r in rows)), "values": vals})
        if data:
            # USER_ENTERED so "2026-11-17" becomes a date, as if typed. None cells are skipped by the API.
            self.book.values_batch_update({"valueInputOption": "USER_ENTERED", "data": data})
        return count_cells(blocks)


def open_google(sheet_id: str | None = None, credentials: str | None = None, oauth: bool | None = None) -> GoogleSheet:
    """The Google Sheet named in private/local.toml (or the environment), unless arguments say otherwise."""
    from .config import ROOT, local
    sid = sheet_id or local().get("sheet_id")
    if not sid:
        raise SystemExit("No Google Sheet ID: pass --sheet-id, set MINERVAL_SHEET_ID, "
                         "or add sheet_id to private/local.toml.")
    cred = credentials or local().get("credentials")
    if cred and not Path(cred).exists() and (ROOT / cred).exists():
        cred = str(ROOT / cred)                     # paths in private/local.toml are relative to the repo
    return GoogleSheet(sid, credentials=cred, oauth=oauth if oauth is not None else local().get("auth") == "oauth")


class ClaudePayloads:
    """Writes applyEdits payloads for a Claude Sheet (see CLAUDE.md for sending them)."""

    MAX_CELLS, MAX_EDITS = 900, 60

    def __init__(self, out_dir: Path, prefix: str, base: int | None = None):
        self.out, self.prefix, self.base = Path(out_dir), prefix, base
        self.files: list[Path] = []

    def read(self, *a, **k):
        raise RuntimeError("A Claude Sheet can't be read from here: read it with the Sheet tool and pass the file in.")

    def write(self, blocks) -> int:
        edits = []
        for tab, cell, rows in blocks:
            # A Claude Sheet has no "leave alone" value: null clears the cell, so callers never send None.
            edits.append({"kind": "writeCells", "sheet": tab, "topLeft": cell,
                          "rows": [[None if _is_clear(v) else v for v in row] for row in rows]})
        packs, cur, n = [], [], 0
        for e in edits:
            c = sum(len(r) for r in e["rows"])
            if cur and (n + c > self.MAX_CELLS or len(cur) >= self.MAX_EDITS):
                packs.append(cur)
                cur, n = [], 0
            cur.append(e)
            n += c
        if cur:
            packs.append(cur)
        self.out.mkdir(parents=True, exist_ok=True)
        for old in self.out.glob(f"payload_{self.prefix}_*.json"):
            old.unlink()
        for i, p in enumerate(packs, 1):
            base = self.base if (i == 1 and self.base is not None) else "SET_TO_PREVIOUS_RESULT_REVISION"
            f = self.out / f"payload_{self.prefix}_{i}.json"
            f.write_text(json.dumps({"kind": "applyEdits", "base": base, "edits": p}))
            self.files.append(f)
        return count_cells(blocks)


class MemorySheet:
    """An in-memory sheet for dry runs and tests: {tab: {"A1": value}}."""

    def __init__(self, cells: dict | None = None):
        self.cells = cells or {}
        self.blocks = []

    def read(self, tab: str, rng: str, formulas: bool = False) -> list[list]:
        a, b = rng.split(":") if ":" in rng else (rng, rng)
        c1, r1 = split_cell(a)
        c2, r2 = split_cell(b)
        t = self.cells.get(tab, {})
        out = []
        for r in range(r1, r2 + 1):
            out.append([t.get(f"{num_to_col(c)}{r}", "") for c in range(col_to_num(c1), col_to_num(c2) + 1)])
        while out and all(v in ("", None) for v in out[-1]):
            out.pop()
        return out

    def write(self, blocks) -> int:
        self.blocks += blocks
        for tab, cell, rows in blocks:
            c0, r0 = split_cell(cell)
            t = self.cells.setdefault(tab, {})
            for i, row in enumerate(rows):
                for j, v in enumerate(row):
                    if v is None:
                        continue
                    t[f"{num_to_col(col_to_num(c0) + j)}{r0 + i}"] = "" if _is_clear(v) else v
        return count_cells(blocks)


def column(rows: list[list], first_row: int, idx: int = 0) -> dict[int, object]:
    """{sheet row: value} for column idx of a read that started at first_row."""
    out = {}
    for i, r in enumerate(rows):
        v = r[idx] if idx < len(r) else ""
        out[first_row + i] = v
    return out


def load_claude_read(path) -> dict[int, list]:
    """{row: [cells]} from a Claude Sheet read saved to a file.

    Accepts the saved tool-result file (a JSON list of {type, text}), the readCells "value"
    object, or a plain {"2": "AEM.TO", ...} mapping. Cells holding {"number"}, {"formula", "value"}
    or {"spilledFrom", "value"} are reduced to their value.
    """
    d = json.loads(Path(path).read_text())
    if isinstance(d, list):
        for part in d:
            if '"rows"' in part.get("text", ""):
                d = json.loads(part["text"])
                break
    if isinstance(d, dict) and "value" in d and isinstance(d["value"], dict):
        d = d["value"]
    if isinstance(d, dict) and "rows" in d:
        d = d["rows"]
    out = {}
    for k, v in d.items():
        cells = v if isinstance(v, list) else [v]
        clean = []
        for c in cells:
            while isinstance(c, dict):
                c = c.get("number", c.get("value", c.get("date")))
            clean.append(c)
        out[int(k)] = clean
    return out
