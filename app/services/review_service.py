from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from app.models import (
    ChannelType,
    ContentStatus,
    ContentUnit,
    RenderedAsset,
    ReviewStatus,
)

REVIEW_PENDING = ReviewStatus.PENDING.value
REVIEW_APPROVED = ReviewStatus.APPROVED.value
REVIEW_REJECTED = ReviewStatus.REJECTED.value


def _sync_overall_review_status(unit: ContentUnit) -> None:
    pair = {unit.threads_review_status, unit.instagram_review_status}
    if pair == {REVIEW_APPROVED}:
        unit.review_status = ReviewStatus.APPROVED
        return
    if pair == {REVIEW_REJECTED}:
        unit.review_status = ReviewStatus.REJECTED
        return
    unit.review_status = ReviewStatus.PENDING


def list_review_queue(
    db: Session,
    biz_date=None,
    limit: int = 100,
    threads_account_id: UUID | None = None,
    instagram_account_id: UUID | None = None,
) -> list[ContentUnit]:
    stmt = select(ContentUnit).where(
        or_(
            ContentUnit.threads_review_status == REVIEW_PENDING,
            ContentUnit.instagram_review_status == REVIEW_PENDING,
        )
    )
    if biz_date is not None:
        stmt = stmt.where(ContentUnit.biz_date == biz_date)
    if threads_account_id is not None:
        stmt = stmt.where(ContentUnit.threads_account_id == threads_account_id)
    if instagram_account_id is not None:
        stmt = stmt.where(ContentUnit.instagram_account_id == instagram_account_id)
    stmt = stmt.order_by(ContentUnit.biz_date.asc(), ContentUnit.slot_no.asc()).limit(limit)
    return db.execute(stmt).scalars().all()


def approve_content_unit(db: Session, content_unit_id: UUID, reviewer_id: UUID | None = None) -> ContentUnit:
    unit = db.get(ContentUnit, content_unit_id)
    if not unit:
        raise ValueError(f"content_unit_id={content_unit_id} not found")

    if unit.generation_status != ContentStatus.READY:
        raise ValueError("READY 상태 콘텐츠만 승인할 수 있습니다.")

    unit.threads_review_status = REVIEW_APPROVED
    unit.instagram_review_status = REVIEW_APPROVED
    _sync_overall_review_status(unit)
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

        schedule_result = schedule_today_jobs(
            db,
            unit.biz_date,
            threads_account_id=unit.threads_account_id,
            instagram_account_id=unit.instagram_account_id,
            content_unit_ids=[unit.id],
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"schedule_failed:{str(exc)}")

    if schedule_result:
        try:
            from app.services.job_orchestrator import enqueue_pending_jobs_for_units

            enqueue_result = enqueue_pending_jobs_for_units(db, [unit.id])
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"enqueue_failed:{str(exc)}")

    return {
        "content_unit": unit,
        "schedule_result": schedule_result,
        "enqueue_result": enqueue_result,
        "warnings": warnings,
    }


def approve_channel_and_prepare_publish(
    db: Session,
    content_unit_id: UUID,
    *,
    channel: ChannelType,
    reviewer_id: UUID | None = None,
) -> dict[str, Any]:
    unit = approve_content_channel(db, content_unit_id, channel=channel, reviewer_id=reviewer_id)
    schedule_result: dict[str, Any] | None = None
    enqueue_result: dict[str, Any] | None = None
    warnings: list[str] = []

    try:
        from app.services.scheduler_service import schedule_today_jobs

        schedule_result = schedule_today_jobs(
            db,
            unit.biz_date,
            threads_account_id=unit.threads_account_id,
            instagram_account_id=unit.instagram_account_id,
            content_unit_ids=[unit.id],
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"schedule_failed:{str(exc)}")

    if schedule_result:
        try:
            from app.services.job_orchestrator import enqueue_pending_jobs_for_units

            enqueue_result = enqueue_pending_jobs_for_units(db, [unit.id])
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"enqueue_failed:{str(exc)}")

    return {
        "content_unit": unit,
        "schedule_result": schedule_result,
        "enqueue_result": enqueue_result,
        "warnings": warnings,
    }


