"""Set a new sign-in password (typing hidden). Updates this computer's app and, optionally, the online version."""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def set_password(engine_url: str | None, email: str | None, pw_hash: str) -> str | None:
    from sqlalchemy import create_engine, select, update
    from app.models import User
    if engine_url:
        from app.config import _database_url
        import os
        os.environ["DATABASE_URL"] = engine_url
        engine_url = _database_url()
    else:
        engine_url = f"sqlite:///{(Path(__file__).parent.parent / 'data' / 'jobhunter.db').as_posix()}"
    eng = create_engine(engine_url)
    with eng.begin() as c:
        u = c.execute(select(User.__table__.c.id, User.__table__.c.email).order_by(User.__table__.c.id)).first()
        if not u:
            return None
        c.execute(update(User.__table__).where(User.__table__.c.id == u.id).values(password_hash=pw_hash))
        return u.email


def main() -> int:
    from app.auth import hash_password
    print("USA Job Hunter - set a new password\n")
    pw = getpass.getpass("New password (at least 8 characters, typing hidden): ")
    if len(pw) < 8:
        print("Too short - nothing changed.")
        return 2
    if getpass.getpass("Type it again: ") != pw:
        print("The two passwords don't match - nothing changed.")
        return 2
    h = hash_password(pw)
    email = set_password(None, None, h)
    print(f"\nThis computer: password changed for {email}." if email else "\nThis computer: no account found.")
    print("\nAlready uploaded your data online? Paste the DATABASE_URL to change it there too,")
    url = getpass.getpass("or just press Enter to skip (typing hidden): ").strip().strip('"').strip("'")
    if url.startswith("DATABASE_URL="):
        url = url.split("=", 1)[1].strip().strip('"')
    if url:
        try:
            email2 = set_password(url, None, h)
            print(f"Online: password changed for {email2}." if email2 else "Online: no account there yet - upload your data first; it will carry the new password.")
        except Exception as e:
            print(f"Online: couldn't connect ({type(e).__name__}). Nothing changed online.")
    # Prove it: type the password once more and check it against what was just saved.
    from app.auth import check_password
    test = getpass.getpass("\nTest it - type the new password once more (hidden): ")
    print(f"You typed {len(test)} characters; the new password has {len(pw)}.")
    print("OK - this is the password to use on the website." if check_password(test, h)
          else "NO MATCH - that isn't the new password. Run this tool again and type slowly.")
    print("\nSign in with pjfreelance02@gmail.com and the new password. On the website, clear the password box first")
    print("(the browser may fill in an old saved password) and type it by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
