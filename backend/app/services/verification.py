"""Verification rules: per-field evidence, job status, freshness and email trust levels."""
import re
from datetime import date, datetime
from urllib.parse import urlparse

VERIFIED = "VERIFIED"
PARTIAL = "PARTIALLY_VERIFIED"
UNKNOWN = "UNKNOWN"
CONFLICTING = "CONFLICTING"

# Hosts of official applicant-tracking systems used by districts (Tier 2).
OFFICIAL_ATS_HOSTS = (
    "applitrack.com", "tedk12.com", "schoolspring.com", "powerschool.com", "myworkdayjobs.com",
    "governmentjobs.com", "edjoin.org", "taleo.net", "icims.com", "oraclecloud.com", "k12jobspot.com",
    "frontlineeducation.com", "paycomonline.net", "ultipro.com", "recruitingsite.com",
    "peopleadmin.com", "winocular.com", "jobappnetwork.com", "ttcportals.com",
)

# Placeholder values some ATS postings put in contact fields. They are not contacts.
PLACEHOLDER_EMAIL_DOMAINS = ("jobs.jobs", "example.com", "example.org", "test.com", "none.com", "noemail.com")
PLACEHOLDER_EMAIL_RE = re.compile(r"^(see|n/?a|none|noreply|no-reply|donotreply|do-not-reply|test)[\w.+-]*@", re.I)
PLACEHOLDER_NAME_RE = re.compile(r"^\s*(see\s+(the\s+)?(job\s+)?posting|n/?a|none|tbd|to be determined|apply online|"
                                 r"see (attached|description|below)|various|staff|anonymous(\s+anonymous)?|unknown(\s+unknown)?|"
                                 r"test(\s+test)?|first\s+last|firstname\s+lastname|name|contact)\s*\.?\s*$", re.I)
PLACEHOLDER_PHONE_RE = re.compile(r"^\D*(\d)\1{2}\D*\1{3}\D*\1{4}\D*$|555\D*55\D*5\D*5555|^\D*555\D*01\d\d\D*$|"
                                  r"^\D*(123\D*456\D*7890|000\D*000\D*0000)\D*$")


def is_placeholder_phone(phone: str | None) -> bool:
    return bool(phone) and bool(PLACEHOLDER_PHONE_RE.search(phone.strip()))
# Names that are departments or roles, not people (kept as the contact's title instead).
DEPARTMENT_NAME_RE = re.compile(r"\b(human\s+resources|hr(\s+(department|office|team))?|personnel|"
                                r"recruit(ment|ing)(\s+(office|team))?|talent\s+acquisition|employment\s+office|"
                                r"hiring\s+(team|committee)|administration|principal'?s\s+office|front\s+office|office)\b", re.I)


# Compliance / legal-notice mailboxes that appear in posting footers; they are not hiring contacts.
NON_HIRING_EMAIL_RE = re.compile(r"^(title[\s._-]?(ix|9)|titleix\w*|title9\w*|section[._-]?504|504\w*|ada\w*coord\w*|ada|"
                                 r"civil[._-]?rights|compliance|equity|nondiscrimination|non[._-]?discrimination|"
                                 r"eeo\w*|webmaster|privacy|foia|records|publicrecords|legal)@", re.I)
LEGAL_NOTICE_RE = re.compile(r"(title\s+ix|section\s+504|non-?discriminat|equal\s+(employment\s+)?opportunity|"
                             r"civil\s+rights|americans\s+with\s+disabilities|harass|inquiries\s+regarding|"
                             r"does\s+not\s+discriminate|compliance\s+(officer|coordinator))", re.I)


def is_non_hiring_email(email: str | None) -> bool:
    return bool(email) and bool(NON_HIRING_EMAIL_RE.match(email.strip()))


def email_in_legal_notice(text: str, email: str) -> bool:
    """True when the email sits inside an EEO / Title IX / 504 notice rather than hiring instructions."""
    i = text.lower().find(email.lower())
    if i < 0:
        return False
    return bool(LEGAL_NOTICE_RE.search(text[max(0, i - 350): i + 150]))


def is_placeholder_email(email: str | None) -> bool:
    if not email:
        return False
    e = email.strip().lower()
    return e.split("@")[-1] in PLACEHOLDER_EMAIL_DOMAINS or bool(PLACEHOLDER_EMAIL_RE.match(e))
DISCOVERY_HOSTS = ("linkedin.com", "indeed.com", "ziprecruiter.com", "glassdoor.com", "joinhandshake.com",
                   "google.com")
