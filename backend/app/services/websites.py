"""Find a district's / school's official website from evidence already on file, and confirm it.

Candidates come from (1) domains of emails the district itself published on its postings and
(2) official posting links hosted on the district's own domain. A candidate is accepted only when the
page loads and its title/heading names the district (or school). Nothing is guessed from the name
alone, and robots.txt is respected.
"""
import re
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from sqlalchemy import select

from ..models import Contact, District, Job, JobContact

# Email providers and hiring/job-board vendors are never a school's own website.
NOT_SCHOOL_DOMAINS = (
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com", "live.com", "msn.com",
    "comcast.net", "att.net", "protonmail.com", "me.com",
    "schoolspring.com", "applitrack.com", "frontlineeducation.com", "powerschool.com", "tedk12.com",
    "peopleadmin.com", "k12jobspot.com", "edjoin.org", "governmentjobs.com", "winocular.com", "taleo.net",
    "icims.com", "myworkdayjobs.com", "paycomonline.net", "ultipro.com", "recruitingsite.com", "jobs.jobs",
    "teachlouisiana.net", "linkedin.com", "indeed.com",
)
GENERIC_WORDS = {
    "the", "of", "and", "school", "schools", "district", "public", "independent", "isd", "cisd", "usd", "unified",
    "county", "city", "parish", "system", "area", "consolidated", "community", "union", "board", "education",
    "high", "joint", "elementary", "regional", "sd", "no", "academy", "charter", "inc", "center", "centre", "cusd",
    "educational", "service", "services", "unit", "township", "local", "exempted", "village", "department",
}


def _base_domain(host: str) -> str:
    host = host.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _is_school_domain(host: str) -> bool:
    d = _base_domain(host)
    return bool(d) and not any(d == x or d.endswith("." + x) for x in NOT_SCHOOL_DOMAINS)


def name_tokens(name: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return [w for w in words if w not in GENERIC_WORDS and len(w) >= 3]


def candidate_domains(db, district: District) -> list[tuple[str, str]]:
    """[(domain, how_found)] from the district's own published data."""
    out: dict[str, str] = {}
    jobs = db.scalars(select(Job).where(Job.district_id == district.id)).all()
    job_ids = [j.id for j in jobs]
    if job_ids:
        emails = db.scalars(select(Contact.email).join(JobContact, JobContact.contact_id == Contact.id)
                            .where(JobContact.job_id.in_(job_ids), Contact.email.is_not(None))).all()
        for e in emails:
            dom = e.split("@")[-1].lower()
            if _is_school_domain(dom):
                out.setdefault(dom, f"domain of the district's published staff email ({e.split('@')[0][:2]}…@{dom})")
    for j in jobs:
        for u in (j.official_job_url, j.application_url):
            h = urlparse(u or "").netloc
            if h and _is_school_domain(h):
                out.setdefault(_base_domain(h), "domain of the district's official job posting")
    return list(out.items())


def _page_matches(html: str, name: str) -> tuple[bool, str]:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "")[:200]
    heads = " ".join(h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2"])[:6])
    meta = " ".join(m.get("content", "") for m in soup.find_all("meta", attrs={"property": "og:site_name"}))
    text = f"{title} {heads} {meta}".lower()
    tokens = name_tokens(name)
    if not tokens:
        return False, title
    hits = sum(1 for t in tokens if re.search(r"\b" + re.escape(t) + r"\b", text))
    return hits >= max(1, (len(tokens) + 1) // 2), title


def domain_matches_name(domain: str, name: str) -> bool:
    """'greenecountyschools.com' ~ 'Greene County Public Schools'; 'cguhsd.org' ~ initials of
    'Casa Grande Union High School District'."""
    label = re.sub(r"[^a-z0-9]", "", _base_domain(domain).split(".")[0])
    if not label:
        return False
    if any(len(t) >= 4 and t in label for t in name_tokens(name)):
        return True
    words = [w for w in re.findall(r"[a-z0-9]+", (name or "").lower()) if w not in ("the", "of", "and")]
    initials = "".join(w[0] for w in words)
    return len(label) >= 3 and (label == initials or (len(initials) >= 3 and label.startswith(initials[:len(label)]) and len(label) >= len(initials) - 1))


def verify_site(client, domain: str, name: str) -> dict:
    """{'url','title'} when confirmed; {'unreachable': reason} when the site can't be opened from here."""
    reasons = []
    for url in (f"https://www.{domain}/", f"https://{domain}/"):
        res = client.get(url, source_name="Official website check", log=False, timeout=12)
        if res.crawl_status == "ROBOTS_BLOCKED":
            reasons.append("its site rules block automated checks")
            continue
        if not res.ok or not res.text:
            reasons.append("it blocks automated visitors (HTTP 403)" if res.status == 403
                           else "it did not respond from this network (many U.S. district sites block visitors outside the U.S.)"
                           if res.error and "Timeout" in res.error else
                           "its security certificate could not be verified" if res.error and "CERTIFICATE" in res.error
                           else f"it returned {res.error or res.status}")
            continue
        final_host = urlparse(res.final_url or url).netloc
        if not _is_school_domain(final_host):
            reasons.append(f"it redirects to {final_host}")
            continue
        ok, title = _page_matches(res.text, name)
        if ok:
            return {"url": f"{urlparse(res.final_url or url).scheme}://{final_host}/", "title": title}
        reasons.append(f"the page title “{title[:80]}” does not name the district")
    return {"unreachable": reasons[0] if reasons else "no response"}


def find_district_website(db, client, district: District, force: bool = False) -> dict | None:
    if district.website and not force:
        return None
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    likely = None
    for domain, how in candidate_domains(db, district):
        found = verify_site(client, domain, district.name)
        if "url" in found:
            district.website = found["url"]
            district.website_evidence = {
                "url": found["url"], "page_title": found["title"], "how_found": how,
                "check": f"Page title/heading names “{district.name}”",
                "verification_status": "VERIFIED", "checked_at": now,
            }
            db.commit()
            return district.website_evidence
        # Couldn't open the page, but the district's own email domain matches its name/initials.
        if likely is None and "the page title" not in found["unreachable"] and domain_matches_name(domain, district.name):
            likely = {"url": f"https://www.{domain}/", "page_title": None, "how_found": how,
                      "check": f"Domain matches the district name, but the page couldn't be opened from here: {found['unreachable']}",
                      "verification_status": "PARTIALLY_VERIFIED", "checked_at": now}
    if likely and not (district.website_evidence or {}).get("verification_status") == "VERIFIED":
        district.website = likely["url"]
        district.website_evidence = likely
        db.commit()
        return likely
    return None


def find_missing_websites(db, client, stop=None, progress=None) -> dict:
    # Missing websites, plus "likely" ones that couldn't be opened last time (they may confirm now).
    todo = [d for d in db.scalars(select(District)).all()
            if not d.website or ((d.website_evidence or {}).get("verification_status") == "PARTIALLY_VERIFIED"
                                 and (d.website_evidence or {}).get("how_found") != "Added by you")]
    found = 0
    for i, d in enumerate(todo, 1):
        if stop and stop():
            break
        if progress and i % 5 == 1:
            progress(i, len(todo))
        ev = find_district_website(db, client, d, force=True)
        if ev and ev.get("verification_status") == "VERIFIED":
            found += 1
    return {"districts_checked": len(todo), "websites_found": found}
