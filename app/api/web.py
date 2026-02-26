from __future__ import annotations

import json
import mimetypes
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlencode
from uuid import UUID
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db
from app.models import (
    AccountStatus,
    AppUser,
    BrandProfile,
    BrandVertical,
    ChannelType,
    CommentActionType,
    CommentTriggerType,
    ContentStatus,
    ContentUnit,
    InstagramAccount,
    JobStatus,
    JobType,
    PostJob,
    RenderedAsset,
    ReviewStatus,
    SourceType,
    ThreadsAccount,
)
from app.schemas.accounts import InstagramAccountCreate, ThreadsAccountCreate
from app.schemas.engagement import (
    BrandProfileCreateRequest,
    CommentRuleCreateRequest,
    CommentRuleUpdateRequest,
)
from app.schemas.seeds import SeedItemIn
from app.services.accounts_service import upsert_instagram_account, upsert_threads_account
from app.services.auth_service import get_current_user
from app.services.engagement_service import (
    create_brand_profile,
    create_comment_rule,
    create_reply_jobs_for_pending_events,
    delete_comment_rule,
    get_or_create_profile_by_vertical,
    list_brand_profiles,
    list_comment_events,
    list_comment_rules,
    list_reply_jobs,
    process_pending_reply_jobs,
    retry_reply_job,
    set_comment_rule_active,
    set_instagram_brand_profile,
    set_threads_brand_profile,
    update_comment_rule,
)
from app.services.generation_service import (
    create_instagram_content_unit_manual,
    generate_content_units_for_keywords,
    generate_today_content_units,
    get_vertical_prompt_settings,
    save_vertical_prompt_settings,
)
from app.services.improvement_service import run_daily_improvement, run_weekly_improvement
from app.services.job_execution_service import dispatch_due_jobs_local
from app.services.job_orchestrator import enqueue_job_by_id, enqueue_pending_jobs_for_units, run_daily_bootstrap
from app.services.jobs_service import RetryNotAllowedError, retry_job
from app.services.render_service import ensure_rendered_assets
from app.services.review_service import (
    approve_all_pending_for_channel,
    approve_channel_and_prepare_publish,
    approve_and_prepare_publish,
    reject_content_channel,
    reject_all_pending_for_channel,
    list_review_queue,
    reject_content_unit,
    update_instagram_copy,
    update_threads_copy,
    update_content_unit_copy,
)
from app.services.scheduler_service import schedule_today_jobs
from app.services.seeds_service import import_seed_items
from app.services.asset_storage import asset_public_url
from app.services.asset_storage import save_uploaded_file
from app.services.publisher_service import publish_threads_manual_post
from app.services.setup_service import get_setup_summary
from app.services.saju_manseryeok_service import (
    BirthInfoPartial,
    build_four_pillars_details,
    build_saju_topic_fallback,
    calculate_four_pillars,
    infer_saju_topic,
    list_missing_birth_fields,
    normalize_gender,
    summarize_birth_info,
)
from app.services.time_utils import KST, kst_today
from app.services.threads_engagement_service import (
    create_threads_reply_jobs_for_pending_events,
    ingest_threads_comment_events_polling,
    list_threads_comment_events,
    list_threads_reply_jobs,
    process_pending_threads_reply_jobs,
)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
router = APIRouter(tags=["web"])


def _require_user_or_redirect(request: Request, db: Session) -> AppUser | RedirectResponse:
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login?flash=로그인이 필요합니다.", status_code=303)
    return user


def _normalize_keywords(raw: str) -> list[str]:
    chunks = [part.strip() for part in raw.replace("\n", ",").split(",")]
    items: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        if not chunk:
            continue
        key = chunk.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(chunk)
    return items[:10]


def _workspace_url(
    threads_account_id: UUID,
    *,
    ig_account_id: UUID | None = None,
    biz_date: date | None = None,
    flash: str | None = None,
) -> str:
    base = f"/app/accounts/{threads_account_id}"
    query: dict[str, str] = {}
    if ig_account_id is not None:
        query["ig_account_id"] = str(ig_account_id)
    if biz_date is not None:
        query["biz_date"] = biz_date.isoformat()
    if flash:
        query["flash"] = flash
    if not query:
        return base
    return f"{base}?{urlencode(query)}"


def _safe_return_to(return_to: str | None, fallback: str) -> str:
    if not return_to:
        return fallback
    trimmed = return_to.strip()
    if trimmed.startswith("/app/accounts/"):
        return trimmed
    return fallback


def _short_error_message(exc: Exception) -> str:
    raw = str(exc)
    lowered = raw.lower()
    if "uq_content_unit_date_slot" in lowered or "(biz_date, slot_no)" in lowered:
        return "생성 요청이 겹쳤습니다. 2초 후 다시 눌러주세요."
    if "활성 threads 계정을 찾을 수 없습니다" in raw:
        return "선택한 Threads 계정을 찾을 수 없습니다."
    if "활성 instagram 계정을 찾을 수 없습니다" in raw:
        return "선택한 Instagram 계정을 찾을 수 없습니다."
    return raw[:140] if raw else "알 수 없는 오류"


def _to_absolute_public_url(path_or_url: str) -> str:
    value = path_or_url.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    base = get_settings().public_base_url.rstrip("/")
    if value.startswith("/"):
        return f"{base}{value}"
    return f"{base}/{value}"


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _flag(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "on", "yes", "y"}


def _format_kst_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")


def _ensure_threads_comment_profile(db: Session, account: ThreadsAccount) -> BrandProfile:
    profile = db.get(BrandProfile, account.brand_profile_id) if account.brand_profile_id else None
    if profile:
        shared_count = (
            db.execute(
                select(func.count(ThreadsAccount.id)).where(ThreadsAccount.brand_profile_id == profile.id)
            ).scalar()
            or 0
        )
        if shared_count <= 1 and not profile.name.startswith("default-"):
            return profile

    if profile:
        vertical = profile.vertical_type
        existing_prompt = profile.comment_style_prompt or ""
    else:
        vertical = BrandVertical.SAJU
        existing_prompt = ""

    new_profile = BrandProfile(
        name=f"threads-comment-{str(account.id)[:8]}-{uuid4().hex[:6]}",
        vertical_type=vertical,
        comment_style_prompt=existing_prompt,
        active=True,
    )
    db.add(new_profile)
    db.flush()
    account.brand_profile_id = new_profile.id
    return new_profile


@router.get("/")
def landing_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/app", status_code=302)
    return templates.TemplateResponse(request, "landing.html", {})


@router.get("/privacy-policy")
def privacy_policy_page(request: Request):
    return templates.TemplateResponse(
        request,
        "privacy_policy.html",
        {
            "effective_date": "2026-02-26",
        },
    )


@router.get("/terms-of-service")
def terms_of_service_page(request: Request):
    return templates.TemplateResponse(
        request,
        "terms_of_service.html",
        {
            "effective_date": "2026-02-26",
        },
    )


@router.get("/web")
def legacy_web_redirect():
    return RedirectResponse("/app", status_code=302)


