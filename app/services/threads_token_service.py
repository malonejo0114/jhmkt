from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import TypeVar

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ThreadsAccount
from app.services.exceptions import PermanentPublishError
from app.services.meta_oauth_service import refresh_threads_access_token
from app.services.security import decrypt_token, encrypt_token

T = TypeVar("T")
THREADS_TOKEN_REFRESH_LEAD = timedelta(days=3)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_expiring_soon(expires_at: datetime | None, *, now: datetime) -> bool:
    normalized = _as_utc(expires_at)
    if normalized is None:
        return False
    return normalized <= now + THREADS_TOKEN_REFRESH_LEAD


def _is_token_error(exc: Exception) -> bool:
    if not isinstance(exc, PermanentPublishError):
        return False
    if exc.code not in {"HTTP_400", "HTTP_401", "HTTP_403"}:
        return False
    msg = str(exc).lower()
    return (
        "access token" in msg
        or "oauth" in msg
        or "error validating access token" in msg
        or '"code":190' in msg
        or '"code": 190' in msg
    )


def ensure_threads_access_token(
    db: Session,
    account: ThreadsAccount,
    *,
    force_refresh: bool = False,
) -> str:
    current_token = decrypt_token(account.access_token_enc)
    if get_settings().run_mode == "mock":
        return current_token

    now = datetime.now(timezone.utc)
    if not force_refresh and not _is_expiring_soon(account.token_expires_at, now=now):
        return current_token

    try:
        refreshed_token, refreshed_expires_at = refresh_threads_access_token(current_token)
    except Exception as exc:  # noqa: BLE001
        if force_refresh:
            raise PermanentPublishError(
                f"threads token refresh 실패: {str(exc)[:500]}",
                code="THREADS_TOKEN_REFRESH_FAILED",
            ) from exc
        return current_token

    account.access_token_enc = encrypt_token(refreshed_token)
    account.token_expires_at = _as_utc(refreshed_expires_at) or account.token_expires_at
    db.commit()
    db.refresh(account)
    return refreshed_token


def run_with_threads_token_retry(
    db: Session,
    account: ThreadsAccount,
    operation: Callable[[str], T],
) -> T:
    token = ensure_threads_access_token(db, account, force_refresh=False)
    try:
        return operation(token)
    except Exception as exc:  # noqa: BLE001
        if not _is_token_error(exc):
            raise
    refreshed = ensure_threads_access_token(db, account, force_refresh=True)
    return operation(refreshed)
