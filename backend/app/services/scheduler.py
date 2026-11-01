"""Scheduled scans (APScheduler, in-process). Intervals follow the product spec and are user-editable."""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from . import scanner

log = logging.getLogger("jobhunter.scheduler")

DEFAULT_SCHEDULE = {
    "QUICK": {"enabled": True, "hours": 6},
    "FULL": {"enabled": True, "hours": 24},
    "VERIFY_CONTACTS": {"enabled": True, "hours": 24},
    "J1": {"enabled": True, "hours": 72},
    "CLOSED_CHECK": {"enabled": True, "hours": 24},
    "H1B": {"enabled": True, "hours": 24},
    "ENG": {"enabled": True, "hours": 24},
}

_sched: BackgroundScheduler | None = None


def _job(kind):
    def run():
        if scanner.is_busy():
            log.info("Skipping scheduled %s: another scan is running", kind)
            return
        scanner.run_sync(kind, {}, trigger="SCHEDULED")
    return run


def start(schedule: dict | None = None):
    global _sched
    schedule = {**DEFAULT_SCHEDULE, **(schedule or {})}   # new scan types appear even in a saved schedule
    if _sched:
        _sched.shutdown(wait=False)
    _sched = BackgroundScheduler(daemon=True)
    for kind, cfg in schedule.items():
        if cfg.get("enabled"):
            _sched.add_job(_job(kind), "interval", hours=float(cfg.get("hours", 24)), id=kind,
                           max_instances=1, coalesce=True)
    _sched.start()
    return _sched


def status():
    if not _sched:
        return []
    return [{"kind": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
            for j in _sched.get_jobs()]


def shutdown():
    if _sched:
        _sched.shutdown(wait=False)
