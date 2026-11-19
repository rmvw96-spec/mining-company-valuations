"""Alerts when a signal or a Model portfolio status changes.

Market signals (public): a status change counts once the new status has held for `hold_days` recorded trading
days (Signal history rows). signals.run() writes those confirmed changes to out/signals/changes.json; the
`alerts` command turns them into an issue title and body (out/alerts/), which the GitHub workflow posts.

Model portfolio (private): column T statuses are read before the price update and after the signals step; any
change is emailed, and only emailed, when ALERT_SMTP_URL and ALERT_EMAIL_TO are set and `prices --notify` is
used. Holding names and statuses never go into a log, the report, an issue or the GitHub step summary.
"""
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import unquote, urlparse

from .config import OUT, ensure, settings
from .signals import BY_KEY, SIGNALS, _fmt, _num, status

DEST = OUT / "alerts"


def cfg() -> dict:
    return settings()["alerts"]


def alertable(key: str) -> bool:
    """Signals whose status can trigger an alert: not "Info" rows, context-only rows or the AISC margin text."""
    s = BY_KEY.get(key)
    return s is not None and s.kind not in ("info", "aisc") and not s.context


# ---------- market signals: confirmed changes from Signal history ----------

def statuses_by_day(history: list[list], thresholds: dict) -> list[tuple[str, dict]]:
    """[(date, {key: status})] from Signal history rows (row 0 is the header), with today's thresholds."""
    if not history:
        return []
    header = [str(x).strip() for x in history[0]]
    out = []
    for row in history[1:]:
        if not row or not str(row[0]).strip():
            continue
        vals = {}
        for i, k in enumerate(header[2:], start=2):
            v = row[i] if i < len(row) else ""
            vals[k] = float(v) if _num(v) else None
        st = {}
        for k, v in vals.items():
            if not alertable(k):
                continue
            g, h = (thresholds.get(k) or [None, None])[:2]
            s = status(BY_KEY[k], v, g, h, vals)
            if s:
                st[k] = s
        out.append((str(row[0]).strip()[:10], st))
    return sorted(out)


def confirmed_changes(days: list[tuple[str, dict]], hold: int) -> list[dict]:
    """Changes confirmed on the last day: a status seen on `hold` consecutive observations of a signal (days with
    no value for it are skipped) that differs from the status confirmed before it. A signal's first confirmed
    status is not a change."""
    if not days:
        return []
    last_day = days[-1][0]
    seen: dict[str, list] = {}
    confirmed: dict[str, str] = {}
    out = []
    for d, st in days:
        for k, v in st.items():
            run = seen.setdefault(k, [])
            run.append(v)
            if len(run) >= hold and len(set(run[-hold:])) == 1 and confirmed.get(k) != v:
                if k in confirmed and d == last_day:
                    out.append({"key": k, "old": confirmed[k], "new": v, "date": d})
                confirmed[k] = v
    return out


def signal_changes(sheet, rows: list[dict], thresholds: dict, today) -> list[dict]:
    """Confirmed changes for today, with label, tier, value and as-of date from this run's rows. Today's row must
    already be in Signal history (signals.run() records it first)."""
    from .history import _read_all, _width
    tab = settings()["sheet"]["signal_history_tab"]
    if not sheet.has_tab(tab):
        return []
    grid = _read_all(sheet, tab, _width(sheet, tab, 2))
    th = {k: list(v) for k, v in settings()["signals"]["thresholds"].items()}
    th.update(thresholds or {})
    days = statuses_by_day(grid, th)
    if not days or days[-1][0] != today.isoformat():
        return []
    by_key = {r["key"]: r for r in rows}
    out = []
    for c in confirmed_changes(days, cfg()["hold_days"]):
        r, s = by_key.get(c["key"], {}), BY_KEY[c["key"]]
        out.append({**c, "label": s.label, "tier": s.tier, "value": r.get("value"), "asof": r.get("asof", ""),
                    "note": s.note})
    order = {s.key: i for i, s in enumerate(SIGNALS)}
    return sorted(out, key=lambda c: order[c["key"]])


