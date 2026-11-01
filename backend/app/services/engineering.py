"""Engineering, Software / AI / Data Science and Engineering Instructor jobs in the USA, matched to the user's profile.

Sources (all allow automated reading; robots.txt and rate limits respected):
  INDUSTRY    Hardware / embedded / electronics / robotics roles and
  SOFTWARE    software / AI / ML / deep learning / data science roles, both from the official Greenhouse, Lever,
              Ashby and Workable job boards of U.S. companies, The Muse public job API, and the remote-only boards
              Remotive, Remote OK, We Work Remotely, Himalayas and Jobicy (U.S.-eligible or worldwide postings only).
              LinkedIn, Indeed, Glassdoor, ZipRecruiter and Dice do not allow automated reading; the page links to
              their own search results instead.
  INSTRUCTOR  Inside Higher Ed and Chronicle of Higher Education job feeds (colleges, community and
              technical colleges, universities) + K-12 engineering / robotics / CTE teacher jobs already
              found by the teaching scans.
Every posting keeps its source link. Sponsorship, citizenship and experience requirements are read
from the posting text itself; nothing is assumed.
"""
import html as _html
import re
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from bs4 import BeautifulSoup
from sqlalchemy import select

from ..models import EngJob, Job, User
from .taxonomy import NAME_TO_ABBR, STATES

# ---------------------------------------------------------------- profile (from the user's description)
PROFILE = {
    "degrees": ["BS Electronics Engineering", "BS Computer Science",
                "Master's in Electronics and Telecommunication Engineering"],
    "skills": ["Embedded systems", "IoT", "AI / Machine learning", "Microcontrollers", "Automation",
               "Electronics", "Telecommunications", "Programming / CS"],
    "experience": "Work experience is in teaching, not yet in industry",
}
SKILLS = [
    ("Embedded systems", r"\bembedded\b|firmware|rtos|bare[- ]metal|device drivers?"),
    ("Microcontrollers", r"micro[- ]?controllers?|\bmcus?\b|arm cortex|stm32|\besp32\b|\bpic\b|\bavr\b|arduino|raspberry pi"),
    ("IoT", r"\biot\b|internet of things|connected devices?|edge devices?|sensor networks?"),
    ("AI / Machine learning", r"machine learning|\bml\b|deep learning|\bai\b|artificial intelligence|neural networks?|computer vision|perception (?:engineer|systems?|stack)|pytorch|tensorflow"),
    ("Automation / controls", r"automation|\bplcs?\b|control systems?|controls engineer|scada|mechatronics|robotics?"),
    ("Electronics / hardware", r"electronics?|electrical engineer|circuits?|\bpcbs?\b|hardware engineer|analog|mixed[- ]signal|power electronics|schematics?"),
    ("Telecommunications / RF", r"telecom|telecommunications?|\brf\b|wireless|antennas?|\b5g\b|\blte\b|signal processing|\bdsp\b|computer networking|network engineer"),
    ("Programming / CS", r"\bpython\b|\bc\+\+|\bc/c\+\+|\bembedded c\b|linux|software engineer|software develop|computer science|\bjava\b|typescript"),
    ("Deep learning / LLMs", r"deep learning|\bllms?\b|large language models?|transformers?\b|generative ai|\bnlp\b|natural language|pytorch|tensorflow|\bjax\b"),
    ("Data science / analytics", r"data scien|statistic|analytics|\bsql\b|pandas|data analysis|a/b test|predictive model"),
    ("Cloud / MLOps", r"\baws\b|\bgcp\b|azure|kubernetes|docker|mlops|\bspark\b|airflow"),
    ("FPGA / digital design", r"\bfpga\b|verilog|vhdl|\basic\b|digital design"),
    ("Test / validation", r"test engineer|validation|verification engineer|hardware test|qa engineer"),
]
OPTIONAL_SKILLS = {"FPGA / digital design", "Test / validation", "Cloud / MLOps"}   # unchecked by default
REMOTE_WORLD = re.compile(r"worldwide|anywhere|global", re.I)
REMOTE_US_OK = re.compile(r"\b(usa?|united states|u\.s\.|north(ern)? america|americas)\b", re.I)
INDUSTRY_TITLE = re.compile(
    r"(embedded|firmware|\biot\b|hardware|electrical|electronics?|\brf\b|radio|wireless|telecom|antenna|\bsignals?\b|"
    r"controls?\b|automation|\bplc\b|robotics?|mechatronics|"
    r"\bfpga\b|\basic\b|silicon|sensor|power electronics|test engineer|\bvalidation\b|systems engineer|"
    r"applications engineer|field applications?|manufacturing engineer|network engineer|autonomy|\bedge\b|\bdevices?\b)", re.I)
SOFTWARE_TITLE = re.compile(
    r"(software|machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|computer vision|perception|\bnlp\b|"
    r"natural language|\bllms?\b|generative|data scien|data engineer|data analyst|analytics engineer|applied scientist|"
    r"research scientist|research engineer|mlops|back[- ]?end|full[- ]?stack|front[- ]?end|platform engineer|"
    r"infrastructure engineer|devops|site reliability|\bsre\b|cloud engineer|python|inference|data platform|"
    r"statistician|decision scien|member of technical staff|forward deployed)", re.I)
ROLE_WORD = re.compile(r"\b(engineer|engineering|developer|technician|scientist|specialist|analyst|researcher|"
                       r"member of technical staff|statistician)\b", re.I)
SENIOR = re.compile(r"\b(senior|sr\.?|staff|principal|lead|manager|director|head of|vp|vice president|chief|"
                    r"distinguished|fellow|architect)\b", re.I)
ENTRY = re.compile(r"\b(entry[- ]level|new grad(uate)?|junior|jr\.?|associate|early[- ]career|graduate|engineer i\b|"
                   r"engineer 1\b|level 1|level i\b)\b", re.I)
EXCLUDE = re.compile(r"\b(intern(ship)?|co-?op|sales|account executive|recruiter|marketing|legal|counsel|finance|"
                     r"accountant|hr\b|people partner|designer \(ux|product designer|product manager|program manager|"
                     r"project manager|customer success|account manager)\b", re.I)
