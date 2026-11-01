"""Cover letter, application email and follow-up email generators.

Only facts present in the candidate profile/résumé and in the job record are used. The addressee is
the HIGH-confidence verified contact, otherwise "Hiring Committee" - a name is never invented.
"""
import re
from datetime import date, timedelta

from .contacts import contact_type_for, recommend_addressee


def business_days_after(d: date, n: int) -> date:
    cur = d
    while n > 0:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n -= 1
    return cur


def _degrees(profile):
    out = []
    for e in profile.get("education", []):
        t = e.get("text", "")
        st = e.get("status", "")
        if "progress" in st or "candidate" in st.lower():
            out.append(f"{t} ({st})")
        else:
            out.append(t)
    return out


def _subject_phrase(job):
    s = [x for x in (job.subjects or []) if x != "Mathematics"]
    return ", ".join(s) if s else "Mathematics"


# Words that never make a school name on their own: "Middle School (26-27SY)", "Various Locations", "Central Office".
_GENERIC_SCHOOL_WORDS = {
    "the", "elementary", "middle", "high", "junior", "senior", "jr", "sr", "primary", "secondary", "intermediate",
    "school", "schools", "campus", "campuses", "academy", "k", "8", "k8", "k12", "12", "upper", "lower", "math",
    "mathematics", "teacher", "position", "district", "various", "multiple", "tbd", "all", "sites", "site",
    "locations", "location", "and", "&", "central", "office", "division", "wide", "districtwide", "year"}


def _real_school_name(job) -> str | None:
    """The school's name, unless it is a generic placeholder taken from the job title."""
    name = (job.school.name if job.school else "") or ""
    n = re.sub(r"\([^)]*\)", " ", name)
    n = re.sub(r"\b\d{2,4}\s*[-/]\s*\d{2,4}\s*(sy)?\b|\bsy\b", " ", n, flags=re.I)
    words = [w for w in re.split(r"[^A-Za-z0-9&]+", n.lower()) if w]
    if not words or all(w in _GENERIC_SCHOOL_WORDS for w in words) or re.search(r"\bdivision[- ]wide\b", name, re.I):
        return None
    return name.strip()


def _place(job):
    return _real_school_name(job) or job.employer_name or "your school"


def cover_letter(job, profile: dict, today: date | None = None) -> dict:
    today = today or date.today()
    rec = recommend_addressee(job)
    c = rec.get("contact") if rec.get("recommended") else None
    header = [today.strftime("%B %d, %Y").replace(" 0", " "), ""]
    if c:
        header += [c["full_name"]] + ([c["title"]] if c.get("title") else [])
    else:
        header += ["Hiring Committee"]
    real_school = _real_school_name(job)
    if real_school:
        header.append(real_school)
    if job.employer_name and (not real_school or not real_school.startswith(job.employer_name)):
        header.append(job.employer_name)
    if job.city or job.state:
        header.append(", ".join(filter(None, [job.city, job.state])))
    name = profile.get("full_name") or "[Your name]"
    # The user's own letter text. Only the addressee and the position/school are filled in per job;
    # the addressee is the verified HIGH-confidence contact, otherwise "Hiring Committee" (never a guessed name).
    salutation = rec["salutation"].rstrip(":") + ","
    position = f"the {job.job_title} position" if job.job_title else "the Mathematics teaching position"
    place = _place(job) if (job.school or job.employer_name) else "your institution"
    paras = [
        f"I am writing to express my interest in {position} at {place}. I am passionate about helping students "
        "recognize the value of mathematics beyond the classroom by making complex concepts accessible, relevant, "
        "and engaging. My teaching philosophy centers on cultivating curiosity, confidence, and perseverance while "
        "encouraging learners to approach challenges with logical reasoning and a growth mindset.",
        "I bring a strong commitment to creating inclusive and intellectually stimulating learning environments where "
        "every student feels supported in reaching their potential. I excel at designing meaningful learning "
        "experiences that connect mathematical concepts to real-world situations, promote collaboration, and "
        "encourage independent thinking. By combining innovative instructional practices with thoughtful assessment "
        "and individualized support, I strive to ensure that students develop not only computational proficiency but "
        "also the critical-thinking skills necessary for academic and lifelong success.",
        "I would welcome the opportunity to contribute my passion, instructional expertise, and dedication to student "
        "achievement to your school community. Thank you for considering my application. I look forward to the "
        "opportunity to discuss how I can support your students and advance your institution’s educational goals.",
    ]
    body = "\n".join(header) + "\n\n" + salutation + "\n\n" + "\n\n".join(paras) + f"\n\nSincerely,\n\n{name}"
    return {"text": body, "addressee": rec}


