import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import COOKIE, MAX_AGE, check_password, current_user, hash_password, make_token
from ..config import UPLOAD_DIR
from ..db import get_db
from ..models import CandidateProfile, Resume, User
from ..seed import ensure_profile
from ..services.ingest import rescore_all
from ..services.resume_parser import extract_text, parse_resume

router = APIRouter(prefix="/api", tags=["profile"])


class Creds(BaseModel):
    email: str
    password: str
    full_name: str | None = None


@router.get("/auth/status")
def auth_status(db: Session = Depends(get_db)):
    from ..config import ON_VERCEL
    empty = (db.scalar(select(func.count()).select_from(User)) or 0) == 0
    # Online, the account is copied from your computer; nobody can create one on the public site.
    return {"needs_setup": empty and not ON_VERCEL, "awaiting_data": empty and ON_VERCEL}


@router.post("/auth/setup")
def setup(body: Creds, response: Response, db: Session = Depends(get_db)):
    from ..config import ON_VERCEL
    if ON_VERCEL:
        raise HTTPException(403, "Accounts can't be created on the online site.")
    if db.scalar(select(func.count()).select_from(User)):
        raise HTTPException(403, "Already set up - sign in instead")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    u = User(email=body.email.strip().lower(), full_name=body.full_name or "", password_hash=hash_password(body.password))
    db.add(u)
    db.commit()
    ensure_profile(db, u)
    response.set_cookie(COOKIE, make_token(u.id), max_age=MAX_AGE, httponly=True, samesite="lax")
    return {"ok": True}


@router.post("/auth/login")
def login(body: Creds, response: Response, db: Session = Depends(get_db)):
    u = db.scalars(select(User).where(User.email == body.email.strip().lower())).first()
    if not u or not check_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    response.set_cookie(COOKIE, make_token(u.id), max_age=MAX_AGE, httponly=True, samesite="lax")
    return {"ok": True}


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
def me(db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = ensure_profile(db, user)
    return {"user": {"id": user.id, "email": user.email, "full_name": user.full_name}, "profile": _profile_out(p)}


PROFILE_FIELDS = ["full_name", "email", "phone", "location", "headline", "years_experience", "education", "licenses",
                  "subjects", "grade_levels", "leadership", "technologies", "awards", "research_stem", "languages",
                  "work_authorization", "preferred_states", "min_salary", "has_us_license", "has_us_drivers_license"]


def _profile_out(p: CandidateProfile) -> dict:
    return {f: getattr(p, f) for f in PROFILE_FIELDS} | {"active_resume_id": p.active_resume_id}


@router.put("/profile")
def update_profile(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = ensure_profile(db, user)
    for k, v in body.items():
        if k in PROFILE_FIELDS:
            setattr(p, k, v)
    db.commit()
    n = rescore_all(db)
    return {"profile": _profile_out(p), "rescored": n}


@router.get("/resumes")
def list_resumes(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{"id": r.id, "filename": r.filename, "version_label": r.version_label, "is_active": r.is_active,
             "uploaded_at": r.uploaded_at.isoformat(), "parsed": r.parsed}
            for r in db.scalars(select(Resume).where(Resume.user_id == user.id).order_by(Resume.uploaded_at.desc()))]


@router.post("/resumes")
def upload_resume(file: UploadFile = File(...), version_label: str = Form(""), apply_to_profile: bool = Form(True),
                  db: Session = Depends(get_db), user: User = Depends(current_user)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt"):
        raise HTTPException(400, "Upload a PDF, DOCX or TXT résumé")
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        text = extract_text(dest)
    except Exception as e:
        raise HTTPException(422, f"Could not read the file: {e}")
    if len(text.strip()) < 50:
        raise HTTPException(422, "Very little text could be extracted (scanned image PDF?). Upload a text-based PDF or DOCX.")
    parsed = parse_resume(text)
    for r in db.scalars(select(Resume).where(Resume.user_id == user.id)):
        r.is_active = False
    count = db.scalar(select(func.count()).select_from(Resume).where(Resume.user_id == user.id)) or 0
    r = Resume(user_id=user.id, filename=file.filename or dest.name, stored_path=str(dest), content=dest.read_bytes(),
               version_label=version_label or f"v{count + 1}", text=text, parsed=parsed, is_active=True)
    db.add(r)
    db.flush()
    p = ensure_profile(db, user)
    p.active_resume_id = r.id
    if apply_to_profile:
        # Replace only fields the parser actually found; keep everything else the user entered.
        for k in ("full_name", "email", "phone", "years_experience"):
            if parsed.get(k):
                setattr(p, k, parsed[k])
        for k in ("education", "licenses", "subjects", "grade_levels", "leadership", "technologies", "awards", "research_stem"):
            if parsed.get(k):
                setattr(p, k, parsed[k])
    db.commit()
    n = rescore_all(db)
    return {"resume_id": r.id, "parsed": parsed, "rescored_jobs": n, "profile": _profile_out(p)}
