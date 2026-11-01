"""Jobs the user has already applied to are hidden from discovery views (job lists, map, dashboard
counts, alerts). They stay in the Applications tracker, and scans keep re-verifying them so a
closed vacancy is still recorded in the application history."""
from sqlalchemy import select

from ..models import Application

# "Mark applied" and every stage after it. SAVED / APPLYING / DISCOVERED stay visible.
APPLIED_STAGES = {"APPLIED", "FOLLOW_UP", "INTERVIEW", "SECOND_INTERVIEW", "OFFER", "HIRED", "REJECTED", "WITHDRAWN"}


def applied_job_ids(db, user_id: int | None = None) -> set[int]:
    q = select(Application.job_id).where(Application.job_id.is_not(None), Application.deleted_at.is_(None),
                                         Application.application_status.in_(APPLIED_STAGES))
    if user_id is not None:
        q = q.where(Application.user_id == user_id)
    return set(db.scalars(q))
