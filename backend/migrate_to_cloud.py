"""Copy this computer's data (data/jobhunter.db) into the cloud PostgreSQL database.

Run "Upload my data to the cloud.bat" (asks for the database address with hidden typing), or:
    set DATABASE_URL=postgresql://...   (Vercel > Storage > your Neon database > .env.local > DATABASE_URL)
    python migrate_to_cloud.py

Copies every table (jobs, contacts, applications, re-applied dates, interviews, outbox, settings ...) and stores
the résumé file inside the database. Scan fetch logs are skipped (only diagnostics).
Runs only on a cloud database that has no account yet.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
LOCAL_DB = (ROOT.parent / "data" / "jobhunter.db").as_posix()
SKIP = {"scan_logs"}


def _clean(table, row: dict) -> dict:
    """PostgreSQL is stricter than SQLite: enforce text lengths and drop NUL characters."""
    for col in table.columns:
        v = row.get(col.name)
        if isinstance(v, str):
            v = v.replace("\x00", "")
            n = getattr(col.type, "length", None)
            row[col.name] = v[:n] if n else v
    return row


def main() -> int:
    if not (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")):
        print("Set DATABASE_URL to the cloud database first.")
        return 2
    from sqlalchemy import create_engine, func, inspect, insert, select, text
    from app.db import Base, engine as cloud
    from app import models  # noqa: F401  (registers every table)
    from app.main import _add_missing_columns

    if not cloud.url.drivername.startswith("postgresql"):
        print("That is not a PostgreSQL database address.")
        return 2
    print("Connecting to the cloud database ...")
    local = create_engine(f"sqlite:///{LOCAL_DB}")
    Base.metadata.create_all(cloud)
    _add_missing_columns()
    with cloud.connect() as c:
        if c.execute(select(func.count()).select_from(models.User.__table__)).scalar():
            print("The cloud database already has your account - nothing copied (this only runs once).")
            return 1
    insp = inspect(local)
    local_tables = set(insp.get_table_names())
    total = skipped = 0
    with local.connect() as src:
        for table in Base.metadata.sorted_tables:
            if table.name in SKIP or table.name not in local_tables:
                continue
            local_cols = {c["name"] for c in insp.get_columns(table.name)}
            cols = [c for c in table.columns if c.name in local_cols]
            rows = [_clean(table, dict(r._mapping)) for r in src.execute(select(*cols))]
            if table.name == "resumes":
                for r in rows:
                    p = Path(r.get("stored_path") or "")
                    if p.is_file():
                        r["content"] = p.read_bytes()
            bad = 0
            with cloud.connect() as dst:
                for i in range(0, len(rows), 500):
                    chunk = rows[i:i + 500]
                    try:
                        with dst.begin():
                            dst.execute(insert(table), chunk)
                    except Exception:
                        # Insert one by one so a single bad row (e.g. pointing at a deleted record) doesn't block the rest.
                        for r in chunk:
                            try:
                                with dst.begin():
                                    dst.execute(insert(table), [r])
                            except Exception:
                                bad += 1
                if rows and "id" in table.c:
                    with dst.begin():
                        dst.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                                         f"(SELECT COALESCE(MAX(id), 1) FROM {table.name}))"))
            total += len(rows) - bad
            skipped += bad
            print(f"  {table.name}: {len(rows) - bad} copied" + (f", {bad} skipped" if bad else ""))
    print(f"\nDone - {total} records copied to the cloud database" + (f" ({skipped} skipped)." if skipped else "."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
