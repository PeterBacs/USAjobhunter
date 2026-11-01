"""Résumé text extraction (PDF / DOCX / TXT) and rule-based profile extraction.

Everything returned here is taken from the résumé text itself; each list item keeps the
line it was found on so the user can review what was extracted.
"""
import re
from datetime import date
from pathlib import Path

from .taxonomy import classify_subjects


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if suffix == ".docx":
        import docx
        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    return path.read_text(encoding="utf-8", errors="ignore")


def _lines(text):
    return [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()]


DEGREE_RE = re.compile(
    r"\b(Ph\.?\s?D\.?|Doctor(ate)? of [A-Z][\w ]+|Ed\.?D\.?|Master of [A-Z][\w ,/]+|M\.?S\.?|M\.?A\.?T?\.?|"
    r"M\.?Eng\.?|MAEd|MAT|Bachelor of [A-Z][\w ,/]+|B\.?S\.?|B\.?A\.?|BSEd|BSECE|BSCS|BSEE)\b[^\n]{0,120}",
)
LICENSE_RE = re.compile(
    r"(Licensed Professional Teacher|LPT\b|Registered Electronics Engineer|Electronics Engineer|"
    r"Professional (Electronics )?Engineer|teaching (license|certificate|certification)|"
    r"(state|standard|professional) (teaching )?(license|certificate)|PRC\b[^\n]{0,60}|TESOL|TEFL|"
    r"Praxis[^\n]{0,60}|certif(ied|ication)[^\n]{0,80})",
    re.I,
)
LEADERSHIP_RE = re.compile(
    r"\b((Mathematics|Math|ICT|STEM|Research|Testing|Data Management|Grade Level|Subject|Department|School)"
    r"[\w /&-]{0,30}(Coordinator|Head|Chair|Chairperson|Adviser|Advisor|Lead|Leader)|"
    r"(Coordinator|Department Head|Head Teacher|Master Teacher|Research Adviser|Coach|Trainer|Mentor)[^\n]{0,60})",
    re.I,
)
TECH_TERMS = [
    "Arduino", "Raspberry Pi", "IoT", "Internet of Things", "Robotics", "Python", "Java", "C++", "C#", "MATLAB",
    "GeoGebra", "Desmos", "Excel", "Google Classroom", "Microsoft Teams", "Canva", "LMS", "Moodle", "Zoom",
    "Scratch", "LEGO", "VEX", "3D printing", "AutoCAD", "SPSS", "LaTeX", "Power BI", "Mathematica", "TI-84",
    "Kahoot", "Quizizz", "Schoology", "Canvas", "PowerPoint", "Blended learning", "Data analysis",
]
AWARD_RE = re.compile(r"(award(ed)?|awardee|honor(s|ee)?|recogni[sz](ed|ation)|outstanding|best [\w ]+|"
                      r"champion|finalist|winner|medal|scholar(ship)?)[^\n]{0,100}", re.I)
RESEARCH_RE = re.compile(r"(research|thesis|dissertation|publication|published|journal|conference|"
                         r"STEM|robotics|IoT|innovation|science fair|investigatory)[^\n]{0,100}", re.I)
GRADE_RE = re.compile(r"(senior high|junior high|high school|secondary|middle school|grades? \d+\s*[-–to]+\s*\d+|"
                      r"grade \d+|college|tertiary|university|elementary)", re.I)
YEAR_RANGE_RE = re.compile(r"((19|20)\d{2})\s*[-–to]+\s*((19|20)\d{2}|present|current|to date|now)", re.I)
YEARS_STATED_RE = re.compile(r"(\d{1,2})\+?\s*(years|yrs)\b[^\n]{0,40}(teaching|experience)", re.I)


def _unique(items, limit=25):
    out, seen = [], set()
    for i in items:
        k = i.lower().strip(" .,;:-")
        if k and k not in seen:
            seen.add(k)
            out.append(i.strip(" .,;:-"))
    return out[:limit]


def estimate_years(text: str) -> float | None:
    stated = [int(m.group(1)) for m in YEARS_STATED_RE.finditer(text)]
    # Merge teaching-related year ranges to avoid double counting overlapping roles.
    spans = []
    for line in _lines(text):
        if not re.search(r"teach|instructor|faculty|professor|lecturer|coordinator|school", line, re.I):
            continue
        for m in YEAR_RANGE_RE.finditer(line):
            start = int(m.group(1))
            end_raw = m.group(3).lower()
            end = date.today().year if not end_raw[:2].isdigit() else int(end_raw)
            if 1970 < start <= end <= date.today().year:
                spans.append((start, end))
    years_from_spans = 0
    if spans:
        spans.sort()
        merged = [list(spans[0])]
        for s, e in spans[1:]:
            if s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        years_from_spans = sum(e - s for s, e in merged)
    candidates = stated + ([years_from_spans] if years_from_spans else [])
    return float(max(candidates)) if candidates else None


