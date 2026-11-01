"""Contact intelligence: normalized contacts, job links and the "Who should I address?" logic."""
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Contact, Job, JobContact
from .verification import (DEPARTMENT_NAME_RE, PLACEHOLDER_NAME_RE, classify_source, email_status_for,
                           is_non_hiring_email, is_placeholder_email, is_placeholder_phone)

HONORIFIC_RE = re.compile(r"^(Mr|Mrs|Ms|Miss|Dr|Mx)\.?\s+", re.I)

# Priority order (spec section 7): lower number = better addressee.
REL_PRIORITY = {
    "JOB_POSTER": 1, "VACANCY_CONTACT": 1, "HIRING_MANAGER": 1,
    "SCHOOL_PRINCIPAL": 2, "PRINCIPAL": 2, "CAMPUS_ADMINISTRATOR": 3,
    "REGIONAL_RECRUITER": 4, "INTERNATIONAL_RECRUITER": 4, "TALENT_PARTNER": 4, "RECRUITER": 4,
    "DISTRICT_RECRUITER": 5, "VISA_COORDINATOR": 5, "HR_ADMINISTRATOR": 6, "HR": 6, "GENERAL_HR_ONLY": 7,
}

RECRUITER_TITLE_RE = re.compile(r"recruit|talent|human resources|\bhr\b|personnel|staffing|employment", re.I)
PRINCIPAL_TITLE_RE = re.compile(r"\bprincipal\b", re.I)


def split_honorific(name: str | None) -> tuple[str | None, str | None]:
    if not name:
        return None, None
    m = HONORIFIC_RE.match(name.strip())
    if m:
        h = m.group(1).capitalize() + "."
        return h, name.strip()[m.end():].strip()
    return None, name.strip()


def contact_type_for(title: str | None) -> str:
    t = re.sub(r"\s+", " ", title or "")
    if re.search(r"assistant principal|vice principal|associate principal", t, re.I):
        return "ASSISTANT_PRINCIPAL"
    if PRINCIPAL_TITLE_RE.search(t):
        return "PRINCIPAL"
    if re.search(r"international|visa|j-?1", t, re.I):
        return "INTERNATIONAL_RECRUITER"
    if re.search(r"talent partner", t, re.I):
        return "TALENT_PARTNER"
    if re.search(r"recruit|talent", t, re.I):
        return "RECRUITER"
    if re.search(r"director", t, re.I) and RECRUITER_TITLE_RE.search(t):
        return "HR_DIRECTOR"
    if RECRUITER_TITLE_RE.search(t):
        return "HR"
    return "OTHER"


def upsert_contact(db: Session, *, full_name, title, organization, email, phone, source_url,
                   district_id=None, school_id=None, page_text=None, source_type=None) -> Contact | None:
    honorific, name = split_honorific(full_name)
    name = re.sub(r"\s+", " ", name or "").strip() or None
    email = (email or "").strip().lower() or None
    phone = (phone or "").strip() or None
    if name and PLACEHOLDER_NAME_RE.match(name):
        name = None
    if name and DEPARTMENT_NAME_RE.search(name):
        title = title or name          # e.g. "Human Resources" is an office, not a person
        name = None
    if is_placeholder_email(email) or is_non_hiring_email(email):
        email = None
    if is_placeholder_phone(phone):
        phone = None
    if not (name or email or phone):
        return None
    q = select(Contact)
    if email:
        q = q.where(Contact.email == email)
    elif name:
        q = q.where(Contact.full_name == name, Contact.district_id == district_id)
    else:
        q = q.where(Contact.phone == phone, Contact.district_id == district_id, Contact.title == title)
    c = db.scalars(q).first()
    if not c:
        c = Contact(full_name=name)
        db.add(c)
    c.honorific = honorific or c.honorific
    c.title = title or c.title
    c.organization = organization or c.organization
    c.district_id = district_id or c.district_id
    c.school_id = school_id or c.school_id
    c.contact_type = contact_type_for(c.title)
    st, _ = classify_source(source_url)
    c.source_type = source_type or st
    c.source_url = source_url or c.source_url
    if email:
        if c.email != email:
            c.mailbox_status, c.mailbox_checked_at, c.mailbox_detail = None, None, None   # re-check new address
        c.email = email
        c.email_status = email_status_for(email, source_url, page_text)
        c.email_source_url = source_url
    if phone:
        c.phone = phone
        c.phone_source_url = source_url
    official = c.source_type in ("OFFICIAL_ATS", "OFFICIAL_DISTRICT", "EMPLOYER_SITE")
    c.verification_status = "VERIFIED" if official else "PARTIALLY_VERIFIED"
    c.verified_at = datetime.utcnow()
    db.flush()
    return c


