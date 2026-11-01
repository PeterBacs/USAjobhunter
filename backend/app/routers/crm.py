import shutil
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import DOCUMENT_DIR
from ..db import get_db
from ..models import Alert, AlertRule, Application, ApplicationEvent, Document, Interview, Job, User
from ..serializers import application_out, interview_out
from ..services.alerts import allowed_states, evaluate, normalize_states
from ..services.applied import applied_job_ids
from ..services.contacts import recommend_addressee
from ..services.generators import business_days_after
from ..services.timezones import US_TIMEZONES, local_to_utc

router = APIRouter(prefix="/api", tags=["crm"])

# Stages shown on the Applications board. Older records in removed stages are grouped into the nearest one.
STAGES = ["APPLIED", "INTERVIEW", "HIRED"]
OUTCOMES = ["REJECTED", "WITHDRAWN", "POSITION_CLOSED"]
BOARD_GROUPS = {"APPLIED": ["APPLIED", "FOLLOW_UP"], "INTERVIEW": ["INTERVIEW", "SECOND_INTERVIEW", "OFFER"],
                "HIRED": ["HIRED"], "REJECTED": ["REJECTED"], "WITHDRAWN": ["WITHDRAWN"],
                "POSITION_CLOSED": ["POSITION_CLOSED"]}
# Every status the database may hold (tracker "saved" entries, legacy stages) stays valid.
ALL_STATUSES = ["DISCOVERED", "SAVED", "APPLYING", "APPLIED", "FOLLOW_UP", "INTERVIEW", "SECOND_INTERVIEW", "OFFER",
                "HIRED"] + OUTCOMES


def _live(q):
    return q.where(Application.deleted_at.is_(None))


class AppCreate(BaseModel):
    job_id: int | None = None
    status: str = "SAVED"
    position: str | None = None
    school: str | None = None
    district: str | None = None
    state: str | None = None
    job_url: str | None = None
    contact_email: str | None = None


class AppUpdate(BaseModel):
    application_status: str | None = None
    date_applied: date | None = None
    follow_up_date: date | None = None
    contact_person: str | None = None
    contact_email: str | None = None
    resume_version: str | None = None
    cover_letter_version: str | None = None
    notes: str | None = None
    documents_sent: list[str] | None = None
    response_received: bool | None = None
    offer_salary: str | None = None
    visa_status: str | None = None
    cover_letter_text: str | None = None
    email_text: str | None = None


def _from_job(db, user, job: Job, status: str) -> Application:
    rec = recommend_addressee(job)
    c = rec.get("contact") if rec.get("recommended") else None
    salary = job.salary_text or (f"${job.salary_min:,.0f}-${job.salary_max:,.0f}" if job.salary_min and job.salary_max else None)
    a = Application(user_id=user.id, job_id=job.id, school=job.school.name if job.school else None,
                    district=job.employer_name, state=job.state, position=job.job_title, salary=salary,
                    job_url=job.application_url or job.official_job_url, date_posted=job.date_posted,
                    contact_person=c["full_name"] if c else None,
                    contact_email=c.get("email") if c else None,   # only set when the mailbox is confirmed
                    application_status=status, visa_status=job.j1_status)
    db.add(a)
    db.flush()
    db.add(ApplicationEvent(application_id=a.id, event_type="STATUS_CHANGE", description=f"Added to tracker as {status}"))
    return a


@router.get("/applications")
def list_apps(db: Session = Depends(get_db), user: User = Depends(current_user)):
    apps = db.scalars(_live(select(Application).where(Application.user_id == user.id))
                      .order_by(Application.date_applied.desc(), Application.updated_at.desc())).all()
    return {"stages": STAGES, "outcomes": OUTCOMES, "groups": BOARD_GROUPS, "items": [application_out(a) for a in apps]}