def issue(changes: list[dict], day: str) -> tuple[str, str] | None:
    """(title, body) for a GitHub issue, or None when nothing changed. Market data only."""
    if not changes:
        return None
    hold = cfg()["hold_days"]
    title = f"Signals changed: {day} ({len(changes)})"
    lines = [f"Signal statuses that changed and have held for {hold} trading days (as of {day}).", ""]
    tier = None
    for c in changes:
        if c["tier"] != tier:
            lines += ([""] if tier is not None else []) + [f"### {c['tier']}", ""]
            tier = c["tier"]
        v = _fmt(c["value"], BY_KEY[c["key"]])
        lines.append(f"- **{c['label']}**: {c['old']} → **{c['new']}** (value {v}, as of {c['asof'] or day})")
        if c.get("note"):
            lines.append(f"  - {c['note']}")
    lines += ["", "The Signals tab has the thresholds and every status; `out/signals/report.txt` lists all changes, "
              "confirmed or not. Signals from a framework, not advice."]
    return title, "\n".join(lines) + "\n"


def write_issue(changes_file=None, out_dir=None) -> list[str]:
    """The `alerts` command: out/alerts/title.txt and body.md from out/signals/changes.json, if anything changed."""
    changes_file = changes_file or OUT / "signals" / "changes.json"
    out_dir = out_dir or DEST
    ensure(out_dir)
    for f in ("title.txt", "body.md"):
        (out_dir / f).unlink(missing_ok=True)
    if not changes_file.exists():
        return ["No out/signals/changes.json: run `signals` (or `prices`) first."]
    d = json.loads(changes_file.read_text())
    got = issue(d.get("changes", []), d.get("date", ""))
    if not got:
        return ["No confirmed signal changes: no issue."]
    (out_dir / "title.txt").write_text(got[0])
    (out_dir / "body.md").write_text(got[1])
    return [f"Issue ready: {got[0]} ({out_dir}/title.txt, body.md)."]


# ---------- Model portfolio: private email ----------

def portfolio_statuses(sheet) -> dict[str, str]:
    """{holding: status} from Model portfolio (B and T)."""
    S = settings()["sheet"]
    C = S["portfolio_cols"]
    a, b = S["portfolio_first_row"], S["portfolio_last_row"]
    hold = sheet.read(S["portfolio_tab"], f"{C['holding']}{a}:{C['holding']}{b}")
    stat = sheet.read(S["portfolio_tab"], f"{C['status']}{a}:{C['status']}{b}")
    out = {}
    for i, r in enumerate(hold):
        name = str(r[0]).strip() if r else ""
        if name:
            st = stat[i] if i < len(stat) else []
            out[name] = str(st[0]).strip() if st else ""
    return out


def portfolio_changes(before: dict, after: dict) -> list[tuple[str, str, str]]:
    return [(k, before.get(k, ""), v) for k, v in after.items() if k in before and before[k] != v]


def send_email(subject: str, body: str, env=None) -> bool:
    """Send through ALERT_SMTP_URL (smtps://user:password@host:465, or smtp://...:587 for STARTTLS) to
    ALERT_EMAIL_TO. Returns False, sending nothing, when either isn't set."""
    env = os.environ if env is None else env
    url, to = env.get("ALERT_SMTP_URL"), env.get("ALERT_EMAIL_TO")
    if not url or not to:
        return False
    u = urlparse(url)
    user, password = unquote(u.username or ""), unquote(u.password or "")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user or to, to
    msg.set_content(body)
    if u.scheme == "smtps":
        with smtplib.SMTP_SSL(u.hostname, u.port or 465, context=ssl.create_default_context()) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(u.hostname, u.port or 587) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(user, password)
            s.send_message(msg)
    return True


def notify_portfolio(sheet, before: dict, day: str, env=None) -> list[str]:
    """Email the Model portfolio rows whose status changed in this run. Report lines never name a holding."""
    try:
        changes = portfolio_changes(before, portfolio_statuses(sheet))
        if not changes:
            return ["Model portfolio: no status changed."]
        body = "\n".join(f"{name}: {old or '(blank)'} -> {new or '(blank)'}" for name, old, new in changes)
        sent = send_email(f"Model portfolio: {len(changes)} status change{'s' * (len(changes) > 1)} ({day})",
                          body + "\n\nFrom the daily price update. Signals from a framework, not advice.\n", env)
        return [f"Model portfolio: {len(changes)} status change(s) " +
                ("emailed." if sent else "(email not set up, so not sent; see the Sheet).")]
    except Exception as e:                          # never fails the price update; no row content in the message
        return [f"Model portfolio alert not sent: {type(e).__name__}."]
