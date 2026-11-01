"""Notification emails to the user (new openings found, application emails waiting for approval).

Sent from the user's own Gmail (app password) to JH_NOTIFY_EMAIL. These go only to the user, never to schools.
"""
import logging
from email.message import EmailMessage
from html import escape

from ..config import APP_URL, NOTIFY_EMAIL
from ..models import Job, OutboxEmail, User
from . import outbox

log = logging.getLogger("jobhunter.notify")


def _send(db, subject: str, text: str, html: str) -> bool:
    from sqlalchemy import select
    user = db.scalars(select(User)).first()
    cfg = outbox.settings(user)
    to = NOTIFY_EMAIL or cfg.get("gmail_address")
    if not to or not cfg.get("app_password"):
        log.info("Notification skipped (no Gmail settings)")
        return False
    msg = EmailMessage()
    msg["From"] = f"USA Job Hunter <{cfg.get('gmail_address')}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    try:
        outbox._smtp_send(cfg, msg)
        return True
    except outbox.SendError as e:
        log.warning("Notification not sent: %s", e)
        return False


def _job_line(j: Job) -> tuple[str, str]:
    school = (j.school.name if j.school else None) or j.employer_name or ""
    where = ", ".join(filter(None, [j.city, j.state]))
    url = f"{APP_URL}/#/job/{j.id}"
    deadline = j.closing_text or (j.closing_date.isoformat() if j.closing_date else "")
    t = f"- {j.job_title} — {school} ({where})" + (f" · match {j.match_score}%" if j.match_score is not None else "") + \
        (f" · deadline {deadline}" if deadline else "") + f"\n  {url}"
    h = (f'<li><a href="{escape(url)}"><b>{escape(j.job_title or "")}</b></a> — {escape(school)} ({escape(where)})'
         + (f" · match <b>{j.match_score}%</b>" if j.match_score is not None else "")
         + (f" · deadline {escape(deadline)}" if deadline else "") + "</li>")
    return t, h


def new_openings(db, jobs: list[Job]) -> bool:
    if not jobs:
        return False
    jobs = sorted(jobs, key=lambda j: -(j.match_score or 0))
    lines = [_job_line(j) for j in jobs[:40]]
    more = len(jobs) - len(lines)
    subject = f"🔔 {len(jobs)} new math teaching opening{'s' if len(jobs) != 1 else ''} found"
    text = f"USA Job Hunter found {len(jobs)} new opening(s):\n\n" + "\n".join(t for t, _ in lines) + \
        (f"\n…and {more} more" if more > 0 else "") + f"\n\nOpen the app: {APP_URL}"
    html = (f"<p>USA Job Hunter found <b>{len(jobs)}</b> new opening(s):</p><ul>" + "".join(h for _, h in lines) + "</ul>"
            + (f"<p>…and {more} more.</p>" if more > 0 else "") + f'<p><a href="{APP_URL}">Open USA Job Hunter</a></p>')
    return _send(db, subject, text, html)


def emails_waiting(db, items: list[OutboxEmail]) -> bool:
    if not items:
        return False
    url = f"{APP_URL}/#/outbox"
    subject = f"📨 {len(items)} application email{'s' if len(items) != 1 else ''} ready for your approval"
    rows_t, rows_h = [], []
    for e in items:
        j = e.job
        school = (j.school.name if j and j.school else None) or (j.employer_name if j else "")
        rows_t.append(f"- To {e.to_name} ({e.to_role or 'Principal'}) <{e.to_email}> — {j.job_title if j else ''}, {school}")
        rows_h.append(f"<li>To <b>{escape(e.to_name or '')}</b> ({escape(e.to_role or 'Principal')}) &lt;{escape(e.to_email)}&gt; — "
                      f"{escape(j.job_title if j else '')}, {escape(school)}</li>")
    text = ("These application emails were prepared for new openings. Nothing is sent until you approve each one.\n\n"
            + "\n".join(rows_t) + f"\n\nReview and approve: {url}")
    html = ("<p>These application emails were prepared for new openings. <b>Nothing is sent until you approve each one.</b></p>"
            f"<ul>{''.join(rows_h)}</ul><p><a href=\"{url}\" style=\"display:inline-block;padding:10px 16px;background:#1a6fb5;"
            "color:#fff;border-radius:8px;text-decoration:none\">Review &amp; approve</a></p>")
    return _send(db, subject, text, html)
