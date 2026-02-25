from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContentStatus, ContentUnit, ReviewStatus


def list_review_queue(db: Session, biz_date=None, limit: int = 100) -> list[ContentUnit]:
    stmt = select(ContentUnit).where(ContentUnit.review_status == ReviewStatus.PENDING)
    if biz_date is not None:
        stmt = stmt.where(ContentUnit.biz_date == biz_date)
    stmt = stmt.order_by(ContentUnit.biz_date.asc(), ContentUnit.slot_no.asc()).limit(limit)
    return db.execute(stmt).scalars().all()


def approve_content_unit(db: Session, content_unit_id: UUID, reviewer_id: UUID | None = None) -> ContentUnit:
    unit = db.get(ContentUnit, content_unit_id)
    if not unit:
        raise ValueError(f"content_unit_id={content_unit_id} not found")

    if unit.generation_status != ContentStatus.READY:
        raise ValueError("READY 상태 콘텐츠만 승인할 수 있습니다.")

    unit.review_status = ReviewStatus.APPROVED
    unit.reviewed_at = datetime.now(timezone.utc)
    unit.reviewed_by = reviewer_id
    db.commit()
    db.refresh(unit)
    return unit


def approve_and_prepare_publish(
    db: Session,
    content_unit_id: UUID,
    reviewer_id: UUID | None = None,
) -> dict[str, Any]:
    unit = approve_content_unit(db, content_unit_id, reviewer_id=reviewer_id)
    schedule_result: dict[str, Any] | None = None
    enqueue_result: dict[str, Any] | None = None
    warnings: list[str] = []

    try:
        from app.services.scheduler_service import schedule_today_jobs

        schedule_result = schedule_today_jobs(db, unit.biz_date)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"schedule_failed:{str(exc)}")

    if schedule_result:
        try:
            from app.services.job_orchestrator import enqueue_pending_jobs_for_date

            enqueue_result = enqueue_pending_jobs_for_date(db, unit.biz_date)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"enqueue_failed:{str(exc)}")

    return {
        "content_unit": unit,
        "schedule_result": schedule_result,
        "enqueue_result": enqueue_result,
        "warnings": warnings,
    }


def reject_content_unit(db: Session, content_unit_id: UUID, reviewer_id: UUID | None = None) -> ContentUnit:
    unit = db.get(ContentUnit, content_unit_id)
    if not unit:
        raise ValueError(f"content_unit_id={content_unit_id} not found")

    unit.review_status = ReviewStatus.REJECTED
    unit.reviewed_at = datetime.now(timezone.utc)
    unit.reviewed_by = reviewer_id
    db.commit()
    db.refresh(unit)
    return unit


def update_content_unit_copy(
    db: Session,
    content_unit_id: UUID,
    *,
    threads_body: str,
    threads_first_reply: str,
    instagram_caption: str,
) -> ContentUnit:
    unit = db.get(ContentUnit, content_unit_id)
    if not unit:
        raise ValueError(f"content_unit_id={content_unit_id} not found")

    unit.threads_body = threads_body.strip()
    unit.threads_first_reply = threads_first_reply.strip()
    unit.instagram_caption = instagram_caption.strip()

    # 수정되면 다시 검수 대기로 돌림
    unit.review_status = ReviewStatus.PENDING
    unit.reviewed_at = None
    unit.reviewed_by = None

    db.commit()
    db.refresh(unit)
    return unit


def review_queue_summary(queue: list[ContentUnit]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(item.id),
            "biz_date": item.biz_date.isoformat(),
            "slot_no": item.slot_no,
            "topic": item.topic,
            "category": item.category,
            "review_status": item.review_status.value,
            "threads_body": item.threads_body,
            "threads_first_reply": item.threads_first_reply,
            "instagram_caption": item.instagram_caption,
        }
        for item in queue
    ]
