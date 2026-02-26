from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccountStatus, InstagramAccount, ThreadsAccount
from app.schemas.accounts import InstagramAccountCreate, ThreadsAccountCreate
from app.services.engagement_service import get_or_create_profile_by_vertical
from app.services.security import encrypt_token


def upsert_threads_account(db: Session, payload: ThreadsAccountCreate) -> ThreadsAccount:
    brand_profile_id = None
    if payload.brand_vertical is not None:
        profile = get_or_create_profile_by_vertical(db, payload.brand_vertical)
        brand_profile_id = profile.id

    existing = (
        db.execute(
            select(ThreadsAccount).where(ThreadsAccount.threads_user_id == payload.threads_user_id)
        )
        .scalars()
        .first()
    )

    if existing:
        existing.name = payload.name
        existing.access_token_enc = encrypt_token(payload.access_token)
        existing.token_expires_at = payload.token_expires_at
        if brand_profile_id is not None:
            existing.brand_profile_id = brand_profile_id
        existing.status = AccountStatus.ACTIVE
        db.commit()
        db.refresh(existing)
        return existing

    account = ThreadsAccount(
        brand_profile_id=brand_profile_id,
        name=payload.name,
        threads_user_id=payload.threads_user_id,
        access_token_enc=encrypt_token(payload.access_token),
        token_expires_at=payload.token_expires_at,
        status=AccountStatus.ACTIVE,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def upsert_instagram_account(db: Session, payload: InstagramAccountCreate) -> InstagramAccount:
    brand_profile_id = None
    if payload.brand_vertical is not None:
        profile = get_or_create_profile_by_vertical(db, payload.brand_vertical)
        brand_profile_id = profile.id

    existing = (
        db.execute(select(InstagramAccount).where(InstagramAccount.ig_user_id == payload.ig_user_id))
        .scalars()
        .first()
    )

    if existing:
        existing.name = payload.name
        existing.access_token_enc = encrypt_token(payload.access_token)
        existing.token_expires_at = payload.token_expires_at
        if brand_profile_id is not None:
            existing.brand_profile_id = brand_profile_id
        existing.status = AccountStatus.ACTIVE
        db.commit()
        db.refresh(existing)
        return existing

    account = InstagramAccount(
        brand_profile_id=brand_profile_id,
        name=payload.name,
        ig_user_id=payload.ig_user_id,
        access_token_enc=encrypt_token(payload.access_token),
        token_expires_at=payload.token_expires_at,
        status=AccountStatus.ACTIVE,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account
