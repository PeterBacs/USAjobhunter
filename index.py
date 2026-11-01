"""Vercel entry point: the FastAPI app (website + API). Scans run in GitHub Actions, not here."""
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

os.environ.setdefault("JH_DATA_DIR", "/tmp/jobhunter")   # Vercel's file system is read-only except /tmp
os.environ.setdefault("JH_SCHEDULER", "0")
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

# Without the cloud database the app would start empty (and offer "Create account" to anyone),
# so until DATABASE_URL is set only this setup page is served.
app = FastAPI()


@app.get("/{path:path}", response_class=HTMLResponse)
def setup_pending(path: str = ""):
    return "<h2>USA Job Hunter</h2><p>Setup in progress: the database is not connected yet.</p>"


if os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL"):
    from app.main import app as _jobhunter_app  # noqa: E402

    app = _jobhunter_app
