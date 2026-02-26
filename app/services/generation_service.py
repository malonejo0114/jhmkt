from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AccountStatus,
    ChannelType,
    ContentSourceItem,
    ContentStatus,
    ContentUnit,
    InstagramAccount,
    PromptProfile,
    ReviewStatus,
    SourceType,
    ThreadsAccount,
)
from app.services.coupang_client import resolve_coupang_source_url
from app.services.content_provider import generate_content_payload
from app.services.deeplink_service import get_or_create_deeplink
from app.services.guardrails import validate_threads_body
from app.services.hash_utils import sha256_hex
from app.services.time_utils import KST

DEFAULT_COUPANG_WRITING_PROMPT = (
    "쿠팡 제휴 글은 손실회피형 훅 1문장으로 시작하고, "
    "바로 체크리스트 4~5개를 짧게 제시해라. "
    "과장 없이 실사용 기준(가격/성능/관리) 위주로 작성해라."
)
DEFAULT_SAJU_WRITING_PROMPT = (
    "사주 글은 공포 조장 없이 실용적 조언 중심으로 작성해라. "
    "해석은 단정하지 말고, 독자가 바로 적용할 수 있는 행동 팁 3~4개를 제시해라."
)


def _default_vertical_prompts() -> dict[str, str]:
    return {
        "COUPANG": DEFAULT_COUPANG_WRITING_PROMPT,
        "SAJU": DEFAULT_SAJU_WRITING_PROMPT,
    }


def _normalize_vertical_prompts(raw: Any) -> dict[str, str]:
    prompts = _default_vertical_prompts()
    if not isinstance(raw, dict):
        return prompts
    for key in ("COUPANG", "SAJU"):
        value = str(raw.get(key, "")).strip()
        if value:
            prompts[key] = value
    return prompts


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
            "vertical_prompts": _default_vertical_prompts(),
        }

    banned_terms = []
    if isinstance(profile.banned_words, dict):
        raw_terms = profile.banned_words.get("terms", [])
        if isinstance(raw_terms, list):
            banned_terms = [str(term).strip() for term in raw_terms if str(term).strip()]

    hook_candidates = []
    target_chars = 280
    vertical_prompts = _default_vertical_prompts()
    if isinstance(profile.style_params, dict):
        weekly_templates = profile.style_params.get("weekly_hook_templates", [])
        weekly_candidates = profile.style_params.get("weekly_hook_candidates", [])
        vertical_prompts = _normalize_vertical_prompts(profile.style_params.get("vertical_prompts"))
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
        "vertical_prompts": vertical_prompts,
    }


def _ensure_active_threads_profile(db: Session) -> PromptProfile:
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
    if profile:
        return profile

    settings = get_settings()
    profile = PromptProfile(
        channel=ChannelType.THREADS,
        account_ref=None,
        version=1,
        disclosure_line=settings.disclosure_line,
        hook_template_weights={"question": 0.34, "checklist": 0.33, "comparison": 0.33},
        style_params={
            "target_chars": 280,
            "cta": "first_comment",
            "vertical_prompts": _default_vertical_prompts(),
        },
        banned_words={"terms": ["완치", "100%", "무조건", "절대", "기적"]},
        active=True,
    )
    db.add(profile)
    db.flush()
    return profile


def get_vertical_prompt_settings(db: Session) -> dict[str, str]:
    return _load_threads_prompt_context(db).get("vertical_prompts", _default_vertical_prompts())


def save_vertical_prompt_settings(
    db: Session,
    *,
    coupang_prompt: str,
    saju_prompt: str,
) -> dict[str, str]:
    profile = _ensure_active_threads_profile(db)
    style_params = dict(profile.style_params or {})
    prompts = _normalize_vertical_prompts(style_params.get("vertical_prompts"))
    prompts["COUPANG"] = coupang_prompt.strip() or DEFAULT_COUPANG_WRITING_PROMPT
    prompts["SAJU"] = saju_prompt.strip() or DEFAULT_SAJU_WRITING_PROMPT
    style_params["vertical_prompts"] = prompts
    profile.style_params = style_params
    db.commit()
    return prompts


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

        try:
            short_url = get_or_create_deeplink(db, seed.source_url)
        except Exception:  # noqa: BLE001
            short_url = seed.source_url

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
                threads_review_status=ReviewStatus.REJECTED.value,
                instagram_review_status=ReviewStatus.REJECTED.value,
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
                slide_script={
                    "slides": payload["slides"],
                    "render_options": payload.get(
                        "render_options", {"font_style": "sans", "background_mode": "stock"}
                    ),
                },
                guardrail_passed=True,
                threads_review_status=ReviewStatus.PENDING.value,
                instagram_review_status=ReviewStatus.PENDING.value,
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


