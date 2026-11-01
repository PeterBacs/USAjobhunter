import math
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Application, ApplicationEvent, Contact, District, Job, JobContact, JobVerification, School, User
from ..serializers import job_detail, job_row
from ..services import contacts as contact_svc
from ..services import generators
from ..services.http import PoliteClient
from ..services.applied import APPLIED_STAGES, applied_job_ids
from ..services.ingest import profile_dict
from ..services.matching import score_job
from ..services.taxonomy import STATES, STATE_TILES

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _apps_by_job(db, user) -> dict[int, Application]:
    return {a.job_id: a for a in db.scalars(select(Application).where(Application.user_id == user.id, Application.deleted_at.is_(None),
                                                                      Application.job_id.is_not(None)))}


def _miles(lat1, lon1, lat2, lon2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def query_jobs(db: Session, user: User, p: dict) -> list[tuple[Job, Application | None]]:
    q = select(Job)
    q = q.where(Job.is_demo.is_(bool(p.get("demo"))))
    if not p.get("include_closed"):
        q = q.where(Job.job_status != "CLOSED")
    if p.get("states"):
        q = q.where(Job.state.in_([s.upper() for s in _csv(p["states"])]))
    if p.get("city"):
        q = q.where(Job.city.ilike(f"%{p['city']}%"))
    if p.get("zip"):
        q = q.where(Job.zip == p["zip"])
    if p.get("district"):
        q = q.where(Job.employer_name.ilike(f"%{p['district']}%"))
    if p.get("school"):
        q = q.join(School, Job.school_id == School.id, isouter=True).where(School.name.ilike(f"%{p['school']}%"))
    if p.get("q"):
        like = f"%{p['q']}%"
        q = q.where(or_(Job.job_title.ilike(like), Job.employer_name.ilike(like), Job.city.ilike(like),
                        Job.job_description.ilike(like)))
    if p.get("j1"):
        q = q.where(Job.j1_status.in_(_csv(p["j1"])))
    if p.get("exclude_no_sponsorship"):
        q = q.where(Job.j1_status != "NO_SPONSORSHIP")
    if p.get("max_days"):
        q = q.where(Job.date_posted >= date.today() - timedelta(days=int(p["max_days"])))
    if p.get("min_salary"):
        q = q.where(Job.salary_max >= float(p["min_salary"]))
    if p.get("min_match"):
        q = q.where(Job.match_score >= int(p["min_match"]))
    if p.get("saved_only"):
        q = q.where(Job.is_saved.is_(True))
    if p.get("job_status"):
        q = q.where(Job.job_status.in_(_csv(p["job_status"])))
    jobs = db.scalars(q).unique().all()

    subjects = _csv(p.get("subjects"))
    grades = [g.lower() for g in _csv(p.get("grades"))]
    contact_flags = _csv(p.get("contact"))
    app_statuses = _csv(p.get("app_status"))
    apps = _apps_by_job(db, user)
    # Applied jobs are hidden unless asked for (toggle, or an application-stage filter that names them).
    show_applied = bool(p.get("include_applied")) or bool(set(app_statuses) & APPLIED_STAGES)
    near = None
    if p.get("near_city") and p.get("radius"):
        city, _, st = p["near_city"].partition("|")
        pts = [(j.latitude, j.longitude) for j in db.scalars(select(Job).where(Job.city == city, Job.state == st,
                                                                                  Job.latitude.is_not(None)))]
        if pts:
            near = (sum(a for a, _ in pts) / len(pts), sum(b for _, b in pts) / len(pts), float(p["radius"]))
    out = []
    for j in jobs:
        if subjects and not any(s in (j.subjects or []) for s in subjects):
            continue
        if grades:
            g = (j.grade_level or "").lower()
            ok = False
            for want in grades:
                if want == "grades 6-12" and ("6-12" in g or ("middle" in g and "high" in g)):
                    ok = True
                elif want == "grades 7-12" and "7-12" in g:
                    ok = True
                elif want in g:
                    ok = True
            if not ok:
                continue
        if contact_flags:
            links = j.contact_links
            def has(pred):
                return any(pred(l) for l in links)
            is_pr = lambda l: l.relationship_type in ("SCHOOL_PRINCIPAL", "PRINCIPAL") or l.contact.contact_type in ("PRINCIPAL", "ASSISTANT_PRINCIPAL")
            checks = {
                "verified_recruiter_email": lambda: has(lambda l: not is_pr(l) and contact_svc.email_usable(l.contact)),
                "verified_principal_email": lambda: has(lambda l: is_pr(l) and contact_svc.email_usable(l.contact)),
                "named_recruiter": lambda: has(lambda l: not is_pr(l) and l.contact.full_name),
                "named_principal": lambda: has(lambda l: is_pr(l) and l.contact.full_name),
                "direct_phone": lambda: has(lambda l: bool(l.contact.phone)),
                "vacancy_contact_only": lambda: has(lambda l: l.relationship_type in ("JOB_POSTER", "VACANCY_CONTACT", "HIRING_MANAGER")),
            }
            if not all(checks[f]() for f in contact_flags if f in checks):
                continue
        a = apps.get(j.id)
        if a and a.application_status in APPLIED_STAGES and not show_applied:
            continue
        if app_statuses:
            st = a.application_status if a else "NOT_APPLIED"
            if st not in app_statuses and not ("INTERESTED" in app_statuses and j.is_saved and not a):
                continue
        if near:
            if j.latitude is None or _miles(near[0], near[1], j.latitude, j.longitude) > near[2]:
                continue
        out.append((j, a))
    sort = p.get("sort") or "match"
    keyfn = {
        "match": lambda t: -(t[0].match_score or 0),
        "newest": lambda t: -(t[0].date_posted.toordinal() if t[0].date_posted else 0),
        "salary": lambda t: -(t[0].salary_max or 0),
        "deadline": lambda t: t[0].closing_date.toordinal() if t[0].closing_date else 10 ** 7,
        "state": lambda t: (t[0].state or "ZZ", -(t[0].match_score or 0)),
    }.get(sort, lambda t: -(t[0].match_score or 0))
    out.sort(key=keyfn)
    return out


@router.get("")
def list_jobs(q: str | None = None, states: str | None = None, city: str | None = None, zip: str | None = None,
              district: str | None = None, school: str | None = None, subjects: str | None = None,
              grades: str | None = None, j1: str | None = None, exclude_no_sponsorship: bool = False,
              max_days: int | None = None, min_salary: float | None = None, contact: str | None = None,
              min_match: int | None = None, app_status: str | None = None, include_closed: bool = False,
              job_status: str | None = None, saved_only: bool = False, demo: bool = False,
              include_applied: bool = False,
              near_city: str | None = None, radius: float | None = None,
              sort: str = "match", page: int = 1, page_size: int = 50,
              db: Session = Depends(get_db), user: User = Depends(current_user)):
    params = dict(locals())
    params.pop("db"), params.pop("user")
    rows = query_jobs(db, user, params)
    total = len(rows)
    start = (max(page, 1) - 1) * page_size
    return {"total": total, "page": page, "page_size": page_size,
            "items": [job_row(j, a) for j, a in rows[start:start + page_size]]}


@router.get("/facets")
def facets(demo: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    applied = applied_job_ids(db, user.id)
    jobs = [j for j in db.scalars(select(Job).where(Job.is_demo.is_(demo), Job.job_status != "CLOSED"))
            if j.id not in applied]
    by_state, by_grade, by_j1, by_salary = {}, {}, {}, {}
    cities = {}
    for j in jobs:
        by_state[j.state or "?"] = by_state.get(j.state or "?", 0) + 1
        g = j.grade_level or "Not stated"
        g = "Middle School" if g.startswith("Middle School (") else g
        by_grade[g] = by_grade.get(g, 0) + 1
        by_j1[j.j1_status] = by_j1.get(j.j1_status, 0) + 1
        if j.salary_max:
            b = "< $50k" if j.salary_max < 50000 else "$50-60k" if j.salary_max < 60000 else "$60-70k" if j.salary_max < 70000 \
                else "$70-80k" if j.salary_max < 80000 else "$80-100k" if j.salary_max < 100000 else "$100k+"
        else:
            b = "Not published"
        by_salary[b] = by_salary.get(b, 0) + 1
        if j.city and j.state and j.latitude is not None:
            cities[f"{j.city}|{j.state}"] = cities.get(f"{j.city}|{j.state}", 0) + 1
    j1_states = {}
    for j in jobs:
        if j.j1_status in ("CONFIRMED_J1_VACANCY", "CONFIRMED_J1_EMPLOYER", "INTERNATIONAL_FRIENDLY"):
            j1_states[j.state] = j1_states.get(j.state, 0) + 1
    return {"by_state": by_state, "by_grade": by_grade, "by_j1": by_j1, "by_salary": by_salary,
            "j1_activity_by_state": j1_states, "cities_with_coordinates": sorted(cities),
            "states": [{"code": k, "name": v, "tile": STATE_TILES.get(k)} for k, v in STATES.items()],
            "districts": sorted({j.employer_name for j in jobs if j.employer_name})}


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    app = db.scalars(select(Application).where(Application.job_id == job_id, Application.user_id == user.id, Application.deleted_at.is_(None))).first()
    return job_detail(job, app)


@router.post("/{job_id}/save")
def toggle_save(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    job.is_saved = not job.is_saved
    db.commit()
    return {"is_saved": job.is_saved}


@router.post("/{job_id}/verify")
def verify_one(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Re-check this vacancy's status against its official source right now."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    client = PoliteClient()
    try:
        return _verify_single(db, client, job)
    finally:
        client.close()


def _verify_single(db, client, job):
    from bs4 import BeautifulSoup
    from ..services import scanner
    from ..services.connectors import schoolspring
    from ..services.verification import decide_job_status
    ss = next((s for s in job.sources if "schoolspring.com/jobs?jobid=" in s.url), None)
    if ss:
        jid = ss.url.split("jobid=")[-1]
        http, detail = schoolspring.recheck(client, jid)
        if detail and detail.get("jobInfo"):
            raw = schoolspring.build_job(detail, jid)
            status, reason = decide_job_status(closing=raw.closing_date, until_filled=raw.until_filled, official_http=http,
                                               official_text=None, listed_in_feed=True, posted=raw.date_posted)
        elif http in (404, 410) or (http and http < 300):
            status, reason = "CLOSED", "Posting no longer returned by the employer's SchoolSpring board"
        else:
            status, reason = "UNKNOWN", f"Source unreachable (HTTP {http})"
        url = schoolspring.detail_api(jid)
    elif job.official_job_url:
        res = client.get(job.official_job_url)
        http, url = res.status, job.official_job_url
        text = BeautifulSoup(res.text, "lxml").get_text(" ", strip=True) if res.ok else None
        if res.crawl_status == "ROBOTS_BLOCKED":
            status, reason = "UNKNOWN", "Site disallows automated checks - open the posting to verify manually"
        else:
            status, reason = decide_job_status(closing=job.closing_date, until_filled=False, official_http=http,
                                               official_text=text, listed_in_feed=None, posted=job.date_posted)
    else:
        return {"job_status": job.job_status, "reason": "No official URL to check"}
    if status == "CLOSED":
        scanner._close_job(db, job, reason, url, http)
    else:
        job.job_status, job.status_reason, job.last_verified = status, reason, datetime.utcnow()
        db.add(JobVerification(job_id=job.id, check_type="STATUS", target="vacancy", result=status, detail=reason,
                               url=url, http_status=http))
    db.commit()
    return {"job_status": job.job_status, "reason": reason, "http_status": http}


@router.get("/{job_id}/safety-check")
def safety_check(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    rec = contact_svc.recommend_addressee(job)
    if rec.get("recommended"):
        contact_obj = db.get(Contact, rec["contact"]["id"])
        if contact_obj and contact_obj.email:
            contact_svc.check_mailbox(db, contact_obj)
            rec = contact_svc.recommend_addressee(job)
    c = rec.get("contact")
    mb = (c or {}).get("mailbox_status")
    mailbox_txt = {"EXISTS": "mailbox confirmed by the school's mail server",
                   "NOT_FOUND": "the school's mail server says this mailbox does NOT exist - do not email it",
                   "NO_MAIL_SERVER": "this domain has no mail server - do not email it",
                   "CATCH_ALL": "server accepts all addresses; mailbox cannot be confirmed",
                   "UNKNOWN": "mailbox check inconclusive"}.get(mb, "mailbox not checked")
    fresh_hours = (datetime.utcnow() - job.last_verified).total_seconds() / 3600 if job.last_verified else None
    items = [
        ("Vacancy still active", job.job_status == "ACTIVE",
         f"{job.job_status}: {job.status_reason or ''}" + (f" (checked {fresh_hours:.0f}h ago)" if fresh_hours is not None else "")),
        ("School verified", bool(job.school and job.school.verification_status == "VERIFIED"),
         job.school.name if job.school else "No exact school identified"),
        ("Job URL verified", bool(job.official_job_url and any(s.is_official for s in job.sources)),
         job.official_job_url or "No official URL"),
        ("Contact currently affiliated", bool(c and c.get("verification_status") == "VERIFIED"),
         (c["full_name"] + " - " + (c.get("source_url") or "")) if c else "No HIGH-confidence contact - use Hiring Committee"),
        ("Email verified", bool(c and c.get("email") and c.get("email_status") == "VERIFIED" and mb in ("EXISTS", "CATCH_ALL")),
         f"{c.get('email')} - {mailbox_txt}" if c and c.get("email") else "Recruiter email not publicly verified - apply via the official portal"),
        ("Deadline valid", not job.closing_date or job.closing_date >= date.today(),
         job.closing_text or (job.closing_date.isoformat() if job.closing_date else "No deadline published (continuous / until filled)")),
    ]
    j1_ok = job.j1_status in ("CONFIRMED_J1_VACANCY", "CONFIRMED_J1_EMPLOYER")
    return {
        "checks": [{"label": l, "ok": ok, "detail": d} for l, ok, d in items],
        "j1": {"ok": j1_ok, "status": job.j1_status,
               "detail": "Employer explicitly recruits J-1 teachers" if j1_ok else "J-1 status requires confirmation"},
        "stale": fresh_hours is None or fresh_hours > 24,
        "recommendation": "Re-verify before sending" if (fresh_hours is None or fresh_hours > 24) else None,
    }


@router.post("/{job_id}/generate/{kind}")
def generate(job_id: int, kind: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    profile = profile_dict(db)
    from ..models import CandidateProfile
    cp = db.scalars(select(CandidateProfile).where(CandidateProfile.user_id == user.id)).first()
    if cp:
        profile["email"] = cp.email
    if kind == "cover-letter":
        return generators.cover_letter(job, profile)
    if kind == "email":
        # Confirm the addressee's mailbox with the school's mail server first (cached 7 days; nothing is sent).
        for link in job.contact_links:
            if link.contact.email:
                contact_svc.check_mailbox(db, link.contact)
        db.refresh(job)
        return generators.application_email(job, profile)
    if kind == "follow-up":
        app = db.scalars(select(Application).where(Application.job_id == job_id, Application.user_id == user.id, Application.deleted_at.is_(None))).first()
        return generators.follow_up_email(job, profile, app.date_applied if app else None)
    raise HTTPException(400, "kind must be cover-letter, email or follow-up")


# ------------------------------------------------------------ manual verification workflow
class ManualContact(BaseModel):
    full_name: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    source_url: str
    relationship: str = "SCHOOL_PRINCIPAL"
    confidence: str = "MEDIUM"
    evidence_text: str | None = None
    confirm_on_source: bool = True


@router.post("/{job_id}/contacts")
def add_contact(job_id: int, body: ManualContact, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Add a contact found by the reviewer. The source page is fetched and must contain the name/email."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    page_text = None
    if body.confirm_on_source:
        from bs4 import BeautifulSoup
        client = PoliteClient()
        try:
            res = client.get(body.source_url)
        finally:
            client.close()
        if not res.ok:
            raise HTTPException(422, f"Could not load the source page ({res.error or res.status}). "
                                     "Uncheck 'confirm on source' to record it as a reviewer-attested contact.")
        page_text = BeautifulSoup(res.text, "lxml").get_text(" ", strip=True)
        if body.full_name and body.full_name.split()[-1].lower() not in page_text.lower():
            raise HTTPException(422, "The name was not found on the source page.")
        if body.email and body.email.lower() not in page_text.lower():
            raise HTTPException(422, "That exact email address was not found on the source page. "
                                     "Guessed addresses cannot be stored.")
    c = contact_svc.upsert_contact(db, full_name=body.full_name, title=body.title,
                                   organization=job.school.name if job.school else job.employer_name,
                                   email=body.email, phone=body.phone, source_url=body.source_url,
                                   district_id=job.district_id,
                                   school_id=job.school_id if body.relationship in ("SCHOOL_PRINCIPAL", "CAMPUS_ADMINISTRATOR") else None,
                                   page_text=page_text)
    if not c:
        raise HTTPException(422, "Provide a name, email or phone")
    if not body.confirm_on_source:
        c.verification_status = "PARTIALLY_VERIFIED"
        if c.email:
            c.email_status = "PUBLISHED_ELSEWHERE"
        c.reviewer_note = f"Reviewer-attested by {user.email}; not machine-confirmed on source"
    if c.deleted_at:                      # adding a previously deleted contact by hand brings it back
        c.deleted_at, c.deleted_links = None, None
    contact_svc.link(db, job, c, body.relationship, body.confidence, body.source_url, body.evidence_text)
    db.add(JobVerification(job_id=job.id, check_type="MANUAL", target="contact", result="ADDED",
                           detail=f"{c.full_name or c.email} as {body.relationship} ({body.confidence})",
                           url=body.source_url, reviewer=user.email))
    db.commit()
    return {"contact_id": c.id}


class Approval(BaseModel):
    target: str        # vacancy | principal | recruiter | email | j1
    approved: bool
    note: str | None = None
    url: str | None = None
    contact_id: int | None = None
    j1_status: str | None = None


@router.post("/{job_id}/review")
def review(job_id: int, body: Approval, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    now = datetime.utcnow()
    if body.target == "vacancy":
        if body.approved:
            job.job_status, job.status_reason = "ACTIVE", f"Manually verified by {user.email}"
        else:
            from ..services import scanner
            scanner._close_job(db, job, body.note or f"Marked closed by {user.email}", body.url)
        job.last_verified = now
    elif body.target in ("principal", "recruiter", "email") and body.contact_id:
        c = db.get(Contact, body.contact_id)
        if not c:
            raise HTTPException(404, "contact")
        if body.target == "email":
            c.email_status = "VERIFIED" if body.approved else "DO_NOT_USE"
        else:
            c.verification_status = "VERIFIED" if body.approved else "CONFLICTING"
            link = db.scalars(select(JobContact).where(JobContact.job_id == job.id, JobContact.contact_id == c.id)).first()
            if link and body.approved:
                link.confidence = "HIGH"
                link.evidence_text = (link.evidence_text or "") + f" | Approved by reviewer {user.email}"
        c.verified_at = now
        c.reviewer_note = body.note or c.reviewer_note
    elif body.target == "j1":
        if body.approved and body.j1_status:
            if not body.url:
                raise HTTPException(422, "J-1 approval requires the evidence URL")
            job.j1_status = body.j1_status
            job.j1_evidence = (job.j1_evidence or []) + [{"url": body.url, "quote": body.note, "kind": "reviewer",
                                                          "checked_at": now.isoformat()}]
        elif not body.approved:
            job.j1_status = "NEEDS_CONFIRMATION"
    else:
        raise HTTPException(400, "unknown target")
    db.add(JobVerification(job_id=job.id, check_type="MANUAL", target=body.target,
                           result="APPROVED" if body.approved else "REJECTED", detail=body.note, url=body.url,
                           reviewer=user.email))
    m = score_job(job, profile_dict(db))
    job.match_score, job.match_breakdown = m["score"], m
    db.commit()
    return {"ok": True}


@router.post("/{job_id}/find-website")
def find_website(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Look for the district's official website now, from its own published emails / posting links."""
    from ..services import websites
    job = db.get(Job, job_id)
    if not job or not job.district:
        raise HTTPException(404, "No district on this job")
    client = PoliteClient()
    try:
        ev = websites.find_district_website(db, client, job.district, force=True)
    finally:
        client.close()
    return {"found": bool(ev), "evidence": ev,
            "candidates": [d for d, _ in websites.candidate_domains(db, job.district)]}


class OrgUrls(BaseModel):
    district_website: str | None = None
    district_careers_url: str | None = None
    district_hr_directory_url: str | None = None
    school_website: str | None = None
    school_staff_directory_url: str | None = None


@router.post("/{job_id}/org-urls")
def set_org_urls(job_id: int, body: OrgUrls, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Record official school/district URLs so contact and J-1 research can use them."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    if job.district:
        if body.district_website and body.district_website != job.district.website:
            job.district.website_evidence = {"url": body.district_website, "how_found": "Added by you",
                                             "check": "Entered manually — not automatically confirmed",
                                             "verification_status": "PARTIALLY_VERIFIED",
                                             "checked_at": datetime.utcnow().isoformat(timespec="seconds") + "Z"}
        job.district.website = body.district_website or job.district.website
        job.district.careers_url = body.district_careers_url or job.district.careers_url
        job.district.hr_directory_url = body.district_hr_directory_url or job.district.hr_directory_url
    if job.school:
        job.school.website = body.school_website or job.school.website
        job.school.staff_directory_url = body.school_staff_directory_url or job.school.staff_directory_url
    db.commit()
    found = None
    if job.school and (job.school.website or job.school.staff_directory_url):
        from ..services.scanner import research_school_principal
        client = PoliteClient()
        try:
            c = research_school_principal(db, client, job.school)
            db.commit()
            found = contact_svc.serialize_contact(c) if c else None
        finally:
            client.close()
    return {"ok": True, "principal_found": found}


@router.post("/{job_id}/ai-contacts")
def ai_contacts(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Find the principal / HR email automatically: the app walks the official school / district website (free,
    with the free Gemini model reading the pages when GEMINI_API_KEY is set; Claude only if a paid key was added).
    Only addresses the app re-reads on the official page are saved."""
    from ..config import AI_FINDER
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    from ..services import free_contacts
    res = free_contacts.find_contacts(db, PoliteClient(), job)
    if not any(k["role"] == "PRINCIPAL" for k in res.get("kept") or []) and AI_FINDER:
        from ..services import ai_contacts as ai
        r2 = ai.find_contacts(db, PoliteClient(), job)
        res = {"ok": True, "kept": (res.get("kept") or []) + (r2.get("kept") or []),
               "rejected": (res.get("rejected") or []) + (r2.get("rejected") or [])}
    if not res.get("ok") and not res.get("kept"):
        raise HTTPException(400, res.get("error") or "Lookup failed")
    try:
        from ..services import outbox
        res["outbox_added"] = outbox.queue_new(db)
    except Exception:
        res["outbox_added"] = 0
    return res