DEAD_MAILBOX = ("NOT_FOUND", "NO_MAIL_SERVER")


def email_usable(c: Contact) -> bool:
    """Only emails that are published by an official source AND confirmed to exist by the school's
    own mail server are shown or used. Unchecked, unconfirmable and dead addresses are hidden."""
    # EXISTS: the school's mail server confirmed the mailbox (checked on this computer).
    # OFFICIAL_PAGE: the app itself re-read the address on the school's / district's official website
    # (used in the cloud, where the mail-server check is blocked).
    return bool(c.email) and c.email_status in ("VERIFIED", "PUBLISHED_ELSEWHERE") and c.mailbox_status in ("EXISTS", "OFFICIAL_PAGE")


def best_confirmed_email(job: Job | None) -> str | None:
    """The confirmed email to contact for a job: the recommended addressee first, then any other
    contact linked to the vacancy whose mailbox the school's mail server confirmed."""
    if not job:
        return None
    rec = recommend_addressee(job)
    if rec.get("recommended") and rec["contact"].get("email"):
        return rec["contact"]["email"]
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for l in sorted(job.contact_links, key=lambda l: (REL_PRIORITY.get(l.relationship_type, 9), order.get(l.confidence, 3))):
        if email_usable(l.contact):
            return l.contact.email
    return None


def _apply_mailbox_result(c: Contact, r: dict):
    if r["result"] == "UNKNOWN" and c.mailbox_status in ("EXISTS", "NOT_FOUND", "CATCH_ALL", "NO_MAIL_SERVER"):
        c.mailbox_detail = f"Last check inconclusive ({r['detail']}); keeping earlier result"
    else:
        c.mailbox_status = r["result"]
        c.mailbox_detail = (f"{r['code']} {r['detail']}" if r["code"] else r["detail"] or "")[:300]
    c.mailbox_checked_at = datetime.utcnow()


def check_mailboxes(db: Session, contacts: list[Contact], workers: int = 8, progress=None) -> None:
    """Check many addresses in parallel (different schools' mail servers at once); results are
    written back on this thread because database sessions are not shared between threads."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from ..config import MAILBOX_CHECK
    from . import mailcheck
    if not MAILBOX_CHECK:
        return  # cloud servers block the mail-server check
    todo = [(c.id, c.email) for c in contacts if c.email]
    by_id = {c.id: c for c in contacts}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(mailcheck.check, email): cid for cid, email in todo}
        for f in as_completed(futs):
            cid = futs[f]
            try:
                _apply_mailbox_result(by_id[cid], f.result())
            except Exception:
                pass
            done += 1
            if done % 10 == 0:
                db.commit()
                if progress:
                    progress(done, len(todo))
    db.commit()


def check_mailbox(db: Session, c: Contact, force: bool = False) -> Contact:
    """Ask the school's mail server whether this address exists (no email is sent); result is cached 7 days."""
    from ..config import MAILBOX_CHECK
    from . import mailcheck
    if not MAILBOX_CHECK or c.mailbox_status == "OFFICIAL_PAGE":
        return c  # cloud: no mail-server check; an official-page confirmation is kept as is
    if not c.email or (not force and not mailcheck.needs_check(c.mailbox_checked_at)):
        return c
    # A temporary/unclear answer never overwrites an earlier definite one.
    _apply_mailbox_result(c, mailcheck.check(c.email))
    db.commit()
    return c


