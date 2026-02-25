from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ChannelType
from app.schemas.internal import (
    DailyBootstrapRequest,
    DispatchDueJobsRequest,
    PublishTaskRequest,
    ThreadsInsightsTaskRequest,
)
from app.services.improvement_service import run_daily_improvement, run_weekly_improvement
from app.services.internal_auth import verify_internal_key
from app.services.job_execution_service import (
    dispatch_due_jobs_local,
    execute_publish_job,
    execute_threads_insights_task,
)
from app.services.job_orchestrator import run_daily_bootstrap

router = APIRouter(tags=["internal"], dependencies=[Depends(verify_internal_key)])


@router.post("/cron/daily-bootstrap")
def cron_daily_bootstrap(
    payload: DailyBootstrapRequest | None = Body(default=None),
    db: Session = Depends(get_db),
):
    try:
        result = run_daily_bootstrap(db, biz_date=payload.biz_date if payload else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "result": result}


@router.post("/cron/improve/daily")
def cron_improve_daily(db: Session = Depends(get_db)):
    result = run_daily_improvement(db)
    return {"status": "ok", "result": result}


@router.post("/cron/improve/weekly")
def cron_improve_weekly(db: Session = Depends(get_db)):
    result = run_weekly_improvement(db)
    return {"status": "ok", "result": result}


@router.post("/tasks/publish/threads")
def task_publish_threads(payload: PublishTaskRequest, db: Session = Depends(get_db)):
    try:
        result = execute_publish_job(db, payload.job_id, expected_channel=ChannelType.THREADS)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "result": result}


@router.post("/tasks/publish/instagram")
def task_publish_instagram(payload: PublishTaskRequest, db: Session = Depends(get_db)):
    try:
        result = execute_publish_job(db, payload.job_id, expected_channel=ChannelType.INSTAGRAM)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "result": result}


@router.post("/tasks/insights/threads")
def task_collect_threads_insights(payload: ThreadsInsightsTaskRequest, db: Session = Depends(get_db)):
    try:
        result = execute_threads_insights_task(db, payload.threads_post_id, payload.media_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "result": result}


@router.post("/tasks/local/dispatch-due")
def task_dispatch_due_local(payload: DispatchDueJobsRequest, db: Session = Depends(get_db)):
    result = dispatch_due_jobs_local(db, limit=payload.limit)
    return {"status": "ok", "result": result}
