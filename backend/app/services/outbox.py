"""Auto-prepared application emails to principals, sent only after the user approves each one.

After every scan, each NEW opening whose school principal is named by an official source and has an email the
school's mail server confirmed exists gets a ready-to-send email (the user's own text, "Dear Principal <name>",
the school's real name). The user is notified and decides per email: Approve & send, or Skip.
Approved emails go out from the user's own Gmail (an app password the user entered); the job is then marked applied.
"""
import mimetypes
import re
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import select

from ..models import Alert, Application, ApplicationEvent, Job, OutboxEmail, Resume, User
from .applied import applied_job_ids
from .contacts import email_usable, ensure_honorific
from .generators import application_email, business_days_after, school_principal
from .ingest import profile_dict

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
NEW_WINDOW_DAYS = 7          # when turned on, openings found in the last 7 days count as "new"
SAME_ADDRESS_DAYS = 30       # never queue a second email to the same principal within 30 days
MATH_TITLE = re.compile(r"math|algebra|geometr|calculus|statistic|trigonometr|pre-?calc", re.I)


def settings(user: User | None) -> dict:
    """Saved settings; in the cloud, environment variables provide the Gmail login and turn the feature on."""
    from ..config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD, IS_CLOUD
    cfg = dict(((user.settings or {}) if user else {}).get("auto_email") or {})
    if GMAIL_ADDRESS and GMAIL_APP_PASSWORD:
        cfg.setdefault("gmail_address", GMAIL_ADDRESS)
        cfg.setdefault("app_password", GMAIL_APP_PASSWORD)
    if IS_CLOUD and "enabled" not in cfg:
        cfg["enabled"] = True
        cfg.setdefault("since", (datetime.utcnow() - timedelta(days=NEW_WINDOW_DAYS)).isoformat(timespec="seconds"))
    return cfg


def save_settings(db, user: User, cfg: dict):
    user.settings = {**(user.settings or {}), "auto_email": cfg}
    db.commit()


def active_resume(db, user_id: int) -> Resume | None:
    """The résumé selected in the profile, otherwise the newest active upload."""
    from ..models import CandidateProfile
    cp = db.scalars(select(CandidateProfile).where(CandidateProfile.user_id == user_id)).first()
    r = db.get(Resume, cp.active_resume_id) if cp and cp.active_resume_id else None
    r = r or db.scalars(select(Resume).where(Resume.user_id == user_id, Resume.is_active.is_(True))
                        .order_by(Resume.uploaded_at.desc())).first()
    return r if r and (r.content or Path(r.stored_path).is_file()) else None


def resume_bytes(r: Resume) -> bytes:
    return r.content if r.content else Path(r.stored_path).read_bytes()


def queue_new(db) -> int:
    """Prepare emails for new openings. Returns how many were added to the Outbox."""
    user = db.scalars(select(User)).first()
    cfg = settings(user)
    if not user or not cfg.get("enabled"):
        return 0
    since = datetime.fromisoformat(cfg.get("since") or datetime.utcnow().isoformat())
    applied = applied_job_ids(db, user.id)
    queued_jobs = set(db.scalars(select(OutboxEmail.job_id)))
    recent_cut = datetime.utcnow() - timedelta(days=SAME_ADDRESS_DAYS)
    recent_to = {e.lower() for e in db.scalars(select(OutboxEmail.to_email).where(
        OutboxEmail.created_at >= recent_cut, OutboxEmail.status.in_(["PENDING", "SENT"])))}
    profile = profile_dict(db)
    # Waiting emails whose posting closed, or whose job was applied to another way, are set aside automatically.
    for e in db.scalars(select(OutboxEmail).where(OutboxEmail.user_id == user.id, OutboxEmail.status.in_(["PENDING", "FAILED"]))):
        if e.job and not MATH_TITLE.search(e.job.job_title or ""):
            e.status, e.decided_at, e.error = "SKIPPED", datetime.utcnow(), "Skipped automatically: not a math teaching job"
            continue
        if e.job and (e.job.job_status == "CLOSED" or e.job_id in applied):
            e.status, e.decided_at = "SKIPPED", datetime.utcnow()
            e.error = "Skipped automatically: the posting closed" if e.job.job_status == "CLOSED" else "Skipped automatically: you already applied"
    refresh_greetings(db)
    added = 0
    jobs = db.scalars(select(Job).where(Job.is_demo.is_(False), Job.job_status == "ACTIVE",
                                        Job.date_discovered >= since)).all()
    for job in jobs:
        if job.id in applied or job.id in queued_jobs:
            continue
        if not MATH_TITLE.search(job.job_title or ""):
            continue  # the email says "the mathematics teaching position" - only math jobs get one
        principal, _link = school_principal(job)
        if not principal or not email_usable(principal):
            continue
        to = principal.email.strip().lower()
        if to in recent_to:
            continue
        ensure_honorific(db, _http(), principal)   # "Dear Mr. Moody," only if the school's page writes it
        em = application_email(job, profile)
        db.add(OutboxEmail(user_id=user.id, job_id=job.id, contact_id=principal.id, to_email=to,
                           to_name=principal.full_name, subject=em["subject"], body=em["body"],
                           attach_resume=bool(cfg.get("attach_resume", True))))
        school = (job.school.name if job.school else None) or job.employer_name or ""
        db.add(Alert(user_id=user.id, job_id=job.id, title="Email ready for your approval",
                     message=f"{job.job_title} — {school} ({job.state}). Email to Principal {principal.full_name} "
                             f"<{to}> is waiting in the Outbox. Nothing is sent until you approve it."))
        recent_to.add(to)
        queued_jobs.add(job.id)
        added += 1
    db.commit()
    return added


