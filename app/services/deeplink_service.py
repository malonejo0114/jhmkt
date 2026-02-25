from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import DeeplinkCache
from app.services.coupang_client import create_coupang_deeplink
from app.services.hash_utils import sha256_hex

CACHE_TTL_DAYS = 90


def get_or_create_deeplink(db: Session, original_url: str) -> str:
    settings = get_settings()
    original_hash = sha256_hex(original_url)
    cached = db.get(DeeplinkCache, original_hash)
    now = datetime.now(timezone.utc)

    if cached and (cached.expires_at is None or cached.expires_at > now):
        return cached.short_url

    if settings.run_mode == "live":
        short_url = create_coupang_deeplink(original_url)
    else:
        short_url = f"https://coupa.ng/{original_hash[:8]}"

    if cached:
        cached.short_url = short_url
        cached.expires_at = now + timedelta(days=CACHE_TTL_DAYS)
    else:
        db.add(
            DeeplinkCache(
                original_url_hash=original_hash,
                original_url=original_url,
                short_url=short_url,
                vendor="COUPANG",
                expires_at=now + timedelta(days=CACHE_TTL_DAYS),
            )
        )
    return short_url