def _manual_schedule_times(
    biz_date: date,
    count: int,
    start_hour: int,
    end_hour: int,
    scope_seed: str,
) -> list[datetime]:
    if count <= 0:
        return []

    now_local = datetime.now(tz=KST)
    if biz_date < now_local.date():
        raise ValueError("지난 게시 날짜로는 생성할 수 없습니다.")

    start_h = max(0, min(23, start_hour))
    end_h = max(1, min(23, end_hour))
    if end_h <= start_h:
        end_h = min(start_h + 1, 23)

    start_local = datetime.combine(biz_date, time(start_h, 0), tzinfo=KST)
    end_local = datetime.combine(biz_date, time(end_h, 0), tzinfo=KST)
    if biz_date == now_local.date():
        # 오늘 생성은 현재 시각 이후 슬롯만 허용한다.
        min_start = (now_local + timedelta(minutes=2)).replace(second=0, microsecond=0)
        if min_start > start_local:
            start_local = min_start
    if end_local <= start_local:
        raise ValueError("선택한 시간이 현재보다 이전입니다. 종료 시각을 더 늦게 설정해주세요.")

    interval_seconds = (end_local - start_local).total_seconds() / (count + 1)
    times: list[datetime] = []
    for i in range(1, count + 1):
        base_local = start_local + timedelta(seconds=interval_seconds * i)
        jitter = (int(sha256_hex(f"{scope_seed}|{biz_date.isoformat()}|{i}")[:8], 16) % 19) - 9
        candidate_local = base_local + timedelta(minutes=jitter)
        candidate_local = max(start_local, min(candidate_local, end_local))
        if times:
            prev_local = times[-1].astimezone(KST)
            if candidate_local <= prev_local:
                candidate_local = prev_local + timedelta(minutes=1)
            if candidate_local > end_local:
                raise ValueError("선택한 시간 범위가 너무 좁아 현재 이후 슬롯을 만들 수 없습니다.")
        times.append(candidate_local.astimezone(timezone.utc))
    return times


def _next_slot_no(db: Session, biz_date: date) -> int:
    slots = [row[0] for row in db.execute(select(ContentUnit.slot_no).where(ContentUnit.biz_date == biz_date)).all()]
    return (max(slots) + 1) if slots else 1


def _is_slot_conflict(exc: IntegrityError) -> bool:
    message = str(getattr(exc, "orig", exc))
    return (
        "uq_content_unit_date_slot" in message
        or "content_unit_date_slot" in message
        or "(biz_date, slot_no)" in message
    )


def _insert_content_unit_with_retry(
    db: Session,
    *,
    biz_date: date,
    unit_kwargs: dict[str, Any],
    max_attempts: int = 8,
) -> ContentUnit:
    for _ in range(max_attempts):
        slot_no = _next_slot_no(db, biz_date)
        unit = ContentUnit(slot_no=slot_no, **unit_kwargs)
        try:
            with db.begin_nested():
                db.add(unit)
                db.flush()
            return unit
        except IntegrityError as exc:
            if _is_slot_conflict(exc):
                continue
            raise

    raise ValueError("생성 요청이 겹쳐 슬롯 충돌이 발생했습니다. 2초 후 다시 시도하세요.")


def _get_or_create_source_item(
    db: Session,
    topic: str,
    source_url: str,
    *,
    category: str = "키워드",
) -> ContentSourceItem:
    existing = (
        db.execute(
            select(ContentSourceItem).where(
                ContentSourceItem.topic == topic,
                ContentSourceItem.source_url == source_url,
            )
        )
        .scalars()
        .first()
    )
    if existing:
        existing.active = True
        existing.priority = max(existing.priority, 70)
        existing.category = category
        return existing

    source_type = SourceType.SEARCH_URL if "/np/search" in source_url else SourceType.PRODUCT_URL
    item = ContentSourceItem(
        topic=topic,
        category=category,
        source_url=source_url,
        source_type=source_type,
        priority=70,
        active=True,
    )
    db.add(item)
    db.flush()
    return item


