"""Generic official-page connector: schema.org JobPosting (JSON-LD) on district/school career pages.

Config:
  url:           official careers/listing page (required)
  link_pattern:  optional regex; matching links on the page are fetched and parsed as job details
  employer_name: optional fallback employer name
"""
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..taxonomy import is_relevant_title, parse_location
from ..verification import classify_source
from .base import RawContact, RawJob, html_to_text, parse_date, salary_from_text


def _iter_postings(data):
    if isinstance(data, list):
        for d in data:
            yield from _iter_postings(d)
    elif isinstance(data, dict):
        t = data.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
            yield data
        for k in ("@graph", "itemListElement", "item"):
            if k in data:
                yield from _iter_postings(data[k])


def postings_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            out.extend(_iter_postings(json.loads(s.string or s.get_text() or "{}")))
        except Exception:
            continue
    return out


def _to_raw(p: dict, page_url: str, source, page_text: str) -> RawJob | None:
    title = (p.get("title") or p.get("name") or "").strip()
    ok, _ = is_relevant_title(title)
    if not ok:
        return None
    org = p.get("hiringOrganization") or {}
    org_name = org.get("name") if isinstance(org, dict) else str(org)
    loc = p.get("jobLocation") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    addr = (loc.get("address") if isinstance(loc, dict) else None) or {}
    if isinstance(addr, str):
        city, state = parse_location(addr)
        zipc = None
    else:
        city = addr.get("addressLocality")
        st = (addr.get("addressRegion") or "")
        _, state = parse_location(f"x, {st}") if st else (None, None)
        zipc = addr.get("postalCode")
    sal = p.get("baseSalary") or {}
    smin = smax = None
    stext = None
    if isinstance(sal, dict):
        v = sal.get("value") or {}
        if isinstance(v, dict):
            smin, smax = v.get("minValue"), v.get("maxValue") or v.get("value")
            unit = v.get("unitText") or ""
            if unit and unit.upper() not in ("YEAR", "ANNUAL"):
                stext = f"{smin or ''}-{smax or ''} per {unit.lower()} (as published)"
                smin = smax = None
    desc = html_to_text(p.get("description"))
    if smin is None and smax is None:
        smin, smax, stext = salary_from_text(desc)
    url = p.get("url") or page_url
    contacts = []
    for c in (p.get("applicationContact") or []) if isinstance(p.get("applicationContact"), list) else \
            ([p["applicationContact"]] if isinstance(p.get("applicationContact"), dict) else []):
        contacts.append(RawContact(c.get("name"), c.get("contactType"), c.get("email"), c.get("telephone"),
                                   "VACANCY_CONTACT", "HIGH" if c.get("name") else "MEDIUM", url,
                                   "applicationContact in the official JobPosting data"))
    st, tier = classify_source(url)
    return RawJob(
        source_name=source.name, source_url=page_url, source_type=st if st != "UNKNOWN" else "EMPLOYER_SITE",
        tier=min(tier, source.tier or tier), title=title,
        external_id=str((p.get("identifier") or {}).get("value")) if isinstance(p.get("identifier"), dict) else p.get("identifier"),
        official_url=url, application_url=p.get("directApply") and url or url,
        employer_name=org_name or (source.config or {}).get("employer_name") or source.name,
        school_name=(loc.get("name") if isinstance(loc, dict) else None),
        city=city or source.city, state=state or source.state, zip=zipc,
        date_posted=parse_date(p.get("datePosted")), closing_date=parse_date(p.get("validThrough")),
        closing_text=p.get("validThrough"), salary_min=smin, salary_max=smax, salary_text=stext,
        employment_type=p.get("employmentType") if isinstance(p.get("employmentType"), str) else None,
        description=desc or None,
        requirements=html_to_text(p.get("qualifications") or p.get("experienceRequirements") or "") or None,
        contacts=contacts, listed_in_feed=True, page_text=page_text, feed_key=f"jsonld:{source.id}",
    )


def scan(client_http, source) -> tuple[list[RawJob], dict]:
    cfg = source.config or {}
    url = cfg["url"]
    res = client_http.get(url, source_name=source.name)
    info = {"requests": 1, "http_status": res.status, "crawl_status": res.crawl_status, "error": res.error,
            "feed_ok": res.ok, "feed_key": f"jsonld:{source.id}"}
    if not res.ok:
        return [], info
    jobs = []
    soup_text = BeautifulSoup(res.text, "lxml").get_text(" ", strip=True)
    for p in postings_from_html(res.text):
        r = _to_raw(p, url, source, soup_text)
        if r:
            jobs.append(r)
    pat = cfg.get("link_pattern")
    if pat:
        soup = BeautifulSoup(res.text, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"])
            if re.search(pat, href) and href not in links:
                links.append(href)
        for href in links[: int(cfg.get("max_links", 40))]:
            d = client_http.get(href, source_name=source.name)
            info["requests"] += 1
            if not d.ok:
                continue
            dtext = BeautifulSoup(d.text, "lxml").get_text(" ", strip=True)
            for p in postings_from_html(d.text):
                r = _to_raw(p, href, source, dtext)
                if r:
                    jobs.append(r)
    info["parser_status"] = "PARSED" if jobs else "NO_MATCH"
    info["postings_seen"] = len(jobs)
    return jobs, info
