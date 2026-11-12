from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import EngJob, ScanRun, User
from ..services import engineering, scanner

router = APIRouter(prefix="/api/engineering", tags=["engineering"])


def out(r: EngJob, snippet: str | None = None) -> dict:
    days = (date.today() - r.posted).days if r.posted else None
    return {"id": r.id, "category": r.category, "title": r.title, "company": r.company, "location": r.location,
            "state": r.state, "remote": r.remote, "url": r.url, "source": r.source, "posted": r.posted.isoformat() if r.posted else None,
            "days_old": days, "level": r.level, "years_required": r.years_required, "sponsorship": r.sponsorship,
            "citizenship_required": r.citizenship_required, "phd_required": r.phd_required, "skills": r.skills or [],
            "match_score": r.match_score, "why": (r.match or {}).get("why", []), "gaps": (r.match or {}).get("gaps", []),
            "skill_points": ((r.match or {}).get("breakdown") or {}).get("skills", 0),
            "snippet": snippet if snippet is not None else (r.description or "")[:700], "is_saved": r.is_saved,
            "applied_on": r.applied_on.isoformat() if r.applied_on else None, "job_id": r.job_id,
            "salary_text": r.salary_text, "salary_annual": engineering.annual(r.salary_min, r.salary_max, r.salary_interval),
            "first_seen": r.first_seen.isoformat() if r.first_seen else None,
            "work_mode": r.work_mode or ("REMOTE" if r.remote else "UNKNOWN"), "remote_scope": r.remote_scope}


@router.get("")
def list_jobs(category: str = "INDUSTRY", include_closed: bool = False,
              db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(EngJob).where(EngJob.category == category.upper())
    if not include_closed:
        q = q.where(EngJob.status == "ACTIVE")
    # Only the first 700 characters of each description leave the database (not the full text).
    rows = db.execute(q.add_columns(func.substr(EngJob.description, 1, 700)).order_by(EngJob.match_score.desc())).all()
    last = db.scalars(select(ScanRun).where(ScanRun.kind == "ENG").order_by(ScanRun.id.desc())).first()
    counts = {c: db.scalar(select(func.count()).select_from(EngJob).where(EngJob.category == c, EngJob.status == "ACTIVE"))
              for c in ("INDUSTRY", "SOFTWARE", "INSTRUCTOR")}
    companies = sorted({c for _, c in engineering.GREENHOUSE + engineering.LEVER + engineering.ASHBY + engineering.WORKABLE})
    return {"items": [out(r, snip or "") for r, snip in rows], "profile": engineering.PROFILE, "counts": counts,
            "skill_options": [label for label, _ in engineering.SKILLS],
            "default_skills": [label for label, _ in engineering.SKILLS if label not in engineering.OPTIONAL_SKILLS],
            "last_scan": {"status": last.status, "finished_at": last.finished_at.isoformat() if last.finished_at else None,
                          "stats": last.stats or {}} if last else None,
            "sources": {"companies": companies,
                        "boards": ["The Muse"] + engineering.REMOTE_BOARDS,
                        "instructor": [s for s, _ in engineering.MADGEX] + ["K-12 engineering / robotics / CTE (teaching scans)"]},
            "scan_running": scanner.is_busy()}


API_KEY_FIELDS = ("jsearch_key", "adzuna_app_id", "adzuna_app_key")


def _mask(v: str | None) -> str | None:
    return ("•" * 8 + v[-4:]) if v else None


@router.get("/apis")
def get_apis(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Job-search API settings. Keys are never sent back to the browser, only a masked hint."""
    cfg = ((user.settings or {}).get("job_apis") or {})
    return {"keys": {k: _mask(cfg.get(k)) for k in API_KEY_FIELDS},
            "queries": cfg.get("queries") or engineering.DEFAULT_API_QUERIES,
            "last_status": cfg.get("last_status") or {}, "jsearch_last": cfg.get("jsearch_last")}


@router.put("/apis")
def put_apis(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Missing field = keep; empty string = remove."""
    cfg = dict((user.settings or {}).get("job_apis") or {})
    for k in API_KEY_FIELDS:
        if k in body:
            v = str(body[k] or "").strip()
            if v:
                cfg[k] = v
            else:
                cfg.pop(k, None)
            # A new or removed key starts fresh: forget its old status and let JSearch run on the next search.
            provider = "JSearch" if k == "jsearch_key" else "Adzuna"
            cfg["last_status"] = {n: s for n, s in (cfg.get("last_status") or {}).items() if not n.startswith(provider)}
            if k == "jsearch_key":
                cfg.pop("jsearch_last", None)
    if "queries" in body:
        qs = [str(q).strip() for q in (body["queries"] or []) if str(q).strip()][:12]
        cfg["queries"] = qs or engineering.DEFAULT_API_QUERIES
    user.settings = {**(user.settings or {}), "job_apis": cfg}
    db.commit()
    return get_apis(db, user)


@router.post("/{jid}/save")
def toggle_save(jid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = db.get(EngJob, jid)
    if not r:
        raise HTTPException(404)
    r.is_saved = not r.is_saved
    db.commit()
    return out(r)


@router.post("/{jid}/applied")
def toggle_applied(jid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = db.get(EngJob, jid)
    if not r:
        raise HTTPException(404)
    r.applied_on = None if r.applied_on else date.today()
    db.commit()
    return out(r)