def _apply_render_overrides(
    payload: dict[str, Any],
    *,
    background_mode: str | None,
    template_style: str | None,
) -> dict[str, Any]:
    render_options = payload.get("render_options")
    if not isinstance(render_options, dict):
        render_options = {}
    if background_mode:
        render_options["background_mode"] = background_mode
    if template_style:
        render_options["template_style"] = template_style
    payload["render_options"] = render_options
    return payload


def _normalize_vertical_mode(raw: str | None) -> str:
    key = (raw or "COUPANG").strip().upper()
    if key not in {"COUPANG", "SAJU"}:
        return "COUPANG"
    return key


def _normalize_tone_style(raw: str | None) -> str:
    key = (raw or "CASUAL").strip().upper()
    if key not in {"FORMAL", "CASUAL"}:
        return "CASUAL"
    return key


def _normalize_emoji_mode(raw: str | None) -> str:
    key = (raw or "ON").strip().upper()
    if key not in {"ON", "OFF"}:
        return "ON"
    return key


def _normalize_slide_count(raw: int) -> int:
    return max(4, min(int(raw), 7))


def _normalize_slides_for_cardnews(
    *,
    slides_raw: Any,
    target_count: int,
    topic: str,
    memo: str,
) -> list[dict[str, Any]]:
    slides: list[dict[str, Any]] = []
    if isinstance(slides_raw, list):
        for row in slides_raw:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title", "")).strip()
            body = str(row.get("body", "")).strip()
            if not title or not body:
                continue
            slides.append({"title": title, "body": body})

    if not slides:
        slides = [
            {"title": f"{topic} 핵심 요약", "body": memo.strip() or f"{topic} 핵심 포인트를 정리했습니다."},
            {"title": "문제 포인트", "body": "대부분 놓치는 비교 포인트부터 짚어봅니다."},
            {"title": "핵심 기준 1", "body": "사용 목적과 예산을 먼저 고정하세요."},
            {"title": "핵심 기준 2", "body": "유지비/관리 난이도를 같이 비교하세요."},
            {"title": "마무리", "body": "바로 적용 가능한 체크리스트로 확인하세요."},
        ]

    if len(slides) > target_count:
        slides = slides[:target_count]

    while len(slides) < target_count:
        no = len(slides) + 1
        slides.append(
            {
                "title": f"체크 {no}",
                "body": memo.strip() or f"{topic} 관련 실전 체크포인트 {no}",
            }
        )

    normalized: list[dict[str, Any]] = []
    for idx, slide in enumerate(slides, start=1):
        normalized.append(
            {
                "slide_no": idx,
                "title": str(slide.get("title", "")).strip() or f"{topic} 포인트 {idx}",
                "body": str(slide.get("body", "")).strip() or f"{topic} 핵심 내용 {idx}",
            }
        )
    return normalized


def _saju_source_url(keyword: str) -> str:
    return f"https://saju.local/request?q={quote_plus(keyword)}"


def _adapt_payload_for_saju(
    payload: dict[str, Any],
    *,
    disclosure_line: str,
    keyword: str,
) -> dict[str, Any]:
    body = str(payload.get("threads_body", "")).strip()
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if disclosure_line and lines and lines[0] == disclosure_line:
        lines = lines[1:]
    core = "\n".join(lines).strip()
    if "링크는 첫 댓글" not in core:
        core = f"{core}\n상담 링크는 첫 댓글에 남길게요.".strip()
    payload["threads_body"] = f"{disclosure_line}\n{core}".strip() if disclosure_line else core
    payload["threads_first_reply"] = (
        f"{disclosure_line}\n사주 상담 신청: 댓글에 생년월일(양/음력), 태어난 시간, 성별을 남겨주세요.".strip()
        if disclosure_line
        else "사주 상담 신청: 댓글에 생년월일(양/음력), 태어난 시간, 성별을 남겨주세요."
    )
    payload["instagram_caption"] = (
        f"{disclosure_line}\n{keyword} 사주 포인트를 카드뉴스로 정리했습니다.\n상담이 필요하면 댓글에 '상담'이라고 남겨주세요.".strip()
        if disclosure_line
        else f"{keyword} 사주 포인트를 카드뉴스로 정리했습니다.\n상담이 필요하면 댓글에 '상담'이라고 남겨주세요."
    )
    return payload


