"""Asks for the cloud database address (typing hidden) and copies this computer's data into it."""
import getpass
import os
import subprocess
import sys
from pathlib import Path

print("USA Job Hunter - copy your data to the online version\n")
print("Paste the DATABASE_URL from Vercel > Storage > your Neon database > .env.local tab")
print("(right-click to paste; nothing is shown while you paste - that's normal), then press Enter.\n")
url = ""
# A pasted multi-line snippet arrives one line at a time: skip comments until the DATABASE_URL line.
for _ in range(12):
    line = getpass.getpass("DATABASE_URL: " if not url else "").strip().strip('"').strip("'")
    if "=" in line and line.split("=", 1)[0].strip() in ("DATABASE_URL", "POSTGRES_URL"):
        line = line.split("=", 1)[1].strip().strip('"').strip("'")
    if line.startswith(("postgres://", "postgresql://")):
        url = line
        break
    if line and not line.startswith("#"):
        break
if not url.startswith(("postgres://", "postgresql://")):
    print("\nThat doesn't look like a database address (it should start with postgresql://). Nothing was copied.")
    sys.exit(2)
env = dict(os.environ, DATABASE_URL=url, PYTHONIOENCODING="utf-8", JH_SCHEDULER="0")
sys.exit(subprocess.call([sys.executable, str(Path(__file__).with_name("migrate_to_cloud.py"))], env=env,
                         cwd=str(Path(__file__).parent)))
