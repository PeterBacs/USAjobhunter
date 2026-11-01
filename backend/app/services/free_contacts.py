"""Free, fully automatic principal / HR email finder.

For a job, the app walks the district's (and school's) OFFICIAL website the way a person would - home page ->
the school's page -> staff / directory / administration / contact pages - and on each page:
  1. looks for "Principal: Jane Smith ... jsmith@district.org" with simple patterns (no AI), then
  2. if that fails and a Gemini key is set (free tier, no Google Search needed), asks Gemini to read the page and
     pick out the principal's / HR contact's name and email.
Every candidate then goes through ai_contacts.verify_and_save: the address must be printed on that official page,
the person's name must be on it, and the email must be on the school's / district's domain. Nothing is guessed.
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select

from ..models import AILookup, Job
from . import contacts as contact_svc
from .ai_contacts import _official_for, _reg_domain, page_text_from_html, verify_and_save
from .websites import domain_matches_name

log = logging.getLogger("jobhunter.finder")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("JH_GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_PAGES = int(os.getenv("JH_FINDER_MAX_PAGES", "15"))
HR_TITLE = re.compile(r"human resources|\bhr\b|personnel|recruit|talent|staffing|employment", re.I)
MAX_LOOKUPS_PER_RUN = int(os.getenv("JH_FINDER_MAX_PER_RUN", "60"))
REPEAT_DAYS = 30
EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LINK_WORDS = re.compile(r"staff|directory|administrat|admin\b|leadership|contact|about|principal|faculty|our[- ]?school|"
                        r"meet|office|personnel|human[- ]?resources|\bhr\b|schools?\b|campus", re.I)
GENERIC = {"school", "schools", "high", "middle", "elementary", "junior", "senior", "academy", "the", "of", "and", "jr",
           "sr", "hs", "ms", "es", "campus", "center", "county", "public", "district", "isd", "unified", "charter"}

_gemini_off = False   # set after a quota / auth error so one run doesn't keep failing


def _school_tokens(name: str | None) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(t) > 2 and t not in GENERIC]


LEVELS = {"elementary": "elementary", "primary": "elementary", "middle": "middle", "junior": "middle",
          "intermediate": "middle", "high": "high", "senior": "high"}


def _level_ok(school: str | None, text: str) -> bool:
    """'East Iredell Middle' must not match a page about 'East Elementary': when the school's name says its level,
    a page naming only other levels is rejected."""
    want = {LEVELS[w] for w in re.findall(r"[a-z]+", (school or "").lower()) if w in LEVELS}
    if not want:
        return True
    found = {LEVELS[w] for w in re.findall(r"[a-z]+", text.lower()) if w in LEVELS}
    return not found or bool(want & found)


def _links(html: str, base: str, allowed_reg: set[str]) -> list[tuple[str, str]]:
    out = []
    for a in BeautifulSoup(html, "lxml").select("a[href]"):
        href = urljoin(base, a.get("href", "").strip())
        p = urlparse(href)
        if p.scheme not in ("http", "https") or _reg_domain(p.netloc) not in allowed_reg:
            continue
        if re.search(r"\.(pdf|docx?|xlsx?|jpe?g|png|gif|zip|mp4)$", p.path, re.I):
            continue
        out.append((href.split("#")[0], (a.get_text(" ", strip=True) or "")[:120]))
    return out


def _ask_gemini(school: str | None, district: str | None, url: str, text: str) -> list[dict]:
    """Free Gemini model reads one page and returns the principal / HR contacts printed on it."""
    global _gemini_off
    if not GEMINI_KEY or _gemini_off:
        return []
    # Send the parts of the page around "principal" / "human resources" (keeps requests small).
    windows = [m.start() for m in re.finditer(r"principal|human resources|personnel|superintendent", text, re.I)][:12]
    excerpt = " … ".join(text[max(0, i - 600):i + 900] for i in windows) if windows else text[:6000]
    prompt = (f"Page: {url}\nSchool: {school or '(district-level posting)'}\nDistrict: {district or ''}\n\n"
              "From the page text below, list ONLY people whose email address is printed in the text: the principal of "
              "this exact school, and the district's human resources / recruiting contact. Copy names and emails exactly "
              "as printed. Do not guess or build addresses. Return an empty list if none are printed.\n\n"
              f"PAGE TEXT:\n{excerpt[:12000]}")
    schema = {"type": "OBJECT", "properties": {"contacts": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "role": {"type": "STRING", "enum": ["PRINCIPAL", "HR"]}, "name": {"type": "STRING"}, "title": {"type": "STRING"},
        "email": {"type": "STRING"}}, "required": ["role", "name", "email"]}}}, "required": ["contacts"]}
    try:
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                       headers={"x-goog-api-key": GEMINI_KEY},
                       json={"contents": [{"parts": [{"text": prompt}]}],
                             "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema,
                                                  "temperature": 0}}, timeout=60)
    except httpx.HTTPError as e:
        log.warning("Gemini unreachable: %s", type(e).__name__)
        return []
    if r.status_code in (401, 403, 429):
        _gemini_off = True
        log.warning("Gemini paused for this run (HTTP %s: %s)", r.status_code, r.json().get("error", {}).get("message", "")[:120])
        return []
    if r.status_code != 200:
        return []
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        return json.loads("".join(p.get("text", "") for p in parts)).get("contacts") or []
    except (KeyError, IndexError, ValueError):
        return []


def _pattern_candidates(text: str) -> list[dict]:
    from .scanner import find_principal_on_page
    name, email, _quote = find_principal_on_page(text)
    return [{"role": "PRINCIPAL", "name": name, "title": "Principal", "email": email}] if name and email else []


def find_contacts(db, client_http, job: Job) -> dict:
    """Walk the official site for this job's school and save confirmed principal / HR emails."""
    from .generators import _real_school_name
    school = _real_school_name(job)
    district = job.district.name if job.district else job.employer_name
    starts = [s for s in [job.school.website if job.school else None, job.district.website if job.district else None] if s]
    for s0 in list(starts):
        # A jobs / careers subsite isn't where staff are listed: also start from the district's main site.
        p0 = urlparse(s0)
        if re.match(r"(jobs|careers?|employment|apply|hr)\.", p0.netloc, re.I) or re.search(r"/(jobs|careers?|employment)", p0.path, re.I):
            starts.append(f"https://www.{_reg_domain(p0.netloc)}/")
    if not starts:
        return {"ok": False, "error": "The school's / district's official website isn't known yet.", "kept": [], "rejected": []}
    allowed = {_reg_domain(urlparse(s).netloc) for s in starts}
    tokens = _school_tokens(school)
    row = AILookup(job_id=job.id, school_id=job.school_id, district_id=job.district_id, status="RUNNING", detail="free finder")
    db.add(row)
    db.commit()
    queue, seen, pages = list(starts), set(), {}
    kept, rejected, have_principal = [], [], False
    while queue and len(seen) < MAX_PAGES and not have_principal:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        res = client_http.get(url, source_name=f"Contact finder - {district or ''}"[:120])
        if not res.ok or "html" not in (res.text[:500].lower() + "html"):
            continue
        final = res.final_url or url
        text = page_text_from_html(res.text)
        pages[url] = pages[final] = (text, final)
        low = text.lower()
        about_school = not tokens or any(t in low for t in tokens) or any(t in final.lower() for t in tokens)
        if about_school and EMAIL_IN_TEXT.search(text) and re.search(r"principal|human resources|personnel", low):
            cands = _pattern_candidates(text) or _ask_gemini(school, district, final, text)
            # HR only when the title on the page says so (staff lists are full of non-HR people).
            cands = [c for c in cands if c.get("role") != "HR" or HR_TITLE.search(str(c.get("title") or ""))]
            # A principal must be the principal of THIS school: the page itself is the school's page (title, address or
            # main heading name it), or the school's name is printed right next to the email.
            if tokens:
                soup0 = BeautifulSoup(res.text, "lxml")
                head = " ".join(filter(None, [final, soup0.title.get_text(" ") if soup0.title else "",
                                              " ".join(h.get_text(" ") for h in soup0.select("h1, h2")[:3])])).lower()
                head_ok = all(t in re.sub(r"[^a-z0-9]", "", head) or t in head for t in tokens) and _level_ok(school, head)

                def near(c):
                    i = low.find(str(c.get("email") or "").lower())
                    win = low[max(0, i - 400):i + 400]
                    return i >= 0 and all(t in win for t in tokens) and _level_ok(school, win)
                cands = [c for c in cands if c.get("role") != "PRINCIPAL" or head_ok or near(c)]
            for c in cands:
                c["source_url"] = final
            if cands:
                k, rj = verify_and_save(db, client_http, job, cands, how="Found on the official website by the app", pages=pages)
                kept += [x for x in k if x["email"] not in {y["email"] for y in kept}]
                rejected += rj
                have_principal = any(x["role"] == "PRINCIPAL" for x in kept)
        # Queue the most promising links: the school's own page first, then staff / directory / contact pages.
        scored = []
        for href, label in _links(res.text, final, allowed):
            if href in seen:
                continue
            hay = (label + " " + href).lower()
            score = (3 if tokens and any(t in hay for t in tokens) else 0) + (2 if LINK_WORDS.search(hay) else 0)
            if re.search(r"principal|staff|directory|administrat", hay):
                score += 1
            if score:
                scored.append((score, href))
        for _s, href in sorted(scored, key=lambda x: -x[0])[:8]:
            if href not in queue:
                queue.append(href)
        queue.sort(key=lambda h: -max([s for s, x in scored if x == h] or [0]))
    row.status = "DONE"
    row.result = {"kept": kept, "rejected": rejected, "pages": len(seen)}
    row.detail = f"free finder: {len(kept)} kept, {len(rejected)} rejected, {len(seen)} pages"
    db.commit()
    return {"ok": True, "kept": kept, "rejected": rejected, "pages_checked": len(seen)}