@router.get("/app")
def app_dashboard_home(request: Request, db: Session = Depends(get_db), flash: str | None = None):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user

    today = kst_today()
    threads_accounts = (
        db.execute(select(ThreadsAccount).order_by(ThreadsAccount.created_at.asc())).scalars().all()
    )
    instagram_accounts = (
        db.execute(select(InstagramAccount).order_by(InstagramAccount.created_at.asc())).scalars().all()
    )
    get_or_create_profile_by_vertical(db, BrandVertical.COUPANG)
    get_or_create_profile_by_vertical(db, BrandVertical.SAJU)
    setup_summary = get_setup_summary(db)

    pending_by_threads = {
        row[0]: int(row[1])
        for row in db.execute(
            select(ContentUnit.threads_account_id, func.count(ContentUnit.id))
            .where(
                and_(
                    or_(
                        ContentUnit.threads_review_status == ReviewStatus.PENDING.value,
                        ContentUnit.instagram_review_status == ReviewStatus.PENDING.value,
                    ),
                    ContentUnit.threads_account_id.is_not(None),
                )
            )
            .group_by(ContentUnit.threads_account_id)
        ).all()
    }
    today_jobs = (
        db.execute(
            select(PostJob)
            .join(ContentUnit, ContentUnit.id == PostJob.content_unit_id)
            .where(ContentUnit.biz_date == today)
        )
        .scalars()
        .all()
    )
    ready_today = (
        db.execute(
            select(func.count(ContentUnit.id)).where(
                and_(
                    ContentUnit.biz_date == today,
                    ContentUnit.threads_review_status == ReviewStatus.APPROVED.value,
                    ContentUnit.instagram_review_status == ReviewStatus.APPROVED.value,
                )
            )
        ).scalar()
        or 0
    )

    return templates.TemplateResponse(
        request,
        "app_home.html",
        {
            "flash": flash,
            "today": today,
            "user": user,
            "setup_summary": setup_summary,
            "threads_accounts": threads_accounts,
            "instagram_accounts": instagram_accounts,
            "pending_by_threads": pending_by_threads,
            "today_jobs": today_jobs,
            "ready_today": int(ready_today),
        },
    )


