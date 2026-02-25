from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AppUser, ContentUnit, InstagramAccount, PostJob, SourceType, ThreadsAccount
from app.schemas.accounts import InstagramAccountCreate, ThreadsAccountCreate
from app.schemas.seeds import SeedItemIn
from app.services.accounts_service import upsert_instagram_account, upsert_threads_account
from app.services.auth_service import get_current_user
from app.services.dashboard_service import get_dashboard_last_7_days
from app.services.generation_service import generate_today_content_units
from app.services.improvement_service import run_daily_improvement, run_weekly_improvement
from app.services.job_execution_service import dispatch_due_jobs_local
from app.services.job_orchestrator import run_daily_bootstrap
from app.services.review_service import (
    approve_and_prepare_publish,
    list_review_queue,
    reject_content_unit,
    update_content_unit_copy,
)
from app.services.scheduler_service import schedule_today_jobs
from app.services.seeds_service import import_seed_items
from app.services.time_utils import kst_today
from app.services.trend_service import sync_naver_trend_keywords

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["web"])


def _require_user_or_redirect(request: Request, db: Session) -> AppUser | RedirectResponse:
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login?flash=로그인이 필요합니다.", status_code=303)
    return user


@router.get("/")
def landing_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/app", status_code=302)
    return templates.TemplateResponse(request, "landing.html", {})


@router.get("/web")
def legacy_web_redirect():
    return RedirectResponse("/app", status_code=302)


@router.get("/app")
def app_dashboard(request: Request, db: Session = Depends(get_db), flash: str | None = None):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user

    today = kst_today()
    dashboard = get_dashboard_last_7_days(db)

    today_units = (
        db.execute(select(ContentUnit).where(ContentUnit.biz_date == today).order_by(ContentUnit.slot_no.asc()))
        .scalars()
        .all()
    )
    today_jobs = (
        db.execute(
            select(PostJob)
            .join(ContentUnit, ContentUnit.id == PostJob.content_unit_id)
            .where(ContentUnit.biz_date == today)
        )
        .scalars()
        .all()
    )

    threads_accounts = db.execute(select(ThreadsAccount)).scalars().all()
    instagram_accounts = db.execute(select(InstagramAccount)).scalars().all()
    review_queue = list_review_queue(db, biz_date=today, limit=20)

    return templates.TemplateResponse(
        request,
        "app_dashboard.html",
        {
            "flash": flash,
            "today": today,
            "dashboard": dashboard,
            "today_units": today_units,
            "today_jobs": today_jobs,
            "threads_accounts": threads_accounts,
            "instagram_accounts": instagram_accounts,
            "user": user,
            "review_queue": review_queue,
        },
    )


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
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    result = dispatch_due_jobs_local(db, limit=max(1, min(limit, 100)))
    return RedirectResponse(f"/app?flash=디스패치완료:{result['dispatched']}건", status_code=303)


@router.post("/app/actions/trend-sync")
def web_trend_sync(request: Request, db: Session = Depends(get_db)):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        result = sync_naver_trend_keywords(db, kst_today())
        return RedirectResponse(
            f"/app?flash=트렌드동기화:{result.get('status')}:{result.get('imported', 0)}건",
            status_code=303,
        )
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/app?flash=트렌드동기화실패:{str(exc)}", status_code=303)


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
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    payload = InstagramAccountCreate(
        name=name.strip(),
        ig_user_id=ig_user_id.strip(),
        access_token=access_token.strip(),
    )
    upsert_instagram_account(db, payload)
    return RedirectResponse("/app?flash=Instagram계정등록완료", status_code=303)


@router.post("/app/actions/add-seed")
def web_add_seed(
    request: Request,
    topic: str = Form(...),
    category: str = Form(...),
    source_url: str = Form(...),
    source_type: str = Form(default="PRODUCT_URL"),
    priority: int = Form(default=50),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    item = SeedItemIn(
        topic=topic.strip(),
        category=category.strip(),
        source_url=source_url.strip(),
        source_type=SourceType(source_type),
        priority=max(1, min(priority, 100)),
        active=True,
    )
    stat = import_seed_items(db, [item])
    return RedirectResponse(
        f"/app?flash=Seed등록:{stat.inserted}insert/{stat.updated}update",
        status_code=303,
    )


@router.post("/app/actions/content/{content_unit_id}/approve")
def web_approve_content(content_unit_id: UUID, request: Request, db: Session = Depends(get_db)):
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

        return RedirectResponse(f"/app?flash={flash}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/app?flash=승인 실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/reject")
def web_reject_content(content_unit_id: UUID, request: Request, db: Session = Depends(get_db)):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user
    user = maybe_user

    try:
        reject_content_unit(db, content_unit_id, reviewer_id=user.id)
        return RedirectResponse("/app?flash=콘텐츠 반려 완료", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/app?flash=반려 실패:{str(exc)}", status_code=303)


@router.post("/app/actions/content/{content_unit_id}/update")
def web_update_content(
    content_unit_id: UUID,
    request: Request,
    threads_body: str = Form(...),
    threads_first_reply: str = Form(...),
    instagram_caption: str = Form(...),
    db: Session = Depends(get_db),
):
    maybe_user = _require_user_or_redirect(request, db)
    if isinstance(maybe_user, RedirectResponse):
        return maybe_user

    try:
        update_content_unit_copy(
            db,
            content_unit_id,
            threads_body=threads_body,
            threads_first_reply=threads_first_reply,
            instagram_caption=instagram_caption,
        )
        return RedirectResponse("/app?flash=콘텐츠 문구 수정 완료(검수대기)", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/app?flash=문구 수정 실패:{str(exc)}", status_code=303)
