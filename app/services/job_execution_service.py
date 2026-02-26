from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    ChannelType,
    ContentStatus,
    ContentUnit,
    InstagramAccount,
    InstagramPost,
    JobStatus,
    PostJob,
    ThreadsAccount,
    ThreadsPost,
)
from app.schemas.tasks import InsightsTaskPayload
from app.services.exceptions import PermanentPublishError, TransientPublishError
from app.services.publisher_service import (
    collect_threads_insights,
    publish_instagram_carousel,
    publish_threads,
    try_send_threads_comment_reply,
)
from app.services.render_service import ensure_rendered_assets
from app.services.retry_policy import next_retry_at
from app.services.task_queue import enqueue_http_task


def _find_job_for_update(db: Session, job_id: int) -> PostJob | None:
    return (
        db.execute(select(PostJob).where(PostJob.id == job_id).with_for_update())
        .scalars()
        .first()
    )


def _strip_exact_line(text: str, line: str) -> str:
    clean_line = line.strip()
    if not clean_line:
        return text.strip()
    kept: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped == clean_line:
            continue
        kept.append(stripped)
    return "\n".join(kept).strip()


def _ensure_first_line(text: str, line: str) -> str:
    clean_line = line.strip()
    if not clean_line:
        return text.strip()
    lines = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped == clean_line:
            continue
        lines.append(stripped)
    tail = "\n".join(lines).strip()
    return f"{clean_line}\n{tail}".strip() if tail else clean_line


def _is_coupang_content(unit: ContentUnit) -> bool:
    source = (unit.original_coupang_url or "").lower()
    return "coupang" in source


def _publish_threads_job(db: Session, job: PostJob) -> dict[str, Any]:
    account = db.get(ThreadsAccount, job.account_ref)
    if not account:
        raise PermanentPublishError("threads account not found", code="THREADS_ACCOUNT_NOT_FOUND")

    unit = db.get(ContentUnit, job.content_unit_id)
    if not unit:
        raise PermanentPublishError("content_unit not found", code="CONTENT_UNIT_NOT_FOUND")

    existing = (
        db.execute(select(ThreadsPost).where(ThreadsPost.content_unit_id == unit.id))
        .scalars()
        .first()
    )
    settings = get_settings()
    disclosure_line = settings.disclosure_line.strip() if _is_coupang_content(unit) else ""
    root_text = unit.threads_body.strip()
    reply_text = unit.threads_first_reply.strip()
    if disclosure_line:
        root_text = _strip_exact_line(root_text, disclosure_line)
        reply_text = _ensure_first_line(reply_text, disclosure_line)
    now_utc = datetime.now(timezone.utc)

    if existing and existing.root_post_id and existing.first_reply_id:
        return {
            "root_post_id": existing.root_post_id,
            "reply_post_id": existing.first_reply_id,
            "permalink": existing.root_permalink,
            "idempotent": True,
        }

    if existing and existing.root_post_id and not existing.first_reply_id:
        if not reply_text:
            return {
                "root_post_id": existing.root_post_id,
                "reply_post_id": None,
                "permalink": existing.root_permalink,
                "idempotent": True,
            }
        reply_post_id = try_send_threads_comment_reply(
            db=db,
            account=account,
            reply_to_id=existing.root_post_id,
            message=reply_text,
        )
        existing.root_text = root_text
        existing.reply_text = reply_text
        if reply_post_id:
            existing.first_reply_id = reply_post_id
            existing.reply_published_at = now_utc
            return {
                "root_post_id": existing.root_post_id,
                "reply_post_id": reply_post_id,
                "permalink": existing.root_permalink,
            }
        raise TransientPublishError("threads first reply pending", code="THREADS_REPLY_PENDING")

    should_enqueue_insights = not (existing and existing.root_post_id)
    result = publish_threads(
        db=db,
        account=account,
        root_text=root_text,
        reply_text=reply_text,
    )

    if existing:
        existing.root_post_id = result.root_post_id
        existing.first_reply_id = result.reply_post_id
        existing.root_text = root_text
        existing.reply_text = reply_text or None
        existing.root_permalink = result.permalink
        existing.published_at = now_utc
        existing.reply_published_at = now_utc if result.reply_post_id else None
        threads_post = existing
    else:
        threads_post = ThreadsPost(
            content_unit_id=unit.id,
            threads_account_id=account.id,
            root_post_id=result.root_post_id,
            first_reply_id=result.reply_post_id,
            root_text=root_text,
            reply_text=reply_text or None,
            root_permalink=result.permalink,
            published_at=now_utc,
            reply_published_at=now_utc if result.reply_post_id else None,
        )
        db.add(threads_post)
        db.flush()

    if should_enqueue_insights:
        _enqueue_threads_insight_tasks(threads_post.id, result.root_post_id)

    if reply_text and not result.reply_post_id:
        raise TransientPublishError("threads first reply pending", code="THREADS_REPLY_PENDING")

    return {
        "root_post_id": result.root_post_id,
        "reply_post_id": result.reply_post_id,
        "permalink": result.permalink,
    }