def approve_content_channel(
    db: Session,
    content_unit_id: UUID,
    *,
    channel: ChannelType,
    reviewer_id: UUID | None = None,
) -> ContentUnit:
    unit = db.get(ContentUnit, content_unit_id)
    if not unit:
        raise ValueError(f"content_unit_id={content_unit_id} not found")
    if unit.generation_status != ContentStatus.READY:
        raise ValueError("READY 상태 콘텐츠만 승인할 수 있습니다.")

    if channel == ChannelType.THREADS:
        unit.threads_review_status = REVIEW_APPROVED
    elif channel == ChannelType.INSTAGRAM:
        unit.instagram_review_status = REVIEW_APPROVED
    else:
        raise ValueError(f"지원하지 않는 채널: {channel}")

    _sync_overall_review_status(unit)
    unit.reviewed_at = datetime.now(timezone.utc)
    unit.reviewed_by = reviewer_id
    db.commit()
    db.refresh(unit)
    return unit


def reject_content_channel(
    db: Session,
    content_unit_id: UUID,
    *,
    channel: ChannelType,
    reviewer_id: UUID | None = None,
) -> ContentUnit:
    unit = db.get(ContentUnit, content_unit_id)
    if not unit:
        raise ValueError(f"content_unit_id={content_unit_id} not found")

    if channel == ChannelType.THREADS:
        unit.threads_review_status = REVIEW_REJECTED
    elif channel == ChannelType.INSTAGRAM:
        unit.instagram_review_status = REVIEW_REJECTED
    else:
        raise ValueError(f"지원하지 않는 채널: {channel}")

    _sync_overall_review_status(unit)
    unit.reviewed_at = datetime.now(timezone.utc)
    unit.reviewed_by = reviewer_id
    db.commit()
    db.refresh(unit)
    return unit


def reject_content_unit(db: Session, content_unit_id: UUID, reviewer_id: UUID | None = None) -> ContentUnit:
    unit = db.get(ContentUnit, content_unit_id)
    if not unit:
        raise ValueError(f"content_unit_id={content_unit_id} not found")

    unit.threads_review_status = REVIEW_REJECTED
    unit.instagram_review_status = REVIEW_REJECTED
    _sync_overall_review_status(unit)
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
    slide_script: dict[str, Any] | None = None,
    font_style: str | None = None,
    background_mode: str | None = None,
    template_style: str | None = None,
) -> ContentUnit:
    unit = db.get(ContentUnit, content_unit_id)
    if not unit:
        raise ValueError(f"content_unit_id={content_unit_id} not found")

    unit.threads_body = threads_body.strip()
    unit.threads_first_reply = threads_first_reply.strip()
    unit.instagram_caption = instagram_caption.strip()

    if slide_script is not None:
        slides = slide_script.get("slides") if isinstance(slide_script, dict) else None
        if not isinstance(slides, list) or not (4 <= len(slides) <= 7):
            raise ValueError("slide_script.slides는 4~7개여야 합니다.")
        for idx, slide in enumerate(slides, start=1):
            if not isinstance(slide, dict):
                raise ValueError(f"slide[{idx}] 형식이 잘못되었습니다.")
            if not str(slide.get("title", "")).strip():
                raise ValueError(f"slide[{idx}].title 이 비어 있습니다.")
            if not str(slide.get("body", "")).strip():
                raise ValueError(f"slide[{idx}].body 이 비어 있습니다.")
        unit.slide_script = slide_script

    if font_style or background_mode or template_style:
        script = unit.slide_script if isinstance(unit.slide_script, dict) else {"slides": []}
        options = script.get("render_options") if isinstance(script.get("render_options"), dict) else {}
        if font_style:
            options["font_style"] = font_style
        if background_mode:
            options["background_mode"] = background_mode
        if template_style:
            options["template_style"] = template_style
        script["render_options"] = options
        unit.slide_script = script

    # 문구/슬라이드가 바뀌면 기존 렌더링 결과는 무효화.
    db.execute(delete(RenderedAsset).where(RenderedAsset.content_unit_id == unit.id))

    # 수정되면 채널별 승인 상태를 다시 검수 대기로 돌림
    unit.threads_review_status = REVIEW_PENDING
    unit.instagram_review_status = REVIEW_PENDING
    _sync_overall_review_status(unit)
    unit.reviewed_at = None
    unit.reviewed_by = None

    db.commit()
    db.refresh(unit)
    return unit


