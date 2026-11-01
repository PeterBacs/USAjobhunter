from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import OutboxEmail, User
from ..services import outbox

router = APIRouter(prefix="/api/outbox", tags=["outbox"])


def item_out(e: OutboxEmail) -> dict:
    j = e.job
    return {"id": e.id, "job_id": e.job_id, "to_email": e.to_email, "to_name": e.to_name, "subject": e.subject,
            "body": e.body, "attach_resume": e.attach_resume, "status": e.status, "error": e.error,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "sent_at": e.sent_at.isoformat() if e.sent_at else None,
            "job_title": j.job_title if j else None, "school": (j.school.name if j and j.school else None),
            "employer_name": j.employer_name if j else None, "state": j.state if j else None,
            "job_status": j.job_status if j else None, "match_score": j.match_score if j else None,
            "date_posted": j.date_posted.isoformat() if j and j.date_posted else None,
            "closing_text": (j.closing_text or (j.closing_date.isoformat() if j.closing_date else None)) if j else None,
            "application_url": (j.application_url or j.official_job_url) if j else None}


def settings_out(db, user: User) -> dict:
    cfg = outbox.settings(user)
    pw = cfg.get("app_password")
    r = outbox.active_resume(db, user.id)
    return {"enabled": bool(cfg.get("enabled")), "gmail_address": cfg.get("gmail_address"),
            "app_password_set": bool(pw), "app_password_hint": ("•" * 8 + pw.replace(" ", "")[-4:]) if pw else None,
            "attach_resume": bool(cfg.get("attach_resume", True)), "resume_name": r.filename if r else None,
            "since": cfg.get("since")}


@router.get("/count")
def count(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"pending": db.scalar(select(func.count()).select_from(OutboxEmail).where(
        OutboxEmail.user_id == user.id, OutboxEmail.status.in_(["PENDING", "FAILED"]))) or 0}


@router.get("")
def list_items(status: str = "PENDING", db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(OutboxEmail).where(OutboxEmail.user_id == user.id)
    q = q.where(OutboxEmail.status.in_(["SENT"] if status == "SENT" else ["SKIPPED"] if status == "SKIPPED"
                                       else ["PENDING", "FAILED"]))
    rows = db.scalars(q.order_by(OutboxEmail.created_at.desc()).limit(300)).all()
    counts = dict(db.execute(select(OutboxEmail.status, func.count()).where(OutboxEmail.user_id == user.id)
                             .group_by(OutboxEmail.status)).all())
    return {"items": [item_out(e) for e in rows], "counts": counts, "settings": settings_out(db, user)}


@router.put("/settings")
def put_settings(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Missing field = keep; empty app_password = remove it."""
    cfg = outbox.settings(user)
    if "gmail_address" in body:
        cfg["gmail_address"] = (body["gmail_address"] or "").strip() or None
    if "app_password" in body:
        pw = (body["app_password"] or "").strip()
        if pw:
            cfg["app_password"] = pw
        else:
            cfg.pop("app_password", None)
    if "attach_resume" in body:
        cfg["attach_resume"] = bool(body["attach_resume"])
    if "enabled" in body:
        on = bool(body["enabled"])
        if on and not cfg.get("enabled"):
            # Openings found in the last few days count as new when the feature is turned on.
            cfg["since"] = (datetime.utcnow() - timedelta(days=outbox.NEW_WINDOW_DAYS)).isoformat(timespec="seconds")
        cfg["enabled"] = on
    outbox.save_settings(db, user, cfg)
    added = outbox.queue_new(db) if cfg.get("enabled") else 0
    return dict(settings_out(db, user), added=added)


@router.post("/test")
def test(db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        return {"sent_to": outbox.send_test(db, user)}
    except outbox.SendError as e:
        raise HTTPException(400, str(e))


@router.post("/refresh")
def refresh(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Look for new openings to prepare emails for (also runs automatically after every scan)."""
    if not outbox.settings(user).get("enabled"):
        raise HTTPException(400, "Turn on auto-prepared emails first.")
    return {"added": outbox.queue_new(db)}


def _own(db, user, eid) -> OutboxEmail:
    e = db.get(OutboxEmail, eid)
    if not e or e.user_id != user.id:
        raise HTTPException(404)
    return e


@router.put("/{eid}")
def edit(eid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Edit the subject, message or résumé choice before approving. The recipient stays the confirmed address."""
    e = _own(db, user, eid)
    if e.status == "SENT":
        raise HTTPException(400, "Already sent")
    for k in ("subject", "body"):
        if k in body and str(body[k]).strip():
            setattr(e, k, str(body[k]))
    if "attach_resume" in body:
        e.attach_resume = bool(body["attach_resume"])
    db.commit()
    return item_out(e)


@router.post("/{eid}/approve")
def approve(eid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _own(db, user, eid)
    try:
        outbox.approve_and_send(db, user, e)
    except outbox.SendError as err:
        e.status, e.error = "FAILED", str(err)
        db.commit()
        raise HTTPException(400, str(err))
    return item_out(e)


@router.post("/{eid}/skip")
def skip(eid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _own(db, user, eid)
    if e.status == "SENT":
        raise HTTPException(400, "Already sent")
    e.status, e.decided_at = "SKIPPED", datetime.utcnow()
    db.commit()
    return item_out(e)


@router.post("/{eid}/restore")
def restore(eid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = _own(db, user, eid)
    if e.status == "SKIPPED":
        e.status, e.decided_at, e.error = "PENDING", None, None
        db.commit()
    return item_out(e)
