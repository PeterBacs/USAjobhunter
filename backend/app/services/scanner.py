"""Scan orchestration. Every number shown in SCAN COMPLETED comes from rows written here."""
import logging
import re
import threading
import traceback
from datetime import date, datetime

from bs4 import BeautifulSoup
from sqlalchemy import func, select

from ..config import SCHOOLSPRING_PAGE_SIZE, SCHOOLSPRING_PAGES_FULL, SCHOOLSPRING_PAGES_QUICK
from ..db import SessionLocal
from ..models import (Application, ApplicationEvent, Contact, District, J1Program, Job, JobContact, JobSource,
                      JobVerification, ScanLog, ScanRun, ScanSource, School)
from . import alerts as alert_svc
from . import contacts as contact_svc
from . import j1 as j1_svc
from .connectors import applitrack, edjoin, jsonld, k12jobspot, schoolspring
from .http import PoliteClient
from .ingest import profile_dict, upsert_raw_job
from .matching import score_job
from .taxonomy import SEARCH_KEYWORDS_FULL, SEARCH_KEYWORDS_QUICK, STATES
from .verification import CLOSED_PHRASES, decide_job_status

_lock = threading.Lock()
_running: dict[int, threading.Event] = {}


def is_busy() -> bool:
    return any(not e.is_set() for e in _running.values())


def cancel(run_id: int):
    ev = _running.get(run_id)
    if ev:
        ev.set()


def start(kind: str, params: dict | None = None, trigger: str = "MANUAL") -> int:
    db = SessionLocal()
    run = ScanRun(kind=kind, params=params or {}, trigger=trigger, status="RUNNING", progress="Queued")
    db.add(run)
    db.commit()
    rid = run.id
    db.close()
    stop = threading.Event()
    _running[rid] = stop
    t = threading.Thread(target=_run, args=(rid, kind, params or {}, stop), daemon=True, name=f"scan-{rid}")
    t.start()
    return rid


def run_sync(kind: str, params: dict | None = None, trigger: str = "SCHEDULED") -> int:
    db = SessionLocal()
    run = ScanRun(kind=kind, params=params or {}, trigger=trigger, status="RUNNING")
    db.add(run)
    db.commit()
    rid = run.id
    db.close()
    stop = threading.Event()
    _running[rid] = stop
    _run(rid, kind, params or {}, stop)
    return rid


def _run(run_id: int, kind: str, params: dict, stop: threading.Event):
    with _lock:  # one scan at a time; keeps rate limiting honest
        db = SessionLocal()
        run = db.get(ScanRun, run_id)

        def log_fetch(res, source_name):
            row = ScanLog(scan_run_id=run_id, source_name=source_name, url=res.url[:1500], http_status=res.status,
                          crawl_status=res.crawl_status, error=res.error, elapsed_ms=res.elapsed_ms)
            db.add(row)
            db.flush()
            res.log_row = row
            return row

        client = PoliteClient(log_fn=log_fetch)
        try:
            if kind in ("QUICK", "FULL"):
                stats = _discover(db, run, client, kind, params, stop)
            elif kind in ("VERIFY_JOBS", "CLOSED_CHECK"):
                stats = verify_jobs(db, run, client, stop, only_tracked=(kind == "CLOSED_CHECK" and params.get("tracked_only")))
            elif kind == "VERIFY_CONTACTS":
                stats = verify_contacts(db, run, client, stop)
            elif kind == "J1":
                stats = j1_research(db, run, client, stop)
            elif kind == "ENG":
                from . import engineering
                stats = engineering.scan_all(db, client, stop=stop.is_set,
                                             progress=lambda i, n, label: _progress(db, run, f"Engineering jobs {i}/{n}: {label}"))
                stats["sources_checked"] = db.scalar(select(func.count()).select_from(ScanLog).where(ScanLog.scan_run_id == run.id))
            elif kind == "H1B":
                from . import h1b
                stats = h1b.check_all(db, client, stop=stop.is_set,
                                      progress=lambda i, n, name: _progress(db, run, f"H-1B employers {i}/{n}: {name}"))
                stats["sources_checked"] = db.scalar(select(func.count()).select_from(ScanLog).where(ScanLog.scan_run_id == run.id))
            else:
                raise ValueError(f"Unknown scan kind {kind}")
            run.stats = stats
            run.status = "CANCELLED" if stop.is_set() else "COMPLETED"
            run.progress = "Done"
        except Exception as e:
            db.rollback()
            run = db.get(ScanRun, run_id)
            run.status = "FAILED"
            run.error = f"{e}\n{traceback.format_exc()[-2000:]}"
        finally:
            run.finished_at = datetime.utcnow()
            db.commit()
            client.close()
            db.close()
            stop.set()


