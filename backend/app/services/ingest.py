"""Turn connector output into canonical, de-duplicated, evidence-backed job records."""
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CandidateProfile, District, Job, JobSource, JobVerification, School
from . import contacts as contact_svc
from . import j1 as j1_svc
from .connectors.base import RawJob
from .matching import score_job
from .resume_parser import DEFAULT_PROFILE
from .taxonomy import classify_grade, classify_subjects, primary_subject
from .verification import VERIFIED, PARTIAL, decide_job_status, evidence

STOP = re.compile(r"\b(the|of|and|school|district|public|schools|independent|isd|usd|unified|county|"
                  r"teacher|position|sy|\d{2,4}[-/]\d{2,4}|full[- ]time|part[- ]time|\d+(\.\d+)?\s*fte)\b")


def norm(s: str | None) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = STOP.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def canonical_key(raw: RawJob) -> str:
    return "|".join([norm(raw.employer_name), norm(raw.school_name), norm(raw.title), (raw.state or "").upper(),
                     norm(raw.city)])


def profile_dict(db: Session) -> dict:
    p = db.scalars(select(CandidateProfile)).first()
    if not p:
        return dict(DEFAULT_PROFILE)
    return {
        "full_name": p.full_name, "years_experience": p.years_experience, "education": p.education or [],
        "licenses": p.licenses or [], "subjects": p.subjects or [], "grade_levels": p.grade_levels or [],
        "leadership": p.leadership or [], "technologies": p.technologies or [], "awards": p.awards or [],
        "research_stem": p.research_stem or [], "preferred_states": p.preferred_states or [],
        "min_salary": p.min_salary, "has_us_license": p.has_us_license,
    }


def get_or_create_district(db: Session, name: str | None, state: str | None, city: str | None,
                           source_url: str | None) -> District | None:
    if not name:
        return None
    d = db.scalars(select(District).where(District.name == name, District.state == state)).first()
    if not d:
        d = District(name=name, state=state, city=city, source_url=source_url,
                     verification_status=VERIFIED if source_url else "UNKNOWN", verified_at=datetime.utcnow())
        db.add(d)
        db.flush()
    return d


def get_or_create_school(db: Session, name: str | None, district: District | None, raw: RawJob) -> School | None:
    if not name:
        return None
    q = select(School).where(School.name == name)
    q = q.where(School.district_id == district.id) if district else q.where(School.state == raw.state)
    s = db.scalars(q).first()
    if not s:
        s = School(name=name, district_id=district.id if district else None, city=raw.city, state=raw.state,
                   zip=raw.zip, latitude=raw.latitude, longitude=raw.longitude, source_url=raw.official_url,
                   verification_status=VERIFIED, verified_at=datetime.utcnow())
        db.add(s)
        db.flush()
    return s


def find_existing(db: Session, raw: RawJob, key: str, district: District | None) -> Job | None:
    urls = [u for u in {raw.source_url, raw.official_url} if u]
    if urls and raw.external_id:
        js = db.scalars(select(JobSource).where(JobSource.url.in_(urls), JobSource.external_id == raw.external_id)).first()
        if js:
            return js.job
    if raw.official_url:
        j = db.scalars(select(Job).where(Job.official_job_url == raw.official_url, Job.is_demo.is_(False))).first()
        if j:
            return j
    if raw.external_id and district:
        j = db.scalars(select(Job).where(Job.external_job_id == raw.external_id, Job.district_id == district.id,
                                         Job.is_demo.is_(False))).first()
        if j:
            return j
    return db.scalars(select(Job).where(Job.canonical_key == key, Job.is_demo.is_(False))).first()


def _add_source(db: Session, job: Job, url: str, raw: RawJob, is_official: bool):
    if not url:
        return
    js = db.scalars(select(JobSource).where(JobSource.job_id == job.id, JobSource.url == url)).first()
    now = datetime.utcnow()
    if not js:
        from .verification import classify_source
        st, tier = classify_source(url)
        js = JobSource(job_id=job.id, url=url, source_name=raw.source_name if url == raw.source_url else "Official posting",
                       source_type=raw.source_type if url == raw.source_url else st,
                       tier=raw.tier if url == raw.source_url else tier, external_id=raw.external_id,
                       is_official=is_official, first_seen=now)
        db.add(js)
    js.last_seen = now


