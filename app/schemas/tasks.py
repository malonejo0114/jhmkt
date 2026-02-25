from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JobTaskPayload(BaseModel):
    job_id: int


class InsightsTaskPayload(BaseModel):
    threads_post_id: str
    media_id: str
    capture_at: datetime


class TaskEnqueueResult(BaseModel):
    queue: str
    task_name: str
    scheduled_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