@router.post("/applications")
def create_app(body: AppCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.job_id:
        job = db.get(Job, body.job_id)
        if not job:
            raise HTTPException(404, "job")
        existing = db.scalars(select(Application).where(Application.job_id == job.id, Application.user_id == user.id)).first()
        if existing:
            if existing.deleted_at:          # re-adding a deleted record brings it back
                existing.deleted_at = None
                existing.application_status = body.status
                db.commit()
            return application_out(existing)
        a = _from_job(db, user, job, body.status)
    else:
        a = Application(user_id=user.id, position=body.position, school=body.school, district=body.district,
                        state=body.state, job_url=body.job_url, application_status=body.status,
                        contact_email=(body.contact_email or "").strip() or None,
                        date_applied=date.today() if body.status == "APPLIED" else None)
        db.add(a)
    db.commit()
    return application_out(a)


@router.patch("/applications/{app_id}")
def update_app(app_id: int, body: AppUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = db.get(Application, app_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    new_status = data.pop("application_status", None)
    for k, v in data.items():
        setattr(a, k, v)
    if new_status and new_status != a.application_status:
        if new_status not in ALL_STATUSES:
            raise HTTPException(400, "bad status")
        db.add(ApplicationEvent(application_id=a.id, event_type="STATUS_CHANGE",
                                description=f"{a.application_status} → {new_status}"))
        a.application_status = new_status
        if new_status == "APPLIED":
            a.date_applied = a.date_applied or date.today()
            a.follow_up_date = a.follow_up_date or business_days_after(a.date_applied, 5)
            db.add(ApplicationEvent(application_id=a.id, event_type="APPLICATION",
                                    description=f"Application submitted; follow-up suggested {a.follow_up_date}"))
        if new_status == "FOLLOW_UP":
            db.add(ApplicationEvent(application_id=a.id, event_type="FOLLOW_UP", description="Follow-up sent"))
    db.commit()
    return application_out(a)


@router.delete("/applications/{app_id}")
def delete_app(app_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Delete an application record. It is hidden everywhere (and its job returns to the job lists),
    but kept so the delete can be undone."""
    a = db.get(Application, app_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404)
    a.deleted_at = datetime.utcnow()
    db.add(ApplicationEvent(application_id=a.id, event_type="STATUS_CHANGE", description="Deleted from Applications"))
    db.commit()
    return {"ok": True, "id": a.id}


@router.post("/applications/{app_id}/restore")
def restore_app(app_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Undo a delete."""
    a = db.get(Application, app_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404)
    a.deleted_at = None
    db.add(ApplicationEvent(application_id=a.id, event_type="STATUS_CHANGE", description="Restored (undo delete)"))
    db.commit()
    return application_out(a)


@router.get("/applications/deleted")
def list_deleted(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Application).where(Application.user_id == user.id, Application.deleted_at.is_not(None))
                      .order_by(Application.deleted_at.desc()).limit(100)).all()
    return [dict(application_out(a), deleted_at=a.deleted_at.isoformat()) for a in rows]


class EventIn(BaseModel):
    event_type: str
    description: str | None = None
    occurred_at: datetime | None = None


@router.post("/applications/{app_id}/events")
def add_event(app_id: int, body: EventIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = db.get(Application, app_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404)
    db.add(ApplicationEvent(application_id=a.id, event_type=body.event_type, description=body.description,
                            occurred_at=body.occurred_at or datetime.utcnow()))
    if body.event_type == "RESPONSE":
        a.response_received = True
    if body.event_type == "FOLLOW_UP":
        a.follow_up_date = business_days_after(date.today(), 5)
    db.commit()
    return application_out(a)


@router.post("/jobs/{job_id}/mark-applied")
def mark_applied(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    a = db.scalars(select(Application).where(Application.job_id == job_id, Application.user_id == user.id)).first()
    if not a:
        a = _from_job(db, user, job, "APPLIED")
    a.deleted_at = None
    # Keep the table's employer/school/state/email current with the job record.
    a.district, a.school, a.state = job.employer_name, (job.school.name if job.school else a.school), job.state
    a.position = job.job_title
    a.application_status = "APPLIED"
    a.date_applied = a.date_applied or date.today()
    a.follow_up_date = a.follow_up_date or business_days_after(a.date_applied, 5)
    db.add(ApplicationEvent(application_id=a.id, event_type="APPLICATION",
                            description=f"Marked applied; follow-up suggested {a.follow_up_date}"))
    db.commit()
    return application_out(a)


@router.post("/jobs/{job_id}/re-applied")
def mark_reapplied(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Record that the user applied to this job again today (RE-APPLIED button in the job view)."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    a = db.scalars(select(Application).where(Application.job_id == job_id, Application.user_id == user.id)).first()
    if not a:
        a = _from_job(db, user, job, "APPLIED")   # first application wasn't recorded in the app; its date stays empty
    a.deleted_at = None
    if a.application_status in ("DISCOVERED", "SAVED", "APPLYING"):
        a.application_status = "APPLIED"
    today = date.today().isoformat()
    dates = list(a.reapplied_dates or [])
    already = today in dates
    if not already:
        a.reapplied_dates = dates + [today]
        a.follow_up_date = business_days_after(date.today(), 5)
        db.add(ApplicationEvent(application_id=a.id, event_type="RE_APPLIED",
                                description=f"Re-applied ({len(a.reapplied_dates)}×); follow-up suggested {a.follow_up_date}"))
    db.commit()
    return dict(application_out(a), already_today=already)


class ReappliedIn(BaseModel):
    dates: list[date]


@router.put("/applications/{app_id}/re-applied")
def set_reapplied(app_id: int, body: ReappliedIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Replace the re-applied dates (used by Undo and Remove in the Re-applied card)."""
    a = db.get(Application, app_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404)
    a.reapplied_dates = sorted({d.isoformat() for d in body.dates})
    db.add(ApplicationEvent(application_id=a.id, event_type="RE_APPLIED",
                            description=f"Re-applied dates updated ({len(a.reapplied_dates)})"))
    db.commit()
    return application_out(a)


# ------------------------------------------------------------ interviews
class InterviewIn(BaseModel):
    application_id: int | None = None
    job_id: int | None = None
    local_datetime: str          # e.g. 2026-10-02T09:30 in the U.S. time zone below
    us_timezone: str = "America/Chicago"
    duration_minutes: int = 30
    round_label: str | None = None
    interviewer: str | None = None
    interviewer_role: str | None = None
    school: str | None = None
    meeting_url: str | None = None
    notes: str | None = None


INTERVIEW_STAGES = ("INTERVIEW", "SECOND_INTERVIEW", "OFFER")


@router.get("/interviews")
def list_interviews(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = [i for i in db.scalars(select(Interview).order_by(Interview.starts_at_utc)).all()
            if not (i.application and i.application.deleted_at)]
    # Applications moved to the Interview stage that have no date/time yet - shown so nothing is missed.
    awaiting = [a for a in db.scalars(_live(select(Application).where(
        Application.user_id == user.id, Application.application_status.in_(INTERVIEW_STAGES)))).all() if not a.interviews]
    return {"timezones": US_TIMEZONES, "items": [interview_out(i) for i in rows],
            "awaiting": [{"id": a.id, "position": a.position, "employer_name": a.district, "school": a.school,
                          "state": a.state, "job_id": a.job_id, "application_status": a.application_status} for a in awaiting]}


@router.post("/interviews")
def add_interview(body: InterviewIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.us_timezone not in US_TIMEZONES:
        raise HTTPException(400, "unknown U.S. time zone")
    utc = local_to_utc(body.local_datetime, body.us_timezone)
    data = body.model_dump(exclude={"local_datetime"})
    had_interview = bool(body.application_id and db.scalars(
        select(Interview).where(Interview.application_id == body.application_id)).first())
    i = Interview(starts_at_utc=utc, **data)
    db.add(i)
    if body.application_id:
        a = db.get(Application, body.application_id)
        if a:
            if not i.school:
                i.school = a.school
            if not i.job_id:
                i.job_id = a.job_id
            a.interview_date, a.interview_timezone = utc, body.us_timezone
            # First interview -> Interview; another one on top of an existing interview -> Second interview.
            nxt = "SECOND_INTERVIEW" if had_interview else "INTERVIEW"
            if a.application_status in ("OFFER", "HIRED", "SECOND_INTERVIEW") or (a.application_status == "INTERVIEW" and not had_interview):
                nxt = a.application_status
            if a.application_status != nxt:
                db.add(ApplicationEvent(application_id=a.id, event_type="STATUS_CHANGE",
                                        description=f"{a.application_status} → {nxt}"))
                a.application_status = nxt
            db.add(ApplicationEvent(application_id=a.id, event_type="INTERVIEW",
                                    description=f"{body.round_label or 'Interview'} scheduled {body.local_datetime} {body.us_timezone}"))
    db.commit()
    return interview_out(i)


@router.put("/interviews/{iid}")
def edit_interview(iid: int, body: InterviewIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    i = db.get(Interview, iid)
    if not i:
        raise HTTPException(404)
    if body.us_timezone not in US_TIMEZONES:
        raise HTTPException(400, "unknown U.S. time zone")
    i.starts_at_utc = local_to_utc(body.local_datetime, body.us_timezone)
    for k, v in body.model_dump(exclude={"local_datetime", "application_id", "job_id"}).items():
        setattr(i, k, v)
    if i.application:
        i.application.interview_date, i.application.interview_timezone = i.starts_at_utc, i.us_timezone
        db.add(ApplicationEvent(application_id=i.application_id, event_type="INTERVIEW",
                                description=f"{i.round_label or 'Interview'} changed to {body.local_datetime} {body.us_timezone}"))
    db.commit()
    return interview_out(i)


@router.delete("/interviews/{iid}")
def delete_interview(iid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    i = db.get(Interview, iid)
    if i:
        db.delete(i)
        db.commit()
    return {"ok": True}


# ------------------------------------------------------------ documents
@router.get("/documents")
def list_docs(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{"id": d.id, "name": d.name, "kind": d.kind, "notes": d.notes, "uploaded_at": d.uploaded_at.isoformat()}
            for d in db.scalars(select(Document).where(Document.user_id == user.id).order_by(Document.uploaded_at.desc()))]


@router.post("/documents")
def upload_doc(file: UploadFile = File(...), kind: str = Form("OTHER"), notes: str = Form(""),
               db: Session = Depends(get_db), user: User = Depends(current_user)):
    safe = f"{uuid.uuid4().hex}_{(file.filename or 'file').replace('/', '_').replace(chr(92), '_')}"
    dest = DOCUMENT_DIR / safe
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    d = Document(user_id=user.id, name=file.filename or safe, kind=kind, stored_path=str(dest), notes=notes or None)
    db.add(d)
    db.commit()
    return {"id": d.id}


@router.get("/documents/{doc_id}/download")
def download_doc(doc_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = db.get(Document, doc_id)
    if not d or d.user_id != user.id:
        raise HTTPException(404)
    return FileResponse(d.stored_path, filename=d.name)


# ------------------------------------------------------------ alerts
class RuleIn(BaseModel):
    rule_type: str
    params: dict = {}
    enabled: bool = True


@router.get("/alerts")
def list_alerts(db: Session = Depends(get_db), user: User = Depends(current_user)):
    applied = applied_job_ids(db, user.id)
    only_states = allowed_states(db, user.id)
    rows = db.scalars(select(Alert).where(Alert.user_id == user.id).order_by(Alert.created_at.desc()).limit(2000)).all()
    job_state = dict(db.execute(select(Job.id, Job.state).where(Job.id.in_({a.job_id for a in rows if a.job_id}))).all())
    alerts = [a for a in rows if a.job_id not in applied
              and (only_states is None or not a.job_id or job_state.get(a.job_id) in only_states)][:300]
    rules = db.scalars(select(AlertRule).where(AlertRule.user_id == user.id)).all()
    return {"alerts": [{"id": a.id, "title": a.title, "message": a.message, "job_id": a.job_id, "is_read": a.is_read,
                        "state": job_state.get(a.job_id), "created_at": a.created_at.isoformat()} for a in alerts],
            "rules": [{"id": r.id, "rule_type": r.rule_type, "params": r.params, "enabled": r.enabled} for r in rules],
            "state_filter": sorted(only_states) if only_states else None,
            "unread": sum(1 for a in alerts if not a.is_read)}


def _clean_rule(body: RuleIn) -> dict:
    data = body.model_dump()
    if body.rule_type == "STATE":
        codes, bad = normalize_states(body.params.get("states", []))
        if bad:
            raise HTTPException(400, f"Not a U.S. state: {', '.join(bad)}")
        if not codes:
            raise HTTPException(400, "Select at least one state")
        data["params"] = {"states": codes}
    return data


def _reevaluate(db):
    evaluate(db, [j for (j,) in db.execute(select(Job.id).where(Job.is_demo.is_(False)))])


@router.post("/alerts/rules")
def add_rule(body: RuleIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = AlertRule(user_id=user.id, **_clean_rule(body))
    db.add(r)
    db.commit()
    _reevaluate(db)
    return {"id": r.id}


@router.patch("/alerts/rules/{rid}")
def toggle_rule(rid: int, body: RuleIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = db.get(AlertRule, rid)
    if not r or r.user_id != user.id:
        raise HTTPException(404)
    data = _clean_rule(body)
    r.rule_type, r.params, r.enabled = data["rule_type"], data["params"], data["enabled"]
    db.commit()
    _reevaluate(db)
    return {"ok": True}


@router.delete("/alerts/rules/{rid}")
def delete_rule(rid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = db.get(AlertRule, rid)
    if r and r.user_id == user.id:
        for a in db.scalars(select(Alert).where(Alert.rule_id == rid)):
            a.rule_id = None
        db.delete(r)
        db.commit()
    return {"ok": True}


@router.post("/alerts/read-all")
def read_all(db: Session = Depends(get_db), user: User = Depends(current_user)):
    for a in db.scalars(select(Alert).where(Alert.user_id == user.id, Alert.is_read.is_(False))):
        a.is_read = True
    db.commit()
    return {"ok": True}
