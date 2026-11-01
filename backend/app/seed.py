"""Initial registry + reference data.

* Scan sources: SchoolSpring nationwide API, plus Frontline AppliTrack district boards whose
  district names were confirmed from each board's own page title on 2026-09-23.
* J-1 sponsors: only Teacher-category sponsors read from the U.S. Department of State BridgeUSA
  "Designated Sponsor Organizations By Program" page on 2026-09-23. Import the full official list via CSV.
* Demo data: created only on request, clearly labeled DEMO / FICTIONAL, never shown in live results.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import select

from .models import AlertRule, CandidateProfile, District, J1Program, Job, ScanSource, School, User

APPLITRACK_BOARDS = [
    # slug, district name (from board title), state, city (district seat, registry data)
    ("humbleisd", "Humble Independent School District", "TX", "Humble"),
    ("aldineisd", "Aldine ISD", "TX", "Houston"),
    ("springisd", "Spring Independent School District", "TX", "Houston"),
    ("galenaparkisd", "Galena Park Independent School District", "TX", "Houston"),
    ("pasadenaisd", "Pasadena Independent School District", "TX", "Pasadena"),
    ("lewisvilleisd", "Lewisville ISD", "TX", "Lewisville"),
    ("garlandisd", "Garland Independent School District", "TX", "Garland"),
    ("mesquiteisd", "Mesquite ISD", "TX", "Mesquite"),
    ("lancasterisd", "Lancaster Independent School District", "TX", "Lancaster"),
    ("saisd", "San Antonio Independent School District", "TX", "San Antonio"),
    ("nisd", "Navarro ISD", "TX", "Seguin"),
    ("killeenisd", "Killeen ISD", "TX", "Killeen"),
    ("bryanisd", "Bryan Independent School District", "TX", "Bryan"),
    ("wacoisd", "Waco ISD", "TX", "Waco"),
    ("lubbockisd", "Lubbock Independent School District", "TX", "Lubbock"),
    ("lafayette", "Lafayette Parish School System", "LA", "Lafayette"),
    ("ebrschools", "East Baton Rouge Parish School System", "LA", "Baton Rouge"),
    ("roosevelt", "Roosevelt School District 66", "AZ", "Phoenix"),
    ("gcsnc", "Guilford County Schools", "NC", "Greensboro"),
    ("richland2", "Richland County School District Two", "SC", "Columbia"),
    ("gwinnett", "Gwinnett County Public Schools", "GA", "Suwanee"),
    ("okcps", "Oklahoma City Public Schools", "OK", "Oklahoma City"),
    ("cumberland", "Cumberland Regional SD", "NJ", "Seabrook"),
    ("charleston", "Charleston CUSD 1", "IL", "Charleston"),
    ("ccsd", "College Community School District", "IA", "Cedar Rapids"),
]

STATE_DOS_URL = "https://j1visa.state.gov/participants/how-to-apply/sponsor-search/?program=Teacher"
J1_SPONSORS = [
    # organization, address, HQ state, phone, website (as listed on the State Department page)
    ("Florida Department of Education", "325 W GAINES ST, Suite 124, TALLAHASSEE, 32399", "FL", "8502450608", "http://fldoe.org"),
    ("Kentucky Department of Education", "300 SOWER BLVD, Office of Standards, Assessment and Accountability, FRANKFORT, 40601",
     "KY", "5025642106 EXT. 4120", "http://education.ky.gov"),
    ("Ohio Department of Education and Workforce", "25 S FRONT ST # 509, COLUMBUS, 43215", "OH", "6147284630",
     "http://education.ohio.gov/"),
]


EXTRA_SOURCES = [
    # name, connector, config, state, tier
    ("CERRA South Carolina (SchoolSpring)", "schoolspring",
     {"locations": ["South Carolina"], "state_codes": ["SC"], "board_url": "https://cerrasc.schoolspring.com/"}, "SC", 2),
    ("EDJOIN – California", "edjoin", {"board_url": "https://www.edjoin.org/"}, "CA", 2),
    ("K12JobSpot – Frontline national network", "k12jobspot", {"board_url": "https://www.k12jobspot.com/"}, None, 2),
]

# Job sites shown on the "Job Sites" page. auto=True means the scanner reads it; otherwise it is a quick link.
JOB_SITES = [
    {"name": "SchoolSpring", "url": "https://employer.schoolspring.com/find/math-teacher-jobs", "auto": True,
     "note": "Searched nationwide on every scan (all 50 states + DC)."},
    {"name": "CERRA South Carolina", "url": "https://cerrasc.schoolspring.com/", "auto": True,
     "note": "South Carolina's SchoolSpring board; searched in depth for SC on every scan."},
    {"name": "K12JobSpot", "url": "https://www.k12jobspot.com/", "auto": True,
     "note": "Frontline's national network; newest postings read on every scan. Confirm each job on the district's site (APPLY button)."},
    {"name": "EDJOIN", "url": "https://www.edjoin.org/", "auto": True,
     "note": "California's official district application system; searched on every scan."},
    {"name": "Frontline district boards", "url": "https://www.applitrack.com/", "auto": True,
     "note": "25 district boards read directly (see Scan Monitor → Sources)."},
    {"name": "Texas Educator Job Sites (TEA)",
     "url": "https://tea.texas.gov/school-and-district-leaders/other-services/education-service-centers/texas-educator-job-sites",
     "auto": False, "note": "Directory of Texas regional (ESC) job boards and the TASA career center. Open it to browse the regional boards."},
    {"name": "Teach Louisiana", "url": "https://www.teachlouisiana.net/job.aspx?PageID=412", "auto": False,
     "note": "Louisiana district and charter openings. Its site rules do not allow automated reading of job listings, so browse it directly."},
    {"name": "School district career pages", "url": None, "auto": False,
     "note": "Add any district's official careers page in Scan Monitor → Sources (official page connector) to scan it automatically."},
]


def ensure_h1b_employers(db):
    from .h1b_seed import H1B_EMPLOYERS
    from .models import H1BEmployer
    have = {(e.rank, e.name) for e in db.scalars(select(H1BEmployer))}
    for rank, name, salary, url in H1B_EMPLOYERS:
        if (rank, name) not in have:
            db.add(H1BEmployer(rank=rank, name=name, avg_salary=salary, careers_url=url, job_ids=[]))
    db.commit()


def ensure_extra_sources(db):
    have = {s.name for s in db.scalars(select(ScanSource))}
    for name, conn, cfg, st, tier in EXTRA_SOURCES:
        if name not in have:
            db.add(ScanSource(name=name, connector=conn, config=cfg, state=st, tier=tier, enabled=True))
    db.commit()


def seed_reference(db):
    if not db.scalars(select(ScanSource)).first():
        db.add(ScanSource(name="SchoolSpring nationwide search", connector="schoolspring", config={}, tier=2,
                          state=None))
        for slug, name, st, city in APPLITRACK_BOARDS:
            db.add(ScanSource(name=f"{name} (Frontline)", connector="applitrack",
                              config={"client": slug, "district_name": name,
                                      "board_url": f"https://www.applitrack.com/{slug}/onlineapp/default.aspx"},
                              state=st, city=city, tier=2))
    if not db.scalars(select(J1Program)).first():
        for org, addr, st, phone, web in J1_SPONSORS:
            db.add(J1Program(organization=org, organization_type="DESIGNATED_J1_SPONSOR", address=addr,
                             headquarters_state=st, phone=phone, official_website=web, source_url=STATE_DOS_URL,
                             subjects_recruited=[], states_served=[],
                             evidence_quote=f"Listed under category 'Teacher' on the BridgeUSA designated sponsor list",
                             verification_status="VERIFIED", last_verified=datetime(2026, 9, 23),
                             notes="Official location listed by the State Department; placement area not stated on that page."))
    db.commit()


def ensure_profile(db, user: User):
    from .services.resume_parser import DEFAULT_PROFILE
    p = db.scalars(select(CandidateProfile).where(CandidateProfile.user_id == user.id)).first()
    if p:
        return p
    p = CandidateProfile(user_id=user.id, email=user.email, **{k: v for k, v in DEFAULT_PROFILE.items()
                                                               if hasattr(CandidateProfile, k)})
    db.add(p)
    db.add(AlertRule(user_id=user.id, rule_type="HIGH_MATCH", params={"min_score": 90}))
    db.add(AlertRule(user_id=user.id, rule_type="CONFIRMED_J1", params={}))
    db.add(AlertRule(user_id=user.id, rule_type="VERIFIED_PRINCIPAL_EMAIL", params={}))
    db.commit()
    return p


def create_demo(db):
    """Clearly fictional records for trying the UI. Excluded from live results unless demo mode is on."""
    if db.scalars(select(Job).where(Job.is_demo.is_(True))).first():
        return 0
    d = District(name="DEMO / FICTIONAL - Example Unified School District", state="TX", city="Exampleville",
                 website="https://example.invalid", verification_status="UNKNOWN")
    db.add(d)
    db.flush()
    s = School(name="DEMO / FICTIONAL - Example Middle School", district_id=d.id, city="Exampleville", state="TX")
    db.add(s)
    db.flush()
    samples = [
        ("DEMO - 8th Grade Mathematics Teacher", "Middle School (Grade 8)", ["Mathematics"], 55000, 68000, 3, "NEEDS_CONFIRMATION"),
        ("DEMO - High School Algebra II / Geometry Teacher", "High School", ["Mathematics", "Algebra", "Geometry"], 58000, 72000, 9, "UNKNOWN"),
        ("DEMO - AP Calculus Teacher", "High School", ["Mathematics", "Calculus"], None, None, 40, "INTERNATIONAL_FRIENDLY"),
    ]
    for title, grade, subj, smin, smax, age, j1 in samples:
        db.add(Job(canonical_key=f"demo|{title}", job_title=title, subject="Mathematics", subjects=subj, grade_level=grade,
                   employer_name=d.name, district_id=d.id, school_id=s.id, city="Exampleville", state="TX",
                   salary_min=smin, salary_max=smax, salary_text="DEMO salary" if smin else None,
                   date_posted=date.today() - timedelta(days=age), job_status="ACTIVE",
                   status_reason="DEMO / FICTIONAL DATA", official_job_url="https://example.invalid/job",
                   application_url="https://example.invalid/apply", j1_status=j1,
                   job_description="DEMO / FICTIONAL DATA. This record exists only to preview the interface.",
                   is_demo=True, verification_status="UNKNOWN", match_score=None))
    db.commit()
    return len(samples)
