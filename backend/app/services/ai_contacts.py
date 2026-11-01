"""AI contact finder: Claude (with web search) looks for the principal, HR / recruiting contact and superintendent
published on a school's or district's OFFICIAL website, then the app re-reads every page itself.

Nothing Claude says is trusted on its own. An email is kept only when ALL of these hold:
  * the app fetched the cited page itself (robots.txt respected) and the exact address is printed on it,
  * the person's last name is on the same page,
  * the page belongs to the school / district (its saved website, or a domain that matches the district or school name),
  * the address is on the school's / district's own email domain (no Gmail etc., no guessed address patterns).
Kept emails get mailbox_status OFFICIAL_PAGE (the cloud can't run the mail-server check).
"""
import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

import anthropic
from bs4 import BeautifulSoup
from sqlalchemy import func, select

from ..config import AI_MAX_LOOKUPS_PER_DAY, AI_MAX_LOOKUPS_PER_RUN, ANTHROPIC_MODEL
from ..models import AILookup, Job
from . import contacts as contact_svc
from .verification import is_non_hiring_email, is_placeholder_email
from .websites import NOT_SCHOOL_DOMAINS, domain_matches_name

log = logging.getLogger("jobhunter.ai")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
REPEAT_DAYS = 60          # a school is looked up again only after 60 days
ROLE_LINK = {"PRINCIPAL": ("SCHOOL_PRINCIPAL", "MEDIUM", "Principal"),
             "HR": ("DISTRICT_RECRUITER", "MEDIUM", "Human Resources"),
             "SUPERINTENDENT": ("SUPERINTENDENT", "LOW", "Superintendent")}

SYSTEM = (
    "You research publicly listed contact details of U.S. K-12 school administrators for a teacher who is applying "
    "to a posted vacancy. Use only the school's or school district's own official website (search results from other "
    "sites may help you find it, but the email must be printed on an official school/district page). Never guess or "
    "construct an email from a name pattern, and never report an address you did not see printed on that page. "
    "If you cannot find it, report nothing for that role."
)


def _reg_domain(host: str) -> str:
    """Registrable part of a host: 'www.hs.katyisd.org' -> 'katyisd.org', 'x.k12.tx.us' -> 'x.k12.tx.us'."""
    parts = host.lower().split(":")[0].strip(".").split(".")
    if parts and parts[0] == "www":
        parts = parts[1:]
    if len(parts) >= 4 and parts[-1] == "us" and parts[-3] == "k12":
        return ".".join(parts[-4:])
    return ".".join(parts[-2:])


def _official_for(host: str, names: list[str], known_sites: list[str]) -> bool:
    reg = _reg_domain(host)
    if any(reg == _reg_domain(urlparse(s).netloc or s) for s in known_sites if s):
        return True
    if any(n and domain_matches_name(reg, n) for n in names):
        return True
    return reg.endswith((".k12.us",)) or bool(re.search(r"\.k12\.[a-z]{2}\.us$", reg))


def _page_text(client_http, url: str) -> tuple[str | None, str | None]:
    res = client_http.get(url, source_name="AI contact check")
    if not res.ok:
        return None, None
    return page_text_from_html(res.text), res.final_url or url


def _cf_decode(hexstr: str) -> str:
    """Cloudflare's email-protection encoding (a simple XOR) - the address the visitor's browser shows."""
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except ValueError:
        return ""


def page_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    extra = [a.get("href", "")[7:].split("?")[0] for a in soup.select('a[href^="mailto:"]')]
    for el in soup.select("[data-cfemail]"):
        extra.append(_cf_decode(el.get("data-cfemail", "")))
    for a in soup.select('a[href*="/cdn-cgi/l/email-protection#"]'):
        extra.append(_cf_decode(a.get("href", "").split("#", 1)[-1]))
    return soup.get_text(" ", strip=True) + " " + " ".join(e for e in extra if e)


