"""H-1B sponsor employers: find their current Math/STEM openings.

For each employer on the user's list:
  1. Work out its job system from the careers link (or links on that careers page).
  2. Read the live board where the job system is readable: Frontline/AppliTrack, EDJOIN, BambooHR.
  3. Also match jobs already found by the national scans (SchoolSpring, K12JobSpot, EDJOIN, Frontline)
     whose employer name matches.
  4. Otherwise record honestly why the board can't be read (blocked, moved, unsupported system).
robots.txt and per-host rate limits are respected throughout; nothing is guessed.
"""
import re
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from sqlalchemy import select

from ..models import H1BEmployer, Job
from .connectors import applitrack, edjoin
from .connectors.base import RawJob, html_to_text, parse_date
from .ingest import profile_dict, upsert_raw_job
from .taxonomy import STATES, is_relevant_title

GENERIC = {"the", "of", "and", "school", "schools", "district", "public", "board", "system", "co", "company",
           "group", "inc", "no", "directors", "education"}
# District-type words distinguish different districts ("Pasadena Unified" CA vs "Pasadena Independent" TX,
# "Lexington City" vs "Lexington County"), so they are kept, in one normal form.
TYPE_WORDS = {"independent": "isd", "isd": "isd", "unified": "usd", "usd": "usd", "consolidated": "cisd", "cisd": "cisd",
              "county": "county", "co": "county", "city": "city", "parish": "parish", "borough": "borough",
              "township": "township", "charter": "charter", "academy": "academy"}
UNSUPPORTED = {
    "taleo": "uses Oracle Taleo, which can't be read automatically",
    "smartrecruiters": "uses SmartRecruiters, whose rules block automated tools",
    "lever": "uses Lever (not readable from this page)",
    "frontline_login": "uses a Frontline login page (no public job list linked)",
    "schoolspring_board": "its SchoolSpring board loads through an anti-bot check and couldn't be read",
}
STATE_ZIP_RE = re.compile(r",\s*(%s)\s+(\d{5})" % "|".join(STATES))