def sanitize_contacts(db: Session) -> dict:
    """Repair stored contacts against the placeholder rules (runs at startup). Placeholder names,
    emails and phones are removed; department names ("Human Resources") become the title; a contact
    left with nothing real is deleted along with its job links."""
    stats = {"fixed": 0, "deleted": 0}
    for c in db.scalars(select(Contact)).all():
        changed = False
        if c.title and c.contact_type != contact_type_for(c.title):
            c.contact_type = contact_type_for(c.title)
        if c.email and (is_placeholder_email(c.email) or is_non_hiring_email(c.email)):
            c.email, c.email_status, c.email_source_url = None, "NONE", None
            changed = True
        if c.phone and is_placeholder_phone(c.phone):
            c.phone, c.phone_source_url = None, None
            changed = True
        if c.full_name and PLACEHOLDER_NAME_RE.match(c.full_name.strip()):
            c.full_name, changed = None, True
        if c.full_name and DEPARTMENT_NAME_RE.search(c.full_name):
            c.title = c.title or c.full_name
            c.full_name, changed = None, True
            c.contact_type = contact_type_for(c.title)
        if not changed:
            continue
        links = db.scalars(select(JobContact).where(JobContact.contact_id == c.id)).all()
        if not (c.full_name or c.email or c.phone):
            for l in links:
                db.delete(l)
            db.delete(c)
            stats["deleted"] += 1
        else:
            for l in links:
                if not c.full_name and l.confidence == "HIGH":
                    l.confidence = "MEDIUM"   # an unnamed office is never an auto-recommended addressee
            stats["fixed"] += 1
    db.commit()
    return stats


def link(db: Session, job: Job, contact: Contact, relationship: str, confidence: str,
         evidence_url: str | None, evidence_text: str | None = None) -> JobContact | None:
    if contact.deleted_at:
        return None          # the user deleted this contact: scans must not attach it to jobs again
    jc = db.scalars(select(JobContact).where(
        JobContact.job_id == job.id, JobContact.contact_id == contact.id,
        JobContact.relationship_type == relationship)).first()
    if not jc:
        jc = JobContact(job_id=job.id, contact_id=contact.id, relationship_type=relationship)
        db.add(jc)
    jc.confidence = confidence
    jc.evidence_url = evidence_url
    jc.evidence_text = evidence_text
    db.flush()
    return jc


def serialize_contact(c: Contact) -> dict:
    return {
        "id": c.id, "full_name": c.full_name, "honorific": c.honorific, "title": c.title,
        "organization": c.organization, "contact_type": c.contact_type,
        # The address itself is only returned once the school's mail server has confirmed it exists.
        "email": c.email if email_usable(c) else None,
        "has_unconfirmed_email": bool(c.email) and not email_usable(c),
        "email_status": c.email_status, "email_source_url": c.email_source_url,
        "mailbox_status": c.mailbox_status, "mailbox_detail": c.mailbox_detail,
        "mailbox_checked_at": c.mailbox_checked_at.isoformat() if c.mailbox_checked_at else None,
        "email_usable": email_usable(c),
        "phone": c.phone, "phone_source_url": c.phone_source_url,
        "source_url": c.source_url, "source_type": c.source_type,
        "verification_status": c.verification_status,
        "verified_at": c.verified_at.isoformat() if c.verified_at else None,
        "school": c.school.name if c.school else None,
        "district": c.district.name if c.district else None,
        "reviewer_note": c.reviewer_note,
    }


def salutation(contact: dict | None) -> str:
    """Never guess Mr./Ms. from a first name: use a published honorific or the full name."""
    if not contact or not contact.get("full_name"):
        return "Dear Hiring Committee:"
    last = contact["full_name"].split()[-1]
    if contact.get("honorific"):
        return f"Dear {contact['honorific']} {last}:"
    return f"Dear {contact['full_name']}:"


