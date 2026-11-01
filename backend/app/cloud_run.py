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
        if AI_FINDER:
            from .services import ai_contacts
            res = ai_contacts.run_for_new_jobs(db, PoliteClient(), since=datetime.utcnow() - timedelta(days=2))
            log.info("AI contact finder: %s", res)
        else:
            log.info("AI contact finder off (no ANTHROPIC_API_KEY)")
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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "scan"))