OFFICIAL_TLD_HINTS = (".k12.", ".edu", ".gov", "isd.", "schools.", "district", "k12")

CLOSED_PHRASES = re.compile(
    r"(this (job|position|posting|vacancy) (is|has been) (no longer available|closed|filled|removed)|"
    r"posting (has )?(closed|expired)|no longer accepting applications|position (has been )?filled|"
    r"job (posting )?not found|this job has expired|vacancy (is )?closed|applications are closed)",
    re.I,
)


def evidence(value, source_url, source_type, status, confidence="HIGH", note=None):
    return {
        "value": value,
        "source_url": source_url,
        "source_type": source_type,
        "verification_status": status,
        "verified_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "confidence": confidence,
        "note": note,
    }


def host_of(url: str | None) -> str:
    return (urlparse(url).netloc or "").lower() if url else ""


def classify_source(url: str | None) -> tuple[str, int]:
    """Return (source_type, tier) for a URL."""
    h = host_of(url)
    if not h:
        return "UNKNOWN", 3
    if any(h.endswith(d) for d in DISCOVERY_HOSTS):
        return "DISCOVERY", 3
    if any(h.endswith(d) for d in OFFICIAL_ATS_HOSTS):
        return "OFFICIAL_ATS", 2
    if any(k in h for k in OFFICIAL_TLD_HINTS):
        return "OFFICIAL_DISTRICT", 1
    return "EMPLOYER_SITE", 2


def days_old(posted: date | None, today: date | None = None) -> int | None:
    if not posted:
        return None
    today = today or date.today()
    return max(0, (today - posted).days)


def freshness(posted: date | None) -> dict:
    d = days_old(posted)
    if d is None:
        return {"days": None, "label": "Date unknown", "color": "gray"}
    label = "TODAY" if d == 0 else ("1 DAY" if d == 1 else (f"{d} DAYS" if d <= 30 else "30+ DAYS"))
    if d <= 14:
        color = "green"
    elif d <= 30:
        color = "yellow"
    elif d <= 60:
        color = "orange"
    else:
        color = "red"
    return {"days": d, "label": label, "color": color}


def decide_job_status(*, closing: date | None, until_filled: bool, official_http: int | None,
                      official_text: str | None, listed_in_feed: bool | None, posted: date | None) -> tuple[str, str]:
    """Combine signals into ACTIVE / POSSIBLY_ACTIVE / CLOSED / UNKNOWN with a human reason."""
    today = date.today()
    if closing and closing < today:
        return "CLOSED", f"Closing date {closing.isoformat()} has passed"
    if official_http in (404, 410):
        return "CLOSED", f"Official posting returned HTTP {official_http}"
    if official_text and CLOSED_PHRASES.search(official_text):
        return "CLOSED", "Official posting states the vacancy is closed"
    if listed_in_feed is False:
        return "CLOSED", "No longer listed on the official job board"
    if listed_in_feed and official_http and 200 <= official_http < 300:
        return "ACTIVE", "Listed on official job board and posting page loads"
    if listed_in_feed:
        why = "Listed on the official job board"
        if closing:
            why += f"; closes {closing.isoformat()}"
        elif until_filled:
            why += "; open until filled"
        return "ACTIVE", why
    if official_http and 200 <= official_http < 300:
        d = days_old(posted)
        if d is not None and d > 60 and not closing:
            return "POSSIBLY_ACTIVE", "Posting page loads but the listing is over 60 days old"
        return "ACTIVE", "Official posting page loads with no closed notice"
    return "UNKNOWN", "Could not reach an official source"


# ------------------------------------------------------------------ emails
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def extract_emails(text: str) -> list[str]:
    return sorted({e.strip(".").lower() for e in EMAIL_RE.findall(text or "")})


def email_status_for(email: str | None, found_on_url: str | None, page_text: str | None = None) -> str:
    """Emails are VERIFIED only when the exact address appears on an official source page.

    There is no code path that constructs an address from a name pattern.
    """
    if not email:
        return "NONE"
    if not found_on_url:
        return "DO_NOT_USE"
    if page_text is not None and email.lower() not in page_text.lower():
        return "DO_NOT_USE"
    st, _ = classify_source(found_on_url)
    if st in ("OFFICIAL_ATS", "OFFICIAL_DISTRICT", "EMPLOYER_SITE"):
        return "VERIFIED"
    return "PUBLISHED_ELSEWHERE"
