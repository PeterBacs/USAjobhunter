"""SchoolSpring (PowerSchool) nationwide K-12 job board API.

SchoolSpring hosts official district job boards (e.g. <district>.schoolspring.com) and aggregates
ATS postings. The detail endpoint returns the employer's own posting URL (infoURL), deadline,
salary, and the posting contact exactly as the employer entered them.
"""
import re

from ..taxonomy import is_relevant_title, parse_location
from ..verification import classify_source
from .base import RawContact, RawJob, html_to_text, parse_date

API = "https://api.schoolspring.com/api/Jobs"
# jobInfo.jobStatusID of a posting that job seekers can see. Checked against the public search: postings with
# 40 / 50 / 60 are still returned by the detail API but are missing from search ("posting can't be viewed").
PUBLIC_STATUS = 30


def search_url(keyword: str, page: int, size: int, location: str = "") -> str:
    from urllib.parse import quote
    return (f"{API}/GetPagedJobsWithSearch?domainName=&keyword={quote(keyword)}&location={quote(location)}"
            f"&category=&gradelevel=&jobtype=&organization=&swLat=&swLon=&neLat=&neLon=&page={page}"
            f"&size={size}&sortDateAscending=false")


def public_url(job_id) -> str:
    return f"https://www.schoolspring.com/jobs?jobid={job_id}"


def detail_api(job_id) -> str:
    return f"{API}/{job_id}"


def _salary(ji: dict) -> tuple[float | None, float | None, str | None]:
    if not ji.get("payDisplay"):
        return None, None, None
    lo, hi, unit = ji.get("payMin"), ji.get("payMax"), (ji.get("salaryCode") or ji.get("payTypeName") or "").strip()
    text = None
    if lo or hi:
        def fmt(v):
            return f"${v:,.0f}" if v and v >= 1000 else (f"${v:,.2f}" if v else "")
        vals = [fmt(lo)] if lo == hi else [fmt(lo), fmt(hi)]
        text = " - ".join(x for x in vals if x) + (f" {unit}" if unit else "") + " (as published)"
    annual = unit.lower() in ("per year", "annual", "annually", "yearly", "")
    lo_a = lo if (annual and lo and lo >= 20000) else None
    hi_a = hi if (annual and hi and hi >= 20000) else None
    if lo_a and not hi_a:
        hi_a = lo_a
    if hi_a and not lo_a:
        lo_a = None
    return lo_a, hi_a, text


GENERIC_SCHOOL_RE = re.compile(r"^\s*(the\s+)?(elementary|middle|high|junior high|senior high|secondary|upper|lower|"
                               r"intermediate|primary)(\s+school)?\s*$|^\s*(district( office| wide|-wide)?|various|"
                               r"multiple (locations|campuses)|tbd|all (schools|campuses))\s*$", re.I)


def school_name(location: str | None, employer: str | None) -> str | None:
    """A bare 'Middle School' is a campus type, not an exact school: prefix the employer so it is not
    mistaken for a verified school name, e.g. 'Rochester Academy Charter School – Middle School'."""
    loc = (location or "").strip() or None
    emp = (employer or "").strip()
    if loc and GENERIC_SCHOOL_RE.match(loc) and emp:
        return f"{emp} – {loc.title()}"
    return loc


def resolve_official_url(client_http, raw: RawJob, job_id) -> None:
    """Some districts moved from TalentEd to SchoolSpring; their old posting links now forward to the
    board's home page. In that case the SchoolSpring posting itself is the direct, official link."""
    url = raw.official_url
    if not url or "schoolspring.com" in url:
        return
    res = client_http.get(url, source_name="Official link check", log=False)
    final = (res.final_url or "").lower()
    if res.ok and "schoolspring.com" in final and "jobid" not in final:
        raw.official_url = public_url(job_id)
        raw.application_url = public_url(job_id)
        raw.extra["redirected_from"] = url