SMALL_WORDS = {"of", "and", "the", "at", "for", "in", "de", "la"}
KEEP_UPPER = {"ISD", "CISD", "USD", "SD", "MS", "HS", "ES", "JH", "STEM", "AP", "IB", "K-8", "K-12", "II", "III", "IV", "CUSD", "PS"}


def smart_title(s: str | None) -> str | None:
    """'DUNBAR MIDDLE SCHOOL' -> 'Dunbar Middle School'. Mixed-case names are left as published."""
    if not s:
        return s
    s = re.sub(r"\s+", " ", s).strip()
    if not s.isupper():
        return s
    words = []
    for i, w in enumerate(s.split(" ")):
        if w in KEEP_UPPER or re.fullmatch(r"[A-Z]\.?|\d+[A-Z]*", w):
            words.append(w)
        elif i and w.lower() in SMALL_WORDS:
            words.append(w.lower())
        else:
            words.append(w.capitalize())
    return " ".join(words)


def upsert_raw_job(db: Session, raw: RawJob, profile: dict, stats: dict, seen_this_run: set) -> tuple[Job, bool]:
    """Returns (job, created)."""
    raw.employer_name = smart_title(raw.employer_name)
    raw.school_name = smart_title(raw.school_name)
    raw.title = re.sub(r"\s+", " ", raw.title).strip()
    raw.city = smart_title(raw.city)
    district = get_or_create_district(db, raw.employer_name, raw.state, raw.city, raw.source_url)
    school = get_or_create_school(db, raw.school_name, district, raw)
    key = canonical_key(raw)
    job = find_existing(db, raw, key, district)
    created = job is None
    now = datetime.utcnow()
    if created:
        job = Job(canonical_key=key, job_title=raw.title, date_discovered=now)
        db.add(job)
    elif job.id in seen_this_run:
        stats["duplicates_removed"] = stats.get("duplicates_removed", 0) + 1
    else:
        # Seen before via another source -> counts as a merged duplicate if the source is new
        known = {s.url for s in job.sources}
        if raw.source_url not in known and raw.official_url not in known:
            stats["duplicates_removed"] = stats.get("duplicates_removed", 0) + 1

    subjects = classify_subjects(" ".join(filter(None, [raw.title, raw.extra.get("categories")])))
    job.canonical_key = key
    job.job_title = raw.title
    job.external_job_id = raw.external_id or job.external_job_id
    job.subjects = subjects
    job.subject = primary_subject(subjects)
    job.grade_level = classify_grade(" ".join(filter(None, [raw.title, raw.school_name, raw.employment_type]))) \
        or classify_grade(raw.description or "") or job.grade_level
    job.employer_name = raw.employer_name
    job.district_id = district.id if district else None
    job.school_id = school.id if school else None
    job.city, job.state = raw.city or job.city, raw.state or job.state
    job.zip = raw.zip or job.zip
    job.latitude, job.longitude = raw.latitude or job.latitude, raw.longitude or job.longitude
    job.employment_type = raw.employment_type
    # Official data wins over earlier values; missing values never overwrite known ones.
    for f in ("salary_min", "salary_max", "salary_text", "date_posted", "closing_date", "closing_text",
              "description", "requirements", "certification_requirements"):
        v = getattr(raw, f)
        target = "job_description" if f == "description" else f
        if v:
            setattr(job, target, v)
    job.official_job_url = raw.official_url or job.official_job_url
    job.application_url = raw.application_url or job.application_url
    job.last_seen_in_scan = now
    cert = re.findall(r"[^.\n]*(certif|licens|credential|endorse)[^.\n]*", job.job_description or "", re.I)
    if cert and not job.certification_requirements:
        job.certification_requirements = "\n".join(
            m.strip() for m in re.findall(r"[^.\n]*(?:certif|licens|credential|endorse)[^.\n]*", job.job_description, re.I)[:5])
    db.flush()

    # Sources
    _add_source(db, job, raw.source_url, raw, raw.source_type in ("OFFICIAL_ATS", "OFFICIAL_DISTRICT"))
    if raw.official_url and raw.official_url != raw.source_url:
        _add_source(db, job, raw.official_url, raw, True)

    # Status
    status, reason = decide_job_status(closing=job.closing_date, until_filled=raw.until_filled, official_http=None,
                                       official_text=None, listed_in_feed=raw.listed_in_feed, posted=job.date_posted)
    job.job_status, job.status_reason = status, reason
    job.last_verified = now
    job.verification_status = VERIFIED if raw.source_type in ("OFFICIAL_ATS", "OFFICIAL_DISTRICT") else PARTIAL

    # Field-level evidence (value, source_url, source_type, verification_status, verified_at)
    st = raw.source_type
    fv = VERIFIED if st in ("OFFICIAL_ATS", "OFFICIAL_DISTRICT") else PARTIAL
    ev = dict(job.field_evidence or {})
    ev["job_title"] = evidence(raw.title, raw.source_url, st, fv)
    ev["employer"] = evidence(raw.employer_name, raw.source_url, st, fv if raw.employer_name else "UNKNOWN")
    ev["school"] = evidence(raw.school_name, raw.source_url, st, fv if raw.school_name else "UNKNOWN")
    ev["location"] = evidence(", ".join(filter(None, [raw.city, raw.state])), raw.source_url, st,
                              fv if raw.state else "UNKNOWN",
                              note="City from district registry" if raw.feed_key and raw.feed_key.startswith("applitrack") else None)
    ev["salary"] = evidence(job.salary_text or (f"${job.salary_min:,.0f}-${job.salary_max:,.0f}" if job.salary_max else None),
                            raw.source_url, st, fv if (job.salary_text or job.salary_max) else "UNKNOWN")
    ev["date_posted"] = evidence(job.date_posted.isoformat() if job.date_posted else None, raw.source_url, st,
                                 fv if job.date_posted else "UNKNOWN")
    ev["deadline"] = evidence(raw.closing_text or (job.closing_date.isoformat() if job.closing_date else None),
                              raw.source_url, st, fv if (raw.closing_text or job.closing_date) else "UNKNOWN")
    ev["application_url"] = evidence(job.application_url, raw.source_url, st, fv if job.application_url else "UNKNOWN")
    ev["job_status"] = evidence(status, raw.source_url, st, fv, note=reason)
    job.field_evidence = ev

    # Contacts (only people/addresses actually published by the source)
    for rc in raw.contacts:
        conf = rc.confidence
        # A department name ("Human Resources") or placeholder is never a HIGH-confidence named addressee.
        if rc.full_name and (contact_svc.PLACEHOLDER_NAME_RE.match(rc.full_name.strip())
                             or contact_svc.DEPARTMENT_NAME_RE.search(rc.full_name)):
            conf = "MEDIUM"
        rc.confidence = conf
        c = contact_svc.upsert_contact(
            db, full_name=rc.full_name, title=rc.title, organization=raw.employer_name, email=rc.email,
            phone=rc.phone, source_url=rc.evidence_url or raw.source_url,
            district_id=job.district_id, school_id=job.school_id, page_text=raw.page_text, source_type=st)
        if c:
            contact_svc.link(db, job, c, rc.relationship, rc.confidence, rc.evidence_url, rc.evidence_text)

    # J-1
    text = " ".join(filter(None, [job.job_description, job.requirements]))
    v_status, v_ev = j1_svc.assess_vacancy_text(text, job.official_job_url or raw.source_url)
    d_status = district.j1_status if district else None
    job.j1_status = j1_svc.combine(v_status, d_status)
    j_ev = [e for e in (job.j1_evidence or []) if not e.get("kind", "").startswith("vacancy")] + v_ev
    if district and district.j1_evidence and d_status and d_status != "UNKNOWN":
        known = {(e.get("url"), e.get("quote")) for e in j_ev}
        j_ev += [dict(e, kind=e.get("kind", "employer")) for e in district.j1_evidence
                 if (e.get("url"), e.get("quote")) not in known]
    job.j1_evidence = j_ev
    db.flush()
    db.refresh(job)

    m = score_job(job, profile)
    job.match_score, job.match_breakdown = m["score"], m
    job.needs_review = not job.date_posted or not job.state
    if created:
        db.add(JobVerification(job_id=job.id, check_type="SOURCE", target="vacancy", result="DISCOVERED",
                               detail=f"Discovered via {raw.source_name}", url=raw.source_url))
    seen_this_run.add(job.id)
    return job, created


def rescore_all(db: Session) -> int:
    profile = profile_dict(db)
    n = 0
    for job in db.scalars(select(Job)):
        m = score_job(job, profile)
        job.match_score, job.match_breakdown = m["score"], m
        n += 1
    db.commit()
    return n
