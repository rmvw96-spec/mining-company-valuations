"""Rows and numbers out of filing text (filing-research-agent spec, Part 3: `research rows`).

Filing text comes in three layouts, and `rows` reads all three:

    pipe rows        EDGAR HTML through documents.to_text: one table row per line, cells joined by " | "
    layout rows      pdftotext -layout: the label, then the values, kept apart by runs of spaces
    one per line     the label alone on its line, each value on a line of its own (Perpetua, Skouries)

`numbers` handles the traps met in the Nov 2026 research: negatives in parentheses, EDGAR's "(3.1 | )" split
negatives, "-" and "--" as zero, unit tokens such as "US$ '000" that aren't figures, and (on request) spaces as
thousands separators. `series` takes a total and N years and refuses them when the years don't add up.
"""
import re

UNIT = re.compile(r"\(?\s*(?:US|C|A|AU|CA)?\$\s*'?0{3}s?\s*\)?|'0{3}s?"
                  r"|\(?\s*(?:US|C|A|AU|CA)?\$\s*(?:MM|M|m|bn|B|millions?|thousands?)\b\s*\)?")
TOKEN = re.compile(r"\(\s*\d[\d,]*(?:\.\d+)?\s*\)"                  # (234.4): negative
                   r"|(?<![\w.])[-−]?\d[\d,]*(?:\.\d+)?"            # 1,182.7 or -45, not a footnote digit stuck to a word
                   r"|(?<![\w.])[-–—]{1,2}(?![\w.])")               # a dash alone: zero
CURRENCY = re.compile(r"(?:US|C|A|AU|CA)?\$|%")
PERIOD = re.compile(r"\b(?:months?|years?|quarters?|weeks?|half[- ]years?|periods?)\s+ended\b"
                    r"|\b(?:three|six|nine|twelve)[- ]months?\b|\byear[- ]to[- ]date\b|\bYTD\b"
                    r"|\bFY ?\d{2,4}\b|\b[HQ][1-4] ?(?:FY)?\d{2,4}\b", re.I)
YEAR_CELL = re.compile(r"(?:FY|Q[1-4]|H[12])?\s*(?:19|20)\d\d(?:\s*\(\w+\))?", re.I)
FOOTNOTE = re.compile(r"\(\d\)")


def numbers(s: str, space_thousands: bool = False) -> list[float]:
    """The figures in a piece of text, in order."""
    s = UNIT.sub(" ", s)
    s = re.sub(r"\(\s*(\d[\d,]*(?:\.\d+)?)\s*\|\s*\)", r"(\1)", s)       # EDGAR splits "(3.1)" across two cells
    if space_thousands:                                                  # "35 645 576": one figure
        s = re.sub(r"(?<![\d.])\d{1,3}(?: \d{3})+(?![\d])", lambda m: m.group(0).replace(" ", ""), s)
    out = []
    for t in TOKEN.findall(s):
        t = t.replace(",", "").replace("−", "-").replace(" ", "")
        if t.strip("-–—") == "":
            out.append(0.0)
        elif t.startswith("("):
            out.append(-float(t.strip("()")))
        else:
            out.append(float(t))
    return out


def _bare(c: str) -> str:
    return CURRENCY.sub("", UNIT.sub("", c)).strip()


def _numeric(c: str) -> bool:
    """A cell holding only figures (and currency signs, percent, dashes, parentheses)."""
    s = _bare(c)
    return bool(s) and bool(re.fullmatch(r"[\d,.\s()\-−–—|]+", s)) and bool(re.search(r"[\d\-−–—]", s))


def _cells(line: str) -> list[str]:
    parts = line.split("|") if "|" in line else re.split(r"\s{2,}", line.strip())
    return [c.strip() for c in parts]


def _above(L: list[str], i: int, found, lookback: int):
    for j in range(i - 1, max(-1, i - lookback - 1), -1):
        if found(L[j]):
            return j
    return None


def _years_row(line: str) -> bool:
    """A line of column years: at least two cells that are a year ("2025", "FY2025", "Q3 2026")."""
    return sum(bool(YEAR_CELL.fullmatch(c)) for c in _cells(line)) >= 2


def rows(text: str, label: str, lookback: int = 300, max_cells: int = 80,
         space_thousands: bool = False) -> list[dict]:
    """Each row whose label matches the regex: its label, its figures, and the nearest period header ("Nine Months
    Ended", "Year ended", "FY2025") and line of column years above it. Text is split on "\\n" only: pdftotext's form
    feeds would shift line numbers away from grep's."""
    L = [x.replace("\u200b", "").replace("\xa0", " ") for x in text.split("\n")]   # EDGAR's blank cells
    rx = re.compile(label, re.I)
    out = []
    for i, x in enumerate(L):
        if len(x) > 5000 or not rx.search(x):
            continue
        cells = _cells(x)
        k = 0
        while k < len(cells) and not _numeric(cells[k]) and _bare(cells[k]):
            k += 1
        lab = " ".join(c for c in cells[:k] if c)
        while k < len(cells) and FOOTNOTE.fullmatch(cells[k]):          # "(2)" in its own cell is a footnote
            lab += " " + cells[k]
            k += 1
        if not lab or len(lab) > 120:                                    # prose that mentions the label
            continue
        vals = numbers(" | ".join(cells[k:]), space_thousands)
        if not vals:                                                     # one value per line below the label
            j = i + 1
            while j < len(L) and len(vals) < max_cells:
                s = L[j].strip()
                if s and not _numeric(s) and _bare(s):
                    break
                vals += numbers(s, space_thousands)
                j += 1
        p, c = _above(L, i, PERIOD.search, lookback), _above(L, i, _years_row, lookback)
        out.append({"line": i, "label": lab, "values": vals,
                    "period": L[p].strip()[:160] if p is not None else "", "period_line": p,
                    "columns": L[c].strip()[:160] if c is not None else "", "text": x.strip()[:200]})
    return out


def _decimals(x: float) -> int:
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return len(s.split(".")[1]) if "." in s else 0


def series(values, n: int, total: str | None = "first", tol: float | None = None) -> list[float]:
    """N years from a row that also carries its total (first or last). Refused when the count is wrong or the years
    miss the total by more than rounding: half the last decimal place for each figure, unless `tol` is given."""
    v = list(values)
    if total is None:
        if len(v) != n:
            raise ValueError(f"expected {n} years, got {len(v)} figures")
        return v
    if len(v) != n + 1:
        raise ValueError(f"expected a total and {n} years, got {len(v)} figures")
    t, years = (v[0], v[1:]) if total == "first" else (v[-1], v[:-1])
    if tol is None:
        tol = (n + 1) * 0.5 * 10 ** -max(_decimals(x) for x in v)
    if abs(sum(years) - t) > tol + 1e-9:
        raise ValueError(f"the {n} years sum to {sum(years):.6g}, not the total {t:.6g} (rounding allows {tol:.3g})")
    return years