PORTFOLIO_URL = "https://pjportfolio-phi.vercel.app/"


def school_principal(job):
    """The principal of this job's school, only when an official source (the vacancy or the school's own
    website) names them as principal.
    Returns (Contact, JobContact) or (None, None); a name is never guessed."""
    best = None
    for link in job.contact_links:
        c = link.contact
        if not c or c.deleted_at or not (c.full_name or "").strip() or link.confidence not in ("HIGH", "MEDIUM"):
            continue
        if not (link.relationship_type in ("SCHOOL_PRINCIPAL", "PRINCIPAL") or contact_type_for(c.title) == "PRINCIPAL"):
            continue
        if job.school_id and c.school_id and c.school_id != job.school_id:
            continue  # principal of a different school in the district
        if not best or (link.confidence == "HIGH" and best[1].confidence != "HIGH"):
            best = (c, link)
    return best or (None, None)


VACANCY_RELS = ("JOB_POSTER", "VACANCY_CONTACT", "HIRING_MANAGER")
HR_RELS = ("DISTRICT_RECRUITER", "RECRUITER", "REGIONAL_RECRUITER", "TALENT_PARTNER", "HR_ADMINISTRATOR", "HR")


def pick_recipient(job):
    """Who the application email goes to: the school's principal; otherwise the person the official posting names
    as its contact (they handle this exact vacancy); otherwise the district's named HR / recruiting contact.
    Only named people with a confirmed email. Returns (contact, label, link) or (None, None, None)."""
    from .contacts import email_usable
    p, plink = school_principal(job)
    if p and email_usable(p) and is_person(p):
        return p, "Principal", plink
    for rels, label in ((VACANCY_RELS, "Hiring contact named in the job posting"),
                        (HR_RELS, "District HR / recruiting contact")):
        for link in sorted(job.contact_links, key=lambda l: {"HIGH": 0, "MEDIUM": 1}.get(l.confidence, 2)):
            c = link.contact
            if (c and not c.deleted_at and link.relationship_type in rels and link.confidence in ("HIGH", "MEDIUM")
                    and is_person(c) and email_usable(c)):
                return c, ("Principal" if contact_type_for(c.title) == "PRINCIPAL" else label), link
    return None, None, None


ORG_WORDS = re.compile(r"\b(school|schools|district|charter|charters|academy|department|office|human|resources|"
                       r"recruit\w*|personnel|county|unified|isd|usd|board|services|center|team|staff|hr|admin\w*|"
                       r"payroll|careers?|jobs?|employment|education)\b", re.I)
GENERIC_MAILBOX = re.compile(r"^(hr|jobs?|careers?|recruit\w*|employment|personnel|substitutes?|subs|info|office|"
                             r"admin\w*|hiring|apply|applications?|teach\w*|staff\w*|frontdesk|principal|"
                             r"human\.?resources|humanresources|talent|certified|classified|noreply|no-reply)\d*$", re.I)


def clean_person_name(name: str | None) -> str:
    """'Kelli Martin, Deputy Superintendent' -> 'Kelli Martin'; 'Dr. Jane Smith' -> 'Jane Smith'."""
    n = re.sub(r"\s+", " ", name or "").strip().split(",")[0].strip()
    return re.sub(r"^(Dr|Mr|Mrs|Ms|Miss)\.?\s+", "", n)


