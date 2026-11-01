from .models import Application, Interview, J1Program, Job, ScanRun, ScanSource
from .services.contacts import recommend_addressee, serialize_contact
from .services.verification import days_old, freshness


def _d(v):
    return v.isoformat() if v else None


def contacts_summary(job: Job) -> dict:
    principal = recruiter = None
    phone = None
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for l in sorted(job.contact_links, key=lambda l: order.get(l.confidence, 3)):
        c = serialize_contact(l.contact)
        c.update(relationship=l.relationship_type, confidence=l.confidence, evidence_url=l.evidence_url)
        if l.relationship_type in ("SCHOOL_PRINCIPAL", "PRINCIPAL", "CAMPUS_ADMINISTRATOR") or \
                l.contact.contact_type in ("PRINCIPAL", "ASSISTANT_PRINCIPAL"):
            principal = principal or c
        else:
            recruiter = recruiter or c
        phone = phone or c.get("phone")
    return {"principal": principal, "recruiter": recruiter, "phone": phone}


def job_row(job: Job, app: Application | None = None) -> dict:
    cs = contacts_summary(job)
    rec = recommend_addressee(job)
    return {
        "id": job.id, "is_demo": job.is_demo, "job_title": job.job_title, "subject": job.subject, "subjects": job.subjects,
        "grade_level": job.grade_level, "employer_name": job.employer_name,
        "school": job.school.name if job.school else None, "city": job.city, "state": job.state,
        "salary_min": job.salary_min, "salary_max": job.salary_max, "salary_text": job.salary_text,
        "date_posted": _d(job.date_posted), "days_old": days_old(job.date_posted), "freshness": freshness(job.date_posted),
        "closing_date": _d(job.closing_date), "closing_text": job.closing_text,
        "job_status": job.job_status, "status_reason": job.status_reason,
        "match_score": job.match_score, "match_label": (job.match_breakdown or {}).get("label"),
        "j1_status": job.j1_status, "official_job_url": job.official_job_url, "application_url": job.application_url,
        "district_website": job.district.website if job.district else None,
        "school_website": job.school.website if job.school else None,
        "principal": cs["principal"], "recruiter": cs["recruiter"], "phone": cs["phone"],
        "recommended_addressee": rec if rec.get("recommended") else None,
        "verification_status": job.verification_status, "last_verified": _d(job.last_verified),
        "date_discovered": _d(job.date_discovered), "is_saved": job.is_saved,
        "application_status": app.application_status if app else "NOT_APPLIED",
        "application_id": app.id if app else None,
        "reapplied_dates": sorted(app.reapplied_dates or []) if app else [],
        "source_count": len(job.sources), "needs_review": job.needs_review,
    }


def h1b_for_job(job: Job) -> dict | None:
    """The user's H-1B sponsor list entry this job belongs to, if any."""
    from sqlalchemy import select
    from sqlalchemy.orm import object_session
    from .models import H1BEmployer
    sess = object_session(job)
    if not sess:
        return None
    for e in sess.scalars(select(H1BEmployer)):
        if job.id in (e.job_ids or []):
            return {"rank": e.rank, "name": e.name, "avg_salary": e.avg_salary}
    return None


def job_detail(job: Job, app: Application | None = None) -> dict:
    d = job_row(job, app)
    d["h1b_employer"] = h1b_for_job(job)
    d.update({
        "external_job_id": job.external_job_id, "employment_type": job.employment_type,
        "job_description": job.job_description, "requirements": job.requirements,
        "certification_requirements": job.certification_requirements,
        "j1_evidence": job.j1_evidence or [], "match": job.match_breakdown or {},
        "field_evidence": job.field_evidence or {},
        "district": {"id": job.district.id, "name": job.district.name, "website": job.district.website,
                     "careers_url": job.district.careers_url, "hr_directory_url": job.district.hr_directory_url,
                     "j1_status": job.district.j1_status,
                     "website_evidence": job.district.website_evidence} if job.district else None,
        "school_record": {"id": job.school.id, "name": job.school.name, "website": job.school.website,
                          "staff_directory_url": job.school.staff_directory_url} if job.school else None,
        "addressee": recommend_addressee(job),
        "contacts": [dict(serialize_contact(l.contact), relationship=l.relationship_type, confidence=l.confidence,
                          evidence_url=l.evidence_url, evidence_text=l.evidence_text, link_id=l.id)
                     for l in job.contact_links],
        "sources": [{"url": s.url, "source_name": s.source_name, "source_type": s.source_type, "tier": s.tier,
                     "is_official": s.is_official, "first_seen": _d(s.first_seen), "last_seen": _d(s.last_seen)}
                    for s in job.sources],
        "verifications": [{"check_type": v.check_type, "target": v.target, "result": v.result, "detail": v.detail,
                           "url": v.url, "http_status": v.http_status, "reviewer": v.reviewer,
                           "checked_at": _d(v.checked_at)} for v in sorted(job.verifications, key=lambda v: v.checked_at, reverse=True)],
    })
    return d


