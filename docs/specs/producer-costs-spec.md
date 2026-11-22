# Producer costs from company AISC and energy exposure

Roadmap 4a · Status: Proposed · Depends on: market signals (the diesel signal); improves roadmap 6's pessimistic
costs

Instructions for Claude Code. Follow CLAUDE.md.

## Goal

The producer cost increase (Signals input `producer_cost_increase`, PNAV inputs H7) applies one percentage to every
producer, on a cost base inferred as revenue minus cash flow (`price_model.cost_change`: −k × max(0, revenue − cash
flow) × c). That proxy includes taxes, interest and working-capital swings, and diesel up 46% doesn't raise a
grid-powered underground mine and a haul-truck open pit by the same amount. Use reported AISC as the cost base, and
each company's energy exposure to turn the diesel move into its own cost increase.

## Scope

- **In:** a company AISC record, an AISC cost base with the proxy as fallback, a per-company cost increase from the
  diesel signal.
- **Out:** forecasting AISC; company figures for energy share that aren't disclosed (a default by mine type
  instead).

## Design

### Part 1: company AISC (the record)

- `data/research/producer_costs.csv`: `ticker`, `period` (`2026Q4`, `FY2026`), `aisc_usd_per_oz`, `unit` (oz Au,
  oz AuEq, oz AgEq, lb Cu, lb CuEq; copper producers report C1 or AISC per lb), `production` (same unit and
  period), `energy_share` (fuel and power ÷ operating costs, 0–1), `mine_type` (open pit / underground / mixed),
  `power` (grid / diesel generation / mixed), `source`.
- Fill it for the Model portfolio's producers first (read the list from the Sheet; it never goes in the repo), then
  by fund weight, from FY2026 reports (February to March 2027).
- `energy_share` only from company disclosure; otherwise blank, and the default by mine type applies
  (`[price_model] energy_share_default`, e.g. open pit 0.20, underground 0.12, mixed 0.16, with the source of the
  defaults in its comment).

### Part 2: cost base from AISC

- Cost base = AISC × production (annualised) when recorded, else today's proxy; `cost_basis` (`AISC` / `proxy`)
  beside it says which.
- `stress.py` (`cost_base_m`), `pnav.py` and the PNAV inputs Z:AC / H7 formulas use the same cost base: a new PNAV
  inputs column written by `financials`, and Z:AC changed to use it when present (a `layout.py` installer step with
  the old and new formulas, as the market-signals installer did).
- With `producer_cost_increase` = 0 every output is unchanged.

### Part 3: company cost increase from the diesel signal

- New Signals input `diesel_pass_through` (default 1.0).
- Company cost increase = `producer_cost_increase` + energy share × `diesel_12m` × pass-through. One new Sheet
  column holds it, and the cost formulas use it instead of H7 alone.
- `energy_share_of_costs` (the user's industry-wide estimate) stays as the fallback for a company with no figure and
  no mine type. New formula row `implied_cost_increase_median`: the median company increase.
- `[price_model] use_energy_pass_through = true`; false gives today's single input.

## Acceptance criteria

- [ ] A1. The cost base uses AISC × production when recorded and the proxy otherwise, with `cost_basis` saying
  which. — new test
- [ ] A2. A company's increase = general input + energy share × diesel move × pass-through, with the mine-type
  default and the industry fallback in that order. — new test
- [ ] A3. `use_energy_pass_through = false` reproduces today's outputs exactly. — new test
- [ ] A4. With `producer_cost_increase` = 0 and pass-through 0, the derived frames and the installed formulas are
  unchanged. — new test (MemorySheet)
- [ ] A5. `producer_costs.csv` is well formed: units from the list, shares 0–1, a source on every row. — new
  data-file test
- [ ] A6. The Model portfolio's producers have AISC cost bases from FY2026 reports. — `financials --dry-run`
  report
- [ ] A7. With pass-through 1.0, each producer's P/NAV moves by its own energy exposure. — `compute` output
- [ ] A8. README explains the cost scenario; CLAUDE.md adds the record file and its earnings-season step.

## Decisions

- None yet.

## Open questions

1. The default energy shares by mine type, and their source, at build time.