def is_person(contact) -> bool:
    """A real person with their own mailbox: first + last name, no digits or organisation words, and not a shared
    department inbox (hr@, jobs@, substitutes@ ...)."""
    name = clean_person_name(contact.full_name)
    if len(name.split()) < 2 or re.search(r"\d", name) or ORG_WORDS.search(name):
        return False
    local = (contact.email or "").split("@", 1)[0].lower()
    return not GENERIC_MAILBOX.match(local)


def greeting_for(contact) -> str:
    """Always the person's complete name, with no title: 'Dear Lea Ann Frank,' (the user's choice - safest)."""
    full = clean_person_name(contact.full_name)
    return f"Dear {full}," if full else "Dear Principal,"


# Subjects that get application emails (the Subject filter in Job Hunter), and how each is named in the email.
SUBJECT_PATTERNS = [
    ("mathematics", r"math|algebra|geometr|calculus|statistic|trigonometr|pre-?calc"),
    ("physics", r"physics"),
    ("computer science", r"computer science|comp\.? sci|\bcoding\b|programming|\bap csp?\b"),
    ("robotics", r"robotic"),
    ("engineering", r"engineer|\bpltw\b|project lead the way"),
    ("STEM", r"\bstem\b|s\.t\.e\.m"),
]
SUBJECT_TITLE = re.compile("|".join(p for _, p in SUBJECT_PATTERNS), re.I)
SUBJECT_TAGS = {"Mathematics", "Algebra", "Geometry", "Calculus", "Precalculus", "Statistics", "STEM", "Robotics",
                "Engineering", "Physics", "Computer Science"}


def is_target_subject(job) -> bool:
    """Math, STEM, robotics, engineering, physics or computer science (title, or the subjects the scan tagged)."""
    return bool(SUBJECT_TITLE.search(job.job_title or "")) or bool(set(job.subjects or []) & SUBJECT_TAGS)


def teaching_subject(job) -> str:
    """'mathematics' / 'physics' / 'computer science' / 'robotics' / 'engineering' / 'STEM' for the email's first line."""
    title = job.job_title or ""
    for name, pat in SUBJECT_PATTERNS:
        if re.search(pat, title, re.I):
            return name
    tags = set(job.subjects or [])
    if tags & {"Mathematics", "Algebra", "Geometry", "Calculus", "Precalculus", "Statistics"}:
        return "mathematics"
    for tag, name in (("Physics", "physics"), ("Computer Science", "computer science"), ("Robotics", "robotics"),
                      ("Engineering", "engineering"), ("STEM", "STEM")):
        if tag in tags:
            return name
    return "mathematics"


def calm_case(title: str | None) -> str:
    """'9-12 MATH TEACHER' -> '9-12 Math Teacher' (all-caps subjects look like spam); normal titles are unchanged."""
    t = (title or "").strip()
    letters = [ch for ch in t if ch.isalpha()]
    if letters and sum(ch.isupper() for ch in letters) / len(letters) > 0.7:
        small = {"and", "or", "of", "the", "for", "in", "at", "to", "a", "an"}
        words = t.lower().split()
        cap = lambda w: re.sub(r"[a-z]", lambda m: m.group(0).upper(), w, count=1)   # "(algebra" -> "(Algebra"
        t = " ".join(w if (i and w in small) else cap(w) for i, w in enumerate(words))
        t = re.sub(r"\b(Ms|Hs|Es|Ap|Ib|Ela|Stem|Sped|Fte|Cte|Avid)\b", lambda m: m.group(1).upper(), t)
    return t


def _possessive(name: str) -> str:
    return name + ("’" if name.endswith("s") else "’s")


