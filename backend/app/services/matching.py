"""Résumé-to-vacancy match scoring (0-100). A prioritization aid, not a hiring prediction."""
import re

from .taxonomy import MATH_CORE, STATES

WEIGHTS = {
    "subject": 25, "grade": 15, "experience": 15, "education": 15,
    "certification": 10, "stem": 10, "j1": 10, "location": 5,
}

J1_POINTS = {
    "CONFIRMED_J1_VACANCY": 10, "CONFIRMED_J1_EMPLOYER": 8, "INTERNATIONAL_FRIENDLY": 6,
    "NEEDS_CONFIRMATION": 4, "UNKNOWN": 3, "NO_SPONSORSHIP": 0,
}

GAP_RULES = [
    (r"\bspanish\b|\bbilingual\b|dual language", "Spanish / bilingual requirement mentioned"),
    (r"coach(ing)?\b", "Coaching duty mentioned"),
    (r"driver'?s licen[sc]e", "U.S. driver's license requirement"),
    (r"special education (endorsement|certification)|sped (endorsement|certified)", "Special Education endorsement required"),
    (r"\bu\.?s\.? citizen(ship)?\b", "U.S. citizenship mentioned"),
    (r"(not|unable to|will not|does not|cannot) (provide |offer )?(visa )?sponsor", "Posting says no visa sponsorship"),
    (r"must be (legally )?(authorized|eligible) to work in the (u\.?s|united states)", "Existing U.S. work authorization required"),
    (r"\bpraxis\b", "Praxis exam mentioned"),
    (r"background check|fingerprint", "Background check / fingerprinting (standard)"),
    (r"\bap\b.*(certified|training)|advanced placement", "AP course experience/training may be expected"),
]


def _has(texts, *words):
    blob = " ".join(texts).lower()
    return any(w.lower() in blob for w in words)


def score_job(job, profile: dict) -> dict:
    subjects_p = [s.lower() for s in profile.get("subjects", [])]
    job_subjects = job.subjects or []
    title = (job.job_title or "")
    text = " ".join(filter(None, [title, job.job_description, job.requirements, job.certification_requirements]))
    low = text.lower()
    why, gaps, parts = [], [], {}

    # Subject (25)
    js_lower = [s.lower() for s in job_subjects]
    core_job = [s for s in job_subjects if s in MATH_CORE]
    if core_job and "mathematics" in subjects_p:
        specific = [s for s in core_job if s != "Mathematics"]
        pts = 25 if (not specific or all(s.lower() in subjects_p for s in specific)) else 22
        why.append("Mathematics teaching experience matches the subject")
        if specific:
            why.append(f"{'/'.join(specific)} experience")
    elif any(s in subjects_p for s in js_lower):
        pts = 18
        why.append(f"Related subject experience: {', '.join(job_subjects)}")
    else:
        pts = 5
        gaps.append("Subject is outside the résumé's primary teaching areas")
    parts["subject"] = pts

    # Grade level (15)
    g = (job.grade_level or "").lower()
    pg = " ".join(profile.get("grade_levels", [])).lower()
    secondary_exp = any(k in pg for k in ("secondary", "high", "senior", "junior", "middle"))
    if not g:
        pts = 10
    elif "elementary" in g:
        pts = 4
        gaps.append("Elementary grade level (résumé is secondary-focused)")
    elif secondary_exp:
        pts = 15
        why.append("Secondary teaching experience")
    else:
        pts = 8
    parts["grade"] = pts

    # Experience (15)
    yrs = profile.get("years_experience") or 0
    pts = 15 if yrs >= 5 else (12 if yrs >= 3 else (8 if yrs >= 1 else 3))
    if yrs:
        why.append(f"{int(yrs)}+ years of teaching experience")
    m = re.search(r"(\d+)\+?\s*years?[^.]{0,40}experience", low)
    if m and yrs and int(m.group(1)) > yrs:
        pts -= 5
        gaps.append(f"Posting asks for {m.group(1)}+ years of experience")
    parts["experience"] = max(pts, 0)

    # Education (15)
    edu = " ".join(e.get("text", "") for e in profile.get("education", [])).lower()
    has_master = "master" in edu or re.search(r"\bm\.?s\.?\b|\bm\.?eng", edu)
    math_edu = "math" in edu or "teaching" in edu
    pts = 7
    if has_master and math_edu:
        pts = 15
        why.append("Master's degree in Mathematics-related teaching")
    elif has_master:
        pts = 12
    elif math_edu:
        pts = 10
    if "phd" in edu or "doctor" in edu:
        why.append("Doctoral study in Educational Management")
    if "engineering" in edu:
        why.append("Engineering background")
    parts["education"] = pts

    # Certification alignment (10)
    lic = " ".join(profile.get("licenses", [])).lower()
    state_name = STATES.get(job.state or "", "state")
    needs_state_cert = bool(re.search(r"certif|licens|credential|endorse", low))
    if profile.get("has_us_license"):
        pts = 10
    else:
        pts = 7 if ("teacher" in lic or "lpt" in lic) else 4
        if needs_state_cert:
            gaps.append(f"{state_name} teaching certification required (J-1 teachers usually obtain a state license/permit through the sponsor)")
        else:
            gaps.append(f"{state_name} certification requirements not stated - confirm with HR")
    parts["certification"] = pts

    # STEM / technology (10)
    stem_blob = profile.get("technologies", []) + profile.get("research_stem", []) + profile.get("subjects", [])
    pts = 4
    if _has(stem_blob, "robot", "iot", "stem", "engineering", "computer"):
        pts = 8
        why.append("STEM / Robotics / technology-integrated instruction")
        if any(s in job_subjects for s in ("STEM", "Robotics", "Engineering", "Computer Science", "Physics")) \
                or re.search(r"\bstem\b|robotic|engineer|coding|computer science|programming", low):
            pts = 10
    parts["stem"] = pts

    # J-1 / international compatibility (10)
    parts["j1"] = J1_POINTS.get(job.j1_status or "UNKNOWN", 3)
    if job.j1_status in ("CONFIRMED_J1_VACANCY", "CONFIRMED_J1_EMPLOYER"):
        why.append("Employer has documented J-1 / international teacher recruitment")
    elif job.j1_status == "NO_SPONSORSHIP":
        gaps.append("Evidence indicates no visa sponsorship")
    else:
        gaps.append("J-1 eligibility not confirmed")

    # Location / other (5)
    pts = 5
    preferred = [s.upper() for s in profile.get("preferred_states", []) or []]
    if preferred and job.state and job.state not in preferred:
        pts = 3
    min_sal = profile.get("min_salary")
    if min_sal and job.salary_max and job.salary_max < min_sal:
        pts -= 2
        gaps.append("Salary below your minimum")
    parts["location"] = max(pts, 0)

    for pat, msg in GAP_RULES:
        if re.search(pat, low) and msg not in gaps:
            if msg.startswith("Background"):
                continue
            gaps.append(msg)
            if "no visa sponsorship" in msg.lower() or "existing u.s. work authorization" in msg.lower():
                parts["j1"] = 0

    total = sum(parts.values())
    label = "STRONG MATCH" if total >= 85 else "GOOD MATCH" if total >= 70 else "PARTIAL MATCH" if total >= 55 else "WEAK MATCH"
    return {
        "score": int(total),
        "label": label,
        "breakdown": [{"key": k, "points": parts[k], "max": WEIGHTS[k]} for k in WEIGHTS],
        "why": list(dict.fromkeys(why)),
        "gaps": list(dict.fromkeys(gaps)),
        "disclaimer": "Match score is a prioritization aid based on your résumé and the posting text, not a hiring prediction.",
    }