_client = None


def _http():
    global _client
    if _client is None:
        from .http import PoliteClient
        _client = PoliteClient()
    return _client


def refresh_greetings(db) -> int:
    """Update the first line of emails still waiting, once the school's own title for the person is known."""
    from .generators import greeting_for
    from ..models import Contact
    n = 0
    for e in db.scalars(select(OutboxEmail).where(OutboxEmail.status.in_(["PENDING", "FAILED"]))).all():
        c = db.get(Contact, e.contact_id) if e.contact_id else None
        if not c or not e.body.startswith("Dear "):
            continue
        ensure_honorific(db, _http(), c)
        first, _, rest = e.body.partition("\n")
        new = greeting_for(c)
        if first != new:
            e.body = new + "\n" + rest
            n += 1
    db.commit()
    return n


class SendError(Exception):
    pass


def _smtp_send(cfg: dict, msg: EmailMessage):
    addr, pw = cfg.get("gmail_address"), (cfg.get("app_password") or "").replace(" ", "")
    if not addr or not pw:
        raise SendError("Connect your Gmail first (Gmail address and app password on the Outbox page).")
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=30) as s:
            s.login(addr, pw)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise SendError("Gmail rejected the address or app password. Create a new app password and save it again.")
    except smtplib.SMTPRecipientsRefused:
        raise SendError("Gmail refused the recipient address.")
    except (smtplib.SMTPException, OSError) as e:
        raise SendError(f"Couldn't send through Gmail: {type(e).__name__}")


def _message(cfg: dict, sender_name: str, to: str, subject: str, body: str, attachment: bytes | None,
             attachment_name: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{sender_name} <{cfg.get('gmail_address')}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment:
        name = attachment_name or "Resume.pdf"
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(attachment, maintype=maintype, subtype=subtype, filename=name)
    return msg


def send_test(db, user: User) -> str:
    cfg = settings(user)
    msg = _message(cfg, "USA Job Hunter", cfg.get("gmail_address") or "", "USA Job Hunter – Gmail connection test",
                   "This is a test from USA Job Hunter. Your Gmail connection works; approved application emails "
                   "will be sent from this address.", None)
    _smtp_send(cfg, msg)
    return cfg.get("gmail_address")


def approve_and_send(db, user: User, item: OutboxEmail) -> OutboxEmail:
    """Send one approved email, then record the application. Checks the posting is still open first."""
    if item.status == "SENT":
        return item
    job = db.get(Job, item.job_id)
    if not job or job.job_status == "CLOSED":
        raise SendError("This posting is closed now, so the email was not sent. Skip it.")
    if job.id in applied_job_ids(db, user.id):
        raise SendError("You already marked this job applied, so the email was not sent. Skip it.")
    cfg = settings(user)
    resume = active_resume(db, user.id) if item.attach_resume else None
    if item.attach_resume and not resume:
        raise SendError("No résumé uploaded. Upload it with UPLOAD RESUME, or untick “Attach my résumé”.")
    sender = profile_dict(db).get("full_name") or "Applicant"
    _smtp_send(cfg, _message(cfg, sender, item.to_email, item.subject, item.body,
                             resume_bytes(resume) if resume else None, resume.filename if resume else None))
    now = datetime.utcnow()
    item.status, item.sent_at, item.decided_at, item.error = "SENT", now, now, None
    # Record it as an application (same as MARK APPLIED), with the email that was sent.
    from ..routers.crm import _from_job
    a = db.scalars(select(Application).where(Application.job_id == job.id, Application.user_id == user.id)).first()
    if not a:
        a = _from_job(db, user, job, "APPLIED")
    a.deleted_at = None
    a.application_status = "APPLIED"
    a.date_applied = a.date_applied or now.date()
    a.follow_up_date = a.follow_up_date or business_days_after(a.date_applied, 5)
    a.contact_person, a.contact_email, a.email_text = item.to_name, item.to_email, item.body
    db.add(ApplicationEvent(application_id=a.id, event_type="APPLICATION",
                            description=f"Application email sent to {item.to_name} <{item.to_email}> (approved in Outbox)"
                                        + (" with résumé attached" if resume else "")))
    db.commit()
    return item
