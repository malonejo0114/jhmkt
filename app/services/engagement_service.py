from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    BrandProfile,
    BrandVertical,
    CommentActionType,
    CommentEvent,
    CommentEventStatus,
    CommentRule,
    CommentTriggerType,
    InstagramAccount,
    QuotaBucket,
    QuotaBucketType,
    ReplyJob,
    ReplyJobStatus,
    ThreadsAccount,
)
from app.schemas.engagement import (
    BrandProfileCreateRequest,
    CommentRuleCreateRequest,
    CommentRuleUpdateRequest,
)
from app.services.exceptions import PermanentPublishError, TransientPublishError
from app.services.hash_utils import sha256_hex
from app.services.publisher_service import (
    send_instagram_private_reply,
    send_instagram_public_reply,
)
from app.services.content_provider import generate_comment_reply
from app.services.retry_policy import next_retry_at

PRIVATE_REPLY_WINDOW_DAYS = 7


def verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    settings = get_settings()
    secret = settings.instagram_app_secret.strip() or settings.meta_app_secret.strip()
    if not secret:
        return True
    if not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    received = signature_header.split("sha256=", 1)[1].strip()
    return hmac.compare_digest(expected, received)


def create_brand_profile(db: Session, payload: BrandProfileCreateRequest) -> BrandProfile:
    existing = db.execute(select(BrandProfile).where(BrandProfile.name == payload.name.strip())).scalars().first()
    if existing:
        raise ValueError("이미 존재하는 brand profile name 입니다.")

    profile = BrandProfile(
        name=payload.name.strip(),
        vertical_type=payload.vertical_type,
        comment_style_prompt=payload.comment_style_prompt.strip(),
        active=True,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def get_or_create_profile_by_vertical(db: Session, vertical: BrandVertical) -> BrandProfile:
    existing = (
        db.execute(
            select(BrandProfile)
            .where(
                BrandProfile.vertical_type == vertical,
                BrandProfile.active.is_(True),
            )
            .order_by(BrandProfile.created_at.asc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if existing:
        return existing

    profile = BrandProfile(
        name=f"default-{vertical.value.lower()}",
        vertical_type=vertical,
        comment_style_prompt="",
        active=True,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def list_brand_profiles(db: Session) -> list[BrandProfile]:
    return db.execute(select(BrandProfile).order_by(BrandProfile.created_at.asc())).scalars().all()


def assign_instagram_brand_profile(
    db: Session,
    instagram_account_id: UUID,
    brand_profile_id: UUID,
) -> InstagramAccount:
    account = db.get(InstagramAccount, instagram_account_id)
    if not account:
        raise ValueError(f"instagram_account_id={instagram_account_id} not found")
    profile = db.get(BrandProfile, brand_profile_id)
    if not profile:
        raise ValueError(f"brand_profile_id={brand_profile_id} not found")

    account.brand_profile_id = profile.id
    db.commit()
    db.refresh(account)
    return account


def set_instagram_brand_profile(
    db: Session,
    instagram_account_id: UUID,
    brand_profile_id: UUID | None,
) -> InstagramAccount:
    account = db.get(InstagramAccount, instagram_account_id)
    if not account:
        raise ValueError(f"instagram_account_id={instagram_account_id} not found")
    if brand_profile_id is not None:
        profile = db.get(BrandProfile, brand_profile_id)
        if not profile:
            raise ValueError(f"brand_profile_id={brand_profile_id} not found")
        account.brand_profile_id = profile.id
    else:
        account.brand_profile_id = None
    db.commit()
    db.refresh(account)
    return account


def set_threads_brand_profile(
    db: Session,
    threads_account_id: UUID,
    brand_profile_id: UUID | None,
) -> ThreadsAccount:
    account = db.get(ThreadsAccount, threads_account_id)
    if not account:
        raise ValueError(f"threads_account_id={threads_account_id} not found")
    if brand_profile_id is not None:
        profile = db.get(BrandProfile, brand_profile_id)
        if not profile:
            raise ValueError(f"brand_profile_id={brand_profile_id} not found")
        account.brand_profile_id = profile.id
    else:
        account.brand_profile_id = None
    db.commit()
    db.refresh(account)
    return account


def create_comment_rule(db: Session, payload: CommentRuleCreateRequest) -> CommentRule:
    account = db.get(InstagramAccount, payload.instagram_account_id)
    if not account:
        raise ValueError(f"instagram_account_id={payload.instagram_account_id} not found")
    if payload.brand_profile_id:
        profile = db.get(BrandProfile, payload.brand_profile_id)
        if not profile:
            raise ValueError(f"brand_profile_id={payload.brand_profile_id} not found")

    if payload.action_type == CommentActionType.PRIVATE_REPLY:
        raise ValueError("DM 자동응답 기능은 비활성화되어 있습니다. 댓글 답글만 사용할 수 있습니다.")

    rule = CommentRule(
        instagram_account_id=payload.instagram_account_id,
        brand_profile_id=payload.brand_profile_id,
        name=payload.name.strip(),
        trigger_type=payload.trigger_type,
        trigger_value=payload.trigger_value.strip(),
        action_type=payload.action_type,
        ai_style_prompt=payload.ai_style_prompt.strip(),
        message_template=payload.message_template.strip(),
        priority=payload.priority,
        cooldown_minutes=payload.cooldown_minutes,
        active=payload.active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_comment_rule(db: Session, rule_id: UUID, payload: CommentRuleUpdateRequest) -> CommentRule:
    rule = db.get(CommentRule, rule_id)
    if not rule:
        raise ValueError(f"comment_rule_id={rule_id} not found")

    if payload.brand_profile_id:
        profile = db.get(BrandProfile, payload.brand_profile_id)
        if not profile:
            raise ValueError(f"brand_profile_id={payload.brand_profile_id} not found")

    if payload.action_type == CommentActionType.PRIVATE_REPLY:
        raise ValueError("DM 자동응답 기능은 비활성화되어 있습니다. 댓글 답글만 사용할 수 있습니다.")

    rule.name = payload.name.strip()
    rule.trigger_type = payload.trigger_type
    rule.trigger_value = payload.trigger_value.strip()
    rule.action_type = payload.action_type
    rule.ai_style_prompt = payload.ai_style_prompt.strip()
    rule.message_template = payload.message_template.strip()
    rule.priority = payload.priority
    rule.cooldown_minutes = payload.cooldown_minutes
    rule.active = payload.active
    rule.brand_profile_id = payload.brand_profile_id
    db.commit()
    db.refresh(rule)
    return rule


def set_comment_rule_active(db: Session, rule_id: UUID, active: bool) -> CommentRule:
    rule = db.get(CommentRule, rule_id)
    if not rule:
        raise ValueError(f"comment_rule_id={rule_id} not found")
    rule.active = active
    db.commit()
    db.refresh(rule)
    return rule


def delete_comment_rule(db: Session, rule_id: UUID) -> None:
    rule = db.get(CommentRule, rule_id)
    if not rule:
        raise ValueError(f"comment_rule_id={rule_id} not found")
    db.execute(update(ReplyJob).where(ReplyJob.rule_id == rule.id).values(rule_id=None))
    db.delete(rule)
    db.commit()


def list_comment_rules(db: Session, instagram_account_id: UUID | None = None) -> list[CommentRule]:
    stmt = select(CommentRule).order_by(CommentRule.priority.desc(), CommentRule.created_at.asc())
    if instagram_account_id:
        stmt = stmt.where(CommentRule.instagram_account_id == instagram_account_id)
    return db.execute(stmt).scalars().all()


def _parse_comment_created_at(value: dict[str, Any]) -> datetime | None:
    raw = value.get("created_time")
    if raw is None:
        return None
    try:
        ts = int(raw)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _event_hash(entry_id: str, field: str, value: dict[str, Any]) -> str:
    canonical = {
        "entry_id": entry_id,
        "field": field,
        "id": value.get("id"),
        "text": value.get("text"),
        "created_time": value.get("created_time"),
        "from_id": (value.get("from") or {}).get("id"),
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return sha256_hex(raw)


def _find_instagram_account_by_external_id(db: Session, external_id: str) -> InstagramAccount | None:
    if not external_id:
        return None
    return (
        db.execute(select(InstagramAccount).where(InstagramAccount.ig_user_id == external_id))
        .scalars()
        .first()
    )


def ingest_instagram_comment_events(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("entry", []) if isinstance(payload.get("entry"), list) else []
    created = 0
    skipped_unknown_account = 0
    skipped_duplicate = 0

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "")
        account = _find_instagram_account_by_external_id(db, entry_id)
        if not account:
            skipped_unknown_account += 1
            continue

        changes = entry.get("changes", []) if isinstance(entry.get("changes"), list) else []
        for change in changes:
            if not isinstance(change, dict):
                continue
            field = str(change.get("field") or "")
            if field not in {"comments", "live_comments"}:
                continue
            value = change.get("value") if isinstance(change.get("value"), dict) else {}
            external_comment_id = str(value.get("id") or "")
            if not external_comment_id:
                continue

            ev_hash = _event_hash(entry_id, field, value)
            exists = (
                db.execute(select(CommentEvent).where(CommentEvent.event_hash == ev_hash))
                .scalars()
                .first()
            )
            if exists:
                skipped_duplicate += 1
                continue

            from_obj = value.get("from") if isinstance(value.get("from"), dict) else {}
            db.add(
                CommentEvent(
                    instagram_account_id=account.id,
                    provider="META",
                    field=field,
                    external_entry_id=entry_id or None,
                    external_comment_id=external_comment_id,
                    external_media_id=str((value.get("media") or {}).get("id") or "") or None,
                    external_from_id=str(from_obj.get("id") or "") or None,
                    external_from_username=str(from_obj.get("username") or "") or None,
                    comment_text=str(value.get("text") or ""),
                    comment_created_at=_parse_comment_created_at(value),
                    status=CommentEventStatus.PENDING,
                    status_reason=None,
                    event_hash=ev_hash,
                    raw_payload={"entry": entry, "change": change},
                )
            )
            created += 1

    db.commit()
    return {
        "created_events": created,
        "skipped_unknown_account": skipped_unknown_account,
        "skipped_duplicate": skipped_duplicate,
    }


def _is_rule_match(rule: CommentRule, text: str) -> bool:
    target = text.strip()
    if not target:
        return False
    if rule.trigger_type == CommentTriggerType.KEYWORD:
        return rule.trigger_value.strip().lower() in target.lower()
    try:
        return re.search(rule.trigger_value, target, flags=re.IGNORECASE) is not None
    except re.error:
        return False


def _resolve_style_prompt(db: Session, rule: CommentRule, event: CommentEvent) -> str:
    if rule.ai_style_prompt:
        return rule.ai_style_prompt

    if rule.brand_profile_id:
        profile = db.get(BrandProfile, rule.brand_profile_id)
        if profile and profile.comment_style_prompt:
            return profile.comment_style_prompt

    account = db.get(InstagramAccount, event.instagram_account_id)
    if account and account.brand_profile_id:
        profile = db.get(BrandProfile, account.brand_profile_id)
        if profile and profile.comment_style_prompt:
            return profile.comment_style_prompt
    return ""


def _render_reply_text(db: Session, rule: CommentRule, event: CommentEvent) -> str:
    settings = get_settings()
    text = rule.message_template
    keyword_for_prompt = "전체댓글" if rule.trigger_value.strip() == ".*" else rule.trigger_value
    text = text.replace("{{comment_text}}", event.comment_text or "")
    text = text.replace("{{keyword}}", keyword_for_prompt)

    if "{{AI_REPLY}}" in text:
        style_prompt = _resolve_style_prompt(db, rule, event)
        ai_reply = generate_comment_reply(
            comment_text=event.comment_text or "",
            keyword=keyword_for_prompt,
            style_prompt=style_prompt,
            fallback_reply="댓글 감사합니다. 요청하신 정보는 고정 댓글/본문을 확인해주세요.",
            max_chars=settings.engagement_ai_reply_max_chars,
        )
        if settings.engagement_ai_reply_enabled:
            text = text.replace("{{AI_REPLY}}", ai_reply)
        else:
            text = text.replace("{{AI_REPLY}}", "댓글 감사합니다. 요청하신 정보는 고정 댓글/본문을 확인해주세요.")
    return text.strip()


def _private_reply_window_ok(event: CommentEvent) -> bool:
    base = event.comment_created_at or event.created_at
    if not base:
        return True
    return base >= datetime.now(timezone.utc) - timedelta(days=PRIVATE_REPLY_WINDOW_DAYS)


def _already_has_private_reply(db: Session, event: CommentEvent) -> bool:
    stmt = (
        select(ReplyJob)
        .join(CommentEvent, CommentEvent.id == ReplyJob.comment_event_id)
        .where(
            ReplyJob.instagram_account_id == event.instagram_account_id,
            ReplyJob.action_type == CommentActionType.PRIVATE_REPLY,
            CommentEvent.external_comment_id == event.external_comment_id,
            ReplyJob.status.in_([ReplyJobStatus.PENDING, ReplyJobStatus.RUNNING, ReplyJobStatus.SENT]),
        )
        .limit(1)
    )
    return db.execute(stmt).scalars().first() is not None


def _consume_quota(
    db: Session,
    instagram_account_id: UUID,
    action_type: CommentActionType,
) -> tuple[bool, str | None]:
    settings = get_settings()
    now = datetime.now(timezone.utc)

    if action_type == CommentActionType.PRIVATE_REPLY:
        hourly_limit = max(1, settings.private_reply_hourly_limit)
        daily_limit = max(1, settings.private_reply_daily_limit)
    else:
        hourly_limit = max(1, settings.public_reply_hourly_limit)
        daily_limit = max(1, settings.public_reply_daily_limit)

    checks = [
        (QuotaBucketType.HOURLY, now.strftime("%Y%m%d%H"), hourly_limit, "HOURLY_LIMIT"),
        (QuotaBucketType.DAILY, now.strftime("%Y%m%d"), daily_limit, "DAILY_LIMIT"),
    ]

    touched: list[QuotaBucket] = []
    for bucket_type, bucket_key, limit, reason in checks:
        bucket = (
            db.execute(
                select(QuotaBucket)
                .where(
                    QuotaBucket.instagram_account_id == instagram_account_id,
                    QuotaBucket.action_type == action_type,
                    QuotaBucket.bucket_type == bucket_type,
                    QuotaBucket.bucket_key == bucket_key,
                )
                .with_for_update()
            )
            .scalars()
            .first()
        )
        if not bucket:
            bucket = QuotaBucket(
                instagram_account_id=instagram_account_id,
                action_type=action_type,
                bucket_type=bucket_type,
                bucket_key=bucket_key,
                used_count=0,
            )
            db.add(bucket)
            db.flush()
        if bucket.used_count >= limit:
            return False, reason
        touched.append(bucket)

    for bucket in touched:
        bucket.used_count += 1
    return True, None


def _pick_matching_rule(db: Session, event: CommentEvent) -> CommentRule | None:
    rules = (
        db.execute(
            select(CommentRule)
            .where(
                CommentRule.instagram_account_id == event.instagram_account_id,
                CommentRule.active.is_(True),
            )
            .order_by(CommentRule.priority.desc(), CommentRule.created_at.asc())
        )
        .scalars()
        .all()
    )
    for rule in rules:
        if _is_rule_match(rule, event.comment_text):
            return rule
    return None


def create_reply_jobs_for_pending_events(db: Session, limit: int = 100) -> dict[str, Any]:
    settings = get_settings()
    if not settings.engagement_enabled:
        return {"status": "SKIPPED_DISABLED", "created_jobs": 0, "skipped_events": 0}

    events = (
        db.execute(
            select(CommentEvent)
            .where(CommentEvent.status == CommentEventStatus.PENDING)
            .order_by(CommentEvent.created_at.asc())
            .limit(max(1, min(limit, 500)))
        )
        .scalars()
        .all()
    )

    created_jobs = 0
    skipped_events = 0

    for event in events:
        account = db.get(InstagramAccount, event.instagram_account_id)
        if not account:
            event.status = CommentEventStatus.SKIPPED
            event.status_reason = "ACCOUNT_NOT_FOUND"
            skipped_events += 1
            continue

        if event.external_from_id and event.external_from_id == account.ig_user_id:
            event.status = CommentEventStatus.SKIPPED
            event.status_reason = "SELF_COMMENT"
            skipped_events += 1
            continue

        rule = _pick_matching_rule(db, event)
        if not rule:
            event.status = CommentEventStatus.SKIPPED
            event.status_reason = "NO_RULE_MATCH"
            skipped_events += 1
            continue

        if rule.action_type == CommentActionType.PRIVATE_REPLY:
            event.status = CommentEventStatus.SKIPPED
            event.status_reason = "DM_DISABLED"
            skipped_events += 1
            continue

        idem = sha256_hex(
            f"{event.instagram_account_id}|{event.external_comment_id}|{rule.action_type.value}"
        )
        exists_job = (
            db.execute(select(ReplyJob).where(ReplyJob.idempotency_key == idem))
            .scalars()
            .first()
        )
        if exists_job:
            event.status = CommentEventStatus.PROCESSED
            event.status_reason = "JOB_DUPLICATE"
            continue

        ok, reason = _consume_quota(db, event.instagram_account_id, rule.action_type)
        if not ok:
            event.status = CommentEventStatus.SKIPPED
            event.status_reason = reason
            skipped_events += 1
            continue

        reply_text = _render_reply_text(db, rule, event)
        db.add(
            ReplyJob(
                comment_event_id=event.id,
                instagram_account_id=event.instagram_account_id,
                rule_id=rule.id,
                action_type=rule.action_type,
                reply_text=reply_text,
                status=ReplyJobStatus.PENDING,
                attempts=0,
                max_attempts=3,
                idempotency_key=idem,
            )
        )
        event.status = CommentEventStatus.PROCESSED
        event.status_reason = "JOB_CREATED"
        created_jobs += 1

    db.commit()
    return {"status": "SUCCESS", "pending_events": len(events), "created_jobs": created_jobs, "skipped_events": skipped_events}


def _extract_error_code(exc: Exception) -> str:
    if isinstance(exc, (TransientPublishError, PermanentPublishError)):
        return exc.code
    return "SEND_UNKNOWN"


def process_pending_reply_jobs(db: Session, limit: int = 50) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    jobs = (
        db.execute(
            select(ReplyJob)
            .where(
                and_(
                    ReplyJob.status == ReplyJobStatus.PENDING,
                    or_(ReplyJob.next_retry_at.is_(None), ReplyJob.next_retry_at <= now),
                )
            )
            .order_by(ReplyJob.created_at.asc())
            .limit(max(1, min(limit, 200)))
        )
        .scalars()
        .all()
    )

    sent = 0
    failed = 0
    skipped = 0
    for job in jobs:
        event = db.get(CommentEvent, job.comment_event_id)
        account = db.get(InstagramAccount, job.instagram_account_id)
        if not event or not account:
            job.status = ReplyJobStatus.SKIPPED
            job.skip_reason = "MISSING_REF"
            job.last_error_code = "MISSING_REF"
            job.last_error_message = "comment_event 또는 instagram_account 참조가 없습니다."
            skipped += 1
            continue

        job.status = ReplyJobStatus.RUNNING
        job.attempts += 1
        db.flush()

        try:
            if job.action_type == CommentActionType.PRIVATE_REPLY:
                send_instagram_private_reply(
                    account=account,
                    comment_id=event.external_comment_id,
                    message=job.reply_text,
                )
            else:
                send_instagram_public_reply(
                    account=account,
                    comment_id=event.external_comment_id,
                    message=job.reply_text,
                )
            job.status = ReplyJobStatus.SENT
            job.sent_at = datetime.now(timezone.utc)
            job.next_retry_at = None
            job.last_error_code = None
            job.last_error_message = None
            job.skip_reason = None
            sent += 1
        except Exception as exc:  # noqa: BLE001
            job.last_error_code = _extract_error_code(exc)
            job.last_error_message = str(exc)[:2000]
            if job.attempts >= job.max_attempts:
                job.status = ReplyJobStatus.FAILED
                job.next_retry_at = None
                job.skip_reason = "MAX_ATTEMPTS"
                failed += 1
            else:
                job.status = ReplyJobStatus.PENDING
                job.next_retry_at = next_retry_at(job.attempts)
                job.skip_reason = "RETRY_SCHEDULED"
                skipped += 1

    db.commit()
    return {"status": "SUCCESS", "total": len(jobs), "sent": sent, "failed": failed, "retrying": skipped}


def retry_reply_job(db: Session, reply_job_id: UUID) -> ReplyJob:
    job = db.get(ReplyJob, reply_job_id)
    if not job:
        raise ValueError(f"reply_job_id={reply_job_id} not found")

    if job.status == ReplyJobStatus.RUNNING:
        raise ValueError("RUNNING 상태의 reply job은 수동 재처리할 수 없습니다.")
    if job.status == ReplyJobStatus.SENT:
        raise ValueError("SENT 상태의 reply job은 수동 재처리할 수 없습니다.")

    job.status = ReplyJobStatus.PENDING
    job.skip_reason = None
    job.next_retry_at = datetime.now(timezone.utc)
    job.last_error_code = None
    job.last_error_message = None
    job.attempts = 0
    db.commit()
    db.refresh(job)
    return job


def list_comment_events(db: Session, limit: int = 100) -> list[CommentEvent]:
    return (
        db.execute(select(CommentEvent).order_by(CommentEvent.created_at.desc()).limit(max(1, min(limit, 500))))
        .scalars()
        .all()
    )


def list_reply_jobs(db: Session, limit: int = 100) -> list[ReplyJob]:
    return (
        db.execute(select(ReplyJob).order_by(ReplyJob.created_at.desc()).limit(max(1, min(limit, 500))))
        .scalars()
        .all()
    )
