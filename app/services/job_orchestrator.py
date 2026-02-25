from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ChannelType, ContentUnit, JobStatus, JobType, PostJob
from app.schemas.tasks import JobTaskPayload
from app.services.generation_service import generate_today_content_units
from app.services.scheduler_service import schedule_today_jobs
from app.services.task_queue import enqueue_http_task
from app.services.time_utils import kst_today
from app.services.trend_service import sync_naver_trend_keywords


def _queue_name(channel: ChannelType, job_type: JobType) -> str:
    settings = get_settings()
    if channel == ChannelType.THREADS and job_type == JobType.THREADS_ROOT:
        return settings.queue_publish_threads
    if channel == ChannelType.INSTAGRAM and job_type == JobType.INSTAGRAM_CAROUSEL:
        return settings.queue_publish_instagram
    return settings.queue_publish_threads


def enqueue_single_job(db: Session, job: PostJob) -> str:
    queue_name = _queue_name(job.channel, job.job_type)
    uri = "/tasks/publish/threads" if job.channel == ChannelType.THREADS else "/tasks/publish/instagram"
    payload = JobTaskPayload(job_id=job.id).model_dump()
    task_name = enqueue_http_task(
        queue_name=queue_name,
        relative_uri=uri,
        payload=payload,
        schedule_at=job.next_retry_at or job.scheduled_at,
    )
    job.cloud_task_name = task_name
    return task_name


def enqueue_pending_jobs_for_date(db: Session, biz_date: date) -> dict[str, Any]:
    jobs = (
        db.execute(
            select(PostJob)
            .join(ContentUnit, ContentUnit.id == PostJob.content_unit_id)
            .where(
                and_(
                    ContentUnit.biz_date == biz_date,
                    PostJob.status.in_([JobStatus.PENDING, JobStatus.RETRYING]),
                )
            )
            .order_by(PostJob.scheduled_at.asc())
        )
        .scalars()
        .all()
    )

    enqueued = 0
    skipped = 0
    for job in jobs:
        if job.cloud_task_name:
            skipped += 1
            continue
        enqueue_single_job(db, job)
        enqueued += 1

    db.commit()
    return {
        "biz_date": biz_date,
        "pending_jobs": len(jobs),
        "enqueued_jobs": enqueued,
        "skipped_jobs": skipped,
    }


def enqueue_job_by_id(db: Session, job_id: int) -> str:
    job = db.get(PostJob, job_id)
    if not job:
        raise ValueError(f"job_id={job_id} not found")
    job.cloud_task_name = None
    task_name = enqueue_single_job(db, job)
    db.commit()
    return task_name


def run_daily_bootstrap(db: Session, biz_date: date | None = None) -> dict[str, Any]:
    settings = get_settings()
    target_date = biz_date or kst_today()
    trend_result: dict[str, Any] = {"status": "SKIPPED"}
    try:
        trend_result = sync_naver_trend_keywords(db, target_date)
    except Exception as exc:  # noqa: BLE001
        trend_result = {"status": "FAILED", "reason": str(exc)}

    gen_result = generate_today_content_units(
        db,
        biz_date=target_date,
        unit_count=max(2, min(3, settings.daily_unit_count)),
    )
    schedule_result = schedule_today_jobs(db, target_date)
    queue_result = enqueue_pending_jobs_for_date(db, target_date)

    return {
        "biz_date": target_date,
        "trend": trend_result,
        "generate": gen_result,
        "schedule": schedule_result,
        "queue": queue_result,
    }