INSTRUCTOR_TITLE = re.compile(r"\b(instructor|professor|lecturer|faculty|teacher|teaching)\b", re.I)
INSTRUCTOR_SUBJECT = re.compile(r"(engineering|electrical|electronics?|computer|robotics?|mechatronics|automation|"
                                r"telecommunications?|networking|cyber|data science|machine learning|artificial intelligence|"
                                r"\bstem\b|\bcte\b|technology|physics|instrumentation|controls?)", re.I)
SPONSOR_YES = re.compile(r"(visa sponsorship (is )?(available|provided|offered)|will sponsor|sponsorship available|"
                         r"h-?1b sponsorship (is )?(available|provided)|we sponsor (visas|h-?1b))", re.I)
SPONSOR_NO = re.compile(r"((not|unable to|cannot|can't|won't|will not|do not|does not)\s+(be able to\s+)?(provide|offer|sponsor)[^.]{0,40}"
                        r"(sponsor|visa)|no (visa )?sponsorship|without (the need for )?(current or future )?(visa )?sponsorship|"
                        r"not eligible for (visa )?sponsorship|must be authorized to work in the (u\.?s|united states) without)", re.I)
CITIZEN = re.compile(r"(u\.?s\.? citizen(ship)?( is)? required|must be a u\.?s\.? citizen|united states citizen(ship)? (is )?required|"
                     r"security clearance|secret clearance|ts/sci|top secret|\bitar\b|u\.?s\.? person|export control)", re.I)
PHD = re.compile(r"\bph\.?\s?d\.?\b|doctorate|doctoral degree", re.I)
YEARS = re.compile(r"(\d{1,2})\+?\s*(?:-\s*\d+\s*)?(?:years|yrs)[^.]{0,40}(experience|industry)", re.I)
US_WORDS = re.compile(r"\b(united states|usa|u\.s\.?|us[- ]remote|remote[- ](us|usa|united states))\b", re.I)

GREENHOUSE = [("samsara", "Samsara"), ("neuralink", "Neuralink"), ("nuro", "Nuro"), ("waymo", "Waymo"),
              ("astranis", "Astranis"), ("relativity", "Relativity Space"), ("flyzipline", "Zipline"),
              ("formlabs", "Formlabs"), ("verkada", "Verkada"), ("anthropic", "Anthropic"), ("scaleai", "Scale AI"),
              ("databricks", "Databricks"), ("axon", "Axon"), ("lucidmotors", "Lucid Motors"), ("figureai", "Figure AI"),
              ("agilityrobotics", "Agility Robotics"), ("archer56", "Archer Aviation"), ("motional", "Motional"),
              ("outrider", "Outrider"), ("locusrobotics", "Locus Robotics"), ("tenstorrent", "Tenstorrent"),
              ("sambanovasystems", "SambaNova Systems"), ("lightmatter", "Lightmatter"), ("psiquantum", "PsiQuantum"),
              ("ionq", "IonQ"), ("twilio", "Twilio"), ("cloudflare", "Cloudflare"),
              # software / AI / data companies
              ("xai", "xAI"), ("snorkelai", "Snorkel AI"), ("inflectionai", "Inflection AI"), ("stripe", "Stripe"),
              ("airbnb", "Airbnb"), ("figma", "Figma"), ("instacart", "Instacart"), ("pinterest", "Pinterest"),
              ("reddit", "Reddit"), ("discord", "Discord"), ("dropbox", "Dropbox"), ("robinhood", "Robinhood"),
              ("datadog", "Datadog"), ("mongodb", "MongoDB"), ("coinbase", "Coinbase"), ("gitlab", "GitLab"),
              ("asana", "Asana"), ("duolingo", "Duolingo"), ("affirm", "Affirm"), ("lyft", "Lyft"), ("brex", "Brex"),
              ("chime", "Chime"), ("elastic", "Elastic"), ("okta", "Okta"), ("roblox", "Roblox"),
              ("sigmacomputing", "Sigma Computing"), ("fivetran", "Fivetran"), ("gusto", "Gusto"), ("toast", "Toast"),
              ("pagerduty", "PagerDuty"), ("recursionpharmaceuticals", "Recursion"), ("zocdoc", "Zocdoc"),
              ("abnormalsecurity", "Abnormal Security"), ("vercel", "Vercel")]
LEVER = [("zoox", "Zoox"), ("shieldai", "Shield AI"), ("palantir", "Palantir"), ("rigetti", "Rigetti Computing"),
         ("dexterity", "Dexterity"), ("veo", "Veo"), ("spotify", "Spotify"), ("matchgroup", "Match Group"),
         ("outreach", "Outreach"), ("jumpcloud", "JumpCloud"), ("levelai", "Level AI")]
ASHBY = [("openai", "OpenAI"), ("cohere", "Cohere"), ("perplexity", "Perplexity"), ("notion", "Notion"), ("ramp", "Ramp"),
         ("linear", "Linear"), ("replit", "Replit"), ("elevenlabs", "ElevenLabs"), ("runway", "Runway"),
         ("pinecone", "Pinecone"), ("modal", "Modal"), ("harvey", "Harvey"), ("sierra", "Sierra"), ("anyscale", "Anyscale"),
         ("deepgram", "Deepgram"), ("snowflake", "Snowflake"), ("plaid", "Plaid"), ("character", "Character.AI"),
         ("cursor", "Cursor"), ("cognition", "Cognition"), ("baseten", "Baseten"), ("lambda", "Lambda"),
         ("writer", "Writer"), ("decagon", "Decagon"), ("vanta", "Vanta"), ("zapier", "Zapier"), ("posthog", "PostHog"),
         ("supabase", "Supabase"), ("cartesia", "Cartesia"), ("suno", "Suno"), ("pika", "Pika")]
WORKABLE = [("huggingface", "Hugging Face")]
REMOTE_BOARDS = ["Remotive", "RemoteOK", "We Work Remotely", "Himalayas", "Jobicy"]
HIMALAYAS_QUERIES = ["machine learning", "data scientist", "AI engineer", "software engineer", "deep learning",
                     "data engineer", "embedded"]
