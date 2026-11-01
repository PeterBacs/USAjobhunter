"""EDJOIN (edjoin.org) - the official application system used by California school districts.

robots.txt allows all. The job list comes from /Home/LoadJobs (the same JSON the site's own search
page uses); each posting page (/Home/JobPosting/<id>) carries the deadline, the contact person and a
schema.org JobPosting block. Applications are submitted through EDJOIN itself, so the posting page is
the official application link.
"""
import re
from datetime import datetime, timezone
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..taxonomy import is_relevant_title
from .base import RawContact, RawJob, html_to_text, parse_date, salary_from_text
from .jsonld import postings_from_html

BASE = "https://www.edjoin.org"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?:\s*(?:x|ext\.?)?\s*\d{1,5})?")
SCHOOL_HINT = re.compile(r"\b(school|high|middle|elementary|academy|junior|intermediate|campus|k-8|charter)\b", re.I)


def search_url(keyword: str, page: int, rows: int) -> str:
    return (f"{BASE}/Home/LoadJobs?rows={rows}&page={page}&sort=postingDate&sortVal=0&order=desc"
            f"&keywords={quote(keyword)}&location=&searchType=all&regions=&jobTypes=&days=0&empType=&catID=0"
            f"&onlineApps=&recruitmentCenterID=0&stateID=0&regionID=0&districtID=0&searchID=0")


def posting_url(posting_id) -> str:
    return f"{BASE}/Home/JobPosting/{posting_id}"


def _ms_date(v):
    """'/Date(1789689600000)/' -> date"""
    m = re.search(r"-?\d{10,}", str(v or ""))
    if not m or m.group(0).startswith("-"):
        return None
    return datetime.fromtimestamp(int(m.group(0)) / 1000, tz=timezone.utc).date()


def _money(s) -> float | None:
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _school_from_title(title: str) -> str | None:
    # "Mathematics Teacher - Yucaipa High School" -> "Yucaipa High School"
    parts = [p.strip() for p in re.split(r"\s[-–@]\s|\s@", title) if p.strip()]
    for p in reversed(parts[1:]):
        p = re.sub(r"^\([^)]*\)\s*", "", p).strip()          # "(Part Time / Spring) Carlmont High School"
        if SCHOOL_HINT.search(p) and not re.search(r"\bteacher\b", p, re.I):
            return p
    return None


def build_job(row: dict, page_html: str | None) -> RawJob:
    pid = row.get("postingID")
    url = posting_url(pid)
    title = (row.get("positionTitle") or "").strip()
    lo, hi = _money(row.get("PayRangeFrom")), _money(row.get("PayRangeTo"))
    unit = (row.get("PayRangeDropdown") or "").strip()
    salary_text = None
    if lo or hi:
        salary_text = f"{row.get('PayRangeFrom') or ''} - {row.get('PayRangeTo') or ''} {unit}".strip(" -") + " (as published)"
    annual = unit.lower().startswith("annual")
    smin, smax = (lo, hi) if annual and (lo or 0) >= 20000 else (None, None)
    description, deadline_text, contacts, page_text = None, None, [], None
    if page_html:
        soup = BeautifulSoup(page_html, "lxml")
        page_text = soup.get_text("\n", strip=True)
        for p in postings_from_html(page_html):
            description = html_to_text(p.get("description")) or description
        m = re.search(r"Application Deadline\n(.+)", page_text)
        deadline_text = m.group(1).strip() if m else None
        m = re.search(r"\nContact\n(.+?)\n(.+?)\n", page_text)
        if m:
            name = m.group(1).strip()
            phone_m = PHONE_RE.search(m.group(2))
            emails = [a["href"][7:].split("?")[0] for a in soup.select('a[href^="mailto:"]')
                      if EMAIL_RE.fullmatch(a["href"][7:].split("?")[0] or "")]
            if name and not EMAIL_RE.search(name) and not PHONE_RE.fullmatch(name):
                contacts.append(RawContact(name, None, emails[0] if emails else None,
                                           phone_m.group(0) if phone_m else None, "VACANCY_CONTACT", "HIGH", url,
                                           "Contact listed on the district's EDJOIN posting"))
        if not smax and page_text:
            smin, smax, st = salary_from_text(page_text)
            salary_text = salary_text or st
    closing = parse_date(deadline_text.split(" ")[0]) if deadline_text else _ms_date(row.get("displayUntil"))
    return RawJob(
        source_name="EDJOIN", source_url=url, source_type="OFFICIAL_ATS", tier=2, title=title,
        external_id=str(pid), official_url=url, application_url=url,
        employer_name=(row.get("districtName") or "").strip() or None, school_name=_school_from_title(title),
        city=(row.get("city") or "").strip() or None, state="CA", zip=row.get("zip"),
        date_posted=_ms_date(row.get("postingDate")), closing_date=closing,
        closing_text=deadline_text or row.get("displayFlag"),
        until_filled=bool(re.search(r"until filled", str(row.get("displayFlag") or ""), re.I)),
        salary_min=smin, salary_max=smax, salary_text=salary_text,
        employment_type=row.get("FullTimePartTime") or row.get("jobType"),
        description=description or html_to_text(row.get("JobSummary")) or None,
        requirements=None, contacts=contacts, listed_in_feed=True, page_text=page_text,
        extra={"categories": row.get("jobType") or ""},
    )


def scan(client_http, source, *, keywords: list[str], pages: int, rows: int = 50, stop_flag=None) -> tuple[list[RawJob], dict]:
    info = {"requests": 0, "errors": [], "postings_seen": 0, "feed_ok": True}
    seen, rows_keep = set(), []
    for kw in keywords:
        for page in range(1, pages + 1):
            if stop_flag and stop_flag():
                break
            res = client_http.get(search_url(kw, page, rows), source_name=source.name,
                                  headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
            info["requests"] += 1
            if not res.ok:
                info["errors"].append(res.error or f"HTTP {res.status}")
                info["feed_ok"] = False
                break
            try:
                data = res.json()
            except Exception as e:
                info["errors"].append(f"parse: {e}")
                break
            batch = data.get("data") or []
            info["postings_seen"] += len(batch)
            for row in batch:
                pid = row.get("postingID")
                if pid in seen:
                    continue
                seen.add(pid)
                if is_relevant_title(row.get("positionTitle") or "")[0]:
                    rows_keep.append(row)
            if page >= int(data.get("totalPages") or 1):
                break
    jobs = []
    for row in rows_keep:
        if stop_flag and stop_flag():
            break
        res = client_http.get(posting_url(row.get("postingID")), source_name=source.name)
        info["requests"] += 1
        jobs.append(build_job(row, res.text if res.ok else None))
    return jobs, info
