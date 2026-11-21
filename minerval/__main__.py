"""Command line: python -m minerval <command> [options]. Run with -h for help on any command.

Daily
  prices          update share prices, FX, metal prices and the 10-year yield on the Sheet, then signals
  signals         refresh the Signals tab (market timing signals for each tier); records Signal history
  history         --backfill DATE: fill Signal history for past dates from the cached series
  alerts          issue text for signal changes that have held 3 trading days (the GitHub workflow posts it)
  test-email      send a test message through ALERT_SMTP_URL to ALERT_EMAIL_TO
After each earnings season (or when Sprott's holdings change)
  refresh         = fetch + compute
  fetch           download financials for every holding from Yahoo (cache/)
  compute         rebuild data/derived/ from the cache (no network)
  financials      write the refreshed company data to the Sheet (and the jurisdiction add-ons from the country table)
  snapshots       rewrite the fund tables on Summary, Metal prices reference and Stress test & downside
  jurisdiction    old vs new jurisdiction add-on for every company (out/jurisdiction/)
After the royalty companies' annual filings (February and March)
  royalty-ocf     rewrite data/research/royalty_ocf.csv (annual operating cash flow) from SEC EDGAR
After each quarter's filings (roadmap 6 research inputs)
  research        sustaining [--write]: trailing-12-month sustaining spending from data/research/capex_periods.csv
                  fetch [--ticker T]: download the documents in sources.csv to cache/research/ as text
                  find T TERM...: search a company's downloaded documents
Model portfolio (before buying, or after a refresh)
  screen          propose the Model portfolio's holdings and weights from the framework (--write to apply)
  portfolio-file  write private/portfolio.csv from the Model portfolio tab, for backtest and project
Once (and after changing the layout settings)
  setup-sheet     add the Signals tab and the new columns to the Sheet
Portfolio research (occasional)
  fetch-history   download monthly price histories for the backtest
  backtest        backtest the portfolio in private/portfolio.csv
  project         Monte Carlo projection of that portfolio
Signal research (occasional)
  backtest-signals  how each signal's statuses did against the outcomes they are meant to predict
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
    p.add_argument("--notify", action="store_true",
                   help="email Model portfolio status changes (needs ALERT_SMTP_URL and ALERT_EMAIL_TO)")
    p = sub.add_parser("signals", help="refresh the Signals tab")
    google(p)
    p = sub.add_parser("history", help="backfill the Signal history tab for past dates")
    google(p)
    p.add_argument("--backfill", metavar="DATE", required=True, help="first date, e.g. 2023-01-01")
    p.add_argument("--end", metavar="DATE", help="last date (default: today)")
    sub.add_parser("alerts", help="write the GitHub issue text for confirmed signal changes (out/alerts/)")
    sub.add_parser("test-email", help="send a test email to check ALERT_SMTP_URL and ALERT_EMAIL_TO")
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
    p = sub.add_parser("snapshots", help="rewrite the fund tables from data/derived/")
    google(p)
    p = sub.add_parser("jurisdiction", help="compare the hand-set and country-table jurisdiction add-ons")
    p.add_argument("--build", metavar="SCORES_CSV",
                   help="first rewrite the table's scored rows from a private Fraser scores file")
    p.add_argument("--source", help="(with --build) the survey edition, for the source column")
    p.add_argument("--as-of", help="(with --build) its publication month, e.g. 2026-02")
    p = sub.add_parser("screen", help="propose the Model portfolio from a screen (report only unless --write)")
    google(p)
    p.add_argument("--write", action="store_true", help="write the proposal to Model portfolio A-F, S, U-V")
    p.add_argument("--all-markets", action="store_true",
                   help="include companies with no US or Canadian listing (about $50 a trade in an IRA)")
    p.add_argument("--email", action="store_true", help="(with --write) email the changes privately")
    p.add_argument("--rule-review-levels", action="store_true",
                   help="set every screened row's review level from the rule, replacing levels typed by hand")
    p.add_argument("--init", action="store_true", help="write private/screen.toml from the tab's current split")
    p = sub.add_parser("portfolio-file", help="write private/portfolio.csv from the Model portfolio tab")
    google(p)
    sub.add_parser("royalty-ocf", help="annual operating cash flow of the royalty companies from SEC EDGAR")
    p = sub.add_parser("research", help="research inputs: sustaining spending, filing downloads and search")
    p.add_argument("what", choices=["sustaining", "fetch", "find"])
    p.add_argument("args", nargs="*", help="find: TICKER TERM...")
    p.add_argument("--ticker")
    p.add_argument("--write", action="store_true")
    p.add_argument("--refresh", action="store_true", help="fetch: download again")
    p.add_argument("--url", help="fetch or find: one document instead of the ticker's list")
    sub.add_parser("fetch-history", help="download monthly price histories")
    sub.add_parser("backtest", help="backtest the portfolio")
    p = sub.add_parser("backtest-signals", help="backtest the market signals (out/backtest-signals/)")
    p.add_argument("--refresh", action="store_true", help="download the full histories again")
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
            before = None
            if a.notify and not a.dry_run:
                from . import alerts
                try:
                    before = alerts.portfolio_statuses(sheet)
                except Exception as e:
                    lines.append(f"Model portfolio alert not set up: {type(e).__name__}.")
            lines += prices.run(sheet=sheet, shares=a.shares, metals=not a.no_metals, dry_run=a.dry_run)
            if not a.no_signals:
                lines += prices.run_signals(sheet, dry_run=a.dry_run)
            if before is not None:
                from .history import today_ny
                lines += alerts.notify_portfolio(sheet, before, today_ny().isoformat())
    if a.cmd == "signals":
        from . import signals
        lines = signals.run(open_sheet(a), dry_run=a.dry_run)
    if a.cmd == "history":
        from . import history
        lines = history.backfill(open_sheet(a), a.backfill, a.end, dry_run=a.dry_run)
    if a.cmd == "alerts":
        from . import alerts
        lines = alerts.write_issue()
    if a.cmd == "test-email":
        from . import alerts
        sent, line = alerts.test_email()
        print(line)
        raise SystemExit(0 if sent else 1)
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
    if a.cmd == "snapshots":
        from . import snapshots
        lines = snapshots.run(open_sheet(a), dry_run=a.dry_run)
    if a.cmd == "jurisdiction":
        from . import jurisdiction
        lines = jurisdiction.run(scores=a.build and Path(a.build), source=a.source, as_of=a.as_of)
    if a.cmd == "screen":
        from . import screen
        sheet = open_sheet(a)
        lines = (screen.init_sizes(sheet) if a.init else
                 screen.run(sheet, write=a.write and not a.dry_run, all_markets=a.all_markets, email=a.email,
                            rule_levels=a.rule_review_levels))
    if a.cmd == "portfolio-file":
        from . import screen
        lines = screen.write_portfolio_file(open_sheet(a))
    if a.cmd == "research":
        from . import sustaining as SU
        if a.what == "sustaining":
            lines = SU.run_sustaining(write=a.write)
        elif a.what == "fetch":
            lines = SU.fetch(a.ticker, refresh=a.refresh, url=a.url)
        else:
            if len(a.args) < 2:
                raise SystemExit("research find TICKER TERM [TERM...]")
            lines = SU.find(a.args[0], a.args[1:], url=a.url)
    if a.cmd == "royalty-ocf":
        from . import royalty_history
        lines = royalty_history.fetch_record()
    if a.cmd == "fetch-history":
        from . import backtest
        lines = backtest.fetch_history()
    if a.cmd == "backtest":
        from . import backtest
        lines = backtest.run()
    if a.cmd == "backtest-signals":
        from . import signal_backtest
        lines = signal_backtest.run(refresh=a.refresh)
    if a.cmd == "project":
        from . import projection
        lines = projection.run(a.kappa)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