@router.get("/app/accounts/{threads_account_id}")
def app_account_workspace(
    threads_account_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    ig_account_id: UUID | None = None,
    biz_date: date | None = None,
    flash: str | None = None,
    saju_run: str | None = None,
    saju_year: str | None = None,
    saju_month: str | None = None,
    saju_day: str | None = None,
    saju_hour: str | None = None,
    saju_minute: str | None = None,
    saju_gender: str | None = None,
    saju_calendar: str | None = None,
    saju_leap_month: str | None = None,
    saju_question: str | None = None,
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user

    threads_account = db.get(ThreadsAccount, threads_account_id)
    if not threads_account:
        return RedirectResponse("/app?flash=Threads계정을 찾을 수 없습니다.", status_code=303)

    target_date = biz_date or kst_today()
    settings = get_settings()
    ig_accounts = (
        db.execute(
            select(InstagramAccount)
            .where(InstagramAccount.status == AccountStatus.ACTIVE)
            .order_by(InstagramAccount.created_at.asc())
        )
        .scalars()
        .all()
    )
    selected_ig = None
    if ig_account_id is not None:
        selected_ig = next((acc for acc in ig_accounts if acc.id == ig_account_id), None)
    if selected_ig is None and ig_accounts:
        selected_ig = ig_accounts[0]

    threads_comment_style_prompt = ""
    threads_comment_profile_name = ""
    if threads_account.brand_profile_id:
        profile = db.get(BrandProfile, threads_account.brand_profile_id)
        if profile:
            threads_comment_style_prompt = (profile.comment_style_prompt or "").strip()
            threads_comment_profile_name = profile.name

    get_or_create_profile_by_vertical(db, BrandVertical.COUPANG)
    get_or_create_profile_by_vertical(db, BrandVertical.SAJU)
    brand_profiles = list_brand_profiles(db)

    threads_base_filters = [ContentUnit.threads_account_id == threads_account.id, ContentUnit.biz_date == target_date]
    threads_pending_units = (
        db.execute(
            select(ContentUnit)
            .where(
                and_(
                    *threads_base_filters,
                    ContentUnit.threads_review_status == ReviewStatus.PENDING.value,
                )
            )
            .order_by(ContentUnit.slot_no.asc())
        )
        .scalars()
        .all()
    )
    threads_approved_count = (
        db.execute(
            select(func.count(ContentUnit.id)).where(
                and_(
                    *threads_base_filters,
                    ContentUnit.threads_review_status == ReviewStatus.APPROVED.value,
                )
            )
        ).scalar()
        or 0
    )

    instagram_pending_units: list[ContentUnit] = []
    instagram_pending_count = 0
    instagram_approved_count = 0
    if selected_ig:
        instagram_base_filters = [
            ContentUnit.threads_account_id == threads_account.id,
            ContentUnit.instagram_account_id == selected_ig.id,
            ContentUnit.biz_date == target_date,
        ]
        instagram_pending_units = (
            db.execute(
                select(ContentUnit)
                .where(
                    and_(
                        *instagram_base_filters,
                        ContentUnit.instagram_review_status == ReviewStatus.PENDING.value,
                    )
                )
                .order_by(ContentUnit.slot_no.asc())
            )
            .scalars()
            .all()
        )
        instagram_pending_count = (
            db.execute(
                select(func.count(ContentUnit.id)).where(
                    and_(
                        *instagram_base_filters,
                        ContentUnit.instagram_review_status == ReviewStatus.PENDING.value,
                    )
                )
            ).scalar()
            or 0
        )
        instagram_approved_count = (
            db.execute(
                select(func.count(ContentUnit.id)).where(
                    and_(
                        *instagram_base_filters,
                        ContentUnit.instagram_review_status == ReviewStatus.APPROVED.value,
                    )
                )
            ).scalar()
            or 0
        )

    threads_pending_count = len(threads_pending_units)
    review_ids = [item.id for item in threads_pending_units + instagram_pending_units]
    preview_map: dict[UUID, list[str]] = {}
    if review_ids:
        rendered_assets = (
            db.execute(
                select(RenderedAsset)
                .where(RenderedAsset.content_unit_id.in_(review_ids))
                .order_by(RenderedAsset.content_unit_id.asc(), RenderedAsset.slide_no.asc())
            )
            .scalars()
            .all()
        )
        for asset in rendered_assets:
            preview_map.setdefault(asset.content_unit_id, []).append(asset_public_url(asset.gcs_uri))
    scheduled_display_map = {
        item.id: _format_kst_datetime(item.scheduled_at)
        for item in (threads_pending_units + instagram_pending_units)
    }

    jobs_filters = [ContentUnit.threads_account_id == threads_account.id, ContentUnit.biz_date == target_date]
    if selected_ig:
        jobs_filters.append(ContentUnit.instagram_account_id == selected_ig.id)
    recent_jobs = (
        db.execute(
            select(PostJob)
            .join(ContentUnit, ContentUnit.id == PostJob.content_unit_id)
            .where(and_(*jobs_filters))
            .order_by(PostJob.updated_at.desc())
            .limit(40)
        )
        .scalars()
        .all()
    )

    comment_rules: list[Any] = []
    recent_comment_events: list[Any] = []
    recent_reply_jobs: list[Any] = []
    recent_qa_rows: list[dict[str, str | None]] = []
    instagram_engagement_available = True
    instagram_engagement_error = ""
    if selected_ig:
        try:
            comment_rules = list_comment_rules(db, instagram_account_id=selected_ig.id)
            recent_comment_events = [
                item
                for item in list_comment_events(db, limit=50)
                if item.instagram_account_id == selected_ig.id
            ][:20]
            recent_reply_jobs = [
                item
                for item in list_reply_jobs(db, limit=50)
                if item.instagram_account_id == selected_ig.id
            ][:20]
            if recent_comment_events:
                reply_by_event = {job.comment_event_id: job for job in recent_reply_jobs}
                for event in recent_comment_events:
                    matched = reply_by_event.get(event.id)
                    recent_qa_rows.append(
                        {
                            "question": event.comment_text or "",
                            "answer": (matched.reply_text if matched else "-") or "-",
                            "status": (matched.status.value if matched else event.status.value),
                            "created_at": (
                                matched.created_at.isoformat()
                                if matched and matched.created_at
                                else (event.created_at.isoformat() if event.created_at else "")
                            ),
                        }
                    )
        except Exception:  # noqa: BLE001
            instagram_engagement_available = False
            instagram_engagement_error = (
                "인스타 댓글 기능 초기화가 필요합니다. DB 마이그레이션 후 사용하세요."
            )

    recent_threads_comment_events: list[Any] = []
    recent_threads_reply_jobs: list[Any] = []
    recent_threads_qa_rows: list[dict[str, str | None]] = []
    threads_engagement_available = True
    threads_engagement_error = ""
    try:
        recent_threads_comment_events = [
            item
            for item in list_threads_comment_events(db, limit=100)
            if item.threads_account_id == threads_account.id
        ][:20]
        recent_threads_reply_jobs = [
            item
            for item in list_threads_reply_jobs(db, limit=100)
            if item.threads_account_id == threads_account.id
        ][:20]
        if recent_threads_comment_events:
            threads_reply_by_event = {job.comment_event_id: job for job in recent_threads_reply_jobs}
            for event in recent_threads_comment_events:
                matched = threads_reply_by_event.get(event.id)
                recent_threads_qa_rows.append(
                    {
                        "question": event.reply_text or "",
                        "answer": (matched.reply_text if matched else "-") or "-",
                        "status": (matched.status.value if matched else event.status.value),
                        "created_at": (
                            matched.created_at.isoformat()
                            if matched and matched.created_at
                            else (event.created_at.isoformat() if event.created_at else "")
                        ),
                    }
                )
    except Exception:  # noqa: BLE001
        threads_engagement_available = False
        threads_engagement_error = "스레드 댓글 기능 초기화가 필요합니다. DB 마이그레이션 후 사용하세요."
    try:
        prompt_settings = get_vertical_prompt_settings(db)
    except Exception:  # noqa: BLE001
        prompt_settings = {
            "COUPANG": "",
            "SAJU": "",
        }

    saju_form = {
        "year": (saju_year or "").strip(),
        "month": (saju_month or "").strip(),
        "day": (saju_day or "").strip(),
        "hour": (saju_hour or "").strip(),
        "minute": (saju_minute or "").strip(),
        "gender": (saju_gender or "").strip(),
        "calendar": "lunar" if (saju_calendar or "").strip().lower() == "lunar" else "solar",
        "leap_month": _flag(saju_leap_month),
        "question": (saju_question or "").strip(),
    }
    saju_preview: dict[str, Any] | None = None
    saju_preview_error = ""
    if saju_run is not None:
        birth = BirthInfoPartial(
            year=_optional_int(saju_form["year"]),
            month=_optional_int(saju_form["month"]),
            day=_optional_int(saju_form["day"]),
            hour=_optional_int(saju_form["hour"]),
            minute=_optional_int(saju_form["minute"]) or 0,
            gender=normalize_gender(saju_form["gender"]),
            is_lunar=saju_form["calendar"] == "lunar",
            is_leap_month=saju_form["leap_month"],
        )
        missing = list_missing_birth_fields(birth)
        if missing:
            saju_preview_error = f"{', '.join(missing)} 입력이 필요합니다."
        else:
            try:
                pillars = calculate_four_pillars(birth)
                topic = infer_saju_topic(saju_form["question"])
                one_line = build_saju_topic_fallback(topic, pillars.korean_string())
                pillar_cells = [
                    {"label": "시", "kor": pillars.hour, "hanja": pillars.hour_hanja, "known": pillars.hour_known},
                    {"label": "일", "kor": pillars.day, "hanja": pillars.day_hanja, "known": True},
                    {"label": "월", "kor": pillars.month, "hanja": pillars.month_hanja, "known": True},
                    {"label": "년", "kor": pillars.year, "hanja": pillars.year_hanja, "known": True},
                ]
                saju_preview = {
                    "topic": topic,
                    "birth_summary": summarize_birth_info(birth),
                    "pillars_kor": pillars.korean_string(),
                    "pillars_hanja": pillars.hanja_string(),
                    "pillar_cells": pillar_cells,
                    "details": build_four_pillars_details(pillars),
                    "one_line": one_line,
                }
            except Exception as exc:  # noqa: BLE001
                saju_preview_error = f"만세력 계산 실패: {str(exc)[:120]}"

    return templates.TemplateResponse(
        request,
        "app_workspace.html",
        {
            "flash": flash,
            "today": target_date,
            "user": user,
            "threads_account": threads_account,
            "ig_accounts": ig_accounts,
            "selected_ig": selected_ig,
            "threads_pending_units": threads_pending_units,
            "instagram_pending_units": instagram_pending_units,
            "threads_pending_count": int(threads_pending_count),
            "instagram_pending_count": int(instagram_pending_count),
            "threads_approved_count": int(threads_approved_count),
            "instagram_approved_count": int(instagram_approved_count),
            "recent_jobs": recent_jobs,
            "comment_rules": comment_rules,
            "recent_comment_events": recent_comment_events,
            "recent_reply_jobs": recent_reply_jobs,
            "recent_qa_rows": recent_qa_rows,
            "instagram_engagement_available": instagram_engagement_available,
            "instagram_engagement_error": instagram_engagement_error,
            "recent_threads_comment_events": recent_threads_comment_events,
            "recent_threads_reply_jobs": recent_threads_reply_jobs,
            "recent_threads_qa_rows": recent_threads_qa_rows,
            "threads_engagement_available": threads_engagement_available,
            "threads_engagement_error": threads_engagement_error,
            "preview_map": preview_map,
            "scheduled_display_map": scheduled_display_map,
            "brand_profiles": brand_profiles,
            "prompt_settings": prompt_settings,
            "threads_comment_style_prompt": threads_comment_style_prompt,
            "threads_comment_profile_name": threads_comment_profile_name,
            "saju_preview_form": saju_form,
            "saju_preview": saju_preview,
            "saju_preview_error": saju_preview_error,
            "show_dispatch_test": settings.run_mode != "live",
        },
    )


@router.get("/local-assets/{content_unit_id}/{file_name}")
def serve_local_asset(content_unit_id: str, file_name: str):
    settings = get_settings()
    root = Path(settings.local_asset_dir).expanduser().resolve()
    target = (root / content_unit_id / file_name).resolve()
    if root not in target.parents:
        raise HTTPException(status_code=404, detail="asset not found")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type)


