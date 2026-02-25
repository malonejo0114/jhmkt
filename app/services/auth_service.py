from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppUser
from app.services.passwords import hash_password, verify_password

SESSION_USER_KEY = "uid"


def create_user(db: Session, *, email: str, display_name: str, password: str) -> AppUser:
    normalized_email = email.strip().lower()
    if not normalized_email:
        raise ValueError("이메일은 필수입니다.")

    existing = db.execute(select(AppUser).where(AppUser.email == normalized_email)).scalars().first()
    if existing:
        raise ValueError("이미 사용 중인 이메일입니다.")

    user = AppUser(
        email=normalized_email,
        display_name=display_name.strip() or normalized_email.split("@")[0],
        password_hash=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, email: str, password: str) -> AppUser | None:
    normalized_email = email.strip().lower()
    user = db.execute(select(AppUser).where(AppUser.email == normalized_email)).scalars().first()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def login_user(request, user: AppUser) -> None:
    request.session[SESSION_USER_KEY] = str(user.id)


def logout_user(request) -> None:
    request.session.clear()


def get_current_user(request, db: Session) -> AppUser | None:
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None

    try:
        user_uuid = UUID(str(user_id))
    except ValueError:
        return None

    user = db.get(AppUser, user_uuid)
    if not user or not user.is_active:
        return None
    return user
