import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .config import FRONTEND_DIR, ON_VERCEL, SCHEDULER_ENABLED
from .db import Base, SessionLocal, engine
from .models import ScanRun, User
from .routers import admin, crm, engineering, h1b, jobs, outbox, profile
from .seed import seed_reference

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _add_missing_columns():
    """Lightweight migration: add columns introduced after the database was created."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    coltype = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {coltype}'))
                    logging.getLogger("jobhunter").info("Added column %s.%s", table.name, col.name)


def startup_tasks(full: bool = True):
    """Create / upgrade tables and seed reference data. `full` also repairs stored contacts (skipped on Vercel,
    where every cold start runs this; the scheduled cloud job runs the full version)."""
    Base.metadata.create_all(engine)
    _add_missing_columns()
    db = SessionLocal()
    try:
        seed_reference(db)
        from .seed import ensure_extra_sources, ensure_h1b_employers
        ensure_extra_sources(db)
        ensure_h1b_employers(db)
        if full:
            from .services.contacts import sanitize_contacts
            fixed = sanitize_contacts(db)
            if fixed["fixed"] or fixed["deleted"]:
                logging.getLogger("jobhunter").info("Contact cleanup: %s", fixed)
        schedule = None
        u = db.scalars(select(User)).first()
        if u and (u.settings or {}).get("schedule"):
            schedule = u.settings["schedule"]
        return db, schedule
    except Exception:
        db.close()
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    db, schedule = startup_tasks(full=not ON_VERCEL)
    try:
        if not ON_VERCEL:
            # Runs interrupted by a restart can never finish (on this computer; cloud runs live in GitHub Actions).
            for r in db.scalars(select(ScanRun).where(ScanRun.status == "RUNNING")):
                r.status, r.error = "FAILED", "Interrupted by server restart"
            db.commit()
    finally:
        db.close()
    if SCHEDULER_ENABLED and not ON_VERCEL:
        from .services import scheduler
        scheduler.start(schedule)
    yield
    if SCHEDULER_ENABLED and not ON_VERCEL:
        from .services import scheduler
        scheduler.shutdown()


app = FastAPI(title="USA JOB HUNTER", version="1.0", lifespan=lifespan)
for r in (profile.router, jobs.router, crm.router, admin.router, h1b.router, engineering.router, outbox.router):
    app.include_router(r)


@app.middleware("http")
async def no_cache_static(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/health")
def health():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")
