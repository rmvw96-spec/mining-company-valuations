# Royalties against their own history

Instructions for Claude Code. Roadmap item 4c. Follow CLAUDE.md.

## Goal

The royalty buy zone compares each company's independent P/NAV with fixed framework bands (buy 1.1–1.4×,
normal 1.5–2.2×, rich above 2.2×), and the Signals tab uses the peer median. Some companies always trade
above the bands (Franco-Nevada is "Rich" almost every day), so the band says little about whether *that*
company is cheap now. Add a second view: each company against its own past valuation.

## Data: what history exists

- **Our own P/NAV history** starts with [signal-history-spec.md](signal-history-spec.md) (Company history tab,
  metric `independent_pnav`). This is the right measure but needs about a year before percentiles mean much.
- **Interim measure from day one: price to operating cash flow.** Yahoo's fundamentals series gives quarterly
  operating cash flow for about five years; with monthly prices that gives a monthly trailing P/OCF series per
  company. Royalty companies have no operating costs to speak of, so P/OCF tracks P/NAV reasonably well, but it
  isn't the same thing: label it as P/OCF everywhere.
- Analyst consensus P/NAV snapshots (`analyst_consensus_pnav_dec2025` in `pnav_companies.csv`) are single points:
  keep them as reference, not as history.

## Design

- `minerval/royalty_history.py`:
  - `pocf_history(ticker) -> Series` from cached prices and fundamentals (extend `fetch` to keep quarterly OCF
    history for royalty rows; check what `cache/fundamentals.json` already holds before adding requests).
  - `own_percentile(series, today_value) -> float`: where today sits in the company's own history (0–100).
- New PNAV inputs columns (spill formulas fed by a small Python-written helper range, or Python-written values;
  pick the simpler for the Sheet and explain in the PR):
  - `P/OCF percentile, own 5 years`;
  - `P/NAV percentile, own history` (blank until 250 recorded days exist);
  - an "own-history band": "Cheap for itself" (≤ 25th percentile), "Normal for itself", "Expensive for itself"
    (≥ 75th), thresholds in `[signals.thresholds]`-style settings.
- Model portfolio W for royalty rows shows both: the framework band and the own-history band.
- Signals tab: `royalty_own_pctile_median` (median of the companies' own percentiles), next to the existing
  median P/NAV row.

## Tests (offline)

- P/OCF history from synthetic prices and quarterly cash flows (trailing four quarters; quarters with negative
  or missing OCF left out).
- Percentile edges; the 250-day minimum for P/NAV history.
- Band texts and the matching Sheet formula, if formula-based.

## Docs

README (two views of royalty value and what each measures), CLAUDE.md (new columns).

## Done when

Each royalty company on PNAV inputs shows where its P/OCF sits in its own 5-year range, and the P/NAV
percentile fills in by itself once enough history is recorded.