def build_job(detail: dict, job_id) -> RawJob:
    ji = detail.get("jobInfo") or {}
    locs = detail.get("jobLocations") or []
    loc = locs[0] if locs else {}
    city, state = parse_location(loc.get("displayLocation") or "")
    info_url = (ji.get("infoURL") or "").strip() or None
    boards = detail.get("jobBoards") or []
    ss_url = public_url(job_id)
    official = info_url or ss_url
    # closeDate is stored in UTC (e.g. 2026-11-02T03:59 = Nov 1, 11:59 PM Eastern). The formatted value is the
    # employer's local deadline, so the calendar date comes from it.
    formatted = (detail.get("formattedExternalCloseDate") or ji.get("formattedExternalCloseDate") or "").strip()
    m = re.match(r"([A-Z][a-z]{2} \d{1,2}, \d{4})", formatted)
    close = parse_date(m.group(1)) if m else parse_date(ji.get("closeDate") or ji.get("applicationDeadline"))
    until_filled = False
    if close and close.year >= 2049:
        close, until_filled = None, True
    if re.search(r"until filled", formatted, re.I):
        until_filled = True
    closing_text = formatted or ("Until filled" if until_filled else None)
    smin, smax, stext = _salary(ji)
    desc = html_to_text(ji.get("jobDescription"))
    reqs = html_to_text(ji.get("requirements")) or None
    if ji.get("degreeTypeName"):
        reqs = ((reqs + "\n") if reqs else "") + f"Degree: {ji['degreeTypeName']}"
    if ji.get("experienceRequired"):
        reqs = ((reqs + "\n") if reqs else "") + f"Experience: {ji['experienceRequired']}"
    name = " ".join(x for x in [ji.get("contactFirstName"), ji.get("contactLastName")] if x and x.strip()) or None
    contacts = []
    if name or ji.get("contactEmail") or ji.get("contactPhone"):
        contacts.append(RawContact(
            full_name=name, title=(ji.get("contactTitle") or None), email=(ji.get("contactEmail") or None),
            phone=(ji.get("contactPhone") or None), relationship="VACANCY_CONTACT",
            confidence="HIGH" if name else "MEDIUM", evidence_url=ss_url,
            evidence_text="Contact listed on the employer's SchoolSpring posting",
        ))
    cats = detail.get("jobCategories") or []
    cat_text = "; ".join(f"{c.get('category')}: {c.get('subCategory')}" for c in cats if c)
    st, tier = classify_source(official)
    page_text = " ".join(filter(None, [desc, reqs, ji.get("contactEmail") or ""]))
    return RawJob(
        source_name="SchoolSpring" + (f" - {boards[0].get('jobBoardName')}" if boards else ""),
        source_url=ss_url, source_type="OFFICIAL_ATS", tier=2,
        title=(ji.get("jobTitle") or "").strip(), external_id=str(ji.get("externalJobCode") or job_id),
        official_url=official, application_url=info_url if ji.get("isAtsJob") and info_url else ss_url,
        employer_name=(ji.get("employerName") or "").strip() or None,
        school_name=school_name(loc.get("locationName") or ji.get("displayEmployer"), ji.get("employerName")),
        city=city, state=state, latitude=loc.get("latitude"), longitude=loc.get("longitude"),
        date_posted=parse_date(ji.get("displayDate") or ji.get("postDate")),
        closing_date=close, closing_text=closing_text, until_filled=until_filled,
        salary_min=smin, salary_max=smax, salary_text=stext,
        employment_type=ji.get("jobTypeName") or ji.get("shiftType"),
        description=desc or None, requirements=reqs,
        certification_requirements=None,
        contacts=contacts, listed_in_feed=True, page_text=page_text,
        extra={"schoolspring_id": job_id, "categories": cat_text, "board": boards[0] if boards else None,
               "official_source_type": st},
    )


def scan(client_http, source, *, keywords: list[str], pages: int, size: int, stop_flag=None,
         locations: list[str] | None = None) -> tuple[list[RawJob], dict]:
    seen_ids, jobs = set(), []
    info = {"requests": 0, "errors": [], "postings_seen": 0, "feed_ok": True}
    states = locations or [""]
    for kw in keywords:
        for loc in states:
            for page in range(1, pages + 1):
                if stop_flag and stop_flag():
                    return jobs, info
                res = client_http.get(search_url(kw, page, size, loc), source_name=source.name)
                info["requests"] += 1
                if not res.ok:
                    info["errors"].append(res.error or f"HTTP {res.status}")
                    info["feed_ok"] = False
                    break
                try:
                    lst = (res.json().get("value") or {}).get("jobsList") or []
                except Exception as e:
                    info["errors"].append(f"parse: {e}")
                    break
                info["postings_seen"] += len(lst)
                for item in lst:
                    jid = item.get("jobId")
                    if jid in seen_ids:
                        continue
                    seen_ids.add(jid)
                    ok, _ = is_relevant_title(item.get("title") or "")
                    if ok:
                        jobs.append(jid)
                if len(lst) < size:
                    break
    raws = []
    for jid in jobs:
        if stop_flag and stop_flag():
            break
        res = client_http.get(detail_api(jid), source_name=source.name)
        info["requests"] += 1
        if not res.ok:
            info["errors"].append(f"detail {jid}: {res.error}")
            continue
        try:
            detail = res.json().get("value") or {}
            raw = build_job(detail, jid)
            ok, _ = is_relevant_title(raw.title)
            if ok:
                resolve_official_url(client_http, raw, jid)
                raws.append(raw)
        except Exception as e:
            info["errors"].append(f"detail {jid} parse: {e}")
    return raws, info


def recheck(client_http, job_id) -> tuple[int | None, dict | None]:
    res = client_http.get(detail_api(job_id), source_name="SchoolSpring recheck")
    if not res.ok:
        return res.status, None
    try:
        return res.status, res.json().get("value")
    except Exception:
        return res.status, None