def _publish_instagram_job(db: Session, job: PostJob) -> dict[str, Any]:
    account = db.get(InstagramAccount, job.account_ref)
    if not account:
        raise PermanentPublishError("instagram account not found", code="INSTAGRAM_ACCOUNT_NOT_FOUND")

    unit = db.get(ContentUnit, job.content_unit_id)
    if not unit:
        raise PermanentPublishError("content_unit not found", code="CONTENT_UNIT_NOT_FOUND")

    existing = (
        db.execute(select(InstagramPost).where(InstagramPost.content_unit_id == unit.id))
        .scalars()
        .first()
    )
    if existing and existing.carousel_media_id:
        return {
            "carousel_media_id": existing.carousel_media_id,
            "carousel_creation_id": existing.carousel_creation_id,
            "idempotent": True,
        }

    assets = ensure_rendered_assets(db, str(unit.id))

    result = publish_instagram_carousel(account=account, caption=unit.instagram_caption, assets=assets)

    if existing:
        existing.media_container_ids = {"children": result.child_container_ids}
        existing.carousel_creation_id = result.carousel_creation_id
        existing.carousel_media_id = result.carousel_media_id
        existing.caption = unit.instagram_caption
        existing.published_at = datetime.now(timezone.utc)
    else:
        db.add(
            InstagramPost(
                content_unit_id=unit.id,
                instagram_account_id=account.id,
                media_container_ids={"children": result.child_container_ids},
                carousel_creation_id=result.carousel_creation_id,
                carousel_media_id=result.carousel_media_id,
                caption=unit.instagram_caption,
                published_at=datetime.now(timezone.utc),
            )
        )

    return {
        "carousel_media_id": result.carousel_media_id,
        "carousel_creation_id": result.carousel_creation_id,
    }


def _enqueue_threads_insight_tasks(threads_post_id, media_id: str) -> None:
    settings = get_settings()

    if not settings.cloud_tasks_enabled:
        return

    base_time = datetime.now(timezone.utc)
    for delay in (timedelta(hours=1), timedelta(hours=24)):
        payload = InsightsTaskPayload(
            threads_post_id=str(threads_post_id),
            media_id=media_id,
            capture_at=base_time + delay,
        )
        enqueue_http_task(
            queue_name=settings.queue_insights,
            relative_uri="/tasks/insights/threads",
            payload=payload.model_dump(mode="json"),
            schedule_at=base_time + delay,
        )


def _mark_content_publication_status(db: Session, content_unit_id) -> None:
    unit = db.get(ContentUnit, content_unit_id)
    if not unit:
        return

    jobs = (
        db.execute(select(PostJob).where(PostJob.content_unit_id == content_unit_id))
        .scalars()
        .all()
    )
    success_channels = {job.channel for job in jobs if job.status == JobStatus.SUCCESS}

    if success_channels == {ChannelType.THREADS, ChannelType.INSTAGRAM}:
        unit.generation_status = ContentStatus.PUBLISHED_ALL
    elif success_channels:
        unit.generation_status = ContentStatus.PUBLISHED_PARTIAL


def _queue_retry_for_job(job: PostJob) -> str:
    queue_name = (
        get_settings().queue_publish_threads
        if job.channel == ChannelType.THREADS
        else get_settings().queue_publish_instagram
    )
    uri = "/tasks/publish/threads" if job.channel == ChannelType.THREADS else "/tasks/publish/instagram"
    return enqueue_http_task(
        queue_name=queue_name,
        relative_uri=uri,
        payload={"job_id": job.id},
        schedule_at=job.next_retry_at,
    )


