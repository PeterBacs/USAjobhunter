"""K12JobSpot (k12jobspot.com) - Frontline Education's national network of K-12 district job postings.

robots.txt allows crawling. Its sitemap lists every posting ID; each posting's details come from the
public api.k12jobspot.com/api/Jobs/<id> endpoint the site itself uses. The sitemap has no titles, so
the connector reads postings it has not seen before, newest first, up to a per-scan cap, and keeps
only teaching titles in the target subjects.

The details carry no direct district application link, so these jobs are stored as found on the
Frontline job network (partially verified); the K12JobSpot page's APPLY button leads to the district.
"""
import re
from datetime import date, timedelta

from ..taxonomy import is_relevant_title
from .base import RawJob, parse_date

SITEMAPS = ["https://www.k12jobspot.com/sitemap/jobs-sitemap-1.xml",
            "https://www.k12jobspot.com/sitemap/jobs-sitemap-2.xml"]
API = "https://api.k12jobspot.com/api/Jobs/{id}"
PAGE = "https://www.k12jobspot.com/Job/{id}"
MAX_AGE_DAYS = 60


def build_job(d: dict) -> RawJob:
    jid = d.get("id")
    loc = (d.get("jobLocation") or [{}])[0] or {}
    base = d.get("location") or {}
    grades = ", ".join(d.get("gradeLevels") or [])
    areas = ", ".join(d.get("positionAreas") or [])
    desc = "\n\n".join(p.get("content", "") for p in (d.get("paragraphs") or []) if p.get("content"))
    school = (loc.get("name") or "").strip() or None
    employer = (d.get("hiringOrganization") or "").strip() or None
    return RawJob(
        source_name="K12JobSpot (Frontline network)", source_url=PAGE.format(id=jid), source_type="ATS_NETWORK", tier=2,
        title=(d.get("title") or "").strip(), external_id=str(jid),
        official_url=PAGE.format(id=jid), application_url=PAGE.format(id=jid),
        employer_name=employer, school_name=school if school and school != employer else None,
        city=(loc.get("city") or base.get("city") or "").strip() or None,
        state=(loc.get("regionCode") or base.get("regionCode") or "").strip().upper() or None,
        zip=(loc.get("postalCode") or base.get("postalCode") or None),
        date_posted=parse_date(d.get("postedDate")),
        closing_date=parse_date(d.get("validThroughDate")) if d.get("validThroughDate") else None,
        closing_text=d.get("endDateTypeDescription"),
        until_filled=bool(re.search(r"until filled", d.get("endDateTypeDescription") or "", re.I)),
        employment_type=", ".join(d.get("types") or []) or None,
        description=desc or None,
        requirements=(d.get("certificationSummary") or "").strip() or None,
        certification_requirements=", ".join(x for x in [d.get("certification"), d.get("certificationAgency")] if x) or None,
        contacts=[], listed_in_feed=True, page_text=desc,
        extra={"categories": " ".join([areas, grades])},
    )


def scan(client_http, source, *, max_new: int, stop_flag=None) -> tuple[list[RawJob], dict]:
    cfg = dict(source.config or {})
    info = {"requests": 0, "errors": [], "postings_seen": 0, "feed_ok": True}
    ids = set()
    for sm in SITEMAPS:
        res = client_http.get(sm, source_name=source.name, timeout=120)
        info["requests"] += 1
        if not res.ok:
            info["errors"].append(f"sitemap: {res.error or res.status}")
            info["feed_ok"] = False
            continue
        ids.update(int(x) for x in re.findall(r"/Job/(\d+)\s*<", res.text))
    if not ids:
        return [], info
    last_max = int(cfg.get("last_max_id") or 0)
    # Newest postings first; on later scans only IDs added since the last scan.
    todo = sorted((i for i in ids if i > last_max), reverse=True)[:max_new]
    info["postings_seen"] = len(todo)
    cutoff = date.today() - timedelta(days=MAX_AGE_DAYS)
    jobs, newest_done = [], last_max
    for i, jid in enumerate(todo):
        if stop_flag and stop_flag():
            break
        res = client_http.get(API.format(id=jid), source_name=source.name, log=(i < 25 or i % 50 == 0))
        info["requests"] += 1
        if not res.ok:
            continue
        newest_done = max(newest_done, jid)
        try:
            d = res.json()
        except Exception:
            continue
        if not is_relevant_title(d.get("title") or "")[0]:
            continue
        posted = parse_date(d.get("postedDate"))
        if posted and posted < cutoff:
            continue
        jobs.append(build_job(d))
    info["new_last_max_id"] = newest_done
    return jobs, info
