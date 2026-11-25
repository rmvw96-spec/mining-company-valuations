"""Alerts: confirmed signal changes, the issue text, and the private Model portfolio email. Offline."""
import json
from datetime import date

import pytest

from minerval import alerts
from minerval.config import ROOT, settings
from minerval.sheets import MemorySheet
from minerval.signals import BY_KEY

TH = {k: list(v) for k, v in settings()["signals"]["thresholds"].items()}
RATIO = BY_KEY["gold_silver_ratio"].texts      # >= 80 silver cheap, <= 50 gold cheap, else neutral


def grid(values, key="gold_silver_ratio", start=1):
    """A Signal history grid: one row per value, dates Nov 1, 2, ..."""
    rows = [["Date", "Source", key, "usd_12m"]]
    for i, v in enumerate(values):
        rows.append([f"2026-11-{start + i:02d}", "live", v, 0.05])
    return rows


def test_statuses_from_history_skip_info_and_context_signals():
    days = alerts.statuses_by_day(grid([85, 70]), TH)
    assert days == [("2026-11-01", {"gold_silver_ratio": RATIO[0]}), ("2026-11-02", {"gold_silver_ratio": RATIO[2]})]
    assert not alerts.alertable("usd_12m") and not alerts.alertable("aisc_margin")
    assert not alerts.alertable("gold_12m") and alerts.alertable("breadth_sgdj")


@pytest.mark.parametrize("values,want", [
    ([70, 70, 70, 85, 85, 85], [(RATIO[2], RATIO[0])]),     # held 3 days: confirmed on the last day
    ([70, 70, 70, 85, 85], []),                              # only 2 days so far
    ([70, 70, 70, 85, 85, 85, 85], []),                      # confirmed yesterday: not again today
    ([70, 70, 70, 85, 70, 70, 70], []),                      # a one-day blip never confirmed
    ([85, 85, 85], []),                                      # the first confirmed status isn't a change
    ([70, 70, 70, 85, "", 85, 85], [(RATIO[2], RATIO[0])]),  # a day without a value is skipped
])
def test_confirmed_changes_need_three_days(values, want):
    days = alerts.statuses_by_day(grid(values), TH)
    got = alerts.confirmed_changes(days, 3)
    assert [(c["old"], c["new"]) for c in got] == want
    assert all(c["date"] == days[-1][0] for c in got)


def test_signal_changes_reads_signal_history_and_needs_todays_row():
    sh = MemorySheet({"Signal history": {f"{'ABCD'[j]}{i + 1}": v for i, row in enumerate(grid([70, 70, 70, 85, 85, 85]))
                                         for j, v in enumerate(row)}})
    rows = [{"key": "gold_silver_ratio", "value": 85.0, "asof": "2026-11-06"}]
    got = alerts.signal_changes(sh, rows, {}, date(2026, 11, 6))
    assert got and got[0]["label"] == BY_KEY["gold_silver_ratio"].label and got[0]["value"] == 85.0
    assert got[0]["tier"] == "Physical metal"
    assert alerts.signal_changes(sh, rows, {}, date(2026, 11, 7)) == []          # today's row isn't there
    assert alerts.signal_changes(sh, rows, {"gold_silver_ratio": [90, 50]}, date(2026, 11, 6)) == []  # the Sheet's G:H


def test_issue_text_is_stable_and_market_data_only():
    ch = [{"key": "gold_silver_ratio", "old": RATIO[2], "new": RATIO[0], "value": 83.1, "asof": "2026-11-18",
           "label": BY_KEY["gold_silver_ratio"].label, "tier": "Physical metal", "note": "A high ratio favours silver."}]
    title, body = alerts.issue(ch, "2026-11-18")
    assert title == "Signals changed: 2026-11-18 (1)"
    assert "### Physical metal" in body
    assert f"- **Gold/silver ratio**: {RATIO[2]} → **{RATIO[0]}** (value 83.10, as of 2026-11-18)" in body
    assert "held for 3 trading days" in body and "Model portfolio" not in body
    assert alerts.issue([], "2026-11-18") is None


def test_write_issue(tmp_path):
    f = tmp_path / "changes.json"
    f.write_text(json.dumps({"date": "2026-11-18", "changes": []}))
    out = tmp_path / "alerts"
    assert "no issue" in alerts.write_issue(f, out)[0]
    assert not (out / "title.txt").exists()
    f.write_text(json.dumps({"date": "2026-11-18", "changes": [
        {"key": "uptrend_gold", "old": "Below its 200-day average", "new": "Above its 200-day average",
         "value": 0.01, "asof": "2026-11-18", "label": "Gold", "tier": "Juniors", "note": ""}]}))
    alerts.write_issue(f, out)
    assert (out / "title.txt").read_text() == "Signals changed: 2026-11-18 (1)"
    assert (out / "body.md").read_text().startswith("Signal statuses that changed")