def parse_resume(text: str) -> dict:
    lines = _lines(text)
    joined = "\n".join(lines)
    name = None
    for l in lines[:6]:
        if 2 <= len(l.split()) <= 6 and not re.search(r"@|\d|resume|curriculum|vitae", l, re.I):
            name = l.title() if l.isupper() else l
            break
    email = next(iter(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", joined)), None)
    phone = next(iter(re.findall(r"\+?\d[\d\s().-]{8,}\d", joined)), None)

    education = []
    for l in lines:
        m = DEGREE_RE.search(l)
        if m and re.search(r"master|bachelor|doctor|ph\.?d|m\.?s|b\.?s|m\.?eng|education|engineering|science|teaching", l, re.I):
            status = "in progress" if re.search(r"candidate|ongoing|in progress|dissertation|units|expected", l, re.I) else "completed"
            education.append({"text": l[:200], "status": status})
    education = [dict(t) for t in {tuple(sorted(e.items())) for e in education}][:12]

    subjects = []
    for l in lines:
        if re.search(r"teach|subject|course|handled|instruct|taught|mathematics|math", l, re.I):
            subjects += classify_subjects(l)
    extra_courses = re.findall(r"\b(General Mathematics|Finite Mathematics|Linear Programming|Trigonometry|"
                               r"Basic Calculus|Differential Equations|Discrete Mathematics|Probability)\b", joined, re.I)
    subjects = _unique(subjects + [c.title() for c in extra_courses])

    return {
        "full_name": name,
        "email": email,
        "phone": phone,
        "education": education,
        "licenses": _unique([m.group(0) for m in LICENSE_RE.finditer(joined)], 15),
        "years_experience": estimate_years(joined),
        "subjects": subjects,
        "grade_levels": _unique([m.group(0).title() for m in GRADE_RE.finditer(joined)], 10),
        "leadership": _unique([m.group(0) for m in LEADERSHIP_RE.finditer(joined)], 20),
        "technologies": _unique([t for t in TECH_TERMS if re.search(r"\b" + re.escape(t) + r"\b", joined, re.I)], 30),
        "awards": _unique([m.group(0) for m in AWARD_RE.finditer(joined)], 15),
        "research_stem": _unique([m.group(0) for m in RESEARCH_RE.finditer(joined)], 15),
    }


# The candidate profile described by the user in the project brief. Used until a résumé is uploaded.
DEFAULT_PROFILE = {
    "full_name": "Peter John R. Bacani",
    "location": "Philippines",
    "headline": "Licensed Professional Teacher and Registered Electronics Engineer - Secondary Mathematics",
    "years_experience": 10,
    "education": [
        {"text": "Master of Science in Teaching (Mathematics)", "status": "completed"},
        {"text": "Master of Engineering (Electronics Engineering)", "status": "completed"},
        {"text": "BS Electronics Engineering", "status": "completed"},
        {"text": "BS Computer Science", "status": "completed"},
        {"text": "PhD Educational Management", "status": "in progress, dissertation/candidate stage"},
    ],
    "licenses": ["Licensed Professional Teacher (Philippines)", "Registered Electronics Engineer (Philippines)"],
    "subjects": ["Mathematics", "Algebra", "Geometry", "Calculus", "Precalculus", "General Mathematics",
                 "Statistics", "Finite Mathematics", "Linear Programming", "STEM", "Robotics", "Engineering",
                 "Physics", "Computer Science", "Research", "Technology/ICT"],
    "grade_levels": ["Secondary", "Senior High School", "High School", "Middle School"],
    "leadership": ["Mathematics Coordinator", "ICT Coordinator", "Testing/Data Management Coordinator",
                   "Research Adviser"],
    "technologies": ["Robotics", "IoT", "STEM technology integration"],
    "awards": [],
    "research_stem": ["Research adviser", "Robotics/IoT/STEM teaching", "Engineering teaching background"],
    "languages": ["English", "Filipino"],
    "work_authorization": "Based in the Philippines; seeking J-1 Teacher Exchange pathway",
}
