from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.accounts import (
    AccountCreateResponse,
    AccountOut,
    InstagramAccountCreate,
    ThreadsAccountCreate,
)
from app.schemas.dashboard import DashboardResponse
from app.schemas.generation import (
    EnqueueTodayRequest,
    EnqueueTodayResponse,
    GenerateTodayRequest,
    GenerateTodayResponse,
    ScheduleTodayRequest,
    ScheduleTodayResponse,
)
from app.schemas.jobs import RetryJobResponse
from app.schemas.review import ContentReviewActionResponse, ContentReviewUpdateRequest
from app.schemas.seeds import SeedImportJsonBody, SeedImportResponse
from app.schemas.trend import TrendSyncRequest, TrendSyncResponse
from app.services.accounts_service import upsert_instagram_account, upsert_threads_account
from app.services.dashboard_service import get_dashboard_last_7_days
from app.services.generation_service import generate_today_content_units
from app.services.job_execution_service import dispatch_due_jobs_local
from app.services.job_orchestrator import enqueue_job_by_id, enqueue_pending_jobs_for_date
from app.services.jobs_service import RetryNotAllowedError, retry_job
from app.services.scheduler_service import schedule_today_jobs
from app.services.seeds_service import import_seed_items, parse_seed_csv
from app.services.review_service import (
    approve_and_prepare_publish,
    list_review_queue,
    reject_content_unit,
    review_queue_summary,
    update_content_unit_copy,
)
from app.services.trend_service import sync_naver_trend_keywords
from app.services.time_utils import kst_today

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/accounts/threads", response_model=AccountCreateResponse, status_code=status.HTTP_201_CREATED)
def create_threads_account(payload: ThreadsAccountCreate, db: Session = Depends(get_db)):
    account = upsert_threads_account(db, payload)
    return AccountCreateResponse(
        account=AccountOut(
            id=account.id,
            name=account.name,
            external_user_id=account.threads_user_id,
            status=account.status,
        )
    )


@router.post("/accounts/instagram", response_model=AccountCreateResponse, status_code=status.HTTP_201_CREATED)
def create_instagram_account(payload: InstagramAccountCreate, db: Session = Depends(get_db)):
    account = upsert_instagram_account(db, payload)
    return AccountCreateResponse(
        account=AccountOut(
            id=account.id,
            name=account.name,
            external_user_id=account.ig_user_id,
            status=account.status,
        )
    )


@router.post("/seeds/import", response_model=SeedImportResponse)
async def import_seeds(
    request: Request,
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    content_type = request.headers.get("content-type", "")

    try:
        if "application/json" in content_type:
            raw = await request.json()
            body = SeedImportJsonBody.model_validate(raw)
            items = body.items
        elif file is not None:
            content = await file.read()
            items = parse_seed_csv(content)
        else:
            raise HTTPException(
                status_code=400,
                detail="application/json(body.items) 또는 multipart(file)로 요청해야 합니다.",
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stat = import_seed_items(db, items)
    return SeedImportResponse(inserted=stat.inserted, updated=stat.updated, errors=stat.errors)


@router.post("/generate/today", response_model=GenerateTodayResponse)
def generate_today(payload: GenerateTodayRequest, db: Session = Depends(get_db)):
    biz_date = payload.biz_date or kst_today()
    try:
        result = generate_today_content_units(db, biz_date=biz_date, unit_count=payload.unit_count)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return GenerateTodayResponse(**result)


@router.post("/schedule/today", response_model=ScheduleTodayResponse)
def schedule_today(payload: ScheduleTodayRequest, db: Session = Depends(get_db)):
    biz_date = payload.biz_date or kst_today()
    try:
        result = schedule_today_jobs(db, biz_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ScheduleTodayResponse(**result)


@router.post("/enqueue/today", response_model=EnqueueTodayResponse)
def enqueue_today(payload: EnqueueTodayRequest, db: Session = Depends(get_db)):
    biz_date = payload.biz_date or kst_today()
    try:
        result = enqueue_pending_jobs_for_date(db, biz_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EnqueueTodayResponse(**result)


@router.post("/dispatch/due")
def dispatch_due(limit: int = 20, db: Session = Depends(get_db)):
    result = dispatch_due_jobs_local(db, limit=max(1, min(limit, 200)))
    return {"result": result}


@router.post("/jobs/{job_id}/retry", response_model=RetryJobResponse)
def retry_job_by_id(job_id: int, db: Session = Depends(get_db)):
    try:
        job = retry_job(db, job_id)
    except RetryNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    task_name = enqueue_job_by_id(db, job.id)
    return RetryJobResponse(
        job_id=job.id,
        status=job.status.value,
        attempts=job.attempts,
        next_retry_at=job.next_retry_at.isoformat() if job.next_retry_at else datetime.utcnow().isoformat(),
        task_name=task_name,
    )


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)):
    data = get_dashboard_last_7_days(db)
    return DashboardResponse(**data)


@router.post("/trends/naver/sync", response_model=TrendSyncResponse)
def sync_naver_trends(payload: TrendSyncRequest, db: Session = Depends(get_db)):
    try:
        result = sync_naver_trend_keywords(db, payload.biz_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return TrendSyncResponse(**result)


@router.get("/review/queue")
def get_review_queue(biz_date: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    parsed_date = None
    if biz_date:
        try:
            parsed_date = datetime.fromisoformat(biz_date).date()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="biz_date는 YYYY-MM-DD 형식이어야 합니다.") from exc

    queue = list_review_queue(db, biz_date=parsed_date, limit=max(1, min(limit, 200)))
    return {"items": review_queue_summary(queue), "count": len(queue)}


@router.post("/content-units/{content_unit_id}/approve", response_model=ContentReviewActionResponse)
def approve_content(content_unit_id: UUID, db: Session = Depends(get_db)):
    try:
        result = approve_and_prepare_publish(db, content_unit_id)
        unit = result["content_unit"]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ContentReviewActionResponse(content_unit_id=str(unit.id), review_status=unit.review_status.value)


@router.post("/content-units/{content_unit_id}/reject", response_model=ContentReviewActionResponse)
def reject_content(content_unit_id: UUID, db: Session = Depends(get_db)):
    try:
        unit = reject_content_unit(db, content_unit_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ContentReviewActionResponse(content_unit_id=str(unit.id), review_status=unit.review_status.value)


@router.put("/content-units/{content_unit_id}", response_model=ContentReviewActionResponse)
def update_content(content_unit_id: UUID, payload: ContentReviewUpdateRequest, db: Session = Depends(get_db)):
    try:
        unit = update_content_unit_copy(
            db,
            content_unit_id,
            threads_body=payload.threads_body,
            threads_first_reply=payload.threads_first_reply,
            instagram_caption=payload.instagram_caption,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ContentReviewActionResponse(content_unit_id=str(unit.id), review_status=unit.review_status.value)