MUSE_CATEGORIES = ["Science and Engineering", "Software Engineering", "Data and Analytics"]
MADGEX = [("Inside Higher Ed", "https://careers.insidehighered.com"), ("Chronicle of Higher Education", "https://jobs.chronicle.com")]
INSTRUCTOR_KEYWORDS = ["engineering instructor", "electrical engineering", "electronics instructor", "computer engineering",
                       "engineering technology", "robotics instructor", "mechatronics", "electronics technology",
                       "computer science instructor", "engineering faculty"]


# ---------------------------------------------------------------- helpers
def text_of(html: str | None) -> str:
    if not html:
        return ""
    return re.sub(r"\n{3,}", "\n\n", BeautifulSoup(_html.unescape(html), "lxml").get_text("\n", strip=True))


def us_state(location: str | None) -> tuple[bool, str | None, bool]:
    """(is_us, state_code, remote)"""
    loc = location or ""
    remote = bool(re.search(r"remote", loc, re.I))
    for m in re.finditer(r"\b([A-Z]{2})\b", loc):
        if m.group(1) in STATES:
            return True, m.group(1), remote
    low = loc.lower()
    for name, code in NAME_TO_ABBR.items():
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            return True, code, remote
    if US_WORDS.search(loc) or "(us)" in low or re.search(r"\bUSA?\b", loc):
        return True, None, remote
    return False, None, remote


def analyse(title: str, desc: str, category: str) -> dict:
    blob = f"{title}\n{desc}"
    skills = [name for name, rx in SKILLS if re.search(rx, blob, re.I)]
    years = [int(m.group(1)) for m in YEARS.finditer(desc or "") if int(m.group(1)) <= 20]
    yrs = min(years) if years else None
    level = "SENIOR" if SENIOR.search(title) else "ENTRY" if ENTRY.search(blob[:600]) or (yrs is not None and yrs <= 1) \
        else "MID" if yrs and yrs >= 3 else "UNKNOWN"
    sponsor = "NOT_OFFERED" if SPONSOR_NO.search(desc or "") else "OFFERED" if SPONSOR_YES.search(desc or "") else "UNKNOWN"
    return {"skills": skills, "years_required": yrs, "level": level, "sponsorship": sponsor,
            "citizenship_required": bool(CITIZEN.search(desc or "")), "phd_required": bool(PHD.search(desc or ""))}


def score(category: str, title: str, a: dict) -> tuple[int, dict]:
    why, gaps, parts = [], [], {}
    n = len(a["skills"])
    parts["skills"] = min(40, n * 10)
    if n:
        why.append("Matches your background in " + ", ".join(a["skills"][:5]))
    if category in ("INDUSTRY", "SOFTWARE"):
        parts["level"] = {"ENTRY": 20, "UNKNOWN": 12, "MID": 6, "SENIOR": 0}[a["level"]]
        if a["level"] == "ENTRY":
            why.append("Entry-level / early-career role — suits a first industry position")
        yrs = a["years_required"]
        parts["experience"] = 10 if yrs is None or yrs <= 2 else 4 if yrs <= 4 else 0
        if yrs and yrs >= 3:
            gaps.append(f"Asks for {yrs}+ years of experience (your experience is in teaching, not industry)")
        # BS Electronics Eng. + BS Computer Science + MS Electronics & Telecom cover electrical, software, AI and data roles.
        parts["degree"] = 15 if re.search(r"electrical|electronics|computer (engineering|science)|\bece\b|\bee\b|\bcs\b|stem|"
                                          r"software|machine learning|deep learning|data|programming", title + " " + " ".join(a["skills"]), re.I) else 10
    else:
        parts["level"] = 20
        why.append("Draws directly on your teaching experience")
        parts["experience"] = 10
        parts["degree"] = 15 if not a["phd_required"] else 6
        if a["phd_required"]:
            gaps.append("Mentions a PhD / doctorate (you have a master's degree)")
        else:
            why.append("Master's-level engineering degree typically meets instructor requirements")
    parts["sponsorship"] = {"OFFERED": 15, "UNKNOWN": 8, "NOT_OFFERED": 0}[a["sponsorship"]]
    if a["sponsorship"] == "OFFERED":
        why.append("Posting says visa sponsorship is available")
    elif a["sponsorship"] == "NOT_OFFERED":
        gaps.append("Posting says it does not sponsor work visas")
    else:
        gaps.append("Visa sponsorship not mentioned — ask the employer")
    if a["citizenship_required"]:
        parts["sponsorship"] = 0
        gaps.append("Requires U.S. citizenship / security clearance / export-control status")
    total = sum(parts.values())
    return int(total), {"why": why, "gaps": gaps, "breakdown": parts}


# ---------------------------------------------------------------- salary (as posted, never estimated)
_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*([kK])?"
# (?<![A-Za-z]) skips other dollar currencies such as CA$, AU$, NZ$ and S$.
SALARY_RANGE = re.compile(r"(?<![A-Za-z])\$\s?" + _NUM + r"\s*(?:-|–|—|to|and)\s*\$?\s?" + _NUM, re.I)
SALARY_ONE = re.compile(r"(?<![A-Za-z])\$\s?" + _NUM + r"(?![\d,])", re.I)
SAL_CONTEXT = re.compile(r"salary|\bpay\b|compensation|wage|\bbase\b|range|hourly|per hour|annual|/yr|/year|per year|a year|rate", re.I)
SAL_NOT = re.compile(r"bonus|stipend|sign[- ]?on|relocation|tuition|reimburs|401|equity|award|\bfees?\b|deposit|scholarship|"
                     r"grant|budget|raised|funding|revenue|billion|million|valuation|allowance|insurance", re.I)
INTERVAL_WORD = {"YEAR": "a year", "HOUR": "an hour", "MONTH": "a month"}


def _val(num: str, k: str | None) -> float:
    return float(num.replace(",", "")) * (1000 if k else 1)


def salary_dict(lo: float, hi: float | None, interval: str) -> dict:
    hi = hi if hi and hi != lo else None
    cents = interval == "HOUR" and any(v and v != int(v) for v in (lo, hi))
    fmt = (lambda v: f"${v:,.2f}") if cents else (lambda v: f"${v:,.0f}")
    text = fmt(lo) + (f" – {fmt(hi)}" if hi else "") + " " + INTERVAL_WORD[interval]
    return {"min": lo, "max": hi or lo, "interval": interval, "text": text}