@router.post("/app/actions/generate")
def web_generate_today(
    request: Request,
    biz_date: date | None = Form(default=None),
    unit_count: int = Form(default=3),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    result = generate_today_content_units(db, target_date, max(2, min(3, unit_count)))
    return RedirectResponse(f"/app?flash=생성완료:{result['created_count']}건", status_code=303)


@router.post("/app/actions/schedule")
def web_schedule_today(
    request: Request,
    biz_date: date | None = Form(default=None),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    result = schedule_today_jobs(db, target_date)
    return RedirectResponse(f"/app?flash=스케줄완료:{result['created_jobs']}개job", status_code=303)


@router.post("/app/actions/bootstrap")
def web_bootstrap(
    request: Request,
    biz_date: date | None = Form(default=None),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    result = run_daily_bootstrap(db, target_date)
    return RedirectResponse(
        f"/app?flash=부트스트랩완료:queue={result['queue']['enqueued_jobs']}",
        status_code=303,
    )


@router.post("/app/actions/dispatch")
def web_dispatch_due(
    request: Request,
    limit: int = Form(default=20),
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    result = dispatch_due_jobs_local(db, limit=max(1, min(limit, 100)))
    target = _safe_return_to(return_to, "/app")
    joiner = "&" if "?" in target else "?"
    return RedirectResponse(f"{target}{joiner}flash=디스패치완료:{result['dispatched']}건", status_code=303)


@router.post("/app/actions/trend-sync")
def web_trend_sync(request: Request, db: Session = Depends(get_db)):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    return RedirectResponse("/app?flash=네이버트렌드기능은_배포전_제거되었습니다.", status_code=303)


@router.post("/app/actions/improve-daily")
def web_improve_daily(request: Request, db: Session = Depends(get_db)):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    result = run_daily_improvement(db)
    return RedirectResponse(f"/app?flash=일간개선:{result['status']}", status_code=303)


@router.post("/app/actions/improve-weekly")
def web_improve_weekly(request: Request, db: Session = Depends(get_db)):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    result = run_weekly_improvement(db)
    return RedirectResponse(f"/app?flash=주간개선:{result['status']}", status_code=303)


@router.post("/app/actions/add-threads-account")
def web_add_threads_account(
    request: Request,
    name: str = Form(...),
    threads_user_id: str = Form(...),
    access_token: str = Form(...),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    payload = ThreadsAccountCreate(
        name=name.strip(),
        threads_user_id=threads_user_id.strip(),
        access_token=access_token.strip(),
    )
    upsert_threads_account(db, payload)
    return RedirectResponse("/app?flash=Threads계정등록완료", status_code=303)


@router.post("/app/actions/add-instagram-account")
def web_add_instagram_account(
    request: Request,
    name: str = Form(...),
    ig_user_id: str = Form(...),
    access_token: str = Form(...),
    brand_vertical: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    payload = InstagramAccountCreate(
        name=name.strip(),
        ig_user_id=ig_user_id.strip(),
        access_token=access_token.strip(),
        brand_vertical=BrandVertical(brand_vertical) if brand_vertical.strip() else None,
    )
    upsert_instagram_account(db, payload)
    return RedirectResponse("/app?flash=Instagram계정등록완료", status_code=303)


@router.post("/app/accounts/{threads_account_id}/generate-keywords")
def web_generate_by_keywords(
    threads_account_id: UUID,
    request: Request,
    ig_account_id: UUID | None = Form(default=None),
    biz_date: date | None = Form(default=None),
    keywords: str = Form(...),
    start_hour: int = Form(default=9),
    end_hour: int = Form(default=22),
    vertical_mode: str = Form(default="COUPANG"),
    tone_style: str = Form(default="CASUAL"),
    emoji_mode: str = Form(default="ON"),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    parsed_keywords = _normalize_keywords(keywords)
    if not parsed_keywords:
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash="키워드를_1개_이상_입력해주세요.(최대10개)",
            ),
            status_code=303,
        )

    try:
        result = generate_content_units_for_keywords(
            db,
            biz_date=target_date,
            threads_account_id=threads_account_id,
            instagram_account_id=ig_account_id,
            keywords=parsed_keywords,
            start_hour=start_hour,
            end_hour=end_hour,
            vertical_mode=vertical_mode,
            tone_style=tone_style,
            emoji_mode=emoji_mode,
            create_instagram=False,
        )
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash=(
                    f"스레드생성완료:{result['created_count']}건"
                    f"|모드={result['vertical_mode']}"
                    f"|말투={result['tone_style']}"
                    f"|이모지={result['emoji_mode']}"
                ),
            ),
            status_code=303,
        )
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash=f"생성실패:{_short_error_message(exc)}",
            ),
            status_code=303,
        )


@router.post("/app/accounts/{threads_account_id}/cards/create-manual")
def web_create_manual_cardnews(
    threads_account_id: UUID,
    request: Request,
    ig_account_id: UUID = Form(...),
    biz_date: date | None = Form(default=None),
    topic: str = Form(...),
    memo: str = Form(default=""),
    vertical_mode: str = Form(default="COUPANG"),
    coupang_url: str = Form(default=""),
    slide_count: int = Form(default=5),
    start_hour: int = Form(default=9),
    end_hour: int = Form(default=22),
    background_mode: str = Form(default="google_free"),
    template_style: str = Form(default="campaign"),
    font_style: str = Form(default="sans"),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    try:
        result = create_instagram_content_unit_manual(
            db,
            biz_date=target_date,
            threads_account_id=threads_account_id,
            instagram_account_id=ig_account_id,
            topic=topic,
            memo=memo,
            vertical_mode=vertical_mode,
            coupang_url=coupang_url,
            slide_count=slide_count,
            start_hour=start_hour,
            end_hour=end_hour,
            background_mode=background_mode,
            template_style=template_style,
            font_style=font_style,
        )
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash=(
                    f"카드뉴스초안생성완료:{result['content_unit_id']}"
                    f"|슬라이드={result['slide_count']}"
                ),
            ),
            status_code=303,
        )
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash=f"카드뉴스생성실패:{_short_error_message(exc)}",
            ),
            status_code=303,
        )


