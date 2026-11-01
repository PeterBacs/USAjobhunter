"""Copy this computer's data (data/jobhunter.db) into the cloud PostgreSQL database.

    set DATABASE_URL=postgresql://...   (from Vercel > Storage > Neon)
    python migrate_to_cloud.py

Copies every table (jobs, contacts, applications, re-applied dates, interviews, outbox, settings ...) and stores
the résumé file inside the database. Scan fetch logs are skipped (they are only diagnostics).
Safe to run once on an empty cloud database; it refuses to run if the cloud database already has users.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
LOCAL_DB = (ROOT.parent / "data" / "jobhunter.db").as_posix()
SKIP = {"scan_logs"}


def main() -> int:
    if not (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")):
        print("Set DATABASE_URL to the cloud database first.")
        return 2
    from sqlalchemy import create_engine, func, inspect, insert, select, text
    from app.db import Base, engine as cloud            # cloud engine (DATABASE_URL)
    from app import models  # noqa: F401  (registers every table)
    from app.main import _add_missing_columns

    if not cloud.url.drivername.startswith("postgresql"):
        print("DATABASE_URL is not a PostgreSQL URL.")
        return 2
    local = create_engine(f"sqlite:///{LOCAL_DB}")
    Base.metadata.create_all(cloud)
    _add_missing_columns()
    with cloud.connect() as c:
        if c.execute(select(func.count()).select_from(models.User.__table__)).scalar():
            print("The cloud database already has an account - nothing copied (run only once).")
            return 1
    local_tables = set(inspect(local).get_table_names())
    total = 0
    with local.connect() as src, cloud.begin() as dst:
        for table in Base.metadata.sorted_tables:
            if table.name in SKIP or table.name not in local_tables:
                continue
            local_cols = {c["name"] for c in inspect(local).get_columns(table.name)}
            cols = [c for c in table.columns if c.name in local_cols]
            rows = [dict(r._mapping) for r in src.execute(select(*cols))]
            if table.name == "resumes":
                for r in rows:
                    p = Path(r.get("stored_path") or "")
                    if p.is_file():
                        r["content"] = p.read_bytes()
            for i in range(0, len(rows), 500):
                dst.execute(insert(table), rows[i:i + 500])
            if rows and "id" in table.c:
                dst.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                                 f"(SELECT COALESCE(MAX(id), 1) FROM {table.name}))"))
            total += len(rows)
            print(f"  {table.name}: {len(rows)}")
    print(f"Done - {total} rows copied to the cloud database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
