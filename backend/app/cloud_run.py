"""Scheduled cloud job (GitHub Actions). Usage:

    python -m app.cloud_run scan     # every 4 hours: scan, AI email lookup, prepare emails, notify
    python -m app.cloud_run daily    # once a day: closed-posting check, contacts, engineering jobs, notify

Notifications go to JH_NOTIFY_EMAIL. Application emails to principals are only PREPARED here;
they are sent only when the user approves them on the website.
"""
import logging
import sys
from datetime import datetime, timedelta

from sqlalchemy import select

from .db import SessionLocal
from .main import startup_tasks
from .models import Job, OutboxEmail, ScanRun
from .services import notify, outbox, scanner
from .services.applied import applied_job_ids
from .services.http import PoliteClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jobhunter.cloud")


def _status(rid: int) -> str:
    db = SessionLocal()
    try:
        r = db.get(ScanRun, rid)
        return f"{r.kind} {r.status} {r.stats or {}} {(r.error or '')[:300]}"
    finally:
        db.close()


def after_scan(started: datetime, notify_new: bool) -> None:
    from .config import AI_FINDER
    db = SessionLocal()
    try:
        from .services import free_contacts
        log.info("Posting emails on the district's own domain confirmed: %s", free_contacts.confirm_posting_emails(db))
        res = free_contacts.run_for_new_jobs(db, PoliteClient(), since=datetime.utcnow() - timedelta(days=2))
        log.info("Free contact finder (official websites%s): %s", " + Gemini" if free_contacts.GEMINI_KEY else "", res)
        if AI_FINDER:   # paid Claude lookup - only if an ANTHROPIC_API_KEY was added
            from .services import ai_contacts
            log.info("Claude contact finder: %s", ai_contacts.run_for_new_jobs(db, PoliteClient(), since=datetime.utcnow() - timedelta(days=2)))
        added = outbox.queue_new(db)
        log.info("Outbox: %s new email(s) prepared", added)
        if notify_new:
            applied = applied_job_ids(db)
            new_jobs = [j for j in db.scalars(select(Job).where(Job.is_demo.is_(False), Job.job_status == "ACTIVE",
                                                                Job.date_discovered >= started)) if j.id not in applied]
            log.info("New openings this run: %s (email sent: %s)", len(new_jobs), notify.new_openings(db, new_jobs))
        waiting = db.scalars(select(OutboxEmail).where(OutboxEmail.status == "PENDING",
                                                       OutboxEmail.created_at >= started)).all()
        log.info("Emails waiting for approval this run: %s (email sent: %s)", len(waiting), notify.emails_waiting(db, waiting))
    finally:
        db.close()


def main(mode: str) -> int:
    import os
    from .config import IS_CLOUD
    if os.getenv("GITHUB_ACTIONS"):
        # Show which secrets this run can see (names only, never values).
        for name in ("DATABASE_URL", "GEMINI_API_KEY", "JH_GMAIL_ADDRESS", "JH_GMAIL_APP_PASSWORD", "JH_NOTIFY_EMAIL"):
            print(f"  secret {name}: {'found' if os.getenv(name) else 'MISSING'}")
    if os.getenv("GITHUB_ACTIONS") and not IS_CLOUD:
        print("DATABASE_URL secret is missing or isn't a postgresql:// address. Add it under GitHub > Settings > "
              "Secrets and variables > Actions > Repository secrets - nothing to do.")
        return 1
    db, _ = startup_tasks(full=True)
    db.close()
    started = datetime.utcnow()
    if mode == "scan":
        rid = scanner.run_sync("QUICK", {}, trigger="SCHEDULED")
        log.info("Scan finished: %s", _status(rid))
        after_scan(started, notify_new=True)
    elif mode == "daily":
        for kind, params in (("CLOSED_CHECK", {"tracked_only": False}), ("VERIFY_CONTACTS", {}), ("ENG", {})):
            rid = scanner.run_sync(kind, params, trigger="SCHEDULED")
            log.info("%s", _status(rid))
        after_scan(started, notify_new=False)
    elif mode in ("full", "QUICK", "FULL", "CLOSED_CHECK", "VERIFY_CONTACTS", "ENG", "H1B", "J1"):
        kind = "FULL" if mode == "full" else mode
        rid = scanner.run_sync(kind, {}, trigger="MANUAL")
        log.info("%s", _status(rid))
        after_scan(started, notify_new=kind in ("QUICK", "FULL"))
    else:
        print(__doc__)
        return 2
    return 0


def _annotate(level: str, msg: str):
    """GitHub shows ::error:: / ::notice:: lines on the run's summary page (no need to open the log)."""
    import os
    if os.getenv("GITHUB_ACTIONS"):
        print(f"::{level} title=USA Job Hunter::{msg}".replace("\n", " | "))


if __name__ == "__main__":
    import os
    import traceback
    missing = [n for n in ("DATABASE_URL", "GEMINI_API_KEY", "JH_GMAIL_ADDRESS", "JH_GMAIL_APP_PASSWORD", "JH_NOTIFY_EMAIL")
               if not os.getenv(n)]
    if os.getenv("GITHUB_ACTIONS"):
        _annotate("notice", "Secrets missing: " + (", ".join(missing) if missing else "none - all 5 found"))
    try:
        code = main(sys.argv[1] if len(sys.argv) > 1 else "scan")
    except Exception as e:
        _annotate("error", f"{type(e).__name__}: {str(e)[:300]} | {traceback.format_exc().splitlines()[-3][:200]}")
        raise
    if code:
        _annotate("error", f"Stopped with code {code}" + (f" - missing secrets: {', '.join(missing)}" if missing else ""))
    sys.exit(code)
