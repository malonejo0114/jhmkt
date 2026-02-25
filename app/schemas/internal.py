from datetime import date

from pydantic import BaseModel, Field


class DailyBootstrapRequest(BaseModel):
    biz_date: date | None = None


class PublishTaskRequest(BaseModel):
    job_id: int


class ThreadsInsightsTaskRequest(BaseModel):
    threads_post_id: str
    media_id: str


class DispatchDueJobsRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)
