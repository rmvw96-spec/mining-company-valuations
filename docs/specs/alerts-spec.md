# Alerts when a signal or Model portfolio status changes

Roadmap 1b · Status: Built Nov 18, 2026 · Depends on: 1a (Signal history)

Instructions for Claude Code. Follow CLAUDE.md.

## Goal

The scheduled run lists "Changed since the last run" in `out/signals/report.txt` and the step summary, but nobody
reads those daily. Notify when a market signal's status (Signals I) or a Model portfolio row's status (T) changes.

## Scope

- **In:** a public GitHub issue for market-signal changes; a private email for Model portfolio changes.
- **Out:** Model portfolio content in any issue, log or step summary (the repo is public).

## Design

- **Market signals: one GitHub issue per change day.**
  - A change counts once the new status has held **3 recorded trading days**, worked out from Signal history
    (statuses recomputed from its values with today's thresholds), so no state is kept on GitHub. A replay of the
    year before gave 107 alert days for every raw change and 47 with the hold.
  - `signals.run()` writes `out/signals/changes.json` (confirmed changes: `key`, `label`, `tier`, `old`, `new`,
    `value`, `asof`); the report still lists every change. "Info" rows and the AISC margin are left out.
  - `update-prices.yml` opens the issue with `gh issue create` and the workflow's token (`permissions: issues:
    write, contents: read`), label `signals`, title `Signals changed: <date> (<n>)`, body built in Python
    (`minerval/alerts.py`). A day that already has a `signals` issue is skipped (reruns). GitHub emails the owner.
- **Model portfolio: private email.**
  - `alerts.notify_portfolio` compares Model portfolio B and T before and after the price write, and emails the
    changed rows when `ALERT_SMTP_URL` and `ALERT_EMAIL_TO` are set. No hold (there's no private place to keep past
    statuses). The log says only how many changed; a failure never prints names.
  - The workflow passes the two secrets when present; README explains a Gmail app password.
- **Locally:** `prices` prints both sets of changes in its report; an issue or email only with `prices --notify`.
  `test-email` sends a fixed message to check the secrets.

## Acceptance criteria

- [x] A1. Statuses come from Signal history, skipping Info and context signals. —
  `tests/test_alerts.py::test_statuses_from_history_skip_info_and_context_signals`
- [x] A2. A change is confirmed only after 3 trading days, and only when today's row exists. —
  `tests/test_alerts.py::test_confirmed_changes_need_three_days`,
  `tests/test_alerts.py::test_signal_changes_reads_signal_history_and_needs_todays_row`
- [x] A3. The issue text is stable and holds market data only. —
  `tests/test_alerts.py::test_issue_text_is_stable_and_market_data_only`, `tests/test_alerts.py::test_write_issue`
- [x] A4. The portfolio email is sent only when set up, never logged, and a failure doesn't leak names. —
  `tests/test_alerts.py::test_portfolio_email_only_when_set_up_and_never_logged`,
  `tests/test_alerts.py::test_portfolio_alert_failure_doesnt_leak_names`
- [x] A5. The workflow asks only for `issues: write` and `contents: read`. —
  `tests/test_alerts.py::test_workflow_permissions_and_steps`
- [x] A6. `test-email` sends a message with no portfolio content. — `tests/test_alerts.py::test_test_email`
- [x] A7. README covers alerts, the email secrets and the privacy rule; CLAUDE.md the privacy rule.

## Decisions

- Public issues are fine for market signals; Model portfolio changes go by private email only (the user,
  2026-11-18).
- Alert a signal change once the new status has held 3 recorded trading days (the user, 2026-11-18).
