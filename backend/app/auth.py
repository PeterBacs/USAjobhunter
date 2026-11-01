"""Minimal session auth: PBKDF2 password hashes and HMAC-signed session cookies."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import DATA_DIR, SECRET_KEY
from .db import get_db
from .models import User

COOKIE = "jh_session"
MAX_AGE = 60 * 60 * 24 * 30


def _secret() -> bytes:
    if SECRET_KEY:
        return SECRET_KEY.encode()
    f = DATA_DIR / ".secret_key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip().encode()


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 310_000)
    return "pbkdf2$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt_b64, dk_b64 = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt_b64), 310_000)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


def make_token(user_id: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"u": user_id, "t": int(time.time())}).encode()).decode()
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_token(token: str | None) -> int | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()):
        return None
    data = json.loads(base64.urlsafe_b64decode(payload.encode()))
    if time.time() - data["t"] > MAX_AGE:
        return None
    return data["u"]


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = read_token(request.cookies.get(COOKIE))
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(401, "Not signed in")
    return user