def run_for_new_jobs(db, client_http, since: datetime) -> dict:
    """After a scan: find contacts for new open vacancies that have no usable principal email yet."""
    from .applied import applied_job_ids
    from .generators import school_principal
    applied = applied_job_ids(db)
    cut = datetime.utcnow() - timedelta(days=REPEAT_DAYS)
    done = found = 0
    seen_keys = set()
    jobs = db.scalars(select(Job).where(Job.is_demo.is_(False), Job.job_status == "ACTIVE", Job.date_discovered >= since)
                      .order_by(Job.match_score.desc().nullslast())).all()
    for job in jobs:
        if done >= MAX_LOOKUPS_PER_RUN:
            break
        key = job.school_id or ("d", job.district_id)
        if job.id in applied or key in seen_keys or not job.district or not job.district.website:
            continue
        from .outbox import posted_recently
        if not posted_recently(job):
            continue   # only recent postings can get an application email, so only those are worth the lookup
        p, _ = school_principal(job)
        if p and contact_svc.email_usable(p):
            continue
        q = select(func.count()).select_from(AILookup).where(AILookup.created_at >= cut,
                                                             AILookup.detail.is_distinct_from("posting text read"))
        q = q.where(AILookup.school_id == job.school_id) if job.school_id else q.where(AILookup.district_id == job.district_id)
        if db.scalar(q):
            continue
        seen_keys.add(key)
        res = find_contacts(db, client_http, job)
        done += 1
        found += len(res.get("kept") or [])
    return {"finder_lookups": done, "finder_emails_confirmed": found}


