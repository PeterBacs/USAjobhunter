"""Vercel entry point: the FastAPI app (website + API). Scans run in GitHub Actions, not here."""
import os
import sys
from pathlib import Path

os.environ.setdefault("JH_DATA_DIR", "/tmp/jobhunter")   # Vercel's file system is read-only except /tmp
os.environ.setdefault("JH_SCHEDULER", "0")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.main import app  # noqa: E402,F401