@router.post("/app/accounts/{threads_account_id}/threads/publish-manual")
async def web_publish_manual_threads(
    threads_account_id: UUID,
    request: Request,
    post_text: str = Form(...),
    first_reply: str = Form(default=""),
    image_file: UploadFile | None = File(default=None),
    ig_account_id: UUID | None = Form(default=None),
    biz_date: date | None = Form(default=None),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    account = db.get(ThreadsAccount, threads_account_id)
    if not account or account.status != AccountStatus.ACTIVE:
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash="수동게시실패:활성_Threads_계정을_찾을_수_없습니다.",
            ),
            status_code=303,
        )

    clean_text = post_text.strip()
    if not clean_text:
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash="수동게시실패:게시본문을_입력해주세요.",
            ),
            status_code=303,
        )

    image_url: str | None = None
    if image_file is not None and (image_file.filename or "").strip():
        suffix = Path(image_file.filename or "").suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            return RedirectResponse(
                _workspace_url(
                    threads_account_id,
                    ig_account_id=ig_account_id,
                    biz_date=target_date,
                    flash="수동게시실패:이미지는_jpg/jpeg/png/webp만_지원합니다.",
                ),
                status_code=303,
            )
        payload = await image_file.read()
        if not payload:
            return RedirectResponse(
                _workspace_url(
                    threads_account_id,
                    ig_account_id=ig_account_id,
                    biz_date=target_date,
                    flash="수동게시실패:이미지_파일이_비어있습니다.",
                ),
                status_code=303,
            )

        folder_id = f"threads_manual_{uuid4().hex[:16]}"
        file_name = f"upload{suffix}"
        uri = save_uploaded_file(
            folder_id=folder_id,
            file_name=file_name,
            file_bytes=payload,
            content_type=image_file.content_type,
        )
        image_url = _to_absolute_public_url(asset_public_url(uri))

    try:
        result = publish_threads_manual_post(
            account=account,
            text=clean_text,
            reply_text=first_reply.strip(),
            image_url=image_url,
        )
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash=(
                    f"수동게시완료:post={result.post_id}"
                    f"|reply={'Y' if result.reply_post_id else 'N'}"
                ),
            ),
            status_code=303,
        )
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash=f"수동게시실패:{_short_error_message(exc)}",
            ),
            status_code=303,
        )


@router.post("/app/accounts/{threads_account_id}/prompts/save")
def web_save_vertical_prompts(
    threads_account_id: UUID,
    request: Request,
    ig_account_id: UUID | None = Form(default=None),
    biz_date: date | None = Form(default=None),
    coupang_prompt: str = Form(default=""),
    saju_prompt: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    try:
        save_vertical_prompt_settings(
            db,
            coupang_prompt=coupang_prompt,
            saju_prompt=saju_prompt,
        )
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash="쿠팡/사주프롬프트저장완료",
            ),
            status_code=303,
        )
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash=f"프롬프트저장실패:{_short_error_message(exc)}",
            ),
            status_code=303,
        )


@router.post("/app/accounts/{threads_account_id}/threads/comment-style/save")
def web_save_threads_comment_style_prompt(
    threads_account_id: UUID,
    request: Request,
    ig_account_id: UUID | None = Form(default=None),
    biz_date: date | None = Form(default=None),
    comment_style_prompt: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    account = db.get(ThreadsAccount, threads_account_id)
    if not account:
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash="Threads계정을찾을수없습니다",
            ),
            status_code=303,
        )

    try:
        profile = _ensure_threads_comment_profile(db, account)
        profile.comment_style_prompt = comment_style_prompt.strip()
        db.commit()
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash="스레드댓글AI프롬프트저장완료",
            ),
            status_code=303,
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash=f"댓글AI프롬프트저장실패:{_short_error_message(exc)}",
            ),
            status_code=303,
        )


@router.post("/app/accounts/{threads_account_id}/schedule-approved")
def web_schedule_account_approved(
    threads_account_id: UUID,
    request: Request,
    ig_account_id: UUID = Form(...),
    biz_date: date | None = Form(default=None),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    try:
        result = schedule_today_jobs(
            db,
            target_date,
            threads_account_id=threads_account_id,
            instagram_account_id=ig_account_id,
        )
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash=f"예약생성완료:{result['created_jobs']}jobs",
            ),
            status_code=303,
        )
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash=f"예약생성실패:{str(exc)}",
            ),
            status_code=303,
        )


