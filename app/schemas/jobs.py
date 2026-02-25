from pydantic import BaseModel


class RetryJobResponse(BaseModel):
    job_id: int
    status: str
    attempts: int
    next_retry_at: str
    task_name: str | None = None