def _ask_claude(job: Job, school: str | None, district: str | None, sites: list[str]) -> dict:
    client = anthropic.Anthropic()
    place = ", ".join(filter(None, [job.city, job.state]))
    prompt = (
        f"Vacancy: {job.job_title}\nSchool: {school or 'not stated (district-level posting)'}\n"
        f"School district / employer: {district or 'unknown'}\nLocation: {place or job.state or 'USA'}\n"
        + (f"Known official website(s): {', '.join(sites)}\n" if sites else "")
        + "\nFind, on the official school or district website:\n"
        "1. PRINCIPAL - the current principal of this school (only if a school is named).\n"
        "2. HR - the district's human resources / recruiting / hiring contact (a named person; skip generic offices).\n"
        "3. SUPERINTENDENT - the district superintendent.\n\n"
        "For each one you find, give the exact email address as printed, the page URL where it is printed, and a short "
        "verbatim quote from that page containing the email. Finish your answer with one JSON code block exactly like:\n"
        '```json\n{"contacts": [{"role": "PRINCIPAL", "name": "...", "title": "...", "email": "...", '
        '"source_url": "https://...", "quote": "..."}]}\n```\n'
        "Use an empty list if nothing is printed on an official page."
    )
    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
             {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 6}]
    response = None
    for _ in range(3):   # continue if the server-side tool loop pauses
        response = client.beta.messages.create(
            model=ANTHROPIC_MODEL, max_tokens=16000, system=SYSTEM, messages=messages, tools=tools,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        if response.stop_reason != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": response.content}]
    if response is None or response.stop_reason == "refusal":
        return {"contacts": [], "note": "declined"}
    text = "\n".join(b.text for b in response.content if b.type == "text")
    m = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S) or re.findall(r"(\{\s*\"contacts\".*\})", text, re.S)
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens,
             "web_searches": getattr(getattr(response.usage, "server_tool_use", None), "web_search_requests", None)}
    try:
        data = json.loads(m[-1]) if m else {"contacts": []}
    except json.JSONDecodeError:
        data = {"contacts": []}
    data["usage"] = usage
    return data


def email_matches_name(email: str, name: str) -> bool:
    """The mailbox should be the person's own: its first part contains their last name, or their first name."""
    local = re.sub(r"[^a-z]", "", email.split("@", 1)[0].lower())
    parts = [re.sub(r"[^a-z]", "", p.lower()) for p in re.sub(r"\b(dr|mr|mrs|ms|miss)\.?\s+", "", name, flags=re.I).split()]
    parts = [p for p in parts if len(p) >= 2]
    if not parts:
        return False
    first, last = parts[0], parts[-1]
    return (len(last) >= 3 and last[:max(4, min(len(last), 4))] in local) or (len(first) >= 3 and first in local)


def lookups_today(db) -> int:
    return db.scalar(select(func.count()).select_from(AILookup).where(
        AILookup.created_at >= datetime.utcnow() - timedelta(days=1))) or 0


def recently_looked_up(db, job: Job) -> bool:
    cut = datetime.utcnow() - timedelta(days=REPEAT_DAYS)
    q = select(AILookup.id).where(AILookup.created_at >= cut)
    q = q.where(AILookup.school_id == job.school_id) if job.school_id else q.where(AILookup.district_id == job.district_id,
                                                                                   AILookup.school_id.is_(None))
    return db.scalar(q.limit(1)) is not None


def find_contacts(db, client_http, job: Job) -> dict:
    """Run one AI lookup for this job's school / district and save only the emails the app could confirm."""
    from .generators import _real_school_name
    school = _real_school_name(job)
    district = job.district.name if job.district else job.employer_name
    sites = [s for s in [job.school.website if job.school else None, job.district.website if job.district else None] if s]
    names = [n for n in [district, job.employer_name, school] if n]
    row = AILookup(job_id=job.id, school_id=job.school_id, district_id=job.district_id, status="RUNNING")
    db.add(row)
    db.commit()
    try:
        data = _ask_claude(job, school, district, sites)
    except anthropic.APIStatusError as e:
        row.status, row.detail = "ERROR", f"Claude API error {e.status_code}"
        db.commit()
        return {"ok": False, "error": row.detail, "kept": []}
    except anthropic.APIConnectionError:
        row.status, row.detail = "ERROR", "Couldn't reach the Claude API"
        db.commit()
        return {"ok": False, "error": row.detail, "kept": []}
    kept, rejected = verify_and_save(db, client_http, job, (data.get("contacts") or [])[:6], how="Found with AI web search")
    row.status = "DONE"
    row.result = {"kept": kept, "rejected": rejected, "usage": data.get("usage")}
    row.detail = f"{len(kept)} kept, {len(rejected)} rejected"
    db.commit()
    return {"ok": True, "kept": kept, "rejected": rejected}