def generate_content_units_for_keywords(
    db: Session,
    *,
    biz_date: date,
    threads_account_id: UUID,
    instagram_account_id: UUID | None,
    keywords: list[str],
    start_hour: int = 9,
    end_hour: int = 22,
    vertical_mode: str = "COUPANG",
    tone_style: str = "CASUAL",
    emoji_mode: str = "ON",
    create_instagram: bool = False,
    background_mode: str = "google_free",
    template_style: str = "campaign",
) -> dict[str, Any]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        item = keyword.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)

    if not cleaned:
        raise ValueError("키워드를 1개 이상 입력해주세요.")
    if len(cleaned) > 10:
        raise ValueError("키워드는 최대 10개까지 입력 가능합니다.")

    threads_account = db.get(ThreadsAccount, threads_account_id)
    if not threads_account or threads_account.status != AccountStatus.ACTIVE:
        raise ValueError("활성 Threads 계정을 찾을 수 없습니다.")
    instagram_account: InstagramAccount | None = None
    if create_instagram:
        if instagram_account_id is None:
            raise ValueError("카드뉴스 생성을 위해 Instagram 계정이 필요합니다.")
        instagram_account = db.get(InstagramAccount, instagram_account_id)
        if not instagram_account or instagram_account.status != AccountStatus.ACTIVE:
            raise ValueError("활성 Instagram 계정을 찾을 수 없습니다.")

    settings = get_settings()
    prompt_ctx = _load_threads_prompt_context(db)
    mode = _normalize_vertical_mode(vertical_mode)
    tone = _normalize_tone_style(tone_style)
    emoji = _normalize_emoji_mode(emoji_mode)
    disclosure_line = (
        prompt_ctx.get("disclosure_line") or settings.disclosure_line
        if mode == "COUPANG"
        else settings.saju_disclosure_line.strip()
    )
    vertical_prompts = prompt_ctx.get("vertical_prompts") or _default_vertical_prompts()
    style_prompt = str(vertical_prompts.get(mode, "")).strip()
    recent_bodies = _load_recent_threads_bodies(db)

    schedule_times = _manual_schedule_times(
        biz_date,
        len(cleaned),
        start_hour=start_hour,
        end_hour=end_hour,
        scope_seed=str(threads_account_id),
    )
    now = datetime.now(timezone.utc)
    created_ids: list[str] = []
    failed_keywords: list[str] = []
    per_mode_category = "키워드" if mode == "COUPANG" else "사주"

    for idx, keyword in enumerate(cleaned):
        topic = f"{keyword} 구매 가이드" if mode == "COUPANG" else f"{keyword} 사주 가이드"
        source_url = resolve_coupang_source_url(keyword) if mode == "COUPANG" else _saju_source_url(keyword)
        source_item = _get_or_create_source_item(
            db,
            topic=topic,
            source_url=source_url,
            category=per_mode_category,
        )
        source_item.last_used_at = now
        if mode == "COUPANG":
            try:
                short_url = get_or_create_deeplink(db, source_url)
            except Exception:  # noqa: BLE001
                short_url = source_url
        else:
            short_url = source_url

        payload = None
        guardrail_reasons: list[str] = []
        duplicate = 0.0
        for variant in range(6):
            candidate = generate_content_payload(
                topic=topic,
                category=per_mode_category,
                short_url=short_url,
                disclosure_line=disclosure_line,
                banned_words=prompt_ctx["banned_words"],
                hook_candidates=prompt_ctx["hook_candidates"],
                target_chars=prompt_ctx["target_chars"],
                tone_style=tone,
                emoji_mode=emoji,
                style_prompt=style_prompt,
                variant=variant,
            )
            if mode == "SAJU":
                candidate = _adapt_payload_for_saju(candidate, disclosure_line=disclosure_line, keyword=keyword)
            if create_instagram:
                candidate = _apply_render_overrides(
                    candidate,
                    background_mode=background_mode,
                    template_style=template_style,
                )
            result = validate_threads_body(candidate["threads_body"], disclosure_line, recent_bodies)
            if result.passed:
                payload = candidate
                duplicate = result.duplicate_score
                break
            guardrail_reasons = result.reasons
            duplicate = result.duplicate_score

        if payload is None:
            failed_keywords.append(keyword)
            unit_kwargs = dict(
                biz_date=biz_date,
                scheduled_at=schedule_times[idx],
                threads_account_id=threads_account.id,
                instagram_account_id=instagram_account.id if create_instagram and instagram_account else None,
                source_item_id=source_item.id,
                topic=topic,
                category=per_mode_category,
                original_coupang_url=source_url,
                coupang_short_url=short_url,
                threads_body="",
                threads_first_reply="",
                instagram_caption="",
                slide_script={"slides": []},
                guardrail_passed=False,
                threads_review_status=ReviewStatus.REJECTED.value,
                instagram_review_status=ReviewStatus.REJECTED.value,
                duplicate_score=duplicate,
                quality_score=0,
                generation_status=ContentStatus.FAILED,
                failure_reason=";".join(guardrail_reasons)[:64] if guardrail_reasons else "guardrail_failed",
                review_status=ReviewStatus.REJECTED,
            )
        else:
            unit_kwargs = dict(
                biz_date=biz_date,
                scheduled_at=schedule_times[idx],
                threads_account_id=threads_account.id,
                instagram_account_id=instagram_account.id if create_instagram and instagram_account else None,
                source_item_id=source_item.id,
                topic=topic,
                category=per_mode_category,
                original_coupang_url=source_url,
                coupang_short_url=short_url,
                threads_body=payload["threads_body"],
                threads_first_reply=payload["threads_first_reply"],
                instagram_caption=payload["instagram_caption"] if create_instagram else "",
                slide_script=(
                    {
                        "slides": payload["slides"],
                        "render_options": payload.get(
                            "render_options",
                            {"font_style": "sans", "background_mode": "google_free", "template_style": "campaign"},
                        ),
                    }
                    if create_instagram
                    else {"slides": [], "render_options": {}}
                ),
                guardrail_passed=True,
                threads_review_status=ReviewStatus.PENDING.value,
                instagram_review_status=(
                    ReviewStatus.PENDING.value if create_instagram else ReviewStatus.REJECTED.value
                ),
                duplicate_score=duplicate,
                quality_score=1,
                generation_status=ContentStatus.READY,
                failure_reason=None,
                review_status=ReviewStatus.PENDING,
            )
            recent_bodies.append(payload["threads_body"])

        unit = _insert_content_unit_with_retry(
            db,
            biz_date=biz_date,
            unit_kwargs=unit_kwargs,
        )
        created_ids.append(str(unit.id))

    db.commit()
    return {
        "biz_date": biz_date,
        "keywords": cleaned,
        "created_count": len(created_ids),
        "failed_count": len(failed_keywords),
        "failed_keywords": failed_keywords,
        "vertical_mode": mode,
        "tone_style": tone,
        "emoji_mode": emoji,
        "create_instagram": create_instagram,
        "content_unit_ids": created_ids,
    }


