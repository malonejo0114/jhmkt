from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ChannelType, ContentSourceItem, ContentStatus, ContentUnit, PromptProfile, ReviewStatus
from app.services.content_provider import generate_content_payload
from app.services.deeplink_service import get_or_create_deeplink
from app.services.guardrails import validate_threads_body


def _load_recent_threads_bodies(db: Session) -> list[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    stmt: Select[tuple[str]] = select(ContentUnit.threads_body).where(ContentUnit.created_at >= cutoff)
    return [row[0] for row in db.execute(stmt).all()]


def _load_threads_prompt_context(db: Session) -> dict[str, Any]:
    profile = (
        db.execute(
            select(PromptProfile)
            .where(
                PromptProfile.channel == ChannelType.THREADS,
                PromptProfile.active.is_(True),
            )
            .order_by(PromptProfile.version.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if not profile:
        return {
            "banned_words": [],
            "hook_candidates": [],
            "target_chars": 280,
            "disclosure_line": None,
        }

    banned_terms = []
    if isinstance(profile.banned_words, dict):
        raw_terms = profile.banned_words.get("terms", [])
        if isinstance(raw_terms, list):
            banned_terms = [str(term).strip() for term in raw_terms if str(term).strip()]

    hook_candidates = []
    target_chars = 280
    if isinstance(profile.style_params, dict):
        weekly_templates = profile.style_params.get("weekly_hook_templates", [])
        weekly_candidates = profile.style_params.get("weekly_hook_candidates", [])
        if isinstance(weekly_templates, list):
            hook_candidates.extend(str(item).strip() for item in weekly_templates if str(item).strip())
        if isinstance(weekly_candidates, list):
            hook_candidates.extend(str(item).strip() for item in weekly_candidates if str(item).strip())
        raw_target_chars = profile.style_params.get("target_chars", 280)
        try:
            target_chars = int(raw_target_chars)
        except (TypeError, ValueError):
            target_chars = 280

    return {
        "banned_words": banned_terms,
        "hook_candidates": hook_candidates[:5],
        "target_chars": max(180, min(target_chars, 460)),
        "disclosure_line": profile.disclosure_line,
    }


def generate_today_content_units(db: Session, biz_date, unit_count: int) -> dict[str, Any]:
    settings = get_settings()
    prompt_ctx = _load_threads_prompt_context(db)
    disclosure_line = prompt_ctx.get("disclosure_line") or settings.disclosure_line

    existing_slots = {
        row[0]
        for row in db.execute(select(ContentUnit.slot_no).where(ContentUnit.biz_date == biz_date)).all()
    }

    missing_slots = [slot for slot in range(1, unit_count + 1) if slot not in existing_slots]
    if not missing_slots:
        return {
            "biz_date": biz_date,
            "requested_count": unit_count,
            "created_count": 0,
            "skipped_count": unit_count,
            "content_unit_ids": [],
        }

    seeds = (
        db.execute(
            select(ContentSourceItem)
            .where(ContentSourceItem.active.is_(True))
            .order_by(ContentSourceItem.last_used_at.asc().nullsfirst(), ContentSourceItem.priority.desc())
            .limit(max(unit_count, 10))
        )
        .scalars()
        .all()
    )

    if not seeds:
        raise ValueError("활성 seed가 없습니다. /admin/seeds/import 후 다시 시도하세요.")

    recent_bodies = _load_recent_threads_bodies(db)

    created_ids: list[str] = []
    seed_index = 0
    now = datetime.now(timezone.utc)

    for slot in missing_slots:
        seed = seeds[seed_index % len(seeds)]
        seed_index += 1

        short_url = get_or_create_deeplink(db, seed.source_url)

        payload = None
        guardrail_reasons: list[str] = []
        duplicate = 0.0
        for variant in range(6):
            candidate = generate_content_payload(
                topic=seed.topic,
                category=seed.category,
                short_url=short_url,
                disclosure_line=disclosure_line,
                banned_words=prompt_ctx["banned_words"],
                hook_candidates=prompt_ctx["hook_candidates"],
                target_chars=prompt_ctx["target_chars"],
                variant=variant,
            )
            result = validate_threads_body(
                candidate["threads_body"], disclosure_line, recent_bodies
            )
            if result.passed:
                payload = candidate
                duplicate = result.duplicate_score
                break
            guardrail_reasons = result.reasons
            duplicate = result.duplicate_score

        if payload is None:
            unit = ContentUnit(
                biz_date=biz_date,
                slot_no=slot,
                source_item_id=seed.id,
                topic=seed.topic,
                category=seed.category,
                original_coupang_url=seed.source_url,
                coupang_short_url=short_url,
                threads_body="",
                threads_first_reply="",
                instagram_caption="",
                slide_script={"slides": []},
                guardrail_passed=False,
                duplicate_score=duplicate,
                quality_score=0,
                generation_status=ContentStatus.FAILED,
                failure_reason=";".join(guardrail_reasons)[:64],
                review_status=ReviewStatus.REJECTED,
            )
        else:
            unit = ContentUnit(
                biz_date=biz_date,
                slot_no=slot,
                source_item_id=seed.id,
                topic=seed.topic,
                category=seed.category,
                original_coupang_url=seed.source_url,
                coupang_short_url=short_url,
                threads_body=payload["threads_body"],
                threads_first_reply=payload["threads_first_reply"],
                instagram_caption=payload["instagram_caption"],
                slide_script={"slides": payload["slides"]},
                guardrail_passed=True,
                duplicate_score=duplicate,
                quality_score=1,
                generation_status=ContentStatus.READY,
                failure_reason=None,
                review_status=ReviewStatus.PENDING,
            )
            recent_bodies.append(payload["threads_body"])

        seed.last_used_at = now
        db.add(unit)
        db.flush()
        created_ids.append(str(unit.id))

    db.commit()
    return {
        "biz_date": biz_date,
        "requested_count": unit_count,
        "created_count": len(created_ids),
        "skipped_count": unit_count - len(created_ids),
        "content_unit_ids": created_ids,
    }
