import csv
import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import (Alert, Application, Contact, District, Interview, J1Program, Job, JobContact, ScanLog, ScanRun,
                      ScanSource, User)
from ..routers.jobs import query_jobs
from ..seed import create_demo
from ..serializers import program_out, run_out, source_out
from ..services import exports, scanner
from ..services.applied import applied_job_ids
from ..services import scheduler as sched
from ..services.contacts import serialize_contact

router = APIRouter(prefix="/api", tags=["admin"])


# ------------------------------------------------------------ dashboard
@router.get("/dashboard")
def dashboard(demo: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    live = select(Job).where(Job.is_demo.is_(demo))
    applied = applied_job_ids(db, user.id)
    active = [j for j in db.scalars(live.where(Job.job_status.in_(["ACTIVE", "POSSIBLY_ACTIVE"]))) if j.id not in applied]
    today = date.today()
    apps = db.scalars(select(Application).where(Application.user_id == user.id, Application.deleted_at.is_(None))).all()
    verified_contacts = db.scalar(select(func.count(func.distinct(Contact.id))).join(JobContact, JobContact.contact_id == Contact.id)
                                  .join(Job, Job.id == JobContact.job_id)
                                  .where(Contact.verification_status == "VERIFIED", Job.is_demo.is_(demo)))
    stage_counts = {}
    for a in apps:
        stage_counts[a.application_status] = stage_counts.get(a.application_status, 0) + 1
    upcoming = db.scalars(select(Interview).where(Interview.starts_at_utc >= datetime.utcnow())).all()
    last = db.scalars(select(ScanRun).where(ScanRun.kind.in_(["QUICK", "FULL"])).order_by(ScanRun.id.desc())).first()
    return {
        "cards": {
            "active_math_jobs": len(active),
            "new_today": sum(1 for j in active if j.date_discovered and j.date_discovered.date() == today),
            "posted_today": sum(1 for j in active if j.date_posted == today),
            "new_this_week": sum(1 for j in active if j.date_discovered and j.date_discovered.date() >= today - timedelta(days=7)),
            "matches_90": sum(1 for j in active if (j.match_score or 0) >= 90),
            "confirmed_j1": sum(1 for j in active if j.j1_status in ("CONFIRMED_J1_VACANCY", "CONFIRMED_J1_EMPLOYER")),
            "verified_contacts": verified_contacts or 0,
            "applications_sent": sum(1 for a in apps if a.date_applied),
            "follow_ups_due": sum(1 for a in apps if a.follow_up_date and a.follow_up_date <= today
                                  and a.application_status in ("APPLIED", "FOLLOW_UP")),
            "interviews": len(upcoming),
            "offers": stage_counts.get("OFFER", 0) + stage_counts.get("HIRED", 0),
        },
        "applications_by_stage": stage_counts,
        "last_scan": run_out(last) if last else None,
        "scan_running": scanner.is_busy(),
        "demo_available": bool(db.scalars(select(Job).where(Job.is_demo.is_(True))).first()),
    }


# ------------------------------------------------------------ scans
class ScanIn(BaseModel):
    kind: str = "QUICK"
    states: list[str] = []
    keywords: list[str] = []
    tracked_only: bool = False   # CLOSED_CHECK: only saved / applied jobs


@router.post("/scans")
def start_scan(body: ScanIn, user: User = Depends(current_user)):
    if body.kind not in ("QUICK", "FULL", "VERIFY_JOBS", "VERIFY_CONTACTS", "J1", "CLOSED_CHECK", "H1B", "ENG"):
        raise HTTPException(400, "unknown scan kind")
    from ..config import GITHUB_DISPATCH_TOKEN, GITHUB_REPO, ON_VERCEL
    if ON_VERCEL:
        # The website can't run long scans; it starts the GitHub Actions workflow instead.
        if not GITHUB_DISPATCH_TOKEN:
            raise HTTPException(400, "Scans run automatically every 4 hours. (To start one from here, add a JH_GITHUB_TOKEN in Vercel.)")
        import httpx
        mode = {"QUICK": "scan", "FULL": "full", "CLOSED_CHECK": "CLOSED_CHECK", "VERIFY_JOBS": "CLOSED_CHECK"}.get(body.kind, body.kind)
        r = httpx.post(f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/scan.yml/dispatches",
                       headers={"Authorization": f"Bearer {GITHUB_DISPATCH_TOKEN}", "Accept": "application/vnd.github+json"},
                       json={"ref": "main", "inputs": {"mode": mode}}, timeout=20)
        if r.status_code >= 300:
            raise HTTPException(502, f"GitHub didn't start the scan (HTTP {r.status_code}).")
        return {"run_id": None, "dispatched": True}
    if scanner.is_busy():
        raise HTTPException(409, "A scan is already running")
    rid = scanner.start(body.kind, {"states": body.states, "keywords": body.keywords, "tracked_only": body.tracked_only})
    return {"run_id": rid}


@router.get("/scans")
def list_scans(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [run_out(r) for r in db.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(50))]


@router.get("/scans/{rid}")
def get_scan(rid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = db.get(ScanRun, rid)
    if not r:
        raise HTTPException(404)
    out = run_out(r)
    out["log_count"] = db.scalar(select(func.count()).select_from(ScanLog).where(ScanLog.scan_run_id == rid))
    return out


@router.post("/scans/{rid}/cancel")
def cancel_scan(rid: int, user: User = Depends(current_user)):
    scanner.cancel(rid)
    return {"ok": True}


@router.get("/scans/{rid}/logs")
def scan_logs(rid: int, only_errors: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(ScanLog).where(ScanLog.scan_run_id == rid)
    if only_errors:
        q = q.where(ScanLog.crawl_status != "FETCHED")
    return [{"id": l.id, "source": l.source_name, "url": l.url, "http_status": l.http_status,
             "crawl_status": l.crawl_status, "parser_status": l.parser_status, "jobs_discovered": l.jobs_discovered,
             "error": l.error, "elapsed_ms": l.elapsed_ms, "scanned_at": l.scanned_at.isoformat()}
            for l in db.scalars(q.order_by(ScanLog.id.desc()).limit(1000))]


@router.get("/schedule")
def get_schedule(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"schedule": {**sched.DEFAULT_SCHEDULE, **((user.settings or {}).get("schedule") or {})}, "next_runs": sched.status()}


@router.put("/schedule")
def put_schedule(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    user.settings = dict(user.settings or {}, schedule=body)
    db.commit()
    sched.start(body)
    return {"ok": True, "next_runs": sched.status()}


# ------------------------------------------------------------ sources
class SourceIn(BaseModel):
    name: str
    connector: str
    config: dict = {}
    state: str | None = None
    city: str | None = None
    tier: int = 1
    enabled: bool = True


@router.get("/sources")
def list_sources(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [source_out(s) for s in db.scalars(select(ScanSource).order_by(ScanSource.tier, ScanSource.name))]


@router.get("/job-sites")
def job_sites(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Job sites and whether the scanner reads them (with last scan result)."""
    from ..seed import JOB_SITES
    by_conn = {}
    for s in db.scalars(select(ScanSource)):
        by_conn.setdefault(s.connector, []).append(s)
    link = {"SchoolSpring": "schoolspring", "CERRA South Carolina": "schoolspring", "K12JobSpot": "k12jobspot",
            "EDJOIN": "edjoin", "Frontline district boards": "applitrack"}
    out = []
    for site in JOB_SITES:
        srcs = by_conn.get(link.get(site["name"], ""), [])
        if site["name"] == "CERRA South Carolina":
            srcs = [s for s in srcs if "CERRA" in s.name]
        elif site["name"] == "SchoolSpring":
            srcs = [s for s in srcs if "CERRA" not in s.name]
        last = max((s.last_scanned for s in srcs if s.last_scanned), default=None)
        out.append(dict(site, enabled=any(s.enabled for s in srcs) if srcs else False,
                        last_scanned=last.isoformat() if last else None,
                        last_jobs_found=sum(s.last_jobs_found or 0 for s in srcs) if srcs else None,
                        last_status=", ".join(sorted({s.last_status for s in srcs if s.last_status})) or None))
    return out


@router.post("/sources")
def add_source(body: SourceIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.connector == "applitrack" and not body.config.get("client"):
        raise HTTPException(400, "AppliTrack needs config.client (the slug after applitrack.com/)")
    if body.connector == "jsonld_page" and not body.config.get("url"):
        raise HTTPException(400, "Official page connector needs config.url")
    s = ScanSource(**body.model_dump())
    db.add(s)
    db.commit()
    return source_out(s)


@router.patch("/sources/{sid}")
def patch_source(sid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = db.get(ScanSource, sid)
    if not s:
        raise HTTPException(404)
    for k in ("name", "config", "state", "city", "tier", "enabled"):
        if k in body:
            setattr(s, k, body[k])
    db.commit()
    return source_out(s)


# ------------------------------------------------------------ contacts directory
@router.get("/contacts")
def list_contacts(include_applied: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    out = []
    today = date.today()
    applied = set() if include_applied else applied_job_ids(db, user.id)
    for c in db.scalars(select(Contact).where(Contact.deleted_at.is_(None)).order_by(Contact.updated_at.desc()).limit(2000)):
        d = serialize_contact(c)
        all_links = db.scalars(select(JobContact).where(JobContact.contact_id == c.id)).all()
        # Jobs already applied to are hidden here too; a contact whose only jobs are applied is hidden.
        links = [l for l in all_links if l.job_id not in applied]
        if all_links and not links:
            continue
        d["hidden_applied_jobs"] = len(all_links) - len(links)
        jobs = []
        for l in links:
            j = l.job
            jobs.append({"job_id": l.job_id, "relationship": l.relationship_type, "confidence": l.confidence,
                         "title": j.job_title, "is_demo": j.is_demo, "job_status": j.job_status,
                         "state": j.state, "city": j.city,
                         "date_posted": j.date_posted.isoformat() if j.date_posted else None,
                         "days_old": (today - j.date_posted).days if j.date_posted else None})
        # Newest posting first within each contact
        jobs.sort(key=lambda x: x["date_posted"] or "", reverse=True)
        d["jobs"] = jobs
        posted = [x["date_posted"] for x in jobs if x["date_posted"]]
        d["states"] = sorted({x["state"] for x in jobs if x["state"]} or
                             ({c.district.state} if c.district and c.district.state else set()))
        d["latest_posted"] = max(posted) if posted else None
        d["latest_days_old"] = min((x["days_old"] for x in jobs if x["days_old"] is not None), default=None)
        out.append(d)
    return out


@router.get("/contacts/deleted")
def list_deleted_contacts(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Contact).where(Contact.deleted_at.is_not(None)).order_by(Contact.deleted_at.desc()).limit(200)).all()
    return [dict(serialize_contact(c), deleted_at=c.deleted_at.isoformat(), job_count=len(c.deleted_links or []))
            for c in rows]


@router.delete("/contacts/{cid}")
def delete_contact(cid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Remove a contact from the Contacts page and from every job (letters, emails, exports).
    Its job links are kept on the record so the delete can be undone."""
    c = db.get(Contact, cid)
    if not c or c.deleted_at:
        raise HTTPException(404)
    links = db.scalars(select(JobContact).where(JobContact.contact_id == c.id)).all()
    c.deleted_links = [{"job_id": l.job_id, "relationship": l.relationship_type, "confidence": l.confidence,
                        "evidence_url": l.evidence_url, "evidence_text": l.evidence_text} for l in links]
    for l in links:
        db.delete(l)
    c.deleted_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "id": c.id, "jobs_unlinked": len(links)}


@router.post("/contacts/{cid}/restore")
def restore_contact(cid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Undo a delete: the contact and its job links come back."""
    c = db.get(Contact, cid)
    if not c:
        raise HTTPException(404)
    c.deleted_at = None
    restored = 0
    for l in c.deleted_links or []:
        job = db.get(Job, l["job_id"])
        if not job:
            continue
        exists = db.scalars(select(JobContact).where(JobContact.job_id == job.id, JobContact.contact_id == c.id,
                                                     JobContact.relationship_type == l["relationship"])).first()
        if not exists:
            db.add(JobContact(job_id=job.id, contact_id=c.id, relationship_type=l["relationship"],
                              confidence=l.get("confidence") or "LOW", evidence_url=l.get("evidence_url"),
                              evidence_text=l.get("evidence_text")))
            restored += 1
    c.deleted_links = None
    db.commit()
    return {"ok": True, "id": c.id, "jobs_relinked": restored}


@router.post("/contacts/{cid}/check-mailbox")
def check_contact_mailbox(cid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Ask the school's mail server right now whether this contact's email exists (no email is sent)."""
    from ..services.contacts import check_mailbox
    c = db.get(Contact, cid)
    if not c or not c.email:
        raise HTTPException(404, "Contact has no email")
    check_mailbox(db, c, force=True)
    return serialize_contact(c)


# ------------------------------------------------------------ J-1 sponsor database
class ProgramIn(BaseModel):
    organization: str
    organization_type: str
    states_served: list[str] = []
    subjects_recruited: list[str] = []
    official_website: str | None = None
    teacher_program_url: str | None = None
    address: str | None = None
    headquarters_state: str | None = None
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    fees_if_public: str | None = None
    district_id: int | None = None
    source_url: str
    evidence_quote: str | None = None
    verification_status: str = "PARTIALLY_VERIFIED"
    notes: str | None = None


@router.get("/j1/programs")
def list_programs(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [program_out(p) for p in db.scalars(select(J1Program).order_by(J1Program.organization_type, J1Program.organization))]


@router.post("/j1/programs")
def add_program(body: ProgramIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.organization_type not in ("DESIGNATED_J1_SPONSOR", "RECRUITMENT_AGENCY", "DISTRICT_EMPLOYER"):
        raise HTTPException(400, "organization_type must be DESIGNATED_J1_SPONSOR, RECRUITMENT_AGENCY or DISTRICT_EMPLOYER")
    p = J1Program(**body.model_dump(), last_verified=datetime.utcnow())
    db.add(p)
    db.commit()
    return program_out(p)


@router.patch("/j1/programs/{pid}")
def patch_program(pid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = db.get(J1Program, pid)
    if not p:
        raise HTTPException(404)
    for k, v in body.items():
        if hasattr(p, k) and k not in ("id", "created_at"):
            setattr(p, k, v)
    p.last_verified = datetime.utcnow()
    db.commit()
    return program_out(p)


@router.post("/j1/programs/import-state-dept-csv")
def import_dos_csv(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Import the CSV exported from https://j1visa.state.gov/participants/how-to-apply/sponsor-search/ (CSV button).
    Only rows in the 'Teacher' category are imported, as DESIGNATED_J1_SPONSOR."""
    text = file.file.read().decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    added = 0
    for row in reader:
        r = {(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}
        if r.get("CATEGORY", "").lower() != "teacher":
            continue
        name = r.get("SPONSOR NAME")
        if not name or db.scalars(select(J1Program).where(J1Program.organization == name,
                                                          J1Program.organization_type == "DESIGNATED_J1_SPONSOR")).first():
            continue
        db.add(J1Program(organization=name, organization_type="DESIGNATED_J1_SPONSOR", address=r.get("ADDRESS"),
                         headquarters_state=r.get("STATE") or None, phone=r.get("PHONE NUMBER"),
                         official_website=r.get("WEBSITE"),
                         source_url="https://j1visa.state.gov/participants/how-to-apply/sponsor-search/?program=Teacher",
                         evidence_quote="Listed under category 'Teacher' in the State Department sponsor export",
                         verification_status="VERIFIED", last_verified=datetime.utcnow()))
        added += 1
    db.commit()
    return {"added": added}


@router.get("/districts")
def list_districts(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{"id": d.id, "name": d.name, "state": d.state, "city": d.city, "website": d.website,
             "careers_url": d.careers_url, "j1_status": d.j1_status, "j1_evidence": d.j1_evidence}
            for d in db.scalars(select(District).order_by(District.state, District.name))]


@router.patch("/districts/{did}")
def patch_district(did: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = db.get(District, did)
    if not d:
        raise HTTPException(404)
    for k in ("website", "careers_url", "hr_directory_url", "city"):
        if k in body:
            setattr(d, k, body[k] or None)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------ export
@router.get("/export/{fmt}")
def export(fmt: str, states: str | None = None, min_match: int | None = None, include_closed: bool = True,
           tracked_only: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = query_jobs(db, user, {"states": states, "min_match": min_match, "include_closed": include_closed,
                                 "include_applied": tracked_only})
    apps = {a.job_id: a for a in db.scalars(select(Application).where(Application.user_id == user.id, Application.deleted_at.is_(None)))}
    jobs = [j for j, _ in rows if not tracked_only or j.id in apps or j.is_saved]
    data = exports.rows_for(jobs, apps)
    stamp = date.today().isoformat()
    if fmt == "csv":
        return Response(exports.to_csv(data), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="usa-job-hunter-{stamp}.csv"'})
    if fmt == "xlsx":
        return Response(exports.to_xlsx(data),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="usa-job-hunter-{stamp}.xlsx"'})
    if fmt == "pdf":
        return Response(exports.to_pdf(data), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="usa-job-hunter-{stamp}.pdf"'})
    raise HTTPException(400, "csv, xlsx or pdf")


@router.post("/demo")
def load_demo(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"created": create_demo(db)}
