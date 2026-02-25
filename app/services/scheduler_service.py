from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AccountStatus,
    ChannelType,
    ContentStatus,
    ContentUnit,
    InstagramAccount,
    JobStatus,
    JobType,
    PostJob,
    ReviewStatus,
    ThreadsAccount,
)
from app.services.hash_utils import sha256_hex
from app.services.time_utils import posting_window


def _deterministic_jitter_minutes(seed: str, max_jitter: int = 25) -> int:
    value = int(sha256_hex(seed)[:8], 16)
    span = (max_jitter * 2) + 1
    return (value % span) - max_jitter


def _compute_slot_datetimes(biz_date: date, count: int) -> list[datetime]:
    start_utc, end_utc = posting_window(biz_date)
    if count <= 0:
        return []

    interval_seconds = (end_utc - start_utc).total_seconds() / (count + 1)
    times: list[datetime] = []
    for i in range(1, count + 1):
        base = start_utc + timedelta(seconds=interval_seconds * i)
        jitter = _deterministic_jitter_minutes(f"{biz_date.isoformat()}-{i}")
        times.append(base + timedelta(minutes=jitter))
    return times


def _idempotency_key(
    channel: ChannelType,
    job_type: JobType,
    account_ref: str,
    content_unit_id: str,
    scheduled_at: datetime,
) -> str:
    raw = f"{channel.value}|{job_type.value}|{account_ref}|{content_unit_id}|{scheduled_at.isoformat()}"
    return sha256_hex(raw)


def schedule_today_jobs(db: Session, biz_date: date) -> dict[str, Any]:
    units = (
        db.execute(
            select(ContentUnit)
            .where(
                ContentUnit.biz_date == biz_date,
                ContentUnit.generation_status == ContentStatus.READY,
                ContentUnit.guardrail_passed.is_(True),
                ContentUnit.review_status == ReviewStatus.APPROVED,
            )
            .order_by(ContentUnit.slot_no.asc())
        )
        .scalars()
        .all()
    )

    if not units:
        return {
            "biz_date": biz_date,
            "total_units": 0,
            "scheduled_units": 0,
            "created_jobs": 0,
            "skipped_jobs": 0,
        }

    threads_accounts = (
        db.execute(
            select(ThreadsAccount)
            .where(ThreadsAccount.status == AccountStatus.ACTIVE)
            .order_by(ThreadsAccount.created_at.asc())
        )
        .scalars()
        .all()
    )
    instagram_account = (
        db.execute(
            select(InstagramAccount)
            .where(InstagramAccount.status == AccountStatus.ACTIVE)
            .order_by(InstagramAccount.created_at.asc())
            .limit(1)
        )
        .scalars()
        .first()
    )

    if not threads_accounts:
        raise ValueError("활성 Threads 계정이 없습니다.")
    if not instagram_account:
        raise ValueError("활성 Instagram 계정이 없습니다.")

    slot_times = _compute_slot_datetimes(biz_date, len(units))

    created_jobs = 0
    skipped_jobs = 0

    for idx, unit in enumerate(units):
        if unit.scheduled_at is None:
            unit.scheduled_at = slot_times[idx]

        threads_account = threads_accounts[idx % len(threads_accounts)]
        plan = [
            (ChannelType.THREADS, JobType.THREADS_ROOT, threads_account.id),
            (ChannelType.INSTAGRAM, JobType.INSTAGRAM_CAROUSEL, instagram_account.id),
        ]

        for channel, job_type, account_id in plan:
            existing_job = (
                db.execute(
                    select(PostJob).where(
                        PostJob.content_unit_id == unit.id,
                        PostJob.channel == channel,
                        PostJob.job_type == job_type,
                    )
                )
                .scalars()
                .first()
            )
            if existing_job:
                skipped_jobs += 1
                continue

            idem = _idempotency_key(
                channel=channel,
                job_type=job_type,
                account_ref=str(account_id),
                content_unit_id=str(unit.id),
                scheduled_at=unit.scheduled_at,
            )
            job = PostJob(
                content_unit_id=unit.id,
                channel=channel,
                job_type=job_type,
                account_ref=account_id,
                scheduled_at=unit.scheduled_at,
                status=JobStatus.PENDING,
                attempts=0,
                max_attempts=8,
                idempotency_key=idem,
            )
            db.add(job)
            created_jobs += 1

    db.commit()
    return {
        "biz_date": biz_date,
        "total_units": len(units),
        "scheduled_units": len(units),
        "created_jobs": created_jobs,
        "skipped_jobs": skipped_jobs,
    }