def verify_and_save(db, client_http, job: Job, candidates: list[dict], how: str, pages: dict | None = None) -> tuple[list, list]:
    """Keep a candidate contact only when the app itself confirms it on the official page (rules in the module doc).
    `pages` may hold already-fetched {url: (text, final_url)} to avoid fetching again."""
    from .generators import _real_school_name
    school = _real_school_name(job)
    district = job.district.name if job.district else job.employer_name
    sites = [s for s in [job.school.website if job.school else None, job.district.website if job.district else None] if s]
    names = [n for n in [district, job.employer_name, school] if n]
    kept, rejected = [], []
    for c in candidates:
        role = str(c.get("role") or "").upper()
        email = str(c.get("email") or "").strip().lower()
        url = str(c.get("source_url") or "").strip()
        name = re.sub(r"\s+", " ", str(c.get("name") or "")).strip()
        why = None
        if role not in ROLE_LINK or not EMAIL_RE.match(email) or not url.startswith("http"):
            why = "incomplete answer"
        elif len(name.split()) < 2:
            why = "no person's full name (generic office addresses are not used)"
        elif is_placeholder_email(email) or is_non_hiring_email(email):
            why = "generic / non-hiring address"
        elif any(email.endswith("@" + d) or email.endswith("." + d) for d in NOT_SCHOOL_DOMAINS):
            why = "not a school email domain"
        if not why:
            text, final = pages[url] if pages and url in pages else _page_text(client_http, url)
            host = urlparse(final or url).netloc
            email_dom = email.split("@", 1)[1]
            if not text:
                why = "page could not be opened"
            elif email not in text.lower():
                why = "address not printed on the cited page"
            elif name and name.split()[-1].lower() not in text.lower():
                why = "name not on the cited page"
            elif not email_matches_name(email, name):
                why = f"{email} doesn't look like {name}'s own address (it may belong to someone else on the page)"
            elif not _official_for(host, names, sites):
                why = f"{host} is not the school's or district's own website"
            elif not (_reg_domain(email_dom) == _reg_domain(host) or _official_for(email_dom, names, sites)):
                why = "email is not on the school's / district's domain"
        if why:
            rejected.append({"role": role, "email": email, "why": why})
            continue
        rel, conf, default_title = ROLE_LINK[role]
        contact = contact_svc.upsert_contact(
            db, full_name=name or None, title=str(c.get("title") or "").strip() or default_title,
            organization=school if role == "PRINCIPAL" and school else district, email=email, phone=None,
            source_url=final or url, district_id=job.district_id,
            school_id=job.school_id if role == "PRINCIPAL" else None, page_text=text, source_type="OFFICIAL_DISTRICT")
        if not contact or contact.deleted_at:
            continue
        contact.email_status = "VERIFIED"
        contact.mailbox_status, contact.mailbox_checked_at = "OFFICIAL_PAGE", datetime.utcnow()
        contact.mailbox_detail = f"Printed on the official page {final or url} ({how.lower()}, re-checked by the app)"
        contact.verification_status = "VERIFIED"
        quote = str(c.get("quote") or "")[:300]
        contact.reviewer_note = f"{how}; confirmed on {host}" + (f": “{quote}”" if quote else "")
        # Link to every open vacancy at this school (principal) or district (HR / superintendent).
        same = select(Job).where(Job.is_demo.is_(False), Job.job_status != "CLOSED")
        same = same.where(Job.school_id == job.school_id) if role == "PRINCIPAL" and job.school_id else same.where(Job.district_id == job.district_id) if job.district_id else same.where(Job.id == job.id)
        for j in db.scalars(same).all() or [job]:
            contact_svc.link(db, j, contact, rel, conf, final or url, quote or None)
        kept.append({"role": role, "name": contact.full_name, "email": email, "source_url": final or url})
    return kept, rejected


def run_for_new_jobs(db, client_http, since: datetime, max_lookups: int | None = None) -> dict:
    """After a scan: look up contacts for new open vacancies that have no usable principal email yet."""
    from .applied import applied_job_ids
    from .generators import school_principal
    budget = min(max_lookups or AI_MAX_LOOKUPS_PER_RUN, max(0, AI_MAX_LOOKUPS_PER_DAY - lookups_today(db)))
    applied = applied_job_ids(db)
    done, found = 0, 0
    seen_schools = set()
    jobs = db.scalars(select(Job).where(Job.is_demo.is_(False), Job.job_status == "ACTIVE", Job.date_discovered >= since)
                      .order_by(Job.match_score.desc().nullslast())).all()
    for job in jobs:
        if done >= budget:
            break
        key = job.school_id or ("d", job.district_id)
        if job.id in applied or key in seen_schools:
            continue
        p, _ = school_principal(job)
        if p and contact_svc.email_usable(p):
            continue
        if recently_looked_up(db, job):
            continue
        seen_schools.add(key)
        res = find_contacts(db, client_http, job)
        done += 1
        found += len(res.get("kept") or [])
    return {"ai_lookups": done, "ai_emails_confirmed": found, "ai_budget_left_today": max(0, AI_MAX_LOOKUPS_PER_DAY - lookups_today(db))}