def application_out(a: Application) -> dict:
    from .services.contacts import best_confirmed_email
    # Only a confirmed-existing address is shown; manually added applications keep what the user typed.
    email = best_confirmed_email(a.job) if a.job else a.contact_email
    return {
        "employer_name": a.district, "email": email,
        "id": a.id, "job_id": a.job_id, "school": a.school, "district": a.district, "state": a.state,
        "position": a.position, "salary": a.salary, "job_url": a.job_url, "date_posted": _d(a.date_posted),
        "date_applied": _d(a.date_applied), "contact_person": a.contact_person, "contact_email": a.contact_email,
        "resume_version": a.resume_version, "cover_letter_version": a.cover_letter_version,
        "application_status": a.application_status, "follow_up_date": _d(a.follow_up_date),
        "interview_date": _d(a.interview_date), "interview_timezone": a.interview_timezone, "notes": a.notes,
        "documents_sent": a.documents_sent or [], "response_received": a.response_received,
        "offer_salary": a.offer_salary, "visa_status": a.visa_status,
        "job_status": a.job.job_status if a.job else None, "match_score": a.job.match_score if a.job else None,
        "job_status_reason": a.job.status_reason if a.job else None,
        "job_last_verified": _d(a.job.last_verified) if a.job else None,
        "j1_status": a.job.j1_status if a.job else None, "is_demo": a.job.is_demo if a.job else False,
        "events": [{"id": e.id, "event_type": e.event_type, "description": e.description,
                    "occurred_at": _d(e.occurred_at)} for e in a.events],
        "interviews": [interview_out(i, with_app=False) for i in a.interviews],
        "updated_at": _d(a.updated_at),
        "reapplied_dates": sorted(a.reapplied_dates or []),
    }


def interview_out(i: Interview, with_app: bool = True) -> dict:
    from datetime import datetime
    from .services.timezones import both_times
    a = i.application if with_app else None
    return {"id": i.id, "application_id": i.application_id, "job_id": i.job_id or (a.job_id if a else None),
            "round_label": i.round_label, "interviewer": i.interviewer, "interviewer_role": i.interviewer_role,
            "school": i.school or (a.school if a else None),
            "meeting_url": i.meeting_url, "notes": i.notes, "duration_minutes": i.duration_minutes,
            "us_timezone": i.us_timezone, "starts_at_utc": _d(i.starts_at_utc), **both_times(i.starts_at_utc, i.us_timezone),
            "is_past": bool(i.starts_at_utc and i.starts_at_utc < datetime.utcnow()),
            "position": a.position if a else None, "employer_name": a.district if a else None,
            "state": a.state if a else None, "application_status": a.application_status if a else None}


def program_out(p: J1Program) -> dict:
    return {c: (_d(getattr(p, c)) if c in ("last_verified", "created_at", "updated_at") else getattr(p, c))
            for c in ("id", "organization", "organization_type", "states_served", "subjects_recruited",
                      "official_website", "teacher_program_url", "address", "headquarters_state", "contact_person",
                      "email", "phone", "fees_if_public", "district_id", "source_url", "evidence_quote",
                      "verification_status", "last_verified", "notes")}


def run_out(r: ScanRun) -> dict:
    return {"id": r.id, "kind": r.kind, "trigger": r.trigger, "status": r.status, "params": r.params,
            "started_at": _d(r.started_at), "finished_at": _d(r.finished_at), "stats": r.stats or {},
            "error": r.error, "progress": r.progress}


def source_out(s: ScanSource) -> dict:
    return {"id": s.id, "name": s.name, "connector": s.connector, "config": s.config, "state": s.state,
            "city": s.city, "tier": s.tier, "enabled": s.enabled, "last_scanned": _d(s.last_scanned),
            "last_status": s.last_status, "last_error": s.last_error, "last_jobs_found": s.last_jobs_found}