def execute_publish_job(db: Session, job_id: int, expected_channel: ChannelType) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    job = _find_job_for_update(db, job_id)
    if not job:
        raise ValueError(f"job_id={job_id} not found")

    if job.channel != expected_channel:
        raise ValueError(f"job channel mismatch: expected={expected_channel.value}, got={job.channel.value}")

    if job.status == JobStatus.SUCCESS:
        return {"job_id": job.id, "status": "NOOP_ALREADY_SUCCESS"}

    if job.status == JobStatus.RUNNING:
        return {"job_id": job.id, "status": "NOOP_ALREADY_RUNNING"}

    if job.next_retry_at and job.next_retry_at > now:
        return {"job_id": job.id, "status": "NOOP_NOT_DUE_YET"}

    if job.scheduled_at > now and job.attempts == 0:
        return {"job_id": job.id, "status": "NOOP_SCHEDULED_FUTURE"}

    job.status = JobStatus.RUNNING
    job.started_at = now
    job.attempts = int(job.attempts) + 1
    job.last_error_code = None
    job.last_error_message = None
    db.commit()
    db.refresh(job)

    try:
        if expected_channel == ChannelType.THREADS:
            result = _publish_threads_job(db, job)
        else:
            result = _publish_instagram_job(db, job)

    except TransientPublishError as exc:
        target = _find_job_for_update(db, job_id)
        if not target:
            raise
        if target.attempts >= target.max_attempts:
            target.status = JobStatus.FAILED
            target.last_error_code = exc.code
            target.last_error_message = str(exc)[:2000]
            target.finished_at = datetime.now(timezone.utc)
            db.commit()
            return {
                "job_id": target.id,
                "status": target.status.value,
                "error_code": target.last_error_code,
            }

        target.status = JobStatus.RETRYING
        target.next_retry_at = next_retry_at(target.attempts)
        target.last_error_code = exc.code
        target.last_error_message = str(exc)[:2000]
        target.cloud_task_name = None
        db.commit()
        db.refresh(target)

        retry_task_name = _queue_retry_for_job(target)
        final_target = _find_job_for_update(db, job_id)
        if final_target:
            final_target.cloud_task_name = retry_task_name
            db.commit()

        return {
            "job_id": job_id,
            "status": "RETRYING",
            "next_retry_at": target.next_retry_at.isoformat() if target.next_retry_at else None,
            "error_code": exc.code,
        }

    except PermanentPublishError as exc:
        target = _find_job_for_update(db, job_id)
        if target:
            target.status = JobStatus.FAILED
            target.last_error_code = exc.code
            target.last_error_message = str(exc)[:2000]
            target.finished_at = datetime.now(timezone.utc)
            db.commit()
        return {
            "job_id": job_id,
            "status": "FAILED",
            "error_code": exc.code,
        }

    target = _find_job_for_update(db, job_id)
    if target:
        target.status = JobStatus.SUCCESS
        target.finished_at = datetime.now(timezone.utc)
        target.last_response = result
        _mark_content_publication_status(db, target.content_unit_id)
        db.commit()

    return {
        "job_id": job_id,
        "status": "SUCCESS",
        "result": result,
    }


def execute_threads_insights_task(db: Session, threads_post_id: str, media_id: str) -> dict[str, Any]:
    threads_post = db.get(ThreadsPost, threads_post_id)
    if not threads_post:
        raise ValueError(f"threads_post_id={threads_post_id} not found")

    account = db.get(ThreadsAccount, threads_post.threads_account_id)
    if not account:
        raise ValueError("threads account not found")

    insight = collect_threads_insights(db=db, account=account, media_id=media_id)

    from app.models import ThreadsInsight

    db.add(
        ThreadsInsight(
            threads_post_id=threads_post.id,
            media_id=insight.media_id,
            captured_at=insight.captured_at,
            views=insight.views,
            likes=insight.likes,
            replies=insight.replies,
            reposts=insight.reposts,
            quotes=insight.quotes,
            shares=insight.shares,
            raw_payload=insight.raw_payload,
        )
    )
    db.commit()

    return {
        "threads_post_id": threads_post_id,
        "media_id": media_id,
        "captured_at": insight.captured_at.isoformat(),
        "views": insight.views,
        "likes": insight.likes,
        "replies": insight.replies,
        "reposts": insight.reposts,
        "quotes": insight.quotes,
        "shares": insight.shares,
    }


def dispatch_due_jobs_local(db: Session, limit: int = 20) -> dict[str, Any]:
    # Local/mock mode helper: execute due jobs without Cloud Tasks.
    now = datetime.now(timezone.utc)
    due_jobs = (
        db.execute(
            select(PostJob)
            .where(
                and_(
                    PostJob.status.in_([JobStatus.PENDING, JobStatus.RETRYING]),
                    or_(
                        and_(PostJob.next_retry_at.is_(None), PostJob.scheduled_at <= now),
                        PostJob.next_retry_at <= now,
                    ),
                )
            )
            .order_by(PostJob.scheduled_at.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    results = []
    for job in due_jobs:
        results.append(execute_publish_job(db, job.id, expected_channel=job.channel))

    return {
        "dispatched": len(results),
        "results": results,
    }