def portfolio_sheet(statuses):
    C, cells = settings()["sheet"]["portfolio_cols"], {}
    for i, (name, st) in enumerate(statuses.items(), start=6):
        cells[f"{C['holding']}{i}"], cells[f"{C['status']}{i}"] = name, st
    return MemorySheet({"Model portfolio": cells})


def test_portfolio_email_only_when_set_up_and_never_logged(monkeypatch):
    before = {"Alpha Gold": "Hold", "Beta Silver": "Hold"}
    sh = portfolio_sheet({"Alpha Gold": "Above fair value: review", "Beta Silver": "Hold"})
    assert alerts.portfolio_statuses(sh) == {"Alpha Gold": "Above fair value: review", "Beta Silver": "Hold"}
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, context=None):
            sent.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, password):
            sent.append(("login", user, password))

        def send_message(self, msg):
            sent.append(("msg", msg["To"], msg["Subject"], msg.get_content()))
    monkeypatch.setattr(alerts.smtplib, "SMTP_SSL", FakeSMTP)

    lines = alerts.notify_portfolio(sh, before, "2026-11-18", env={})
    assert sent == [] and "not set up" in lines[0]
    assert all("Alpha" not in line and "Review" not in line for line in lines)

    env = {"ALERT_SMTP_URL": "smtps://me%40example.com:app%20pw@smtp.example.com:465", "ALERT_EMAIL_TO": "me@example.com"}
    lines = alerts.notify_portfolio(sh, before, "2026-11-18", env=env)
    assert lines == ["Model portfolio: 1 status change(s) emailed."]
    assert sent[0] == ("connect", "smtp.example.com", 465)
    assert sent[1] == ("login", "me@example.com", "app pw")
    msg = sent[2]
    assert msg[1] == "me@example.com" and msg[2] == "Model portfolio: 1 status change (2026-11-18)"
    assert "Alpha Gold: Hold -> Above fair value: review" in msg[3] and "Beta Silver" not in msg[3]
    assert alerts.notify_portfolio(sh, alerts.portfolio_statuses(sh), "2026-11-18", env=env) == \
        ["Model portfolio: no status changed."]


def test_portfolio_alert_failure_doesnt_leak_names(monkeypatch):
    sh = portfolio_sheet({"Alpha Gold": "Above fair value: review"})

    def boom(*a, **k):
        raise RuntimeError("Alpha Gold failed")
    monkeypatch.setattr(alerts, "send_email", boom)
    lines = alerts.notify_portfolio(sh, {"Alpha Gold": "Hold"}, "2026-11-18", env={})
    assert lines == ["Model portfolio alert not sent: RuntimeError."]


def test_workflow_permissions_and_steps():
    y = (ROOT / ".github" / "workflows" / "update-prices.yml").read_text()
    perms = y.split("permissions:")[1].split("jobs:")[0]
    assert [line.split("#")[0].strip() for line in perms.strip().splitlines()] == ["contents: read", "issues: write"]
    assert "minerval prices --notify" in y and "minerval alerts" in y
    assert "secrets.ALERT_SMTP_URL" in y and "secrets.ALERT_EMAIL_TO" in y
    assert "gh issue create" in y and "--label signals" in y
    assert "\t" not in y
    assert "test_email:" in y and "if: ${{ inputs.test_email }}" in y and "minerval test-email" in y


def test_test_email(monkeypatch):
    assert alerts.test_email(env={}) == (False, "Test email not sent: ALERT_SMTP_URL or ALERT_EMAIL_TO is not set.")
    env = {"ALERT_SMTP_URL": "smtps://me%40example.com:secretpw@smtp.example.com:465", "ALERT_EMAIL_TO": "me@example.com"}
    sent = []
    monkeypatch.setattr(alerts, "send_email", lambda subject, body, env: sent.append((subject, body)) or True)
    ok, line = alerts.test_email(env=env)
    assert ok and "sent" in line and sent[0][0] == "minerval: test email"

    def refused(*a, **k):
        raise alerts.smtplib.SMTPAuthenticationError(535, b"me@example.com secretpw rejected")
    monkeypatch.setattr(alerts, "send_email", refused)
    ok, line = alerts.test_email(env=env)
    assert not ok and "SMTPAuthenticationError 535" in line and "app password" in line
    assert "example.com" not in line and "secretpw" not in line