def create_instagram_content_unit_manual(
    db: Session,
    *,
    biz_date: date,
    threads_account_id: UUID,
    instagram_account_id: UUID,
    topic: str,
    memo: str = "",
    vertical_mode: str = "COUPANG",
    coupang_url: str = "",
    slide_count: int = 5,
    start_hour: int = 9,
    end_hour: int = 22,
    background_mode: str = "google_free",
    template_style: str = "campaign",
    font_style: str = "sans",
) -> dict[str, Any]:
    clean_topic = topic.strip()
    if not clean_topic:
        raise ValueError("카드뉴스 주제를 입력해주세요.")

    threads_account = db.get(ThreadsAccount, threads_account_id)
    if not threads_account or threads_account.status != AccountStatus.ACTIVE:
        raise ValueError("활성 Threads 계정을 찾을 수 없습니다.")
    instagram_account = db.get(InstagramAccount, instagram_account_id)
    if not instagram_account or instagram_account.status != AccountStatus.ACTIVE:
        raise ValueError("활성 Instagram 계정을 찾을 수 없습니다.")

    mode = _normalize_vertical_mode(vertical_mode)
    safe_slide_count = _normalize_slide_count(slide_count)
    settings = get_settings()
    prompt_ctx = _load_threads_prompt_context(db)

    disclosure_line = (
        prompt_ctx.get("disclosure_line") or settings.disclosure_line
        if mode == "COUPANG"
        else settings.saju_disclosure_line.strip()
    )
    style_prompt = str((prompt_ctx.get("vertical_prompts") or _default_vertical_prompts()).get(mode, "")).strip()
    if memo.strip():
        style_prompt = f"{style_prompt}\n추가 요청: {memo.strip()}"

    source_url = (
        coupang_url.strip() or resolve_coupang_source_url(clean_topic)
        if mode == "COUPANG"
        else _saju_source_url(clean_topic)
    )
    short_url = source_url
    if mode == "COUPANG":
        try:
            short_url = get_or_create_deeplink(db, source_url)
        except Exception:  # noqa: BLE001
            short_url = source_url

    source_item = _get_or_create_source_item(
        db,
        topic=f"{clean_topic} 카드뉴스",
        source_url=source_url,
        category="카드뉴스",
    )
    source_item.last_used_at = datetime.now(timezone.utc)

    payload = generate_content_payload(
        topic=f"{clean_topic} 카드뉴스",
        category="카드뉴스",
        short_url=short_url,
        disclosure_line=disclosure_line,
        banned_words=prompt_ctx["banned_words"],
        hook_candidates=prompt_ctx["hook_candidates"],
        target_chars=prompt_ctx["target_chars"],
        tone_style="FORMAL",
        emoji_mode="OFF",
        style_prompt=style_prompt,
        variant=0,
    )

    caption = str(payload.get("instagram_caption", "")).strip()
    if not caption:
        caption = (
            f"{disclosure_line}\n{clean_topic} 카드뉴스 요약입니다.\n프로필 링크에서 자세한 내용을 확인하세요.".strip()
            if disclosure_line
            else f"{clean_topic} 카드뉴스 요약입니다.\n프로필 링크에서 자세한 내용을 확인하세요."
        )
    if "프로필 링크" not in caption:
        caption = f"{caption}\n프로필 링크에서 자세한 내용을 확인하세요."

    slides = _normalize_slides_for_cardnews(
        slides_raw=payload.get("slides"),
        target_count=safe_slide_count,
        topic=clean_topic,
        memo=memo,
    )
    render_options = payload.get("render_options")
    if not isinstance(render_options, dict):
        render_options = {}
    render_options["background_mode"] = background_mode.strip() or "google_free"
    render_options["template_style"] = template_style.strip() or "campaign"
    render_options["font_style"] = font_style.strip() or "sans"

    scheduled_at = _manual_schedule_times(
        biz_date=biz_date,
        count=1,
        start_hour=start_hour,
        end_hour=end_hour,
        scope_seed=str(instagram_account_id),
    )[0]

    unit_kwargs = dict(
        biz_date=biz_date,
        scheduled_at=scheduled_at,
        threads_account_id=threads_account.id,
        instagram_account_id=instagram_account.id,
        source_item_id=source_item.id,
        topic=f"{clean_topic} 카드뉴스",
        category="카드뉴스",
        original_coupang_url=source_url,
        coupang_short_url=short_url,
        threads_body="",
        threads_first_reply="",
        instagram_caption=caption,
        slide_script={"slides": slides, "render_options": render_options},
        guardrail_passed=True,
        threads_review_status=ReviewStatus.REJECTED.value,
        instagram_review_status=ReviewStatus.PENDING.value,
        duplicate_score=0,
        quality_score=1,
        generation_status=ContentStatus.READY,
        failure_reason=None,
        review_status=ReviewStatus.PENDING,
    )

    unit = _insert_content_unit_with_retry(
        db,
        biz_date=biz_date,
        unit_kwargs=unit_kwargs,
    )
    db.commit()
    return {
        "biz_date": biz_date,
        "content_unit_id": str(unit.id),
        "topic": clean_topic,
        "vertical_mode": mode,
        "slide_count": safe_slide_count,
    }
