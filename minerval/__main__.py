"""Command line: python -m minerval <command> [options]. Run with -h for help on any command.

Daily
  prices          update share prices, FX, metal prices and the 10-year yield on the Sheet, then signals
  signals         refresh the Signals tab (market timing signals for each tier)
After each earnings season (or when Sprott's holdings change)
  refresh         = fetch + compute
  fetch           download financials for every holding from Yahoo (cache/)
  compute         rebuild data/derived/ from the cache (no network)
  financials      write the refreshed company data to the Sheet
Once (and after changing the layout settings)
  setup-sheet     add the Signals tab and the new columns to the Sheet
Portfolio research (occasional)
  fetch-history   download monthly price histories for the backtest
  backtest        backtest the portfolio in private/portfolio.csv
  project         Monte Carlo projection of that portfolio
"""
import argparse
from pathlib import Path


def open_sheet(a):
    from .sheets import open_google
    return open_google(a.sheet_id, a.credentials, True if a.oauth else None)


def parse_today(s):
    if not s:
        return None
    out = {}
    for part in s.split(","):
        k, v = part.split("=")
        out[k.strip()] = float(v)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m minerval", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def google(p):
        p.add_argument("--sheet-id", help="Google Sheet ID (default: private/local.toml or MINERVAL_SHEET_ID)")
        p.add_argument("--credentials", help="service-account key file (or OAuth client file with --oauth)")
        p.add_argument("--oauth", action="store_true", help="sign in as yourself instead of a service account")
        p.add_argument("--dry-run", action="store_true", help="read the Sheet and report, but write nothing")

    p = sub.add_parser("prices", help="daily price update")
    google(p)
    p.add_argument("--claude", metavar="SYMBOLS_FILE",
                   help="write payloads for a Claude Sheet instead, from a saved read of Holdings!P1:P<last>")
    p.add_argument("--base", type=int, help="(Claude Sheet) revision for the first payload")
    p.add_argument("--payload-dir", help="(Claude Sheet) where to write payloads (default out/prices)")
    p.add_argument("--shares", action="store_true", help="also update share counts (after earnings season)")
    p.add_argument("--old-shares", help="(Claude Sheet) saved read of Holdings!U1:U<last>, to flag big changes")
    p.add_argument("--no-metals", action="store_true", help="leave metal prices and the 10-year yield alone")
    p.add_argument("--no-signals", action="store_true", help="don't refresh the Signals tab afterwards")
    p = sub.add_parser("signals", help="refresh the Signals tab")
    google(p)
    p = sub.add_parser("setup-sheet", help="add the Signals tab and new columns (idempotent)")
    google(p)

    sub.add_parser("fetch", help="download financials for every holding")
    for name in ("compute", "refresh"):
        p = sub.add_parser(name, help="rebuild data/derived/" + (" after fetching" if name == "refresh" else ""))
        p.add_argument("--today", help="metal prices to use as today's, e.g. gold=3859,silver=47.7,copper=5.99 "
                                       "(default: the latest COMEX close in the cache)")
        p.add_argument("--cost-increase", type=float,
                       help="producers' cost increase since their reported period, e.g. 0.1 for 10%% "
                            "(default: price_model.cost_increase in settings.toml)")
    p = sub.add_parser("financials", help="write refreshed company data to the Sheet")
    google(p)
    sub.add_parser("fetch-history", help="download monthly price histories")
    sub.add_parser("backtest", help="backtest the portfolio")
    p = sub.add_parser("project", help="Monte Carlo projection")
    p.add_argument("--kappa", type=float, help="valuation catch-up speed (default: config/projection.toml)")
    a = ap.parse_args(argv)

    lines = []
    if a.cmd == "prices":
        from . import prices
        if a.claude:
            lines = prices.run(symbols_file=a.claude, payload_dir=Path(a.payload_dir) if a.payload_dir else None,
                               base=a.base, shares=a.shares, old_shares=a.old_shares, metals=not a.no_metals)
        else:
            sheet = open_sheet(a)
            lines = prices.run(sheet=sheet, shares=a.shares, metals=not a.no_metals, dry_run=a.dry_run)
            if not a.no_signals:
                lines += prices.run_signals(sheet, dry_run=a.dry_run)
    if a.cmd == "signals":
        from . import signals
        lines = signals.run(open_sheet(a), dry_run=a.dry_run)
    if a.cmd == "setup-sheet":
        from . import layout
        lines = layout.run(open_sheet(a), dry_run=a.dry_run)
    if a.cmd in ("fetch", "refresh"):
        from . import fundamentals
        lines += fundamentals.run()
    if a.cmd in ("compute", "refresh"):
        from . import holdings, pnav, stress
        today = parse_today(a.today)
        X, F = holdings.run()
        stress.run(today, a.cost_increase)
        pnav.run(today, a.cost_increase)
        lines.append(f"Wrote data/derived/: {len(X)} holdings, {len(F)} funds.")
    if a.cmd == "financials":
        from . import financials
        lines = financials.run(open_sheet(a), dry_run=a.dry_run)
    if a.cmd == "fetch-history":
        from . import backtest
        lines = backtest.fetch_history()
    if a.cmd == "backtest":
        from . import backtest
        lines = backtest.run()
    if a.cmd == "project":
        from . import projection
        lines = projection.run(a.kappa)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
