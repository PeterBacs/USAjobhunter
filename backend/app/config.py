"""Runtime configuration. Every value can be overridden with an environment variable."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("JH_DATA_DIR", ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DOCUMENT_DIR = DATA_DIR / "documents"
FRONTEND_DIR = ROOT / "frontend"

for d in (DATA_DIR, UPLOAD_DIR, DOCUMENT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# PostgreSQL in the cloud (Neon via Vercel sets DATABASE_URL / POSTGRES_URL), SQLite on this computer.
def _database_url() -> str:
    url = os.getenv("JH_DATABASE_URL") or os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or f"sqlite:///{(DATA_DIR / 'jobhunter.db').as_posix()}"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _database_url()
IS_CLOUD = DATABASE_URL.startswith("postgresql")
ON_VERCEL = bool(os.getenv("VERCEL"))

SECRET_KEY = os.getenv("JH_SECRET_KEY", "")  # generated and persisted on first run if empty
USER_AGENT = os.getenv(
    "JH_USER_AGENT",
    "USAJobHunter/1.0 (+personal teacher job research; respects robots.txt)",
)
# Minimum seconds between two requests to the same host.
PER_HOST_DELAY = float(os.getenv("JH_PER_HOST_DELAY", "1.0"))
HTTP_TIMEOUT = float(os.getenv("JH_HTTP_TIMEOUT", "30"))

# SchoolSpring pagination limits per keyword during a scan.
SCHOOLSPRING_PAGES_QUICK = int(os.getenv("JH_SS_PAGES_QUICK", "2"))
SCHOOLSPRING_PAGES_FULL = int(os.getenv("JH_SS_PAGES_FULL", "8"))
SCHOOLSPRING_PAGE_SIZE = int(os.getenv("JH_SS_PAGE_SIZE", "50"))

SCHEDULER_ENABLED = os.getenv("JH_SCHEDULER", "1") == "1"

# Optional LLM extraction (only runs on text actually retrieved from a source).
ANTHROPIC_MODEL = os.getenv("JH_ANTHROPIC_MODEL", "claude-opus-5-5")
LLM_ENABLED = os.getenv("JH_LLM", "0") == "1"

# Philippines time zone for interview conversion.
HOME_TZ = os.getenv("JH_HOME_TZ", "Asia/Manila")

# Cloud mode: cloud servers block the mail-server check (port 25), so mailbox confirmation is turned off there and
# emails are accepted only when printed on the school's / district's official website (found by the AI finder).
MAILBOX_CHECK = os.getenv("JH_MAILBOX_CHECK", "0" if IS_CLOUD else "1") == "1"

# AI contact finder (Claude + web search). Off unless an API key is configured. Caps keep the cost predictable.
AI_FINDER = bool(os.getenv("ANTHROPIC_API_KEY")) and os.getenv("JH_AI_FINDER", "1") == "1"
AI_MAX_LOOKUPS_PER_RUN = int(os.getenv("JH_AI_MAX_LOOKUPS_PER_RUN", "8"))
AI_MAX_LOOKUPS_PER_DAY = int(os.getenv("JH_AI_MAX_LOOKUPS_PER_DAY", "25"))

# Email notifications and sending (Gmail app password). Values come from environment variables in the cloud.
NOTIFY_EMAIL = os.getenv("JH_NOTIFY_EMAIL", "")
GMAIL_ADDRESS = os.getenv("JH_GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("JH_GMAIL_APP_PASSWORD", "")
APP_URL = os.getenv("JH_APP_URL", "https://sniperteacherjob.vercel.app").rstrip("/")

# "Run scan now" on the website starts the GitHub Actions workflow (needs a GitHub token with Actions: write).
GITHUB_REPO = os.getenv("JH_GITHUB_REPO", "PeterBacs/USAjobhunter")
GITHUB_DISPATCH_TOKEN = os.getenv("JH_GITHUB_TOKEN", "")