def _progress(db, run, msg):
    run.progress = msg[:500]
    db.commit()


# ------------------------------------------------------------------ discovery
def _discover(db, run, client, kind, params, stop) -> dict:
    profile = profile_dict(db)
    stats = {"duplicates_removed": 0}
    seen_this_run: set[int] = set()
    new_job_ids: list[int] = []
    potential = 0
    feeds_ok: dict[str, set] = {}   # feed_key -> job ids seen
    states_filter = [s.upper() for s in params.get("states", []) if s]
    sources = db.scalars(select(ScanSource).where(ScanSource.enabled.is_(True)).order_by(ScanSource.tier, ScanSource.id)).all()
    if states_filter:
        # Multi-state sources always run (their results are filtered by state below); district boards only in-state.
        sources = [s for s in sources if s.connector in ("schoolspring", "edjoin", "k12jobspot") or (s.state in states_filter)]
    if kind == "QUICK":
        # Quick scan: nationwide SchoolSpring (few pages) + official district boards.
        pages, keywords = SCHOOLSPRING_PAGES_QUICK, SEARCH_KEYWORDS_QUICK
    else:
        pages, keywords = SCHOOLSPRING_PAGES_FULL, SEARCH_KEYWORDS_FULL
    if params.get("keywords"):
        keywords = params["keywords"]

    for i, src in enumerate(sources, 1):
        if stop.is_set():
            break
        _progress(db, run, f"[{i}/{len(sources)}] {src.name}")
        try:
            if src.connector == "applitrack":
                raws, info = applitrack.scan(client, src)
            elif src.connector == "schoolspring":
                # A state-focused board (e.g. CERRA South Carolina) searches its own state(s) in depth.
                locs = [STATES[s] for s in states_filter if s in STATES] or (src.config or {}).get("locations") or None
                if states_filter and (src.config or {}).get("locations") and not set(states_filter) & set(src.config.get("state_codes", [])):
                    raws, info = [], {"feed_ok": True, "parser_status": "SKIPPED", "errors": []}
                else:
                    raws, info = schoolspring.scan(client, src, keywords=keywords, pages=pages,
                                                   size=SCHOOLSPRING_PAGE_SIZE, stop_flag=stop.is_set, locations=locs)
            elif src.connector == "edjoin":
                if states_filter and "CA" not in states_filter:
                    raws, info = [], {"feed_ok": True, "parser_status": "SKIPPED", "errors": []}
                else:
                    raws, info = edjoin.scan(client, src, keywords=keywords, pages=2 if kind == "QUICK" else 4,
                                             stop_flag=stop.is_set)
            elif src.connector == "k12jobspot":
                raws, info = k12jobspot.scan(client, src, max_new=300 if kind == "QUICK" else 1500, stop_flag=stop.is_set)
                if info.get("new_last_max_id"):
                    src.config = dict(src.config or {}, last_max_id=info["new_last_max_id"])
            elif src.connector == "jsonld_page":
                raws, info = jsonld.scan(client, src)
            else:
                raws, info = [], {"error": f"unknown connector {src.connector}", "feed_ok": False}
        except Exception as e:
            raws, info = [], {"error": f"{type(e).__name__}: {e}", "feed_ok": False, "parser_status": "PARSE_ERROR"}

        if states_filter:
            raws = [r for r in raws if (r.state or "").upper() in states_filter]
        potential += len(raws)
        ids = set()
        for raw in raws:
            job, created = upsert_raw_job(db, raw, profile, stats, seen_this_run)
            ids.add(job.id)
            if created:
                new_job_ids.append(job.id)
        # Mark the source's log rows with parser outcome
        log_row = info.get("log")
        if log_row is not None:
            log_row.parser_status = info.get("parser_status")
            log_row.jobs_discovered = len(raws)
        src.last_scanned = datetime.utcnow()
        src.last_status = "OK" if info.get("feed_ok") else ("ROBOTS_BLOCKED" if info.get("crawl_status") == "ROBOTS_BLOCKED" else "ERROR")
        errs = info.get("errors") or ([info["error"]] if info.get("error") else [])
        src.last_error = "; ".join(errs)[:2000] if errs else None
        src.last_jobs_found = len(raws)
        if info.get("feed_ok") and info.get("feed_key") and src.connector != "schoolspring":
            feeds_ok[info["feed_key"]] = ids
        db.commit()

    # Closed-job detection for complete official feeds: a job that was on the board and is gone -> CLOSED.
    closed = 0
    for feed_key, ids in feeds_ok.items():
        slug = feed_key.split(":", 1)[1]
        prefix = f"https://www.applitrack.com/{slug}/" if feed_key.startswith("applitrack:") else None
        if not prefix:
            continue
        stale = db.scalars(select(Job).join(JobSource).where(
            JobSource.url.like(prefix + "%"), Job.job_status != "CLOSED", Job.is_demo.is_(False))).unique().all()
        for job in stale:
            if job.id not in ids:
                _close_job(db, job, "No longer listed on the official district job board", None)
                closed += 1
    db.commit()

    # Confirm new contact emails with each school's mail server (no email sent). Only confirmed
    # addresses are ever shown, so this runs before the scan reports completion.
    unchecked = db.scalars(select(Contact).where(Contact.deleted_at.is_(None), Contact.email.is_not(None), Contact.mailbox_status.is_(None))).all()
    if unchecked and not stop.is_set():
        _progress(db, run, f"Confirming {len(unchecked)} contact emails")
        contact_svc.check_mailboxes(db, unchecked,
                                    progress=lambda d, n: _progress(db, run, f"Confirming contact emails {d}/{n}"))
    # Official websites for districts seen in this scan that don't have one yet (confirmed by page title).
    from . import websites
    touched_districts = {d for (d,) in db.execute(select(Job.district_id).where(Job.id.in_(list(seen_this_run)))) if d} if seen_this_run else set()
    missing = db.scalars(select(District).where(District.id.in_(touched_districts), District.website.is_(None))).all()[:80]
    for i, d in enumerate(missing, 1):
        if stop.is_set():
            break
        if i % 5 == 1:
            _progress(db, run, f"Finding official websites {i}/{len(missing)}")
        websites.find_district_website(db, client, d)
    alert_svc.evaluate(db, new_job_ids)
    _queue_outbox(db, run)
    live = select(Job).where(Job.is_demo.is_(False))
    touched = list(seen_this_run)
    verified_math = db.scalar(select(func.count()).select_from(Job).where(
        Job.id.in_(touched), Job.job_status == "ACTIVE", Job.verification_status == "VERIFIED")) if touched else 0
    with_contacts = db.scalar(select(func.count(func.distinct(JobContact.job_id))).join(Contact).where(
        JobContact.job_id.in_(touched), Contact.verification_status == "VERIFIED")) if touched else 0
    confirmed_j1 = db.scalar(select(func.count()).select_from(Job).where(
        Job.id.in_(touched), Job.j1_status.in_(["CONFIRMED_J1_VACANCY", "CONFIRMED_J1_EMPLOYER"]))) if touched else 0
    states_with_jobs = db.scalar(select(func.count(func.distinct(Job.state))).where(Job.id.in_(touched))) if touched else 0
    sources_checked = db.scalar(select(func.count()).select_from(ScanLog).where(ScanLog.scan_run_id == run.id))
    ss_used = any(s.connector == "schoolspring" for s in sources)
    return {
        "coverage": ("Nationwide (all 50 states + DC)" if ss_used and not states_filter
                     else f"States: {', '.join(states_filter)}" if states_filter else "District boards only")
                    + " · " + ", ".join(sorted({{"schoolspring": "SchoolSpring", "edjoin": "EDJOIN (CA)", "k12jobspot": "K12JobSpot",
                                                 "jsonld_page": "official career pages"}.get(s.connector, "") for s in sources
                                                if s.connector != "applitrack"} - {""}))
                    + f" + {sum(1 for s in sources if s.connector == 'applitrack')} Frontline district boards",
        "states_searched": "50 + DC" if (ss_used and not states_filter) else len(states_filter or {s.state for s in sources if s.state}),
        "states_with_results": states_with_jobs,
        "sources_checked": sources_checked,
        "potential_jobs_discovered": potential,
        "unique_jobs": len(seen_this_run),
        "new_jobs": len(new_job_ids),
        "verified_math_jobs": verified_math,
        "duplicates_removed": stats.get("duplicates_removed", 0),
        "closed_jobs_detected": closed,
        "jobs_with_verified_contacts": with_contacts,
        "confirmed_j1_opportunities": confirmed_j1,
        "keywords": keywords,
    }


