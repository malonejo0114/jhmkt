from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import JobStatus, PostJob


class RetryNotAllowedError(ValueError):
    pass


def retry_job(db: Session, job_id: int) -> PostJob:
    job = db.get(PostJob, job_id)
    if not job:
        raise ValueError(f"job_id={job_id} 를 찾을 수 없습니다.")

    if job.status == JobStatus.SUCCESS:
        raise RetryNotAllowedError("성공한 job은 retry할 수 없습니다.")
    if job.status == JobStatus.RUNNING:
        raise RetryNotAllowedError("실행 중인 job은 retry할 수 없습니다.")

    job.status = JobStatus.PENDING
    job.next_retry_at = datetime.now(timezone.utc)
    job.last_error_code = None
    job.last_error_message = None
    job.cloud_task_name = None
    db.commit()
    db.refresh(job)
    return job