def update_threads_copy(
    db: Session,
    content_unit_id: UUID,
    *,
    threads_body: str,
    threads_first_reply: str,
) -> ContentUnit:
    unit = db.get(ContentUnit, content_unit_id)
    if not unit:
        raise ValueError(f"content_unit_id={content_unit_id} not found")

    unit.threads_body = threads_body.strip()
    unit.threads_first_reply = threads_first_reply.strip()
    unit.threads_review_status = REVIEW_PENDING
    _sync_overall_review_status(unit)
    unit.reviewed_at = None
    unit.reviewed_by = None

    db.commit()
    db.refresh(unit)
    return unit


def update_instagram_copy(
    db: Session,
    content_unit_id: UUID,
    *,
    instagram_caption: str,
    slide_script: dict[str, Any] | None = None,
    font_style: str | None = None,
    background_mode: str | None = None,
    template_style: str | None = None,
) -> ContentUnit:
    unit = db.get(ContentUnit, content_unit_id)
    if not unit:
        raise ValueError(f"content_unit_id={content_unit_id} not found")

    unit.instagram_caption = instagram_caption.strip()

    if slide_script is not None:
        slides = slide_script.get("slides") if isinstance(slide_script, dict) else None
        if not isinstance(slides, list) or not (4 <= len(slides) <= 7):
            raise ValueError("slide_script.slides는 4~7개여야 합니다.")
        for idx, slide in enumerate(slides, start=1):
            if not isinstance(slide, dict):
                raise ValueError(f"slide[{idx}] 형식이 잘못되었습니다.")
            if not str(slide.get("title", "")).strip():
                raise ValueError(f"slide[{idx}].title 이 비어 있습니다.")
            if not str(slide.get("body", "")).strip():
                raise ValueError(f"slide[{idx}].body 이 비어 있습니다.")
        unit.slide_script = slide_script

    if font_style or background_mode or template_style:
        script = unit.slide_script if isinstance(unit.slide_script, dict) else {"slides": []}
        options = script.get("render_options") if isinstance(script.get("render_options"), dict) else {}
        if font_style:
            options["font_style"] = font_style
        if background_mode:
            options["background_mode"] = background_mode
        if template_style:
            options["template_style"] = template_style
        script["render_options"] = options
        unit.slide_script = script

    db.execute(delete(RenderedAsset).where(RenderedAsset.content_unit_id == unit.id))
    unit.instagram_review_status = REVIEW_PENDING
    _sync_overall_review_status(unit)
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
            "threads_review_status": item.threads_review_status,
            "instagram_review_status": item.instagram_review_status,
            "threads_body": item.threads_body,
            "threads_first_reply": item.threads_first_reply,
            "instagram_caption": item.instagram_caption,
            "slide_script": item.slide_script,
        }
        for item in queue
    ]


def approve_all_pending_for_channel(
    db: Session,
    *,
    biz_date,
    threads_account_id: UUID | None,
    instagram_account_id: UUID | None,
    channel: ChannelType,
    reviewer_id: UUID | None = None,
) -> dict[str, Any]:
    if channel == ChannelType.THREADS:
        target_col = ContentUnit.threads_review_status
    elif channel == ChannelType.INSTAGRAM:
        target_col = ContentUnit.instagram_review_status
    else:
        raise ValueError(f"지원하지 않는 채널: {channel}")

    conditions = [
        ContentUnit.biz_date == biz_date,
        ContentUnit.generation_status == ContentStatus.READY,
        ContentUnit.guardrail_passed.is_(True),
        target_col == REVIEW_PENDING,
    ]
    if threads_account_id is not None:
        conditions.append(ContentUnit.threads_account_id == threads_account_id)
    if instagram_account_id is not None:
        conditions.append(ContentUnit.instagram_account_id == instagram_account_id)

    units = (
        db.execute(select(ContentUnit).where(and_(*conditions)).order_by(ContentUnit.slot_no.asc()))
        .scalars()
        .all()
    )
    if not units:
        return {"updated": 0, "content_unit_ids": []}

    now = datetime.now(timezone.utc)
    updated_ids: list[UUID] = []
    for unit in units:
        if channel == ChannelType.THREADS:
            unit.threads_review_status = REVIEW_APPROVED
        else:
            unit.instagram_review_status = REVIEW_APPROVED
        _sync_overall_review_status(unit)
        unit.reviewed_at = now
        unit.reviewed_by = reviewer_id
        updated_ids.append(unit.id)

    db.commit()
    return {"updated": len(updated_ids), "content_unit_ids": updated_ids}
