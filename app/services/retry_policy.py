from __future__ import annotations

from datetime import datetime, timedelta, timezone

BACKOFF_SECONDS = [60, 180, 420, 900, 1800]


def backoff_seconds(attempt: int) -> int:
    # attempt starts at 1
    if attempt <= 0:
        return BACKOFF_SECONDS[0]
    if attempt > len(BACKOFF_SECONDS):
        return BACKOFF_SECONDS[-1]
    return BACKOFF_SECONDS[attempt - 1]


def next_retry_at(attempt: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds(attempt))


def is_retryable_http_status(status_code: int) -> bool:
    return status_code in {408, 409, 429, 500, 502, 503, 504}
