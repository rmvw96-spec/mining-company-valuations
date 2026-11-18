# Producer costs from company AISC and energy exposure

Instructions for Claude Code. Roadmap item 4a. Follow CLAUDE.md.

## Goal

The producer cost increase (Signals input `producer_cost_increase`, PNAV inputs H7) applies one percentage to
every producer's costs, and a company's costs are inferred as revenue minus cash flow
(`price_model.cost_change`: −k × max(0, revenue − cash flow) × c). Two problems:

1. **The cost base is a proxy.** Revenue minus cash flow includes taxes, interest and working-capital swings,
   so it overstates costs for some companies and understates them for others.
2. **Every company gets the same increase.** Diesel up 46% doesn't raise an underground mine on grid power and an
   open pit running a haul-truck fleet by the same amount.

Replace the proxy with reported AISC where available, and let each company's energy exposure turn the diesel
move into its own cost increase, so the diesel signal feeds the cost scenario directly.

## Part 1: company AISC (the record)

- New file `data/research/producer_costs.csv`: `ticker`, `period` (e.g. `2026Q4` or `FY2026`), `aisc_usd_per_oz`,
  `unit` (oz Au, oz AuEq, oz AgEq, lb Cu, lb CuEq; copper producers report C1 or AISC per lb), `production`
  (in the unit, same period), `energy_share` (share of operating costs from fuel and power, 0–1), `mine_type`
  (open pit, underground, mixed), `power` (grid, diesel generation, mixed), `source`.
- Fill it for the producers on the Model portfolio first (read the list from the Sheet; don't write it into the
  repo, which is public), then by fund weight. Use Q4 2026 / FY2026 reports (February to March 2027).
- `energy_share`: from company disclosure where given (many report fuel and power as a share of site costs).
  Otherwise leave blank and use the default by mine type (`[price_model] energy_share_default`, e.g. open pit
  0.20, underground 0.12, mixed 0.16, with a comment naming the source of the defaults). Never invent a
  company figure.

## Part 2: cost base from AISC

- Cost base = AISC × production (annualised), when the row is filled in. Falls back to today's proxy otherwise,
  and the row says which basis it used (new column next to the cost base, e.g. `cost_basis` = `AISC` or `proxy`).
- `stress.py` (cost_base_m), `pnav.py` and the PNAV inputs Z:AC / H7 formulas use the same cost base. On the
  Sheet, add the cost base as an input column on PNAV inputs (written by `financials` from the CSV), and change
  the Z:AC formula to use it when present. That's an installer step in `layout.py` with the old and new formulas,
  as PR #5 did.
- With `producer_cost_increase` = 0 every output must be unchanged (the post-install check already verifies this).

## Part 3: company cost increase from the diesel signal

- New Signals input `diesel_pass_through` (default 1.0): how much of the diesel move to apply.
- Company cost increase = `producer_cost_increase` (the user's general input) + energy share ×
  `diesel_12m` × pass-through, where `diesel_12m` is the Signals value. One new Sheet column holds each company's
  increase; the cost formulas use it instead of H7 alone.
- The Signals inputs already have `energy_share_of_costs` (one industry-wide estimate, the user's to fill in) and
  `implied_cost_increase` (a formula: that share × the diesel move). Keep `energy_share_of_costs` as the fallback
  for companies with no figure and no mine type, and add a formula row `implied_cost_increase_median`: the median
  company increase, so the Signals tab shows what the diesel move means across the producers.
- Keep it switchable: `[price_model] use_energy_pass_through = true`; false gives today's single input.

## Tests (offline)

- Cost base from AISC vs proxy, and the fallback label.
- Company increase arithmetic, the default energy share by mine type, the switch.
- The zero-increase invariant on the derived frames and on the installed formulas (MemorySheet check).
- Data-file validation for `producer_costs.csv`.

## Docs

README (how the cost scenario works now), CLAUDE.md (new record file, earnings-season step to update it).

## Done when

The Model portfolio producers have AISC-based cost bases from FY2026 reports, and setting diesel pass-through
to 1.0 moves each producer's P/NAV by its own energy exposure.
