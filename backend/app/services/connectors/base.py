"""Common shape for jobs produced by connectors (before normalization / dedup)."""
import html as _html
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from bs4 import BeautifulSoup


@dataclass
class RawContact:
    full_name: str | None
    title: str | None
    email: str | None
    phone: str | None
    relationship: str           # JOB_POSTER | VACANCY_CONTACT | ...
    confidence: str             # HIGH | MEDIUM | LOW
    evidence_url: str | None
    evidence_text: str | None = None


@dataclass
class RawJob:
    source_name: str
    source_url: str              # where we saw it (listing/detail/API)
    source_type: str             # OFFICIAL_ATS | OFFICIAL_DISTRICT | STATE_BOARD | DISCOVERY
    tier: int
    title: str
    external_id: str | None = None
    official_url: str | None = None
    application_url: str | None = None
    employer_name: str | None = None      # district / charter network
    school_name: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    date_posted: date | None = None
    closing_date: date | None = None
    closing_text: str | None = None
    until_filled: bool = False
    salary_min: float | None = None
    salary_max: float | None = None
    salary_text: str | None = None
    employment_type: str | None = None
    description: str | None = None
    requirements: str | None = None
    certification_requirements: str | None = None
    contacts: list[RawContact] = field(default_factory=list)
    listed_in_feed: bool | None = True
    page_text: str | None = None          # raw text of the official source (for email verification)
    feed_key: str | None = None           # identifies the feed for closed-job detection
    extra: dict = field(default_factory=dict)


def html_to_text(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\n{3,}", "\n\n", BeautifulSoup(s, "lxml").get_text("\n", strip=True))


def parse_date(s) -> date | None:
    if not s:
        return None
    if isinstance(s, date):
        return s
    s = str(s).strip()
    for candidate in (s, s[:19], s[:10]):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    try:
        from dateutil import parser
        return parser.parse(s, fuzzy=True).date()
    except Exception:
        return None


def unescape(s: str) -> str:
    return _html.unescape(s or "").strip()


MONEY_RE = re.compile(r"\$\s?(\d{2,3}(?:,\d{3})+|\d{4,6})(?:\.\d{2})?")


def salary_from_text(text: str) -> tuple[float | None, float | None, str | None]:
    """Extract an annual salary range only when dollar amounts are explicitly published."""
    if not text:
        return None, None, None
    vals = [float(m.group(1).replace(",", "")) for m in MONEY_RE.finditer(text)]
    vals = [v for v in vals if 20000 <= v <= 250000]
    if not vals:
        return None, None, None
    m = MONEY_RE.search(text)
    s = max(0, m.start() - 60)
    snippet = re.sub(r"\s+", " ", text[s:m.end() + 80]).strip()
    return min(vals), max(vals), snippet
