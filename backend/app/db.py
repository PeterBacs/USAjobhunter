from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL

_is_sqlite = DATABASE_URL.startswith("sqlite")


def _ipv4_connect_args() -> dict:
    """Connect to PostgreSQL over IPv4. GitHub's runners have no IPv6 network, and the database host can resolve to
    an IPv6 address first ("Network is unreachable"). `hostaddr` picks the IPv4 address; `host` is still sent, so
    TLS and Neon's endpoint routing keep working."""
    import socket
    from sqlalchemy.engine import make_url
    host = make_url(DATABASE_URL).host
    try:
        ip = socket.getaddrinfo(host, 5432, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        return {"hostaddr": ip, "connect_timeout": 20}
    except (OSError, IndexError, TypeError):
        return {"connect_timeout": 20}


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else _ipv4_connect_args(),
    pool_pre_ping=True,
    **({} if _is_sqlite else {"pool_size": 3, "max_overflow": 2, "pool_recycle": 280}),
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