def _has_mail_server(domain: str) -> bool:
    try:
        import dns.resolver
        return bool(dns.resolver.resolve(domain, "MX", lifetime=10))
    except Exception:
        return False


_domain_cache: dict = {}


def domain_is_districts(db, client_http, job: Job, email_domain: str) -> bool:
    """True when an email domain belongs to this job's district / school: it is the saved website's domain, or the
    domain's own website names the district (e.g. hlpusd.org for 'Hacienda La Puente Unified'), and it receives mail.
    Saves the district's website when it was unknown."""
    reg = _reg_domain(email_domain)
    sites = [s for s in [job.school.website if job.school else None, job.district.website if job.district else None] if s]
    if any(reg == _reg_domain(urlparse(s).netloc) for s in sites):
        return True
    names = [n for n in [job.district.name if job.district else None, job.employer_name] if n]
    key = (reg, tuple(names))
    if key in _domain_cache:
        return _domain_cache[key]
    ok = False
    if names and any(domain_matches_name(reg, n) for n in names) and _has_mail_server(reg):
        ok = True
    elif names and _has_mail_server(reg):
        for url in (f"https://www.{reg}/", f"https://{reg}/"):
            res = client_http.get(url, source_name="District domain check")
            if not res.ok:
                continue
            soup = BeautifulSoup(res.text, "lxml")
            head = " ".join(filter(None, [soup.title.get_text(" ") if soup.title else "",
                                          " ".join(h.get_text(" ") for h in soup.select("h1")[:2])])).lower()
            for n in names:
                toks = _school_tokens(n)
                if toks and all(t in head for t in toks):
                    ok = True
            if ok:
                if job.district and not job.district.website:
                    job.district.website = res.final_url or url
                break
    _domain_cache[key] = ok
    return ok


