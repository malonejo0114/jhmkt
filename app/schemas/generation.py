from datetime import date
from pydantic import BaseModel, Field


class GenerateTodayRequest(BaseModel):
    biz_date: date | None = None
    unit_count: int = Field(default=3, ge=2, le=3)


class GenerateTodayResponse(BaseModel):
    biz_date: date
    requested_count: int
    created_count: int
    skipped_count: int
    content_unit_ids: list[str]


class ScheduleTodayRequest(BaseModel):
    biz_date: date | None = None


class ScheduleTodayResponse(BaseModel):
    biz_date: date
    total_units: int
    scheduled_units: int
    created_jobs: int
    skipped_jobs: int


class EnqueueTodayRequest(BaseModel):
    biz_date: date | None = None


class EnqueueTodayResponse(BaseModel):
    biz_date: date
    pending_jobs: int
    enqueued_jobs: int
    skipped_jobs: int
