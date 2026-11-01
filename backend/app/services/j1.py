"""J-1 / international teacher research.

Rules:
* A vacancy is CONFIRMED_J1_VACANCY only when its own official posting says so.
* An employer is CONFIRMED_J1_EMPLOYER only with an official district/employer page (or a verified
  DISTRICT_EMPLOYER record in the sponsor database) documenting international/J-1 teacher hiring.
* A designated sponsor existing in the same state is never evidence about a specific school.
"""
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

POSITIVE_VACANCY = re.compile(
    r"(j-?1 (visa )?(sponsorship )?(is )?(available|accepted|welcome|eligible|candidates)|"
    r"(will|can|may) sponsor (a )?j-?1|j-?1 (teacher|exchange) (program|candidates|applicants)|"
    r"international (teacher|educator)s? (are )?(welcome|encouraged|eligible)|"
    r"visa sponsorship (is )?(available|provided|offered)|bridgeusa|cultural exchange teacher)",
    re.I,
)
NEGATIVE = re.compile(
    r"((does|will|can)? ?not (be able to )?(provide|offer|sponsor)[^.]{0,30}(visa|sponsorship)|"
    r"no (visa )?sponsorship|unable to sponsor|without (the need for )?(visa )?sponsorship|"
    r"not eligible for (visa )?sponsorship|must be a u\.?s\.? citizen)",
    re.I,
)
FRIENDLY = re.compile(
    r"(international (teacher|educator|recruit|candidate|hiring)s?|foreign (teacher|educator)s?|"
    r"\bj-1\b|\bj1 visa\b|teacher exchange|exchange visitor|visa (sponsor|support)|global educators?|cultural exchange)",
    re.I,
)
LINK_HINT = re.compile(r"international|j-?1|visa|exchange|global|foreign", re.I)


def _quote(text: str, m: re.Match, width=140) -> str:
    s = max(0, m.start() - width // 2)
    return re.sub(r"\s+", " ", text[s:m.end() + width // 2]).strip()


def assess_vacancy_text(text: str, url: str | None) -> tuple[str | None, list]:
    """Return (status or None, evidence list) from the posting's own text."""
    if not text:
        return None, []
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    neg = NEGATIVE.search(text)
    if neg:
        return "NO_SPONSORSHIP", [{"url": url, "quote": _quote(text, neg), "kind": "vacancy_negative", "checked_at": now}]
    pos = POSITIVE_VACANCY.search(text)
    if pos:
        return "CONFIRMED_J1_VACANCY", [{"url": url, "quote": _quote(text, pos), "kind": "vacancy_positive", "checked_at": now}]
    fr = FRIENDLY.search(text)
    if fr:
        return "INTERNATIONAL_FRIENDLY", [{"url": url, "quote": _quote(text, fr), "kind": "vacancy_mention", "checked_at": now}]
    return None, []


def combine(vacancy_status: str | None, district_status: str | None) -> str:
    if vacancy_status in ("NO_SPONSORSHIP", "CONFIRMED_J1_VACANCY"):
        return vacancy_status
    if district_status == "CONFIRMED_J1_EMPLOYER":
        return "CONFIRMED_J1_EMPLOYER"
    if vacancy_status == "INTERNATIONAL_FRIENDLY" or district_status == "INTERNATIONAL_FRIENDLY":
        return "INTERNATIONAL_FRIENDLY"
    if district_status == "NEEDS_CONFIRMATION":
        return "NEEDS_CONFIRMATION"
    return "UNKNOWN"


def research_district_site(client, district, source_name="J-1 research") -> tuple[str | None, list]:
    """Crawl a district's official site/careers page (shallow) for international-teacher evidence."""
    start_urls = [u for u in [district.careers_url, district.website] if u]
    if not start_urls:
        return None, []
    evidence, visited = [], set()
    queue = list(start_urls)
    base_hosts = {urlparse(u).netloc for u in start_urls}
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    while queue and len(visited) < 6:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        res = client.get(url, source_name=source_name)
        if not res.ok:
            continue
        soup = BeautifulSoup(res.text, "lxml")
        text = soup.get_text(" ", strip=True)
        for rx, kind in ((POSITIVE_VACANCY, "employer_positive"), (FRIENDLY, "employer_mention")):
            m = rx.search(text)
            if m:
                evidence.append({"url": url, "quote": _quote(text, m), "kind": kind, "checked_at": now})
                break
        neg = NEGATIVE.search(text)
        if neg:
            evidence.append({"url": url, "quote": _quote(text, neg), "kind": "employer_negative", "checked_at": now})
        for a in soup.find_all("a", href=True):
            label = (a.get_text(" ", strip=True) or "") + " " + a["href"]
            if LINK_HINT.search(label):
                nxt = urljoin(url, a["href"])
                if urlparse(nxt).netloc in base_hosts and nxt not in visited and len(queue) < 10:
                    queue.append(nxt)
    kinds = {e["kind"] for e in evidence}
    if "employer_positive" in kinds:
        return "CONFIRMED_J1_EMPLOYER", evidence
    if "employer_negative" in kinds and "employer_mention" not in kinds:
        return "NO_SPONSORSHIP", evidence
    if "employer_mention" in kinds:
        return "INTERNATIONAL_FRIENDLY", evidence
    return None, evidence