def confirm_posting_emails(db, client_http=None) -> int:
    """Cloud rule for emails the school printed in its own job posting (SchoolSpring / EDJOIN "Contact: ..."):
    usable when the address is printed in the official posting and its domain belongs to the district (see
    domain_is_districts). Typos and personal addresses (the usual cause of bounces) fail this check."""
    from ..models import Contact, JobContact
    from .http import PoliteClient
    client_http = client_http or PoliteClient()
    n = 0
    rows = db.execute(select(Contact, Job).join(JobContact, JobContact.contact_id == Contact.id).join(Job, Job.id == JobContact.job_id)
                      .where(Contact.email.is_not(None), Contact.deleted_at.is_(None),
                             (Contact.mailbox_status.is_(None)) | (Contact.mailbox_status.in_(["CATCH_ALL", "UNKNOWN"])),
                             Contact.email_status.in_(["VERIFIED", "PUBLISHED_ELSEWHERE"]), Job.is_demo.is_(False),
                             Job.job_status == "ACTIVE")).all()
    done = set()
    for c, job in rows:
        if c.id in done:
            continue
        done.add(c.id)
        if domain_is_districts(db, client_http, job, c.email.split("@", 1)[-1]):
            c.mailbox_status, c.mailbox_checked_at = "OFFICIAL_PAGE", datetime.utcnow()
            c.mailbox_detail = "Printed in the school's official job posting, on the district's own email domain"
            n += 1
    db.commit()
    return n


def recheck_posting_email_status(db) -> int:
    """Emails taken from a posting's mailto link were once marked DO_NOT_USE because the address wasn't in the
    visible text. They came from the official posting itself, so they are re-marked VERIFIED."""
    from ..models import Contact
    n = 0
    for c in db.scalars(select(Contact).where(Contact.email_status == "DO_NOT_USE", Contact.email.is_not(None),
                                              Contact.source_url.like("%edjoin.org/Home/JobPosting/%"))).all():
        c.email_status = "VERIFIED"
        n += 1
    db.commit()
    return n


def contacts_from_posting(db, client_http, job: Job) -> list[dict]:
    """Free Gemini reads the job posting's own text and picks out the principal / hiring contact it names
    ("Questions? Contact Principal Jane Doe at jdoe@district.org"). Kept only when the email is printed in that text,
    the person's name is too, the address is the person's own, and the domain belongs to the district."""
    from .ai_contacts import email_matches_name
    text = "\n".join(filter(None, [job.job_description, job.requirements]))
    if not text or not EMAIL_IN_TEXT.search(text) or not GEMINI_KEY:
        return []
    from .generators import _real_school_name
    cands = _ask_gemini(_real_school_name(job), job.district.name if job.district else job.employer_name,
                        job.official_job_url or "", text)
    low = text.lower()
    kept = []
    for c in cands:
        email = str(c.get("email") or "").strip().lower()
        name = re.sub(r"\s+", " ", str(c.get("name") or "")).strip()
        if (not email or email not in low or len(name.split()) < 2 or name.split()[-1].lower() not in low
                or not email_matches_name(email, name)
                or not domain_is_districts(db, client_http, job, email.split("@", 1)[-1])):
            continue
        role = "SCHOOL_PRINCIPAL" if str(c.get("role")).upper() == "PRINCIPAL" else "VACANCY_CONTACT"
        contact = contact_svc.upsert_contact(
            db, full_name=name, title=str(c.get("title") or "") or ("Principal" if role == "SCHOOL_PRINCIPAL" else None),
            organization=job.employer_name, email=email, phone=None, source_url=job.official_job_url,
            district_id=job.district_id, school_id=job.school_id if role == "SCHOOL_PRINCIPAL" else None,
            page_text=text, source_type="OFFICIAL_ATS")
        if not contact or contact.deleted_at:
            continue
        contact.email_status, contact.verification_status = "VERIFIED", "VERIFIED"
        contact.mailbox_status, contact.mailbox_checked_at = "OFFICIAL_PAGE", datetime.utcnow()
        contact.mailbox_detail = "Named with this email in the school's official job posting (read by Gemini, checked by the app)"
        contact_svc.link(db, job, contact, role, "HIGH", job.official_job_url, None)
        kept.append({"role": role, "name": name, "email": email})
    db.commit()
    return kept
