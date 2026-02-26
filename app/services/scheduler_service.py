from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
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


def schedule_today_jobs(
    db: Session,
    biz_date: date,
    *,
    threads_account_id: UUID | None = None,
    instagram_account_id: UUID | None = None,
    content_unit_ids: list[UUID] | None = None,
) -> dict[str, Any]:
    conditions = [
        ContentUnit.biz_date == biz_date,
        ContentUnit.generation_status == ContentStatus.READY,
        ContentUnit.guardrail_passed.is_(True),
        or_(
            ContentUnit.threads_review_status == "APPROVED",
            ContentUnit.instagram_review_status == "APPROVED",
        ),
    ]
    if threads_account_id is not None:
        conditions.append(ContentUnit.threads_account_id == threads_account_id)
    if instagram_account_id is not None:
        conditions.append(ContentUnit.instagram_account_id == instagram_account_id)
    if content_unit_ids:
        conditions.append(ContentUnit.id.in_(content_unit_ids))

    units = (
        db.execute(
            select(ContentUnit).where(and_(*conditions)).order_by(ContentUnit.slot_no.asc())
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

    threads_accounts: list[ThreadsAccount] = []
    selected_threads: ThreadsAccount | None = None
    if threads_account_id is not None:
        selected_threads = db.get(ThreadsAccount, threads_account_id)
        if not selected_threads or selected_threads.status != AccountStatus.ACTIVE:
            raise ValueError("선택한 Threads 계정이 활성 상태가 아닙니다.")

    selected_instagram: InstagramAccount | None = None
    if instagram_account_id is not None:
        selected_instagram = db.get(InstagramAccount, instagram_account_id)
        if not selected_instagram or selected_instagram.status != AccountStatus.ACTIVE:
            raise ValueError("선택한 Instagram 계정이 활성 상태가 아닙니다.")

    slot_times = _compute_slot_datetimes(biz_date, len(units))

    created_jobs = 0
    skipped_jobs = 0
    scheduled_units = 0
    rr_idx = 0

    for idx, unit in enumerate(units):
        if unit.scheduled_at is None:
            unit.scheduled_at = slot_times[idx]

        plan: list[tuple[ChannelType, JobType, UUID]] = []

        if unit.threads_review_status == "APPROVED":
            if unit.threads_account_id is not None:
                threads_account = db.get(ThreadsAccount, unit.threads_account_id)
                if not threads_account or threads_account.status != AccountStatus.ACTIVE:
                    raise ValueError("콘텐츠 유닛에 연결된 Threads 계정이 비활성 상태입니다.")
            elif selected_threads is not None:
                threads_account = selected_threads
            else:
                if not threads_accounts:
                    threads_accounts = (
                        db.execute(
                            select(ThreadsAccount)
                            .where(ThreadsAccount.status == AccountStatus.ACTIVE)
                            .order_by(ThreadsAccount.created_at.asc())
                        )
                        .scalars()
                        .all()
                    )
                if not threads_accounts:
                    raise ValueError("활성 Threads 계정이 없습니다.")
                threads_account = threads_accounts[rr_idx % len(threads_accounts)]
                rr_idx += 1
            plan.append((ChannelType.THREADS, JobType.THREADS_ROOT, threads_account.id))

        if unit.instagram_review_status == "APPROVED":
            if unit.instagram_account_id is not None:
                unit_ig_account = db.get(InstagramAccount, unit.instagram_account_id)
                if not unit_ig_account or unit_ig_account.status != AccountStatus.ACTIVE:
                    raise ValueError("콘텐츠 유닛에 연결된 Instagram 계정이 비활성 상태입니다.")
            elif selected_instagram is not None:
                unit_ig_account = selected_instagram
            else:
                unit_ig_account = (
                    db.execute(
                        select(InstagramAccount)
                        .where(InstagramAccount.status == AccountStatus.ACTIVE)
                        .order_by(InstagramAccount.created_at.asc())
                        .limit(1)
                    )
                    .scalars()
                    .first()
                )
                if not unit_ig_account:
                    raise ValueError("활성 Instagram 계정이 없습니다.")
            plan.append((ChannelType.INSTAGRAM, JobType.INSTAGRAM_CAROUSEL, unit_ig_account.id))

        if plan:
            scheduled_units += 1

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
        "scheduled_units": scheduled_units,
        "created_jobs": created_jobs,
        "skipped_jobs": skipped_jobs,
    }
