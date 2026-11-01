"""New-job alert rules."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..models import Alert, AlertRule, Job
from .applied import applied_job_ids
from .taxonomy import NAME_TO_ABBR, STATES


def normalize_states(values) -> tuple[list[str], list[str]]:
    """'Texas', 'tx', 'TX' -> 'TX'. Returns (valid codes, unrecognised inputs)."""
    if isinstance(values, str):
        values = values.split(",")
    codes, bad = [], []
    for v in values or []:
        s = str(v).strip()
        if not s:
            continue
        code = s.upper() if s.upper() in STATES else NAME_TO_ABBR.get(s.lower())
        if code:
            if code not in codes:
                codes.append(code)
        else:
            bad.append(s)
    return codes, bad


def allowed_states(db, user_id: int | None = None) -> set[str] | None:
    """States selected in the enabled 'state' rule(s). They filter ALL alerts; None means every state."""
    q = select(AlertRule).where(AlertRule.enabled.is_(True), AlertRule.rule_type == "STATE")
    if user_id is not None:
        q = q.where(AlertRule.user_id == user_id)
    states = set()
    for r in db.scalars(q):
        states.update(normalize_states((r.params or {}).get("states", []))[0])
    return states or None


def _matches(rule: AlertRule, job: Job) -> bool:
    p = rule.params or {}
    if job.is_demo or job.job_status == "CLOSED":
        return False
    t = rule.rule_type
    if t == "HIGH_MATCH":
        return (job.match_score or 0) >= int(p.get("min_score", 90))
    if t == "CONFIRMED_J1":
        return job.j1_status in ("CONFIRMED_J1_VACANCY", "CONFIRMED_J1_EMPLOYER")
    if t == "STATE":
        return (job.state or "") in normalize_states(p.get("states", []))[0]
    if t == "SALARY":
        return (job.salary_max or 0) >= float(p.get("min_salary", 0)) > 0
    if t in ("VERIFIED_RECRUITER_EMAIL", "VERIFIED_PRINCIPAL_EMAIL"):
        want = ("PRINCIPAL", "ASSISTANT_PRINCIPAL") if t.endswith("PRINCIPAL_EMAIL") else None
        for l in job.contact_links:
            c = l.contact
            from .contacts import email_usable
            if email_usable(c):
                if want and c.contact_type in want:
                    return True
                if not want and c.contact_type not in ("PRINCIPAL", "ASSISTANT_PRINCIPAL"):
                    return True
        return False
    return False


TITLES = {
    "HIGH_MATCH": "NEW HIGH-MATCH JOB", "CONFIRMED_J1": "NEW CONFIRMED J-1 MATH JOB", "STATE": "NEW MATH JOB IN STATE",
    "SALARY": "NEW JOB ABOVE SALARY THRESHOLD", "VERIFIED_RECRUITER_EMAIL": "VERIFIED RECRUITER EMAIL FOUND",
    "VERIFIED_PRINCIPAL_EMAIL": "VERIFIED PRINCIPAL EMAIL FOUND",
}


def evaluate(db, new_job_ids: list[int]):
    rules = db.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))).all()
    if not rules:
        return 0
    # New jobs for "new job" rules; all live jobs for "found email" rules (emails may appear later).
    new_jobs = db.scalars(select(Job).where(Job.id.in_(new_job_ids))).all() if new_job_ids else []
    all_live = None
    n = 0
    applied = applied_job_ids(db)  # never alert about a job already applied to
    state_cache: dict[int, set[str] | None] = {}
    for r in rules:
        if r.user_id not in state_cache:
            state_cache[r.user_id] = allowed_states(db, r.user_id)
        only_states = state_cache[r.user_id]
        pool = new_jobs
        if r.rule_type in ("VERIFIED_RECRUITER_EMAIL", "VERIFIED_PRINCIPAL_EMAIL"):
            if all_live is None:
                all_live = db.scalars(select(Job).where(Job.is_demo.is_(False), Job.job_status != "CLOSED")).all()
            pool = all_live
        for job in pool:
            if job.id in applied or not _matches(r, job):
                continue
            if only_states is not None and (job.state or "") not in only_states:
                continue
            exists = db.scalars(select(Alert).where(Alert.rule_id == r.id, Alert.job_id == job.id)).first()
            if exists:
                continue
            place = ", ".join(filter(None, [job.school.name if job.school else None, job.employer_name, job.city, job.state]))
            db.add(Alert(user_id=r.user_id, rule_id=r.id, job_id=job.id, title=TITLES.get(r.rule_type, "ALERT"),
                         message=f"{job.job_title} - {place}. Match: {job.match_score}%"))
            try:
                db.flush()
                n += 1
            except IntegrityError:
                db.rollback()
    db.commit()
    return n