def _plausible(lo: float, hi: float, interval: str) -> bool:
    bounds = {"YEAR": (20000, 1_000_000), "HOUR": (10, 300), "MONTH": (1500, 30000)}[interval]
    return bounds[0] <= lo <= hi <= bounds[1] and hi <= lo * 4


def parse_salary(text: str | None) -> dict | None:
    """First pay figure in the posting that is clearly labelled as salary / pay / wage."""
    if not text:
        return None
    taken = []
    cands = []
    for m in SALARY_RANGE.finditer(text):
        cands.append((m.start(), m.end(), _val(m.group(1), m.group(2)), _val(m.group(3), m.group(4))))
        taken.append((m.start(), m.end()))
    for m in SALARY_ONE.finditer(text):
        if not any(a <= m.start() < b for a, b in taken):
            v = _val(m.group(1), m.group(2))
            cands.append((m.start(), m.end(), v, v))
    for start, end, lo, hi in sorted(cands):
        before, after = text[max(0, start - 150):start], text[end:end + 40]
        if SAL_NOT.search(before[-60:] + " " + after[:25]) or not SAL_CONTEXT.search(before + " " + after):
            continue
        a = after.lower()
        if re.search(r"hour|\bhr\b|hourly", a[:30]):
            interval = "HOUR"
        elif "month" in a[:30]:
            interval = "MONTH"
        elif lo >= 10000:
            interval = "YEAR"
        elif hi < 300:
            interval = "HOUR"
        else:
            continue
        if _plausible(lo, hi, interval):
            return salary_dict(lo, hi, interval)
    return None


def annual(min_: float | None, max_: float | None, interval: str | None) -> float | None:
    v = max_ or min_
    if not v:
        return None
    return v * {"YEAR": 1, "HOUR": 2080, "MONTH": 12}.get(interval or "YEAR", 1)


def work_mode(location: str, desc: str, hint: str | None = None) -> str:
    """REMOTE | HYBRID | ONSITE | UNKNOWN — from the board's own field first, then the location, then the posting text."""
    hint = (hint or "").lower()
    if hint in ("remote", "hybrid", "onsite", "on-site"):
        return {"on-site": "ONSITE"}.get(hint, hint.upper())
    loc = location or ""
    if re.search(r"\bhybrid\b", loc, re.I):
        return "HYBRID"
    if re.search(r"\bremote\b", loc, re.I):
        return "REMOTE"
    head = (desc or "")[:4000]
    if re.search(r"\b(fully remote|100% remote|remote[- ]first|work from anywhere|this (is a )?remote (role|position))\b", head, re.I):
        return "REMOTE"
    if re.search(r"\bhybrid\b", head, re.I):
        return "HYBRID"
    return "ONSITE" if us_state(loc)[1] else "UNKNOWN"


def category_for(title: str) -> str | None:
    """INDUSTRY (hardware / embedded / electronics), SOFTWARE (software / AI / ML / data) or None."""
    if EXCLUDE.search(title) or not ROLE_WORD.search(title):
        return None
    if INDUSTRY_TITLE.search(title):
        return "INDUSTRY"
    if SOFTWARE_TITLE.search(title):
        return "SOFTWARE"
    return None


def remote_scope(text: str | None) -> str | None:
    """For remote-only boards: 'US' when U.S. residents are eligible, 'WORLDWIDE' when open everywhere, else None."""
    t = text or ""
    if REMOTE_WORLD.search(t):
        return "WORLDWIDE"
    if REMOTE_US_OK.search(t) or us_state(t)[0]:
        return "US"
    return None


def _upsert(db, category, key, source, title, company, location, url, posted, desc, seen: set, stats: dict,
            salary: dict | None = None, mode_hint: str | None = None, scope: str | None = None):
    if key in seen or any(isinstance(o, EngJob) and o.source_key == key for o in db.new):
        return None  # the same posting listed twice in one feed
    is_us, st, remote = us_state(location)
    if not is_us and not scope:
        stats["skipped_non_us"] = stats.get("skipped_non_us", 0) + 1
        return None
    a = analyse(title, desc, category)
    sc, m = score(category, title, a)
    row = db.scalars(select(EngJob).where(EngJob.source_key == key)).first()
    now = datetime.utcnow()
    if not row:
        row = EngJob(source_key=key, first_seen=now)
        db.add(row)
        stats["new"] = stats.get("new", 0) + 1
    row.category, row.source, row.title, row.company = category, source, title.strip(), company
    row.location, row.state, row.remote, row.url, row.posted = location, st, remote, url, posted or row.posted
    row.description = (desc or "")[:20000] or row.description
    row.level, row.years_required, row.sponsorship = a["level"], a["years_required"], a["sponsorship"]
    row.citizenship_required, row.phd_required, row.skills = a["citizenship_required"], a["phd_required"], a["skills"]
    row.match_score, row.match = sc, m
    sal = salary or parse_salary(desc)
    row.salary_min, row.salary_max = (sal["min"], sal["max"]) if sal else (None, None)
    row.salary_interval, row.salary_text = (sal["interval"], sal["text"]) if sal else (None, None)
    row.work_mode = work_mode(location, desc, mode_hint)
    row.remote = row.work_mode == "REMOTE"
    row.remote_scope = scope if row.work_mode == "REMOTE" else None
    row.status, row.last_seen = "ACTIVE", now
    seen.add(key)
    return row


def _close_missing(db, prefix: str, seen: set) -> int:
    n = 0
    for row in db.scalars(select(EngJob).where(EngJob.source_key.like(prefix + "%"), EngJob.status == "ACTIVE")):
        if row.source_key not in seen:
            row.status = "CLOSED"
            n += 1
    return n


# ---------------------------------------------------------------- sources
def scan_greenhouse(db, client, token, company, stats):
    # content=true returns every description in one request instead of one request per posting.
    res = client.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true", source_name=f"Greenhouse – {company}")
    if not res.ok:
        stats.setdefault("errors", []).append(f"{company}: {res.error or res.status}")
        return
    seen = set()
    for j in res.json().get("jobs", []):
        title = j.get("title") or ""
        loc = (j.get("location") or {}).get("name") or ""
        cat = category_for(title)
        if not cat or not us_state(loc)[0]:
            continue
        desc = text_of(j.get("content"))
        posted = (j.get("first_published") or j.get("updated_at") or "")[:10]
        _upsert(db, cat, f"gh:{token}:{j['id']}", f"Greenhouse – {company}", title, company, loc,
                j.get("absolute_url"), date.fromisoformat(posted) if posted else None, desc, seen, stats)
    stats["closed"] = stats.get("closed", 0) + _close_missing(db, f"gh:{token}:", seen)
    db.commit()