def application_email(job, profile: dict) -> dict:
    rec = recommend_addressee(job)
    name = profile.get("full_name") or "[Your name]"
    principal, role, plink = pick_recipient(job)
    if not principal:
        principal, plink = school_principal(job)
        role = "Principal" if principal else None
    if principal:
        greeting = greeting_for(principal)
        pname = re.sub(r"^(Dr|Mr|Mrs|Ms|Miss)\.?\s+", "", re.sub(r"\s+", " ", principal.full_name).strip())
        greeting_note = (f"Addressed to {pname} ({role.lower()}) by complete name - named in the official source"
                         + (f": {plink.evidence_url}" if plink and plink.evidence_url else "") + ".")
    else:
        greeting = "Dear Principal,"
        greeting_note = "The school's principal hasn't been confirmed from an official source, so the greeting is \"Dear Principal,\" (no name guessed)."
    school = _place(job)
    subject = f"Application – {calm_case(job.job_title)} – {name}"
    c = rec.get("contact") if rec.get("recommended") else None
    to = c["email"] if c and c.get("email") and c.get("email_status") == "VERIFIED" and c.get("email_usable") else None
    from .contacts import email_usable
    if principal and email_usable(principal):
        to = principal.email   # the same person the greeting names
    mailbox_note = None
    if c and c.get("has_unconfirmed_email"):
        why = ("its mail server says that mailbox does not exist"
               if c.get("mailbox_status") in ("NOT_FOUND", "NO_MAIL_SERVER")
               else "its mail server could not confirm that the mailbox exists")
        mailbox_note = (f"The school published an address for {c.get('full_name') or 'this contact'}, but {why}, so it was "
                        "left out. Apply through the official application link, or call "
                        + (c.get("phone") or "the district HR office") + " to ask for the right address.")
    # The user's own email text, verbatim, with the school's real name in place of "your institution" and
    # the principal's name (from the school's official site) after "Dear Principal" when it is known.
    body = (
        f"{greeting}\n\n"
        f"I am writing to express my interest in the {teaching_subject(job)} teaching position at {school}. I am "
        "passionate about helping students recognize the value of mathematics beyond the classroom by making complex "
        "concepts accessible, relevant, and engaging. My teaching philosophy centers on cultivating curiosity, "
        "confidence, and perseverance while encouraging learners to approach challenges with logical reasoning and a "
        "growth mindset.\n\n"
        "I bring a strong commitment to creating inclusive and intellectually stimulating learning environments where "
        "every student feels supported in reaching their potential. I excel at designing meaningful learning "
        "experiences that connect mathematical concepts to real-world situations, promote collaboration, and "
        "encourage independent thinking. By combining innovative instructional practices with thoughtful assessment "
        "and individualized support, I strive to ensure that students develop not only computational proficiency but "
        "also the critical-thinking skills necessary for academic and lifelong success.\n\n"
        "I would welcome the opportunity to contribute my passion, instructional expertise, and dedication to student "
        "achievement to your school community. Thank you for considering my application. I look forward to the "
        f"opportunity to discuss how I can support your students and advance {_possessive(school)} educational goals.\n\n"
        "To learn more about my teaching background, research, and projects, please visit my professional portfolio.\n\n"
        f"{PORTFOLIO_URL}\n\n"
        f"Sincerely,\n{name}"
    )
    return {"subject": subject, "to": to, "body": body, "addressee": rec, "greeting_note": greeting_note,
            "mailbox_status": c.get("mailbox_status") if c else None,
            "mailbox_detail": c.get("mailbox_detail") if c else None,
            "note": mailbox_note or (None if to else "No verified email for a HIGH-confidence contact. Apply through the official application link.")}


def follow_up_email(job, profile: dict, applied_on: date | None) -> dict:
    rec = recommend_addressee(job)
    name = profile.get("full_name") or "[Your name]"
    when = applied_on.strftime("%B %d, %Y").replace(" 0", " ") if applied_on else "recently"
    subject = f"Follow-up – {job.job_title} Application – {name}"
    body = (
        f"{rec['salutation'].rstrip(':')},\n\n"
        f"I hope you are well. I submitted my application for the {job.job_title} position at {_place(job)} on {when} "
        "and wanted to confirm that it was received.\n\n"
        "I remain very interested in the role and would be glad to provide any additional documents. I would also be "
        "grateful to know whether international candidates on the J-1 Teacher Exchange pathway can be considered.\n\n"
        f"Thank you for your time.\n\nSincerely,\n\n{name}"
    )
    return {"subject": subject, "body": body, "addressee": rec}
