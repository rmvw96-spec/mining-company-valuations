# Alerts when a signal or Model portfolio status changes

Instructions for Claude Code. Roadmap item 1b. Follow CLAUDE.md.

## Goal

The scheduled run reports "Changed since the last run" in `out/signals/report.txt` and the GitHub step summary,
but nobody reads those daily. Send a notification when something changes:

1. **Market signals** (Signals tab status, column I) — market data only, nothing personal.
2. **Model portfolio** rows whose Status (T) changes, e.g. to "Review: above level".

## Privacy constraint (decides the channels)

The repo is public, so its issues are public. Signal statuses are market data and fine to publish. Model
portfolio statuses name the holdings the user is tracking, which is closer to personal: **they never go into a
GitHub issue, log or step summary.** They go only by private email, and only when the user has set it up.

## Design

### 1. Market signals → one GitHub issue per change day

- In `update-prices.yml`, after the update step: if `out/signals/changes.json` is non-empty, open an issue with
  `gh issue create` using the workflow's `GITHUB_TOKEN` (add `permissions: issues: write, contents: read`).
- Title: `Signals changed: 2026-11-18 (3)`. Body: one line per change (`label: old → new`, value and as-of date),
  then the tier it applies to. Label `signals` (create it if missing).
- `signals.run()` writes `out/signals/changes.json` (list of `{key, label, tier, old, new, value, asof}`) next to
  report.txt. The workflow reads that file; the issue text is built in Python (`minerval/alerts.py`), not in YAML.
- Leave out "Info" rows and the AISC margin (as the report already does).
- GitHub emails the repo owner on new issues by default, so this needs no secrets.

### 2. Model portfolio → private email (optional)

- `minerval/alerts.py` reads Model portfolio B and T (rows from `[sheet]` portfolio settings) before and after the
  price write. Before: read at the start of `prices.run()`. After: read after the signals step.
- If both `ALERT_SMTP_URL` (e.g. `smtps://user:app-password@smtp.gmail.com:465`) and `ALERT_EMAIL_TO` are set,
  send one email listing the changed rows. Otherwise do nothing and **don't** print the rows to the log.
- The workflow passes the two secrets when present. Document how to make a Gmail app password in README;
  the user adds the secrets.

### 3. Locally

`uv run python -m minerval prices` prints both sets of changes in the terminal report as today. No issue, no email
unless `--notify` is passed (so local test runs don't spam).

## Tests (offline)

- `changes.json` contents for a run where one status flips; empty list when nothing changes.
- Issue body builder: stable text, no Model portfolio content.
- Email: with the env vars unset nothing is sent and nothing is logged; with them set, `smtplib` is called once
  (monkeypatched) with the changed rows.
- The workflow YAML parses and requests only `issues: write` and `contents: read`.

## Docs

- README: alerts, the optional email secrets, and the privacy rule.
- CLAUDE.md: Model portfolio content never goes into issues, logs or step summaries.

## Open question for the user

Is a public GitHub issue for market-signal changes acceptable, or should those go by email too? The default
above assumes yes (it's market data).