def recommend_addressee(job: Job) -> dict:
    links = sorted(job.contact_links, key=lambda l: (REL_PRIORITY.get(l.relationship_type, 9),
                                                     {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(l.confidence, 3)))
    named = [l for l in links if l.contact.full_name]
    best = named[0] if named else None
    if best and best.confidence == "HIGH":
        c = serialize_contact(best.contact)
        why = {
            "JOB_POSTER": "The official vacancy identifies this person as the job poster.",
            "VACANCY_CONTACT": "The official vacancy lists this person as the contact for the position.",
            "HIRING_MANAGER": "The official vacancy identifies this person as the hiring manager.",
            "SCHOOL_PRINCIPAL": "The official source directs applicants to this principal for this vacancy.",
            "PRINCIPAL": "The official source directs applicants to this principal for this vacancy.",
        }.get(best.relationship_type, f"Verified {best.relationship_type.replace('_', ' ').lower()} for this vacancy.")
        return {"recommended": True, "contact": c, "relationship": best.relationship_type,
                "confidence": best.confidence, "why": why, "evidence_url": best.evidence_url,
                "salutation": salutation(c)}
    alternatives = [{"contact": serialize_contact(l.contact), "relationship": l.relationship_type,
                     "confidence": l.confidence, "evidence_url": l.evidence_url} for l in links[:5]]
    reason = ("No HIGH-confidence named contact is linked to this vacancy." if links
              else "No verified contact has been found for this vacancy yet.")
    return {"recommended": False, "contact": None, "confidence": best.confidence if best else None,
            "why": reason + " Use a neutral greeting rather than guessing a name.",
            "salutation": "Dear Hiring Committee:", "alternatives": alternatives}


# ---------------------------------------------------------------- titles (Mr. / Mrs. / Ms. / Dr.)
_TITLE_RE = r"\b(Mr|Mrs|Ms|Miss|Dr)\.?\s+(?:[A-Z][a-zA-Z'\-]+\.?\s+){{0,2}}{last}\b"   # "Mrs. Lea Ann Frank"


def published_honorific(text: str | None, full_name: str | None) -> str | None:
    """The title the school itself uses for this person, e.g. 'Mrs. Frank' on the school's page.
    Returns None when the page never writes one, or writes conflicting ones. Never guessed from a first name."""
    if not text or not full_name:
        return None
    parts = [w for w in re.sub(r"^(Dr|Mr|Mrs|Ms|Miss)\.?\s+", "", full_name.strip(), flags=re.I).split()
             if w.rstrip(".").lower() not in ("jr", "sr", "ii", "iii", "iv")]
    if not parts or len(parts[-1]) < 2:
        return None
    first, last = parts[0], parts[-1]
    found = set()
    for m in re.finditer(_TITLE_RE.format(last=re.escape(last)), text):
        said = m.group(0)
        near = text[max(0, m.start() - 250):m.end() + 250].lower()
        # The title must belong to THIS person: written with their full name ("Dr. Cindy Stone"), or with the last
        # name right next to their full name or the word "principal" (another "Dr. Stone" on the page doesn't count).
        if first.lower() in said.lower() or (first.lower() + " " + last.lower()) in near or "principal" in near:
            found.add(m.group(1).capitalize())
    found = {"Miss" if f == "Miss" else f for f in found}
    if len(found) == 1:
        t = found.pop()
        return t if t == "Miss" else t + "."
    if found == {"Mrs", "Ms"}:
        return "Ms."   # both used for the same woman on one page
    return None


def ensure_honorific(db: Session, client_http, contact: Contact) -> str | None:
    """Read the contact's official page once and store the title the school uses (if any)."""
    if contact.honorific or contact.honorific_checked_at or not contact.full_name:
        return contact.honorific
    from datetime import datetime
    from bs4 import BeautifulSoup
    for url in dict.fromkeys(u for u in (contact.source_url, contact.email_source_url) if u):
        res = client_http.get(url, source_name="Title check")
        if res.ok:
            t = published_honorific(BeautifulSoup(res.text, "lxml").get_text(" ", strip=True), contact.full_name)
            if t:
                contact.honorific = t
                break
    contact.honorific_checked_at = datetime.utcnow()
    db.commit()
    return contact.honorific