def _close_job(db, job: Job, reason: str, url: str | None, http_status: int | None = None):
    was = job.job_status
    job.job_status, job.status_reason = "CLOSED", reason
    job.last_verified = datetime.utcnow()
    db.add(JobVerification(job_id=job.id, check_type="STATUS", target="vacancy", result="CLOSED", detail=reason,
                           url=url, http_status=http_status))
    for app in db.scalars(select(Application).where(Application.job_id == job.id)):
        db.add(ApplicationEvent(application_id=app.id, event_type="STATUS_CHANGE",
                                description=f"Vacancy status changed {was} -> CLOSED: {reason}"))
        if app.application_status in ("DISCOVERED", "SAVED", "APPLYING"):
            app.application_status = "POSITION_CLOSED"


# ------------------------------------------------------------------ job verification / closed check
def verify_jobs(db, run, client, stop, only_tracked=False) -> dict:
    q = select(Job).where(Job.is_demo.is_(False), Job.job_status != "CLOSED")
    if only_tracked:
        q = q.where((Job.is_saved.is_(True)) | Job.id.in_(select(Application.job_id).where(Application.deleted_at.is_(None))))
    jobs = db.scalars(q).all()
    # Jobs you applied to are checked first.
    applied_ids = set(db.scalars(select(Application.job_id).where(Application.deleted_at.is_(None))))
    jobs.sort(key=lambda j: j.id not in applied_ids)
    checked = active = closed = unknown = 0
    for i, job in enumerate(jobs, 1):
        if stop.is_set():
            break
        if i % 10 == 1:
            _progress(db, run, f"Verifying {i}/{len(jobs)}")
        ss = next((s for s in job.sources if "schoolspring.com/jobs?jobid=" in s.url), None)
        status, reason, http, url = None, None, None, job.official_job_url
        if ss:
            jid = ss.url.split("jobid=")[-1]
            http, detail = schoolspring.recheck(client, jid)
            url = schoolspring.detail_api(jid)
            ss_status = ((detail or {}).get("jobInfo") or {}).get("jobStatusID")
            if http in (404, 410) or (http and 200 <= http < 300 and not (detail and detail.get("jobInfo"))):
                status, reason = "CLOSED", "Posting no longer returned by the employer's SchoolSpring board"
            elif ss_status is not None and ss_status != schoolspring.PUBLIC_STATUS:
                # SchoolSpring keeps closed / filled postings in its API but hides them from job seekers.
                status, reason = "CLOSED", f"SchoolSpring no longer shows this posting to applicants (closed or filled; status {ss_status})"
            elif detail and detail.get("jobInfo"):
                raw = schoolspring.build_job(detail, jid)
                status, reason = decide_job_status(closing=raw.closing_date, until_filled=raw.until_filled,
                                                   official_http=http, official_text=None, listed_in_feed=True,
                                                   posted=raw.date_posted)
        elif job.official_job_url:
            res = client.get(job.official_job_url, source_name="Job verification")
            http = res.status
            text = BeautifulSoup(res.text, "lxml").get_text(" ", strip=True) if res.ok else None
            if res.crawl_status == "ROBOTS_BLOCKED":
                status, reason = "UNKNOWN", "Official page disallows automated checks (robots.txt) - verify manually"
            else:
                status, reason = decide_job_status(closing=job.closing_date, until_filled=False, official_http=http,
                                                   official_text=text, listed_in_feed=None, posted=job.date_posted)
        if not status:
            status, reason = "UNKNOWN", "No official source reachable"
        checked += 1
        if status == "CLOSED":
            _close_job(db, job, reason, url, http)
            closed += 1
        else:
            job.job_status, job.status_reason = status, reason
            job.last_verified = datetime.utcnow()
            db.add(JobVerification(job_id=job.id, check_type="STATUS", target="vacancy", result=status,
                                   detail=reason, url=url, http_status=http))
            active += status == "ACTIVE"
            unknown += status in ("UNKNOWN", "POSSIBLY_ACTIVE")
        db.commit()
    # Deadline sweep (no network needed)
    for job in db.scalars(select(Job).where(Job.closing_date < date.today(), Job.job_status != "CLOSED",
                                            Job.is_demo.is_(False))):
        _close_job(db, job, f"Closing date {job.closing_date} has passed", job.official_job_url)
        closed += 1
    db.commit()
    return {"jobs_checked": checked, "active": active, "closed_jobs_detected": closed, "unknown_or_possible": unknown,
            "sources_checked": db.scalar(select(func.count()).select_from(ScanLog).where(ScanLog.scan_run_id == run.id))}


