from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import H1BEmployer, Job, User
from ..serializers import job_row
from ..services import scanner
from ..services.applied import applied_job_ids
from ..services.http import PoliteClient

router = APIRouter(prefix="/api/h1b", tags=["h1b"])


def employer_out(e: H1BEmployer, jobs: dict[int, Job], applied: set[int]) -> dict:
    rows = []
    for jid in e.job_ids or []:
        j = jobs.get(jid)
        if j and j.job_status != "CLOSED":
            r = job_row(j)
            r["applied"] = jid in applied
            rows.append(r)
    rows.sort(key=lambda r: r.get("date_posted") or "", reverse=True)
    return {"id": e.id, "rank": e.rank, "name": e.name, "avg_salary": e.avg_salary, "careers_url": e.careers_url,
            "state": e.state, "board_type": e.board_type, "board_url": e.board_url, "status": e.status,
            "status_detail": e.status_detail, "total_openings": e.total_openings,
            "last_checked": e.last_checked.isoformat() if e.last_checked else None, "jobs": rows}


@router.get("")
def list_employers(db: Session = Depends(get_db), user: User = Depends(current_user)):
    emps = db.scalars(select(H1BEmployer).order_by(H1BEmployer.rank)).all()
    ids = {i for e in emps for i in (e.job_ids or [])}
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_(ids)))} if ids else {}
    applied = applied_job_ids(db, user.id)
    return {"employers": [employer_out(e, jobs, applied) for e in emps], "scan_running": scanner.is_busy()}


@router.post("/{eid}/check")
def check_one(eid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Check one employer right now (live board + matches from the national scans)."""
    from ..services import h1b
    e = db.get(H1BEmployer, eid)
    if not e:
        raise HTTPException(404)
    client = PoliteClient()
    try:
        h1b.check_employer(db, client, e)
    finally:
        client.close()
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_(e.job_ids or [])))} if e.job_ids else {}
    return employer_out(e, jobs, applied_job_ids(db, user.id))