def scan_lever(db, client, token, company, stats):
    res = client.get(f"https://api.lever.co/v0/postings/{token}?mode=json", source_name=f"Lever – {company}")
    if not res.ok:
        stats.setdefault("errors", []).append(f"{company}: {res.error or res.status}")
        return
    seen = set()
    for j in res.json():
        title = j.get("text") or ""
        cats = j.get("categories") or {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
        cat = category_for(title)
        if not cat or not us_state(loc)[0]:
            continue
        desc = "\n".join(filter(None, [j.get("descriptionPlain"), *[text_of(l.get("content")) for l in j.get("lists") or []],
                                       j.get("additionalPlain")]))
        posted = datetime.utcfromtimestamp(j["createdAt"] / 1000).date() if j.get("createdAt") else None
        sr = j.get("salaryRange") or {}
        interval = {"per-year-salary": "YEAR", "per-hour-wage": "HOUR", "per-month-salary": "MONTH"}.get(sr.get("interval"))
        if interval and sr.get("min") and sr.get("currency", "USD") == "USD":
            sal = salary_dict(float(sr["min"]), float(sr.get("max") or sr["min"]), interval)
        else:
            sal = parse_salary(j.get("salaryDescriptionPlain"))
        _upsert(db, cat, f"lv:{token}:{j['id']}", f"Lever – {company}", title, company, loc,
                j.get("hostedUrl"), posted, desc, seen, stats, salary=sal, mode_hint=j.get("workplaceType"))
    stats["closed"] = stats.get("closed", 0) + _close_missing(db, f"lv:{token}:", seen)
    db.commit()


def scan_muse(db, client, stats, pages=3):
    seen = set()
    for muse_cat in MUSE_CATEGORIES:
        for level in ("Entry Level", "Mid Level"):
            for page in range(1, pages + 1):
                url = f"https://www.themuse.com/api/public/jobs?category={quote(muse_cat)}&level={quote(level)}&page={page}"
                res = client.get(url, source_name="The Muse")
                if not res.ok:
                    stats.setdefault("errors", []).append(f"The Muse: {res.error or res.status}")
                    break
                data = res.json()
                for j in data.get("results", []):
                    title = j.get("name") or ""
                    locs = [l.get("name", "") for l in j.get("locations") or []]
                    loc = next((l for l in locs if us_state(l)[0]), None)
                    cat = category_for(title)
                    if not loc or not cat:
                        continue
                    desc = text_of(j.get("contents"))
                    _upsert(db, cat, f"muse:{j['id']}", "The Muse", title, (j.get("company") or {}).get("name"), loc,
                            (j.get("refs") or {}).get("landing_page"), _iso_date(j.get("publication_date")),
                            f"{level}. " + desc, seen, stats)
                if page >= int(data.get("page_count") or 1):
                    break
    # The Muse API is a rolling search, so absent jobs are only closed after 21 days unseen.
    cutoff = datetime.utcnow() - timedelta(days=21)
    for row in db.scalars(select(EngJob).where(EngJob.source_key.like("muse:%"), EngJob.status == "ACTIVE", EngJob.last_seen < cutoff)):
        row.status = "CLOSED"
    db.commit()


PERIOD = {"yearly": "YEAR", "annual": "YEAR", "annually": "YEAR", "year": "YEAR", "1 year": "YEAR",
          "hourly": "HOUR", "hour": "HOUR", "1 hour": "HOUR", "monthly": "MONTH", "month": "MONTH", "1 month": "MONTH"}


def _board_salary(lo, hi, period, currency="USD") -> dict | None:
    """Salary from a board's structured fields, kept only when it is USD and plausible."""
    interval = PERIOD.get(str(period or "").lower()) or ("YEAR" if lo and float(lo) >= 10000 else None)
    if not lo or not interval or (currency or "USD").upper() != "USD":
        return None
    lo, hi = float(lo), float(hi or lo)
    return salary_dict(lo, hi, interval) if _plausible(lo, hi, interval) else None


def _close_stale(db, prefix: str, days: int = 14):
    """Rolling feeds only show the newest postings, so absent jobs are closed after some days unseen."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    for row in db.scalars(select(EngJob).where(EngJob.source_key.like(prefix + "%"), EngJob.status == "ACTIVE",
                                               EngJob.last_seen < cutoff)):
        row.status = "CLOSED"


def _iso_date(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def scan_ashby(db, client, org, company, stats):
    res = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true",
                     source_name=f"Ashby – {company}")
    if not res.ok:
        stats.setdefault("errors", []).append(f"{company}: {res.error or res.status}")
        return
    seen = set()
    for j in res.json().get("jobs", []):
        title = j.get("title") or ""
        cat = category_for(title)
        if not cat or j.get("isListed") is False:
            continue
        addr = (j.get("address") or {}).get("postalAddress") or {}
        locs = [j.get("location") or ""] + [s.get("location") or "" for s in j.get("secondaryLocations") or []]
        loc = next((l for l in locs if us_state(l)[0]), None)
        if not loc and addr.get("addressCountry") in ("United States", "USA", "US"):
            loc = ", ".join(filter(None, [addr.get("addressLocality"), addr.get("addressRegion")])) or "United States"
        if not loc:
            continue
        mode = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}.get(str(j.get("workplaceType") or "").lower())
        if not mode and j.get("isRemote"):
            mode = "remote"
        if mode == "remote" and "remote" not in loc.lower():
            loc = f"Remote – {loc}"
        sal = None
        for tier in (j.get("compensation") or {}).get("compensationTiers") or []:
            for c in tier.get("components") or []:
                if c.get("compensationType") == "Salary" and not sal:
                    sal = _board_salary(c.get("minValue"), c.get("maxValue"), c.get("interval"), c.get("currencyCode"))
        _upsert(db, cat, f"ab:{org}:{j['id']}", f"Ashby – {company}", title, company, loc, j.get("jobUrl"),
                _iso_date(j.get("publishedAt")), j.get("descriptionPlain") or text_of(j.get("descriptionHtml")),
                seen, stats, salary=sal, mode_hint=mode)
    stats["closed"] = stats.get("closed", 0) + _close_missing(db, f"ab:{org}:", seen)
    db.commit()


def scan_workable(db, client, account, company, stats):
    res = client.get(f"https://apply.workable.com/api/v1/widget/accounts/{account}?details=true", source_name=f"Workable – {company}")
    if not res.ok:
        stats.setdefault("errors", []).append(f"{company}: {res.error or res.status}")
        return
    seen = set()
    for j in res.json().get("jobs", []):
        title = j.get("title") or ""
        cat = category_for(title)
        if not cat or (j.get("country") or "") not in ("United States", "USA", "US"):
            continue
        loc = ", ".join(filter(None, [j.get("city"), j.get("state")])) or "United States"
        if j.get("telecommuting"):
            loc = f"Remote – {loc}"
        _upsert(db, cat, f"wk:{account}:{j.get('shortcode')}", f"Workable – {company}", title, company, loc,
                j.get("url") or j.get("shortlink"), _iso_date(j.get("published_on")), text_of(j.get("description")),
                seen, stats, mode_hint="remote" if j.get("telecommuting") else None)
    stats["closed"] = stats.get("closed", 0) + _close_missing(db, f"wk:{account}:", seen)
    db.commit()


def _remote_job(db, key, source, title, company, geo, url, posted, desc, seen, stats, salary=None):
    """A posting from a remote-only job board. Kept only when the board says U.S. residents (or everyone) can apply."""
    cat = category_for(title or "")
    scope = remote_scope(geo)
    if not cat or not scope or not url:
        return
    _upsert(db, cat, key, source, title.strip(), company, f"Remote – {geo or 'location not stated'}", url, posted,
            desc, seen, stats, salary=salary, mode_hint="remote", scope=scope)


def scan_remote_boards(db, client, stats):
    # Remotive public API (asks for a link back to the Remotive posting, which is the url kept here).
    seen = set()
    res = client.get("https://remotive.com/api/remote-jobs", source_name="Remotive")
    if res.ok:
        for j in res.json().get("jobs", []):
            sal = parse_salary(f"Salary: {j['salary']}") if j.get("salary") else None
            _remote_job(db, f"rmt:{j['id']}", "Remotive", j.get("title"), (j.get("company_name") or "").strip(),
                        j.get("candidate_required_location"), j.get("url"), _iso_date(j.get("publication_date")),
                        text_of(j.get("description")), seen, stats, sal)
    else:
        stats.setdefault("errors", []).append(f"Remotive: {res.error or res.status}")
    _close_stale(db, "rmt:")
    db.commit()

    # Remote OK public API (terms: link back to the Remote OK posting and name Remote OK as the source).
    seen = set()
    res = client.get("https://remoteok.com/api", source_name="RemoteOK")
    if res.ok:
        for j in res.json()[1:]:
            _remote_job(db, f"rok:{j.get('id')}", "RemoteOK", j.get("position"), j.get("company"), j.get("location"),
                        j.get("url") or j.get("apply_url"), _iso_date(j.get("date")), text_of(j.get("description")),
                        seen, stats, _board_salary(j.get("salary_min"), j.get("salary_max"), "yearly"))
    else:
        stats.setdefault("errors", []).append(f"RemoteOK: {res.error or res.status}")
    _close_stale(db, "rok:")
    db.commit()

    # We Work Remotely RSS feeds.
    seen = set()
    for feed in ("remote-programming-jobs", "remote-full-stack-programming-jobs", "remote-back-end-programming-jobs",
                 "remote-devops-sysadmin-jobs"):
        res = client.get(f"https://weworkremotely.com/categories/{feed}.rss", source_name="We Work Remotely")
        if not res.ok:
            stats.setdefault("errors", []).append(f"We Work Remotely: {res.error or res.status}")
            continue
        for item in re.findall(r"<item>(.*?)</item>", res.text, re.S):
            def tag(t):
                m = re.search(rf"<{t}>(.*?)</{t}>", item, re.S)
                return _html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip() if m else ""
            company, _, title = tag("title").partition(": ")
            link = tag("link")
            try:
                posted = parsedate_to_datetime(tag("pubDate")).date()
            except Exception:
                posted = None
            _remote_job(db, f"wwr:{link.rsplit('/', 1)[-1]}", "We Work Remotely", title or company, company if title else "",
                        tag("region"), link, posted, text_of(tag("description")), seen, stats)
    _close_stale(db, "wwr:")
    db.commit()

    # Himalayas public search API (newest first, U.S.-eligible remote jobs).
    seen = set()
    for q in HIMALAYAS_QUERIES:
        cursor = None
        for _page in range(2):
            url = f"https://himalayas.app/jobs/api/search?q={quote(q)}&country=US&sort=recent" + (f"&cursor={quote(cursor)}" if cursor else "")
            res = client.get(url, source_name="Himalayas")
            if not res.ok:
                stats.setdefault("errors", []).append(f"Himalayas: {res.error or res.status}")
                break
            data = res.json()
            for j in data.get("jobs", []):
                geo = ", ".join(j.get("locationRestrictions") or []) or "Worldwide"
                posted = datetime.utcfromtimestamp(j["pubDate"]).date() if j.get("pubDate") else None
                _remote_job(db, f"him:{j.get('guid')}", "Himalayas", j.get("title"), j.get("companyName"), geo,
                            j.get("guid") or j.get("applicationLink"), posted, text_of(j.get("description")), seen, stats,
                            _board_salary(j.get("minSalary"), j.get("maxSalary"), j.get("salaryPeriod"), j.get("currency")))
            cursor = data.get("nextCursor")
            if not cursor:
                break
    _close_stale(db, "him:")
    db.commit()

    # Jobicy public API (U.S. remote jobs in software development and data science).
    seen = set()
    for industry in ("dev", "data-science"):
        res = client.get(f"https://jobicy.com/api/v2/remote-jobs?count=50&geo=usa&industry={industry}", source_name="Jobicy")
        if not res.ok:
            stats.setdefault("errors", []).append(f"Jobicy: {res.error or res.status}")
            continue
        for j in res.json().get("jobs", []):
            _remote_job(db, f"jcy:{j.get('id')}", "Jobicy", _html.unescape(j.get("jobTitle") or ""), j.get("companyName"),
                        j.get("jobGeo"), j.get("url"), _iso_date(j.get("pubDate")), text_of(j.get("jobDescription")), seen, stats,
                        _board_salary(j.get("salaryMin"), j.get("salaryMax"), j.get("salaryPeriod"), j.get("salaryCurrency")))
    _close_stale(db, "jcy:")
    db.commit()


# ---------------------------------------------------------------- keyed job-search APIs (user's own free keys)
# JSearch (RapidAPI) returns Google-for-Jobs listings, which include LinkedIn, Indeed, Glassdoor, ZipRecruiter
# and company career pages. Adzuna is a U.S. job aggregator with an official API. Keys live in the user's settings.
DEFAULT_API_QUERIES = ["machine learning engineer", "data scientist", "AI engineer", "embedded systems engineer",
                       "electrical engineer entry level", "engineering instructor"]
JSEARCH_MIN_HOURS = 20   # free JSearch plans have a small monthly quota, so it runs at most about once a day


def api_settings(db) -> tuple[User | None, dict]:
    u = db.scalars(select(User)).first()
    return u, dict(((u.settings or {}) if u else {}).get("job_apis") or {})


def _any_category(title: str) -> str | None:
    cat = category_for(title)
    if cat:
        return cat
    return "INSTRUCTOR" if INSTRUCTOR_TITLE.search(title) and INSTRUCTOR_SUBJECT.search(title) else None


def _duplicate(db, title: str, company: str | None, prefix: str) -> bool:
    """Skip an aggregator copy of a posting already read from the employer's own board."""
    if not company:
        return False
    return db.scalar(select(EngJob.id).where(EngJob.status == "ACTIVE", ~EngJob.source_key.like(prefix + "%"),
                                             EngJob.title.ilike(title.strip()), EngJob.company.ilike(company.strip()))) is not None


def scan_jsearch(db, client, cfg: dict, stats) -> str:
    key = cfg.get("jsearch_key")
    if not key:
        return "Not set up"
    last = cfg.get("jsearch_last")
    if last and datetime.utcnow() - datetime.fromisoformat(last) < timedelta(hours=JSEARCH_MIN_HOURS):
        return f"Skipped (already searched {last[:16].replace('T', ' ')} UTC — runs about once a day to save your free quota)"
    seen, found, dups = set(), 0, 0
    for q in cfg.get("queries") or DEFAULT_API_QUERIES:
        res = client.get("https://jsearch.p.rapidapi.com/search", source_name="JSearch", api=True,
                         params={"query": f"{q} in USA", "page": 1, "num_pages": 1, "date_posted": "month", "country": "us"},
                         headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
        if not res.ok:
            msg = f"Error: HTTP {res.status}" if res.status else f"Error: {res.error}"
            try:
                msg += f" – {res.json().get('message')}"
            except Exception:
                pass
            return msg
        for j in res.json().get("data") or []:
            title, company = j.get("job_title") or "", j.get("employer_name")
            cat = _any_category(title)
            if not cat or (j.get("job_country") or "US").upper() not in ("US", "USA", "UNITED STATES"):
                continue
            if _duplicate(db, title, company, "js:"):
                dups += 1
                continue
            loc = ", ".join(filter(None, [j.get("job_city"), j.get("job_state")])) or "United States"
            remote = bool(j.get("job_is_remote"))
            if remote:
                loc = f"Remote – {loc}"
            publisher = j.get("job_publisher") or "JSearch"
            url = j.get("job_apply_link") or j.get("job_google_link")
            if not url:
                continue
            sal = _board_salary(j.get("job_min_salary"), j.get("job_max_salary"), j.get("job_salary_period"))
            row = _upsert(db, cat, f"js:{j.get('job_id')}", f"{publisher} (via JSearch)", title, company, loc, url,
                          _iso_date(j.get("job_posted_at_datetime_utc")), j.get("job_description") or "", seen, stats,
                          salary=sal, mode_hint="remote" if remote else None, scope="US" if remote else None)
            found += 1 if row else 0
    cfg["jsearch_last"] = datetime.utcnow().isoformat(timespec="seconds")
    _close_stale(db, "js:", 10)
    db.commit()
    return f"OK – {found} jobs ({dups} already found on employers' own boards)"


def scan_adzuna(db, client, cfg: dict, stats) -> str:
    app_id, app_key = cfg.get("adzuna_app_id"), cfg.get("adzuna_app_key")
    if not (app_id and app_key):
        return "Not set up"
    seen, found, dups = set(), 0, 0
    for q in cfg.get("queries") or DEFAULT_API_QUERIES:
        for page in (1, 2):
            res = client.get(f"https://api.adzuna.com/v1/api/jobs/us/search/{page}", source_name="Adzuna", api=True,
                             params={"app_id": app_id, "app_key": app_key, "what": q, "results_per_page": 50,
                                     "max_days_old": 30, "sort_by": "date", "content-type": "application/json"})
            if not res.ok:
                hint = " – check the Application ID and Key" if res.status in (401, 403) else ""
                return (f"Error: HTTP {res.status}" if res.status else f"Error: {res.error}") + hint
            results = res.json().get("results") or []
            for j in results:
                title = text_of(j.get("title"))
                company = (j.get("company") or {}).get("display_name")
                cat = _any_category(title)
                if not cat or not j.get("redirect_url"):
                    continue
                if _duplicate(db, title, company, "adz:"):
                    dups += 1
                    continue
                area = (j.get("location") or {}).get("area") or []
                # area = ["US", state, county, city]
                loc = f"{area[-1]}, {area[1]}" if len(area) > 2 else area[1] if len(area) == 2 else \
                    (j.get("location") or {}).get("display_name") or "United States"
                # Adzuna marks estimated salaries with salary_is_predicted; only employer-posted pay is kept.
                sal = None if str(j.get("salary_is_predicted")) == "1" else _board_salary(j.get("salary_min"), j.get("salary_max"), "yearly")
                row = _upsert(db, cat, f"adz:{j.get('id')}", "Adzuna", title, company, loc, j["redirect_url"],
                              _iso_date(j.get("created")), text_of(j.get("description")), seen, stats, salary=sal)
                found += 1 if row else 0
            if len(results) < 50:
                break
    _close_stale(db, "adz:", 10)
    db.commit()
    return f"OK – {found} jobs ({dups} already found on employers' own boards)"


def scan_job_apis(db, client, stats):
    u, cfg = api_settings(db)
    status = {"JSearch (LinkedIn, Indeed, Glassdoor, ZipRecruiter…)": scan_jsearch(db, client, cfg, stats),
              "Adzuna": scan_adzuna(db, client, cfg, stats)}
    if u:
        u.settings = {**(u.settings or {}), "job_apis": {**cfg, "last_status": status}}
        db.commit()
    stats["job_apis"] = status


def scan_madgex(db, client, stats):
    for site, base in MADGEX:
        seen = set()
        for kw in INSTRUCTOR_KEYWORDS:
            res = client.get(f"{base}/jobsrss/?keywords={quote(kw)}", source_name=site)
            if not res.ok:
                stats.setdefault("errors", []).append(f"{site}: {res.error or res.status}")
                continue
            for item in re.findall(r"<item>(.*?)</item>", res.text, re.S):
                def tag(t):
                    m = re.search(rf"<{t}>(.*?)</{t}>", item, re.S)
                    return _html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip() if m else ""
                raw_title = tag("title")
                employer, _, title = raw_title.partition(": ")
                if not title:
                    employer, title = "", raw_title
                if not (INSTRUCTOR_TITLE.search(title) and INSTRUCTOR_SUBJECT.search(title)):
                    continue
                desc = tag("description")
                lines = [l.strip() for l in desc.splitlines() if l.strip()]
                loc = lines[-1] if lines else ""
                link = re.sub(r"\?.*$", "", tag("link"))
                m = re.search(r"/job/(\d+)", link)
                if not m:
                    continue
                try:
                    posted = parsedate_to_datetime(tag("pubDate")).date()
                except Exception:
                    posted = None
                _upsert(db, "INSTRUCTOR", f"mx:{base}:{m.group(1)}", site, title, employer, loc, link, posted,
                        "\n".join(lines[:-1]), seen, stats)
        # RSS keyword feeds are partial; only close postings unseen for 21 days.
        cutoff = datetime.utcnow() - timedelta(days=21)
        for row in db.scalars(select(EngJob).where(EngJob.source_key.like(f"mx:{base}:%"), EngJob.status == "ACTIVE",
                                                   EngJob.last_seen < cutoff)):
            row.status = "CLOSED"
        db.commit()


def sync_k12(db, stats):
    """K-12 engineering / robotics / CTE teacher jobs already found by the teaching scans."""
    seen = set()
    rx = re.compile(r"engineer|robotic|mechatronic|\bcte\b|career and technical|pltw|project lead the way|electronics|computer science|\bstem\b", re.I)
    not_eng = re.compile(r"special education|\bsped\b|resource specialist|counsel|nurse|librarian|paraprofessional|\baides?\b", re.I)
    for j in db.scalars(select(Job).where(Job.is_demo.is_(False), Job.job_status != "CLOSED")):
        subj = set(j.subjects or [])
        if not (subj & {"Engineering", "Robotics", "Computer Science"} or rx.search(j.job_title or "")):
            continue
        if not_eng.search(j.job_title or ""):
            continue  # e.g. "Special Education Teacher – Riverview STEM Academy" is not an engineering role
        loc = ", ".join(filter(None, [j.city, j.state]))
        sal = parse_salary(j.salary_text)
        if not sal and j.salary_min and j.salary_min >= 10000:
            sal = salary_dict(j.salary_min, j.salary_max, "YEAR")
        row = _upsert(db, "INSTRUCTOR", f"k12:{j.id}", "Teaching scans (K-12)", j.job_title,
                      j.employer_name or (j.school.name if j.school else None), loc or (j.state or ""),
                      j.application_url or j.official_job_url or f"#/job/{j.id}", j.date_posted,
                      j.job_description or "", seen, stats, salary=sal)
        if row:
            row.job_id = j.id
    stats["closed"] = stats.get("closed", 0) + _close_missing(db, "k12:", seen)
    db.commit()


def scan_all(db, client, stop=None, progress=None) -> dict:
    stats: dict = {}
    steps = [(f"Greenhouse – {c}", lambda t=t, c=c: scan_greenhouse(db, client, t, c, stats)) for t, c in GREENHOUSE]
    steps += [(f"Lever – {c}", lambda t=t, c=c: scan_lever(db, client, t, c, stats)) for t, c in LEVER]
    steps += [(f"Ashby – {c}", lambda t=t, c=c: scan_ashby(db, client, t, c, stats)) for t, c in ASHBY]
    steps += [(f"Workable – {c}", lambda t=t, c=c: scan_workable(db, client, t, c, stats)) for t, c in WORKABLE]
    steps += [("Remote job boards", lambda: scan_remote_boards(db, client, stats)),
              ("Job search APIs (JSearch, Adzuna)", lambda: scan_job_apis(db, client, stats))]
    steps += [("The Muse", lambda: scan_muse(db, client, stats)), ("College job boards", lambda: scan_madgex(db, client, stats)),
              ("K-12 engineering teacher jobs", lambda: sync_k12(db, stats))]
    for i, (label, fn) in enumerate(steps, 1):
        if stop and stop():
            break
        if progress:
            progress(i, len(steps), label)
        try:
            fn()
        except Exception as e:
            db.rollback()
            stats.setdefault("errors", []).append(f"{label}: {type(e).__name__}: {e}"[:200])
    active = db.scalars(select(EngJob).where(EngJob.status == "ACTIVE")).all()
    stats["engineering_jobs"] = sum(1 for r in active if r.category == "INDUSTRY")
    stats["software_ai_data_jobs"] = sum(1 for r in active if r.category == "SOFTWARE")
    stats["instructor_jobs"] = sum(1 for r in active if r.category == "INSTRUCTOR")
    stats["errors"] = (stats.get("errors") or [])[:20]
    return stats