@router.post("/app/accounts/{threads_account_id}/schedule-approved-threads")
def web_schedule_threads_only(
    threads_account_id: UUID,
    request: Request,
    biz_date: date | None = Form(default=None),
    ig_account_id: UUID | None = Form(default=None),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    try:
        unit_ids = [
            row[0]
            for row in db.execute(
                select(ContentUnit.id).where(
                    and_(
                        ContentUnit.biz_date == target_date,
                        ContentUnit.threads_account_id == threads_account_id,
                        ContentUnit.generation_status == ContentStatus.READY,
                        ContentUnit.guardrail_passed.is_(True),
                        ContentUnit.threads_review_status == ReviewStatus.APPROVED.value,
                    )
                )
            ).all()
        ]
        result = schedule_today_jobs(
            db,
            target_date,
            threads_account_id=threads_account_id,
            content_unit_ids=unit_ids,
        )
        flash = f"스레드예약완료:{result['created_jobs']}jobs"
    except Exception as exc:  # noqa: BLE001
        flash = f"스레드예약실패:{_short_error_message(exc)}"
    return RedirectResponse(
        _workspace_url(
            threads_account_id,
            ig_account_id=ig_account_id,
            biz_date=target_date,
            flash=flash,
        ),
        status_code=303,
    )


@router.post("/app/accounts/{threads_account_id}/schedule-approved-instagram")
def web_schedule_instagram_only(
    threads_account_id: UUID,
    request: Request,
    ig_account_id: UUID = Form(...),
    biz_date: date | None = Form(default=None),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    try:
        unit_ids = [
            row[0]
            for row in db.execute(
                select(ContentUnit.id).where(
                    and_(
                        ContentUnit.biz_date == target_date,
                        ContentUnit.threads_account_id == threads_account_id,
                        ContentUnit.instagram_account_id == ig_account_id,
                        ContentUnit.generation_status == ContentStatus.READY,
                        ContentUnit.guardrail_passed.is_(True),
                        ContentUnit.instagram_review_status == ReviewStatus.APPROVED.value,
                    )
                )
            ).all()
        ]
        result = schedule_today_jobs(
            db,
            target_date,
            threads_account_id=threads_account_id,
            instagram_account_id=ig_account_id,
            content_unit_ids=unit_ids,
        )
        flash = f"카드뉴스예약완료:{result['created_jobs']}jobs"
    except Exception as exc:  # noqa: BLE001
        flash = f"카드뉴스예약실패:{_short_error_message(exc)}"
    return RedirectResponse(
        _workspace_url(
            threads_account_id,
            ig_account_id=ig_account_id,
            biz_date=target_date,
            flash=flash,
        ),
        status_code=303,
    )


@router.post("/app/accounts/{threads_account_id}/threads/comments/process")
def web_process_threads_comments(
    threads_account_id: UUID,
    request: Request,
    ig_account_id: UUID | None = Form(default=None),
    biz_date: date | None = Form(default=None),
    limit_posts_per_account: int = Form(default=20),
    limit_comments_per_post: int = Form(default=50),
    limit_events: int = Form(default=100),
    limit_jobs: int = Form(default=100),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    try:
        ingest_result = ingest_threads_comment_events_polling(
            db,
            limit_posts_per_account=max(1, min(limit_posts_per_account, 50)),
            limit_comments_per_post=max(1, min(limit_comments_per_post, 100)),
            threads_account_id=threads_account_id,
        )
        queue_result = create_threads_reply_jobs_for_pending_events(
            db,
            limit=max(1, min(limit_events, 500)),
            threads_account_id=threads_account_id,
        )
        send_result = process_pending_threads_reply_jobs(
            db,
            limit=max(1, min(limit_jobs, 500)),
            threads_account_id=threads_account_id,
        )
        flash = (
            "스레드댓글처리완료"
            f"|events={ingest_result.get('created_events', 0)}"
            f"|jobs={queue_result.get('created_jobs', 0)}"
            f"|sent={send_result.get('sent', 0)}"
            f"|failed={send_result.get('failed', 0)}"
        )
    except Exception as exc:  # noqa: BLE001
        flash = f"스레드댓글처리실패:{_short_error_message(exc)}"

    return RedirectResponse(
        _workspace_url(
            threads_account_id,
            ig_account_id=ig_account_id,
            biz_date=target_date,
            flash=flash,
        ),
        status_code=303,
    )


@router.post("/app/accounts/{threads_account_id}/comment-rules/simple")
def web_add_simple_comment_rule(
    threads_account_id: UUID,
    request: Request,
    ig_account_id: UUID = Form(...),
    trigger_keyword: str = Form(...),
    ai_style_prompt: str = Form(default=""),
    message_template: str = Form(...),
    biz_date: date | None = Form(default=None),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    target_date = biz_date or kst_today()
    keyword = trigger_keyword.strip()

    try:
        trigger_type = CommentTriggerType.KEYWORD if keyword else CommentTriggerType.REGEX
        trigger_value = keyword if keyword else ".*"
        rule_name = f"자동응답-{keyword}" if keyword else "자동응답-전체"
        payload = CommentRuleCreateRequest(
            instagram_account_id=ig_account_id,
            brand_profile_id=None,
            name=rule_name,
            trigger_type=trigger_type,
            trigger_value=trigger_value,
            action_type=CommentActionType.PUBLIC_REPLY,
            ai_style_prompt=ai_style_prompt.strip(),
            message_template=message_template.strip(),
            priority=100,
            cooldown_minutes=60,
            active=True,
        )
        create_comment_rule(db, payload)
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash="댓글룰등록완료",
            ),
            status_code=303,
        )
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            _workspace_url(
                threads_account_id,
                ig_account_id=ig_account_id,
                biz_date=target_date,
                flash=f"댓글룰등록실패:{str(exc)}",
            ),
            status_code=303,
        )


@router.post("/app/actions/threads-accounts/{account_id}/profile")
def web_set_threads_account_profile(
    account_id: UUID,
    request: Request,
    brand_profile_id: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        set_threads_brand_profile(
            db,
            threads_account_id=account_id,
            brand_profile_id=UUID(brand_profile_id) if brand_profile_id.strip() else None,
        )
        return RedirectResponse("/app?flash=Threads계정용도설정완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/app?flash=Threads계정용도설정실패:{str(exc)}", status_code=303)


@router.post("/app/actions/instagram-accounts/{account_id}/profile")
def web_set_instagram_account_profile(
    account_id: UUID,
    request: Request,
    brand_profile_id: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        set_instagram_brand_profile(
            db,
            instagram_account_id=account_id,
            brand_profile_id=UUID(brand_profile_id) if brand_profile_id.strip() else None,
        )
        return RedirectResponse("/app?flash=Instagram계정용도설정완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/app?flash=Instagram계정용도설정실패:{str(exc)}", status_code=303)


@router.post("/app/actions/add-seed")
def web_add_seed(
    request: Request,
    topic: str = Form(...),
    category: str = Form(default=""),
    source_url: str = Form(default=""),
    source_type: str = Form(default="PRODUCT_URL"),
    priority: int = Form(default=50),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    clean_topic = topic.strip()
    if not clean_topic:
        return RedirectResponse("/app?flash=주제를 입력해주세요.", status_code=303)

    clean_category = category.strip() or "일반"
    clean_url = source_url.strip()
    if not clean_url:
        clean_url = f"https://www.coupang.com/np/search?q={quote_plus(clean_topic)}"

    inferred_type = SourceType.SEARCH_URL if "/np/search" in clean_url else SourceType.PRODUCT_URL
    try:
        selected_type = SourceType(source_type)
    except Exception:  # noqa: BLE001
        selected_type = inferred_type

    item = SeedItemIn(
        topic=clean_topic,
        category=clean_category,
        source_url=clean_url,
        source_type=selected_type,
        priority=max(1, min(priority, 100)),
        active=True,
    )
    stat = import_seed_items(db, [item])
    return RedirectResponse(
        f"/app?flash=Seed등록:{stat.inserted}insert/{stat.updated}update",
        status_code=303,
    )


@router.post("/app/actions/add-seed-quick")
def web_add_seed_quick(
    request: Request,
    keyword: str = Form(...),
    coupang_url: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    clean_keyword = keyword.strip()
    if not clean_keyword:
        return RedirectResponse("/app?flash=키워드를 입력해주세요.", status_code=303)

    clean_url = coupang_url.strip()
    if not clean_url:
        clean_url = f"https://www.coupang.com/np/search?q={quote_plus(clean_keyword)}"

    source_type = SourceType.SEARCH_URL if "/np/search" in clean_url else SourceType.PRODUCT_URL
    item = SeedItemIn(
        topic=f"{clean_keyword} 추천 가이드",
        category="일반",
        source_url=clean_url,
        source_type=source_type,
        priority=70,
        active=True,
    )
    stat = import_seed_items(db, [item])
    return RedirectResponse(
        f"/app?flash=간편주제저장완료:{stat.inserted}건",
        status_code=303,
    )


@router.post("/app/actions/add-brand-profile")
def web_add_brand_profile(
    request: Request,
    name: str = Form(...),
    vertical_type: str = Form(...),
    comment_style_prompt: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        payload = BrandProfileCreateRequest(
            name=name.strip(),
            vertical_type=BrandVertical(vertical_type),
            comment_style_prompt=comment_style_prompt.strip(),
        )
        create_brand_profile(db, payload)
        return RedirectResponse("/app?flash=브랜드프로필등록완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/app?flash=브랜드프로필등록실패:{str(exc)}", status_code=303)


@router.post("/app/actions/add-comment-rule")
def web_add_comment_rule(
    request: Request,
    instagram_account_id: str = Form(...),
    brand_profile_id: str = Form(default=""),
    name: str = Form(...),
    trigger_type: str = Form(...),
    trigger_value: str = Form(...),
    action_type: str = Form(...),
    ai_style_prompt: str = Form(default=""),
    message_template: str = Form(...),
    priority: int = Form(default=100),
    cooldown_minutes: int = Form(default=60),
    active: bool = Form(default=False),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        payload = CommentRuleCreateRequest(
            instagram_account_id=UUID(instagram_account_id),
            brand_profile_id=UUID(brand_profile_id) if brand_profile_id.strip() else None,
            name=name.strip(),
            trigger_type=trigger_type,
            trigger_value=trigger_value.strip(),
            action_type=action_type,
            ai_style_prompt=ai_style_prompt.strip(),
            message_template=message_template.strip(),
            priority=max(1, min(priority, 1000)),
            cooldown_minutes=max(0, min(cooldown_minutes, 1440)),
            active=active,
        )
        create_comment_rule(db, payload)
        return RedirectResponse("/app?flash=댓글룰등록완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/app?flash=댓글룰등록실패:{str(exc)}", status_code=303)


@router.post("/app/actions/comment-rules/{rule_id}/update")
def web_update_comment_rule(
    rule_id: UUID,
    request: Request,
    name: str = Form(...),
    trigger_type: str = Form(...),
    trigger_value: str = Form(...),
    action_type: str = Form(...),
    ai_style_prompt: str = Form(default=""),
    message_template: str = Form(...),
    priority: int = Form(default=100),
    cooldown_minutes: int = Form(default=60),
    active: bool = Form(default=False),
    brand_profile_id: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        payload = CommentRuleUpdateRequest(
            name=name.strip(),
            trigger_type=trigger_type,
            trigger_value=trigger_value.strip(),
            action_type=action_type,
            ai_style_prompt=ai_style_prompt.strip(),
            message_template=message_template.strip(),
            priority=max(1, min(priority, 1000)),
            cooldown_minutes=max(0, min(cooldown_minutes, 1440)),
            active=active,
            brand_profile_id=UUID(brand_profile_id) if brand_profile_id.strip() else None,
        )
        update_comment_rule(db, rule_id, payload)
        return RedirectResponse("/app?flash=댓글룰수정완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/app?flash=댓글룰수정실패:{str(exc)}", status_code=303)


@router.post("/app/actions/comment-rules/{rule_id}/toggle")
def web_toggle_comment_rule(
    rule_id: UUID,
    request: Request,
    active: bool = Form(default=False),
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        set_comment_rule_active(db, rule_id, active=active)
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=댓글룰상태변경완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=댓글룰상태변경실패:{str(exc)}", status_code=303)


@router.post("/app/actions/comment-rules/{rule_id}/delete")
def web_delete_comment_rule(
    rule_id: UUID,
    request: Request,
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        delete_comment_rule(db, rule_id)
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=댓글룰삭제완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=댓글룰삭제실패:{str(exc)}", status_code=303)


@router.post("/app/actions/engagement-process")
def web_engagement_process(
    request: Request,
    limit_events: int = Form(default=100),
    limit_jobs: int = Form(default=100),
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        queue_result = create_reply_jobs_for_pending_events(db, limit=max(1, min(limit_events, 500)))
        send_result = process_pending_reply_jobs(db, limit=max(1, min(limit_jobs, 500)))
        flash = (
            "댓글자동화실행완료"
            f"|jobs={queue_result.get('created_jobs', 0)}"
            f"|sent={send_result.get('sent', 0)}"
            f"|failed={send_result.get('failed', 0)}"
        )
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash={flash}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=댓글자동화실패:{str(exc)}", status_code=303)


@router.post("/app/actions/reply-jobs/{reply_job_id}/retry")
def web_retry_reply_job(
    reply_job_id: UUID,
    request: Request,
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        retry_reply_job(db, reply_job_id)
        send_result = process_pending_reply_jobs(db, limit=20)
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=댓글응답재처리요청완료:sent={send_result.get('sent', 0)}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=댓글응답재처리실패:{str(exc)}", status_code=303)


@router.post("/app/actions/jobs/{job_id}/retry")
def web_retry_publish_job(
    job_id: int,
    request: Request,
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        job = retry_job(db, job_id)
        enqueue_job_by_id(db, job.id)
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=발행잡재처리큐등록:{job.id}", status_code=303)
    except RetryNotAllowedError as exc:
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=재처리불가:{str(exc)}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=발행잡재처리실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/approve")
def web_approve_content(
    content_unit_id: UUID,
    request: Request,
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user

    try:
        result = approve_and_prepare_publish(db, content_unit_id, reviewer_id=user.id)
        schedule = result.get("schedule_result") or {}
        enqueue = result.get("enqueue_result") or {}
        warnings = result.get("warnings") or []

        flash = (
            "콘텐츠 승인 완료"
            f" | schedule_jobs={schedule.get('created_jobs', 0)}"
            f" | enqueued={enqueue.get('enqueued_jobs', 0)}"
        )
        if warnings:
            flash += f" | warning={';'.join(warnings)}"

        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash={flash}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=승인실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/approve-threads")
def web_approve_content_threads(
    content_unit_id: UUID,
    request: Request,
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user

    try:
        result = approve_channel_and_prepare_publish(
            db,
            content_unit_id,
            channel=ChannelType.THREADS,
            reviewer_id=user.id,
        )
        schedule = result.get("schedule_result") or {}
        enqueue = result.get("enqueue_result") or {}
        flash = (
            "스레드 승인 완료"
            f" | schedule_jobs={schedule.get('created_jobs', 0)}"
            f" | enqueued={enqueue.get('enqueued_jobs', 0)}"
        )
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash={flash}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=스레드승인실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/publish-now-threads")
def web_publish_content_threads_now(
    content_unit_id: UUID,
    request: Request,
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user

    try:
        result = approve_channel_and_prepare_publish(
            db,
            content_unit_id,
            channel=ChannelType.THREADS,
            reviewer_id=user.id,
        )
        warnings = result.get("warnings") or []

        job = (
            db.execute(
                select(PostJob).where(
                    PostJob.content_unit_id == content_unit_id,
                    PostJob.channel == ChannelType.THREADS,
                    PostJob.job_type == JobType.THREADS_ROOT,
                ).order_by(PostJob.id.desc())
            )
            .scalars()
            .first()
        )
        if not job:
            raise ValueError("스레드 발행 잡을 찾을 수 없습니다.")

        if job.status == JobStatus.SUCCESS:
            flash = f"스레드 바로올리기:이미발행완료(job={job.id})"
        elif job.status == JobStatus.RUNNING:
            flash = f"스레드 바로올리기:현재발행중(job={job.id})"
        else:
            now_utc = datetime.now(timezone.utc)
            job.scheduled_at = now_utc
            job.next_retry_at = None
            job.cloud_task_name = None
            job.last_error_code = None
            job.last_error_message = None
            job.started_at = None
            job.finished_at = None
            job.attempts = 0
            job.status = JobStatus.PENDING
            db.commit()
            enqueue_job_by_id(db, job.id)
            flash = f"스레드 바로올리기큐등록(job={job.id})"

        if warnings:
            flash += f"|warning={';'.join(warnings)}"

        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash={flash}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=스레드바로올리기실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/approve-instagram")
def web_approve_content_instagram(
    content_unit_id: UUID,
    request: Request,
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user

    try:
        result = approve_channel_and_prepare_publish(
            db,
            content_unit_id,
            channel=ChannelType.INSTAGRAM,
            reviewer_id=user.id,
        )
        schedule = result.get("schedule_result") or {}
        enqueue = result.get("enqueue_result") or {}
        flash = (
            "카드뉴스 승인 완료"
            f" | schedule_jobs={schedule.get('created_jobs', 0)}"
            f" | enqueued={enqueue.get('enqueued_jobs', 0)}"
        )
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash={flash}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=카드뉴스승인실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/reject")
def web_reject_content(
    content_unit_id: UUID,
    request: Request,
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user

    try:
        reject_content_unit(db, content_unit_id, reviewer_id=user.id)
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=콘텐츠반려완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=반려실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/reject-threads")
def web_reject_content_threads(
    content_unit_id: UUID,
    request: Request,
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user

    try:
        reject_content_channel(
            db,
            content_unit_id,
            channel=ChannelType.THREADS,
            reviewer_id=user.id,
        )
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=스레드반려완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=스레드반려실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/reject-instagram")
def web_reject_content_instagram(
    content_unit_id: UUID,
    request: Request,
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user

    try:
        reject_content_channel(
            db,
            content_unit_id,
            channel=ChannelType.INSTAGRAM,
            reviewer_id=user.id,
        )
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=카드뉴스반려완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=카드뉴스반려실패:{str(exc)}", status_code=303)


@router.post("/app/accounts/{threads_account_id}/approve-all")
def web_approve_all_for_channel(
    threads_account_id: UUID,
    request: Request,
    ig_account_id: UUID | None = Form(default=None),
    biz_date: date | None = Form(default=None),
    channel: str = Form(...),
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user
    target_date = biz_date or kst_today()

    channel_key = channel.strip().upper()
    if channel_key not in {"THREADS", "INSTAGRAM"}:
        target = _safe_return_to(return_to, _workspace_url(threads_account_id, ig_account_id=ig_account_id, biz_date=target_date))
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=지원하지않는채널", status_code=303)
    if channel_key == "INSTAGRAM" and ig_account_id is None:
        target = _safe_return_to(return_to, _workspace_url(threads_account_id, biz_date=target_date))
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=카드뉴스채널은_IG계정선택이필요합니다", status_code=303)

    try:
        updated_total = 0
        unit_ids: list[UUID] = []
        channel_plan = [ChannelType(channel_key)]
        for one in channel_plan:
            updated = approve_all_pending_for_channel(
                db,
                biz_date=target_date,
                threads_account_id=threads_account_id,
                instagram_account_id=ig_account_id,
                channel=one,
                reviewer_id=user.id,
            )
            updated_total += int(updated.get("updated", 0))
            unit_ids.extend(updated.get("content_unit_ids", []))

        schedule_result = schedule_today_jobs(
            db,
            target_date,
            threads_account_id=threads_account_id,
            instagram_account_id=ig_account_id,
            content_unit_ids=list({uid for uid in unit_ids}),
        )
        enqueue_result = enqueue_pending_jobs_for_units(db, list({uid for uid in unit_ids})) if unit_ids else {"enqueued_jobs": 0}

        target = _safe_return_to(
            return_to,
            _workspace_url(threads_account_id, ig_account_id=ig_account_id, biz_date=target_date),
        )
        joiner = "&" if "?" in target else "?"
        flash = (
            f"일괄승인완료:{updated_total}건"
            f"|schedule_jobs={schedule_result.get('created_jobs', 0)}"
            f"|enqueued={enqueue_result.get('enqueued_jobs', 0)}"
        )
        return RedirectResponse(f"{target}{joiner}flash={flash}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(
            return_to,
            _workspace_url(threads_account_id, ig_account_id=ig_account_id, biz_date=target_date),
        )
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=일괄승인실패:{str(exc)}", status_code=303)


@router.post("/app/accounts/{threads_account_id}/reject-all")
def web_reject_all_for_channel(
    threads_account_id: UUID,
    request: Request,
    ig_account_id: UUID | None = Form(default=None),
    biz_date: date | None = Form(default=None),
    channel: str = Form(...),
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user
    target_date = biz_date or kst_today()

    channel_key = channel.strip().upper()
    if channel_key not in {"THREADS", "INSTAGRAM"}:
        target = _safe_return_to(return_to, _workspace_url(threads_account_id, ig_account_id=ig_account_id, biz_date=target_date))
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=지원하지않는채널", status_code=303)
    if channel_key == "INSTAGRAM" and ig_account_id is None:
        target = _safe_return_to(return_to, _workspace_url(threads_account_id, biz_date=target_date))
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=카드뉴스채널은_IG계정선택이필요합니다", status_code=303)

    try:
        updated = reject_all_pending_for_channel(
            db,
            biz_date=target_date,
            threads_account_id=threads_account_id,
            instagram_account_id=ig_account_id,
            channel=ChannelType(channel_key),
            reviewer_id=user.id,
        )
        target = _safe_return_to(
            return_to,
            _workspace_url(threads_account_id, ig_account_id=ig_account_id, biz_date=target_date),
        )
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=일괄반려완료:{int(updated.get('updated', 0))}건", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(
            return_to,
            _workspace_url(threads_account_id, ig_account_id=ig_account_id, biz_date=target_date),
        )
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=일괄반려실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/update-threads")
def web_update_threads_content(
    content_unit_id: UUID,
    request: Request,
    threads_body: str = Form(...),
    threads_first_reply: str = Form(...),
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        update_threads_copy(
            db,
            content_unit_id,
            threads_body=threads_body,
            threads_first_reply=threads_first_reply,
        )
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=스레드문구저장완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=스레드문구수정실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/update-instagram")
def web_update_instagram_content(
    content_unit_id: UUID,
    request: Request,
    instagram_caption: str = Form(...),
    slide_script_json: str = Form(default=""),
    font_style: str = Form(default=""),
    background_mode: str = Form(default=""),
    template_style: str = Form(default=""),
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        slide_script = None
        if slide_script_json.strip():
            parsed = json.loads(slide_script_json)
            if not isinstance(parsed, dict):
                raise ValueError("slide_script_json은 JSON object여야 합니다.")
            slide_script = parsed
        update_instagram_copy(
            db,
            content_unit_id,
            instagram_caption=instagram_caption,
            slide_script=slide_script,
            font_style=font_style.strip() or None,
            background_mode=background_mode.strip() or None,
            template_style=template_style.strip() or None,
        )
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=카드뉴스문구저장완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=카드뉴스문구수정실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/update")
def web_update_content(
    content_unit_id: UUID,
    request: Request,
    threads_body: str = Form(...),
    threads_first_reply: str = Form(...),
    instagram_caption: str = Form(...),
    slide_script_json: str = Form(default=""),
    font_style: str = Form(default=""),
    background_mode: str = Form(default=""),
    template_style: str = Form(default=""),
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        slide_script = None
        if slide_script_json.strip():
            parsed = json.loads(slide_script_json)
            if not isinstance(parsed, dict):
                raise ValueError("slide_script_json은 JSON object여야 합니다.")
            slide_script = parsed

        update_content_unit_copy(
            db,
            content_unit_id,
            threads_body=threads_body,
            threads_first_reply=threads_first_reply,
            instagram_caption=instagram_caption,
            slide_script=slide_script,
            font_style=font_style.strip() or None,
            background_mode=background_mode.strip() or None,
            template_style=template_style.strip() or None,
        )
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=문구저장완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=문구수정실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/render")
def web_render_content_assets(
    content_unit_id: UUID,
    request: Request,
    return_to: str = Form(default=""),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        assets = ensure_rendered_assets(db, str(content_unit_id))
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=카드뉴스렌더완료:{len(assets)}장", status_code=303)
    except Exception as exc:  # noqa: BLE001
        target = _safe_return_to(return_to, "/app")
        joiner = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{joiner}flash=카드뉴스렌더실패:{str(exc)}", status_code=303)