def name_tokens(name: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", (name or "").lower().replace("&amp;", "&")):
        if w in TYPE_WORDS:
            out.add(TYPE_WORDS[w])
        elif w not in GENERIC and len(w) > 1:
            out.add(w)
    return out


def names_match(a: str, b: str, strict: bool = True) -> bool:
    """strict: same name words and same district type. loose: 75% overlap (only used with website proof)."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    return (not strict) and len(ta & tb) / len(ta | tb) >= 0.75


# ------------------------------------------------------------------ board detection
def detect_board(url: str, html: str | None = None) -> tuple[str | None, str | None, str | None]:
    """(board_type, board_ref, board_url) from a URL and optionally the page it serves."""
    def from_text(t: str):
        m = re.search(r"applitrack\.com/([A-Za-z0-9_\-]+)/onlineapp", t, re.I)
        if m:
            return "applitrack", m.group(1), applitrack.board_url(m.group(1))
        m = re.search(r"edjoin\.org/[^\"'\s]*districtID=(\d+)", t, re.I)
        if m and m.group(1) != "0":
            return "edjoin", m.group(1), f"https://www.edjoin.org/Home/Jobs?districtID={m.group(1)}"
        m = re.search(r"([a-z0-9\-]+)\.bamboohr\.com", t, re.I)
        if m and m.group(1).lower() not in ("www", "api"):
            return "bamboohr", m.group(1).lower(), f"https://{m.group(1).lower()}.bamboohr.com/careers"
        if re.search(r"taleo\.net", t, re.I):
            return "taleo", None, None
        if re.search(r"smartrecruiters\.com", t, re.I):
            return "smartrecruiters", None, None
        if re.search(r"(tedk12\.com|ted\.peopleadmin\.com|\.schoolspring\.com)", t, re.I):
            return "schoolspring_board", None, None
        if re.search(r"jobs\.lever\.co|lever\.co/", t, re.I):
            return "lever", None, None
        if re.search(r"frontlineeducation\.com", t, re.I):
            return "frontline_login", None, None
        if re.search(r"edjoin\.org", t, re.I):
            return "edjoin_name", None, "https://www.edjoin.org/"
        return None, None, None

    found = from_text(url)
    if found[0] or not html:
        return found
    soup = BeautifulSoup(html, "lxml")
    links = " ".join(urljoin(url, a["href"]) for a in soup.find_all("a", href=True))
    links += " " + " ".join(f.get("src", "") for f in soup.find_all("iframe"))
    return from_text(links)


def resolve(client, emp: H1BEmployer) -> None:
    btype, ref, burl = detect_board(emp.careers_url)
    if not btype:
        res = client.get(emp.careers_url, source_name=f"H-1B: {emp.name}", timeout=25)
        if res.crawl_status == "ROBOTS_BLOCKED":
            emp.board_type, emp.status, emp.status_detail = "none", "UNREADABLE", "its site rules block automated tools"
            return
        if not res.ok:
            emp.board_type, emp.status = "none", "UNREADABLE"
            emp.status_detail = ("the careers page blocks automated visitors (HTTP 403)" if res.status == 403
                                 else "the careers page link no longer exists (HTTP 404) — it may have moved" if res.status == 404
                                 else "the careers page did not respond from this network" if res.error and "Timeout" in res.error
                                 else f"the careers page could not be opened ({res.error or res.status})")
            return
        btype, ref, burl = detect_board(emp.careers_url, res.text)
    emp.board_type, emp.board_ref, emp.board_url = btype or "none", ref, burl


# ------------------------------------------------------------------ live boards
def _applitrack(client, emp) -> tuple[list[RawJob], int | None, str | None]:
    page = client.get(applitrack.board_url(emp.board_ref), source_name=f"H-1B: {emp.name}", timeout=60)
    state = None
    if page.ok:
        m = STATE_ZIP_RE.search(BeautifulSoup(page.text, "lxml").get_text(" ", strip=True))
        state = m.group(1) if m else None
    res = client.get(applitrack.feed_url(emp.board_ref), source_name=f"H-1B: {emp.name}", timeout=150)
    if not res.ok:
        raise RuntimeError(f"Frontline board did not load ({res.error or res.status})")
    title = BeautifulSoup(page.text, "lxml").title.get_text(strip=True) if page.ok and BeautifulSoup(page.text, "lxml").title else ""
    district = re.sub(r"\s*-\s*Frontline Recruitment\s*$", "", title).strip() or emp.name
    raws, total = applitrack.parse_feed(res.text, client=emp.board_ref, district_name=district, state=state, city=None)
    return raws, total, state


def _edjoin(client, emp) -> tuple[list[RawJob], int | None, str | None]:
    url = (f"{edjoin.BASE}/Home/LoadJobs?rows=100&page=1&sort=postingDate&sortVal=0&order=desc&keywords=&location="
           f"&searchType=all&regions=&jobTypes=&days=0&empType=&catID=0&onlineApps=&recruitmentCenterID=0&stateID=0"
           f"&regionID=0&districtID={emp.board_ref}&searchID=0")
    res = client.get(url, source_name=f"H-1B: {emp.name}", headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
    if not res.ok:
        raise RuntimeError(f"EDJOIN did not respond ({res.error or res.status})")
    data = res.json()
    rows = [r for r in (data.get("data") or []) if is_relevant_title(r.get("positionTitle") or "")[0]]
    raws = []
    for r in rows:
        page = client.get(edjoin.posting_url(r.get("postingID")), source_name=f"H-1B: {emp.name}")
        raws.append(edjoin.build_job(r, page.text if page.ok else None))
    return raws, int(data.get("totalRecords") or 0), "CA"


def _bamboohr(client, emp) -> tuple[list[RawJob], int | None, str | None]:
    co = emp.board_ref
    res = client.get(f"https://{co}.bamboohr.com/careers/list", source_name=f"H-1B: {emp.name}", headers={"Accept": "application/json"})
    if not res.ok:
        raise RuntimeError(f"BambooHR did not respond ({res.error or res.status})")
    items = res.json().get("result") or []
    raws, state = [], None
    for it in items:
        title = (it.get("jobOpeningName") or "").strip()
        loc = it.get("location") or {}
        st = loc.get("state") or ""
        code = st.upper() if st.upper() in STATES else next((k for k, v in STATES.items() if v.lower() == st.lower()), None)
        state = state or code
        if not is_relevant_title(title)[0]:
            continue
        url = f"https://{co}.bamboohr.com/careers/{it.get('id')}"
        raws.append(RawJob(source_name=f"BambooHR – {emp.name}", source_url=url, source_type="EMPLOYER_SITE", tier=1,
                           title=title, external_id=str(it.get("id")), official_url=url, application_url=url,
                           employer_name=emp.name, school_name=(it.get("departmentLabel") or None),
                           city=loc.get("city"), state=code, employment_type=it.get("employmentStatusLabel"),
                           listed_in_feed=True, feed_key=f"bamboohr:{co}"))
    return raws, len(items), state


READERS = {"applitrack": (_applitrack, "Frontline board"), "edjoin": (_edjoin, "EDJOIN"), "bamboohr": (_bamboohr, "BambooHR")}


# ------------------------------------------------------------------ check one employer
def _domain(url: str | None) -> str:
    h = urlparse(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def matched_scan_jobs(db, emp: H1BEmployer) -> tuple[list[Job], str | None]:
    """Jobs from the national scans whose employer is this employer. Same-name districts in different
    states (e.g. several 'Lee County' districts) are told apart by state or by the district's official
    website domain; if that can't be settled, nothing is matched."""
    jobs = db.scalars(select(Job).where(Job.is_demo.is_(False), Job.job_status != "CLOSED")).all()
    dom = _domain(emp.careers_url)

    def site_matches(j):
        w = _domain(j.district.website) if j.district and j.district.website else ""
        return bool(w and dom and (w == dom or dom.endswith("." + w) or w.endswith("." + dom)))

    # A name that reduces to one plain word ("District of Columbia Public Schools" -> "columbia") is too weak
    # on its own: it would also match "Columbia Public Schools" in Missouri. Such names need website proof.
    toks = name_tokens(emp.name)
    weak = len(toks) < 2 and not (toks & set(TYPE_WORDS.values()))
    cand = [j for j in jobs
            if ((names_match(emp.name, j.employer_name or "") or names_match(emp.name, j.school.name if j.school else ""))
                and (not weak or site_matches(j) or (emp.state and j.state == emp.state)))
            or (names_match(emp.name, j.employer_name or "", strict=False) and site_matches(j))]
    if emp.state:
        return [j for j in cand if not j.state or j.state == emp.state], None
    states = {j.state for j in cand if j.state}
    if len(states) <= 1:
        return cand, None
    by_site = [j for j in cand if site_matches(j)]
    if by_site:
        return by_site, None
    return [], f"Name matches districts in several states ({', '.join(sorted(states))}); not linked to avoid a wrong match"


def check_employer(db, client, emp: H1BEmployer, profile=None) -> H1BEmployer:
    profile = profile or profile_dict(db)
    if not emp.board_type or emp.status == "UNREADABLE":
        resolve(client, emp)
    live_ids, total, note = [], None, None
    reader = READERS.get(emp.board_type or "")
    if not reader:
        emp.state = None     # only an employer's own board can tell us its state; clear anything older
    if reader:
        fn, label = reader
        try:
            raws, total, state = fn(client, emp)
            emp.state = emp.state or state
            stats, seen = {}, set()
            for raw in raws:
                if raw.date_posted and (date.today() - raw.date_posted).days > 120:
                    continue
                job, _ = upsert_raw_job(db, raw, profile, stats, seen)
                if job.job_status != "CLOSED":
                    live_ids.append(job.id)
            emp.status = "LIVE"
            emp.status_detail = f"Read live from the employer's {label}"
        except Exception as e:
            emp.status, emp.status_detail = "SCANS_ONLY", f"Live board couldn't be read this time: {e}"[:480]
    elif emp.board_type in UNSUPPORTED:
        emp.status, emp.status_detail = "UNREADABLE", "The careers page " + UNSUPPORTED[emp.board_type]
    elif emp.board_type in ("none", None) and emp.status != "UNREADABLE":
        emp.status, emp.status_detail = "UNREADABLE", "No job list or known job system was found on the careers page"
    elif emp.board_type == "edjoin_name":
        emp.status, emp.status_detail = "SCANS_ONLY", "Posts on EDJOIN; openings are matched from EDJOIN scans by name"
    matched_jobs, ambiguity = matched_scan_jobs(db, emp)
    matched = [j.id for j in matched_jobs]
    if ambiguity:
        emp.status_detail = ((emp.status_detail or "") + ". " + ambiguity).lstrip(". ")
    # The employer's state is only ever taken from its own board (above), never inferred from name matches.
    ids = list(dict.fromkeys(live_ids + matched))
    if emp.status == "UNREADABLE" and matched:
        # Careers page can't be read, but the national scans found this employer's openings.
        emp.status = "SCANS_ONLY"
        emp.status_detail = f"Found by the national scans ({len(matched)}). Careers page: " + (emp.status_detail or "").lstrip(". ")
    emp.job_ids = ids
    emp.total_openings = total
    emp.last_checked = datetime.utcnow()
    db.commit()
    return emp


def check_all(db, client, stop=None, progress=None) -> dict:
    profile = profile_dict(db)
    emps = db.scalars(select(H1BEmployer).order_by(H1BEmployer.rank)).all()
    live = with_jobs = openings = 0
    for i, e in enumerate(emps, 1):
        if stop and stop():
            break
        if progress:
            progress(i, len(emps), e.name)
        check_employer(db, client, e, profile)
        live += e.status == "LIVE"
        with_jobs += bool(e.job_ids)
        openings += len(e.job_ids or [])
    return {"employers_checked": len(emps), "live_boards_read": live, "employers_with_math_openings": with_jobs,
            "math_stem_openings": openings}
