"""Title classification, subject/grade detection and U.S. state reference data."""
import re

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
NAME_TO_ABBR = {v.lower(): k for k, v in STATES.items()}

# Tile-grid layout (col, row) for the dashboard map.
STATE_TILES = {
    "AK": (0, 0), "ME": (11, 0), "VT": (10, 1), "NH": (11, 1), "WA": (1, 2), "ID": (2, 2), "MT": (3, 2),
    "ND": (4, 2), "MN": (5, 2), "IL": (6, 2), "WI": (7, 2), "MI": (8, 2), "NY": (9, 2), "RI": (10, 2),
    "MA": (11, 2), "OR": (1, 3), "NV": (2, 3), "WY": (3, 3), "SD": (4, 3), "IA": (5, 3), "IN": (6, 3),
    "OH": (7, 3), "PA": (8, 3), "NJ": (9, 3), "CT": (10, 3), "CA": (1, 4), "UT": (2, 4), "CO": (3, 4),
    "NE": (4, 4), "MO": (5, 4), "KY": (6, 4), "WV": (7, 4), "VA": (8, 4), "MD": (9, 4), "DE": (10, 4),
    "AZ": (2, 5), "NM": (3, 5), "KS": (4, 5), "AR": (5, 5), "TN": (6, 5), "NC": (7, 5), "SC": (8, 5),
    "DC": (9, 5), "OK": (4, 6), "LA": (5, 6), "MS": (6, 6), "AL": (7, 6), "GA": (8, 6), "HI": (0, 7),
    "TX": (4, 7), "FL": (9, 7),
}

# Keywords used to query discovery sources (the SEARCH TARGETS of the spec).
SEARCH_KEYWORDS_QUICK = ["mathematics teacher", "math teacher"]
SEARCH_KEYWORDS_FULL = [
    "mathematics teacher", "math teacher", "algebra", "geometry", "calculus", "precalculus",
    "statistics teacher", "secondary math", "math specialist", "math intervention",
    "STEM teacher", "engineering teacher", "robotics", "physics teacher", "computer science teacher",
]

SUBJECT_PATTERNS = [
    ("Calculus", r"\b(ap\s+)?calc(ulus)?\b"),
    ("Precalculus", r"\bpre-?\s?calc(ulus)?\b"),
    ("Algebra", r"\balgebra\b"),
    ("Geometry", r"\bgeometry\b"),
    ("Statistics", r"\b(ap\s+)?statistics\b|\bstats\b"),
    ("Mathematics", r"\bmath(ematics|ematic|s)?\b"),
    ("STEM", r"\bs\.?t\.?e\.?a?\.?m\.?\b"),
    ("Robotics", r"\brobotics?\b"),
    ("Engineering", r"\bengineering\b|\bpltw\b|project lead the way"),
    ("Physics", r"\bphysics\b|\bphysical science\b"),
    ("Computer Science", r"\bcomputer science\b|\bcomputing\b|\bprogramming\b|\bcoding\b|\bcs teacher\b"),
    ("Technology/ICT", r"\btechnology (teacher|education)\b|\bict\b|\binformation technology\b"),
]
MATH_CORE = {"Mathematics", "Algebra", "Geometry", "Calculus", "Precalculus", "Statistics"}

TEACHING_RE = re.compile(
    r"\b(teacher|teaching|instructor|educator|faculty|specialist|interventionist|lecturer|tutor)\b", re.I)
# Roles that are not teaching positions for this candidate.
EXCLUDE_RE = re.compile(
    r"\b(para(professional|educator)?|aide|assistant teacher|teacher assistant|teaching assistant|"
    r"substitute|sub|bus|custodian|nurse|cafeteria|secretary|clerk|"
    r"student teach(er|ing)|internship|intern|volunteer|summer school|after[- ]school|extended day|"
    r"homebound)\b",
    re.I,
)
# Roles excluded only when the title does not also say "teacher".
NON_TEACHER_ONLY_RE = re.compile(r"\b(coach|tutor(ing)?|coordinator|director|supervisor|principal)\b", re.I)
ELEMENTARY_ONLY_RE = re.compile(
    r"\b(pre-?k|kindergarten|k-?[1-5]\b|1st grade|2nd grade|3rd grade|4th grade|5th grade|"
    r"grade [1-5]\b|grades? [k1-4]-[1-5]\b|elementary)\b", re.I)


def classify_subjects(text: str) -> list[str]:
    found = []
    t = text or ""
    for name, pat in SUBJECT_PATTERNS:
        if re.search(pat, t, re.I) and name not in found:
            found.append(name)
    # "Mathematics" implied by any specific math course
    if any(s in MATH_CORE for s in found) and "Mathematics" not in found:
        found.insert(0, "Mathematics")
    return found


def primary_subject(subjects: list[str]) -> str | None:
    for s in ["Mathematics", "STEM", "Engineering", "Robotics", "Computer Science", "Physics", "Technology/ICT"]:
        if s in subjects:
            return s
    return subjects[0] if subjects else None


def classify_grade(text: str) -> str | None:
    t = (text or "").lower()
    m = re.search(r"\b(grades?\s*)?(6|7|8|9)\s*[-–to]+\s*(8|12)\b", t)
    if m:
        return f"Grades {m.group(2)}-{m.group(3)}"
    if re.search(r"\b(6th|7th|8th)\s+grade|\bgrade\s*(6|7|8)\b", t):
        g = re.search(r"\b(6|7|8)(th)?\s*(grade)?", t)
        return f"Middle School (Grade {g.group(1)})" if g else "Middle School"
    if re.search(r"\bhigh school\b|\bhs\b|\bsecondary\b|\b(9th|10th|11th|12th)\s+grade|\bap\s|\bsenior high\b", t):
        return "High School" if "middle" not in t else "Middle/High School"
    if re.search(r"\bmiddle\b|\bjunior high\b|\bjr\.? high\b|\bintermediate school\b", t):
        return "Middle School"
    if ELEMENTARY_ONLY_RE.search(t):
        return "Elementary"
    if re.search(r"\bk-?12\b|\bk-?8\b", t):
        return "K-12"
    return None


def is_relevant_title(title: str) -> tuple[bool, str]:
    """Return (relevant, reason). Only teaching roles in target subjects pass."""
    t = title or ""
    if EXCLUDE_RE.search(t):
        return False, "non-teaching or out-of-scope role"
    if NON_TEACHER_ONLY_RE.search(t) and not re.search(r"\bteacher\b", t, re.I):
        return False, "non-classroom role"
    subjects = classify_subjects(t)
    if not subjects:
        return False, "no target subject in title"
    if not TEACHING_RE.search(t) and not re.search(r"\b(math|mathematics)\b", t, re.I):
        return False, "not a teaching title"
    # Bare "Technology/ICT" titles are often IT staff, require the word teacher.
    if subjects == ["Technology/ICT"] and not re.search(r"teacher|instructor", t, re.I):
        return False, "technology staff role"
    return True, "ok"


def parse_location(loc: str) -> tuple[str | None, str | None]:
    """'Norfolk, Virginia' -> ('Norfolk', 'VA')."""
    if not loc:
        return None, None
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    state = None
    city = parts[0] if parts else None
    if len(parts) >= 2:
        s = parts[-1]
        s2 = re.sub(r"\s+\d{5}(-\d{4})?$", "", s).strip()
        if s2.upper() in STATES:
            state = s2.upper()
        else:
            state = NAME_TO_ABBR.get(s2.lower())
    return city, state