# ------------------------------------------------------------------ contact verification
PRINCIPAL_PATTERNS = [
    re.compile(r"Principal\s*[:\-–]\s*((?:Dr\.|Mr\.|Mrs\.|Ms\.)?\s*[A-Z][a-zA-Z'\-]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-zA-Z'\-]+){1,2})"),
    re.compile(r"((?:Dr\.|Mr\.|Mrs\.|Ms\.)?\s*[A-Z][a-zA-Z'\-]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-zA-Z'\-]+){1,2})\s*[,|\-–]\s*Principal\b"),
    re.compile(r"\bPrincipal\s+((?:Dr\.|Mr\.|Mrs\.|Ms\.)\s*[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)?)"),
]
BAD_NAME = re.compile(r"\b(Assistant|Associate|Vice|School|Meet|Our|The|Message|From|Welcome|Office|Contact|Staff|Directory)\b")


def find_principal_on_page(text: str) -> tuple[str | None, str | None, str | None]:
    """Return (name, email, quote) only when a principal is explicitly named on the page."""
    for rx in PRINCIPAL_PATTERNS:
        for m in rx.finditer(text):
            name = re.sub(r"\s+", " ", m.group(1)).strip()
            if BAD_NAME.search(name) or len(name.split()) < 2:
                continue
            before = text[max(0, m.start() - 20):m.start()]
            if re.search(r"(assistant|associate|vice)\s*$", before, re.I):
                continue
            window = text[m.start(): m.end() + 200]
            em = re.search(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", window)
            quote = re.sub(r"\s+", " ", text[max(0, m.start() - 40): m.end() + 60])
            return name, (em.group(0).lower() if em else None), quote
    return None, None, None


def research_school_principal(db, client, school: School) -> Contact | None:
    url = school.staff_directory_url or school.website
    if not url:
        return None
    res = client.get(url, source_name=f"Principal lookup - {school.name}")
    if not res.ok:
        return None
    text = BeautifulSoup(res.text, "lxml").get_text(" ", strip=True)
    name, email, quote = find_principal_on_page(text)
    if not name:
        return None
    c = contact_svc.upsert_contact(db, full_name=name, title="Principal", organization=school.name, email=email,
                                   phone=None, source_url=url, district_id=school.district_id, school_id=school.id,
                                   page_text=text, source_type="OFFICIAL_DISTRICT")
    if c:
        c.reviewer_note = f"Found on school page: \"{quote}\""
        for job in db.scalars(select(Job).where(Job.school_id == school.id, Job.is_demo.is_(False))):
            # Directory listing proves the role, not that this person handles the vacancy -> MEDIUM.
            contact_svc.link(db, job, c, "SCHOOL_PRINCIPAL", "MEDIUM", url, quote)
    return c


def _queue_outbox(db, run):
    """Prepare application emails for new openings (sent only after the user approves them)."""
    try:
        from . import outbox
        n = outbox.queue_new(db)
        if n:
            _progress(db, run, f"{n} application email(s) waiting for your approval in the Outbox")
    except Exception:
        db.rollback()
        logging.getLogger("jobhunter").exception("Outbox queue failed")


def verify_contacts(db, run, client, stop) -> dict:
    checked = still = lost = principals = 0
    # 1) Re-confirm stored contacts against their source
    contacts = db.scalars(select(Contact).where(Contact.deleted_at.is_(None), Contact.source_url.is_not(None))).all()
    for i, c in enumerate(contacts, 1):
        if stop.is_set():
            break
        if i % 10 == 1:
            _progress(db, run, f"Contacts {i}/{len(contacts)}")
        text = None
        if "schoolspring.com/jobs?jobid=" in (c.source_url or ""):
            jid = c.source_url.split("jobid=")[-1]
            http, detail = schoolspring.recheck(client, jid)
            if detail and detail.get("jobInfo"):
                ji = detail["jobInfo"]
                text = " ".join(str(ji.get(k) or "") for k in ("contactFirstName", "contactLastName", "contactEmail",
                                                               "contactPhone", "contactTitle", "jobDescription"))
        else:
            res = client.get(c.source_url, source_name="Contact verification")
            if res.ok:
                text = BeautifulSoup(res.text, "lxml").get_text(" ", strip=True)
        checked += 1
        if text is None:
            c.reviewer_note = "Source could not be re-checked on " + date.today().isoformat()
            continue
        present = (not c.full_name or c.full_name.split()[-1].lower() in text.lower()) and \
                  (not c.email or c.email.lower() in text.lower())
        if present:
            c.verification_status = "VERIFIED" if c.source_type in ("OFFICIAL_ATS", "OFFICIAL_DISTRICT", "EMPLOYER_SITE") else "PARTIALLY_VERIFIED"
            c.verified_at = datetime.utcnow()
            still += 1
        else:
            c.verification_status = "CONFLICTING"
            c.reviewer_note = "Name/email no longer found on the source page - affiliation may have changed"
            if c.email_status == "VERIFIED":
                c.email_status = "PUBLISHED_ELSEWHERE"
            lost += 1
        db.commit()
    # 2) Mailbox check with each school's mail server (no email is sent; cached 7 days)
    mb = {"EXISTS": 0, "NOT_FOUND": 0, "CATCH_ALL": 0, "NO_MAIL_SERVER": 0, "UNKNOWN": 0}
    from . import mailcheck
    with_email = db.scalars(select(Contact).where(Contact.deleted_at.is_(None), Contact.email.is_not(None))).all()
    due = [c for c in with_email if mailcheck.needs_check(c.mailbox_checked_at)]
    if due and not stop.is_set():
        contact_svc.check_mailboxes(db, due, progress=lambda d, n: _progress(db, run, f"Checking mailboxes {d}/{n}"))
    for c in with_email:
        mb[c.mailbox_status or "UNKNOWN"] = mb.get(c.mailbox_status or "UNKNOWN", 0) + 1
    # 3) Official district websites still missing (confirmed by the page naming the district)
    from . import websites
    web = websites.find_missing_websites(db, client, stop=stop.is_set,
                                         progress=lambda i, n: _progress(db, run, f"Finding official websites {i}/{n}"))
    # 4) Principal discovery where a school website / staff directory is known
    for school in db.scalars(select(School).where((School.staff_directory_url.is_not(None)) | (School.website.is_not(None)))):
        if stop.is_set():
            break
        if research_school_principal(db, client, school):
            principals += 1
        db.commit()
    _queue_outbox(db, run)
    return {"contacts_checked": checked, "still_verified": still, "no_longer_found": lost,
            "principals_found": principals, "mailboxes_confirmed": mb["EXISTS"],
            "official_websites_found": web["websites_found"],
            "mailboxes_not_existing": mb["NOT_FOUND"] + mb["NO_MAIL_SERVER"],
            "mailboxes_unconfirmable": mb["CATCH_ALL"] + mb["UNKNOWN"],
            "sources_checked": db.scalar(select(func.count()).select_from(ScanLog).where(ScanLog.scan_run_id == run.id))}


# ------------------------------------------------------------------ J-1 research
def j1_research(db, run, client, stop) -> dict:
    updated = 0
    # Apply verified DISTRICT_EMPLOYER records from the sponsor database
    for prog in db.scalars(select(J1Program).where(J1Program.organization_type == "DISTRICT_EMPLOYER",
                                                   J1Program.district_id.is_not(None))):
        d = db.get(District, prog.district_id)
        if d and prog.verification_status == "VERIFIED":
            d.j1_status = "CONFIRMED_J1_EMPLOYER"
            ev = {"url": prog.teacher_program_url or prog.source_url, "quote": prog.evidence_quote or prog.organization,
                  "kind": "employer_positive", "checked_at": (prog.last_verified or datetime.utcnow()).isoformat()}
            if ev not in (d.j1_evidence or []):
                d.j1_evidence = (d.j1_evidence or []) + [ev]
    db.commit()
    districts = db.scalars(select(District).where((District.website.is_not(None)) | (District.careers_url.is_not(None)))).all()
    for i, d in enumerate(districts, 1):
        if stop.is_set():
            break
        _progress(db, run, f"J-1 research {i}/{len(districts)}: {d.name}")
        status, ev = j1_svc.research_district_site(client, d)
        if ev:
            d.j1_evidence = ev
        if status:
            d.j1_status = status
            updated += 1
        elif d.j1_status in (None, "UNKNOWN"):
            d.j1_status = "UNKNOWN"
        db.commit()
    # Re-derive every job's J-1 status and score
    profile = profile_dict(db)
    for job in db.scalars(select(Job).where(Job.is_demo.is_(False))):
        text = " ".join(filter(None, [job.job_description, job.requirements]))
        v_status, v_ev = j1_svc.assess_vacancy_text(text, job.official_job_url)
        d_status = job.district.j1_status if job.district else None
        job.j1_status = j1_svc.combine(v_status, d_status)
        job.j1_evidence = v_ev + ((job.district.j1_evidence or []) if job.district and d_status not in (None, "UNKNOWN") else [])
        m = score_job(job, profile)
        job.match_score, job.match_breakdown = m["score"], m
    db.commit()
    alert_svc.evaluate(db, [])
    return {"districts_researched": len(districts), "districts_with_evidence": updated,
            "confirmed_j1_opportunities": db.scalar(select(func.count()).select_from(Job).where(
                Job.is_demo.is_(False), Job.j1_status.in_(["CONFIRMED_J1_VACANCY", "CONFIRMED_J1_EMPLOYER"]))),
            "sources_checked": db.scalar(select(func.count()).select_from(ScanLog).where(ScanLog.scan_run_id == run.id))}
