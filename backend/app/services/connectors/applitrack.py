"""Frontline Recruitment (AppliTrack) district job boards.

Each district hosts a public board at https://www.applitrack.com/<client>/onlineapp/.
The vacancy list is served by jobpostings/Output.asp as a series of document.write() calls.
robots.txt for applitrack.com only disallows /*/onlineapp/admin.
"""
import re

from bs4 import BeautifulSoup

from ..taxonomy import is_relevant_title
from ..verification import email_in_legal_notice, is_non_hiring_email
from .schoolspring import school_name
from .base import RawContact, RawJob, html_to_text, parse_date, salary_from_text

WRITE_RE = re.compile(r"document\.write\('((?:[^'\\]|\\.)*)'\)", re.S)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def board_url(client: str) -> str:
    return f"https://www.applitrack.com/{client}/onlineapp/default.aspx"


def feed_url(client: str) -> str:
    return f"https://www.applitrack.com/{client}/onlineapp/jobpostings/Output.asp?all=1"


def detail_url(client: str, job_id: str) -> str:
    return (f"https://www.applitrack.com/{client}/onlineapp/default.aspx?AppliTrackJobId={job_id}"
            f"&AppliTrackLayoutMode=detail&AppliTrackViewPosting=1")


def _unwrap(js: str) -> str:
    out = []
    for m in WRITE_RE.finditer(js):
        s = m.group(1)
        s = s.replace("\\'", "'").replace('\\"', '"').replace("\\n", "\n").replace("\\r", "").replace("\\/", "/")
        out.append(s)
    return "".join(out)


def parse_feed(js: str, *, client: str, district_name: str, state: str | None, city: str | None) -> tuple[list[RawJob], int]:
    """Return (relevant jobs, total postings seen)."""
    html = _unwrap(js)
    soup = BeautifulSoup(html, "lxml")
    postings = soup.select("ul.postingsList")
    jobs = []
    for ul in postings:
        title_el = ul.select_one("td#wrapword") or ul.select_one(".title td")
        if not title_el:
            continue
        title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True))
        id_el = ul.select_one("span.title2")
        m = re.search(r"JobID:\s*(\d+)", id_el.get_text(" ", strip=True) if id_el else "")
        job_id = m.group(1) if m else None
        ok, _ = is_relevant_title(title)
        if not ok or not job_id:
            continue
        fields = {}
        for li in ul.find_all("li"):
            lab = li.select_one("span.label")
            if not lab:
                continue
            key = lab.get_text(" ", strip=True).rstrip(":").strip()
            val = " ".join(n.get_text(" ", strip=True) for n in li.select("span.normal"))
            fields[key] = val.strip()
        desc_el = ul.select_one(f"#DescriptionText{job_id}_") or ul.select_one("[id^=DescriptionText]")
        desc_html = str(desc_el) if desc_el else ""
        whole_text = ul.get_text("\n", strip=True)
        description = html_to_text(desc_html) or None
        # Salary block (outside the description span on some boards)
        smin, smax, stext = salary_from_text(whole_text)
        closing = fields.get("Closing Date") or fields.get("Closing date") or fields.get("Deadline")
        contacts = []
        contact_field = fields.get("Contact") or fields.get("Contact Person")
        # Emails inside EEO / Title IX / 504 notices are compliance offices, not hiring contacts.
        emails = sorted(e for e in set(x.lower() for x in EMAIL_RE.findall(whole_text))
                        if not is_non_hiring_email(e) and not email_in_legal_notice(whole_text, e))
        if contact_field:
            em = EMAIL_RE.search(contact_field)
            name = EMAIL_RE.sub("", contact_field).strip(" ,;-") or None
            contacts.append(RawContact(name, None, em.group(0) if em else None, None, "VACANCY_CONTACT",
                                       "HIGH" if name else "MEDIUM", detail_url(client, job_id),
                                       f"Contact: {contact_field}"))
        for e in emails:
            if not any(c.email == e for c in contacts):
                contacts.append(RawContact(None, None, e, None, "VACANCY_CONTACT", "MEDIUM", detail_url(client, job_id),
                                           "Email published in the vacancy text"))
        location = fields.get("Location") or None
        jobs.append(RawJob(
            source_name=f"Frontline AppliTrack - {district_name}",
            source_url=feed_url(client),
            source_type="OFFICIAL_ATS", tier=2, title=title, external_id=job_id,
            official_url=detail_url(client, job_id), application_url=detail_url(client, job_id),
            employer_name=district_name,
            school_name=school_name(location.title() if location and location.isupper() else location, district_name),
            city=city, state=state,
            date_posted=parse_date(fields.get("Date Posted")),
            closing_date=parse_date(closing) if closing and re.search(r"\d", closing) else None,
            closing_text=closing, until_filled=bool(closing and re.search(r"until filled", closing, re.I)),
            salary_min=smin, salary_max=smax, salary_text=stext,
            employment_type=fields.get("Position Type"),
            description=description, contacts=contacts, listed_in_feed=True,
            page_text=whole_text, feed_key=f"applitrack:{client}",
            extra={"fields": fields},
        ))
    return jobs, len(postings)


def scan(client_http, source) -> tuple[list[RawJob], dict]:
    cfg = source.config or {}
    slug = cfg["client"]
    # Large districts publish multi-megabyte feeds (East Baton Rouge ~8 MB); allow extra time.
    res = client_http.get(feed_url(slug), source_name=source.name, timeout=150)
    info = {"requests": 1, "http_status": res.status, "crawl_status": res.crawl_status, "error": res.error,
            "feed_ok": res.ok, "feed_key": f"applitrack:{slug}", "log": getattr(res, "log_row", None)}
    if not res.ok:
        return [], info
    try:
        jobs, total = parse_feed(res.text, client=slug, district_name=cfg.get("district_name") or source.name,
                                 state=source.state, city=source.city)
        info.update(parser_status="PARSED" if total else "NO_POSTINGS", postings_seen=total)
    except Exception as e:
        info.update(parser_status="PARSE_ERROR", error=f"{type(e).__name__}: {e}")
        jobs = []
    return jobs, info
