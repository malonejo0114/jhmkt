from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import CommentRule, ContentSourceItem, InstagramAccount, ThreadsAccount


def get_setup_summary(db: Session) -> dict:
    settings = get_settings()

    checks = {
        "public_base_url": bool(settings.public_base_url.strip()),
        "oauth_enabled": settings.oauth_enabled,
        "threads_app": bool(settings.threads_app_id.strip() and settings.threads_app_secret.strip()),
        "instagram_app": bool(
            settings.instagram_app_id.strip() and settings.instagram_app_secret.strip()
        ),
        "meta_webhook_verify_token": bool(settings.meta_webhook_verify_token.strip()),
        "coupang_api": bool(settings.coupang_access_key.strip() and settings.coupang_secret_key.strip()),
        "gemini_api": bool(settings.gemini_api_key.strip()),
        "stock_image_api": bool(settings.pexels_api_key.strip() or settings.unsplash_access_key.strip()),
        "internal_api_key": bool(settings.internal_api_key.strip()),
    }

    missing = [name for name, ok in checks.items() if not ok]

    threads_accounts = db.execute(select(func.count(ThreadsAccount.id))).scalar_one()
    instagram_accounts = db.execute(select(func.count(InstagramAccount.id))).scalar_one()
    comment_rules = db.execute(select(func.count(CommentRule.id))).scalar_one()
    seed_items = db.execute(select(func.count(ContentSourceItem.id))).scalar_one()

    base = settings.public_base_url.rstrip("/")
    callbacks = {
        "threads_callback": f"{base}/auth/connect/threads/callback" if base else "",
        "instagram_callback": f"{base}/auth/connect/instagram/callback" if base else "",
        "meta_webhook": f"{base}/webhooks/meta" if base else "",
    }

    return {
        "checks": checks,
        "missing": missing,
        "counts": {
            "threads_accounts": int(threads_accounts),
            "instagram_accounts": int(instagram_accounts),
            "comment_rules": int(comment_rules),
            "seed_items": int(seed_items),
        },
        "callbacks": callbacks,
    }
