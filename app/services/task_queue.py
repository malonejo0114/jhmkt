from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urljoin
from uuid import uuid4

from app.core.config import get_settings


def _cloud_tasks_client():
    from google.cloud import tasks_v2

    return tasks_v2.CloudTasksClient()


def enqueue_http_task(
    *,
    queue_name: str,
    relative_uri: str,
    payload: dict,
    schedule_at: datetime | None = None,
) -> str:
    settings = get_settings()

    if not settings.cloud_tasks_enabled:
        ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        return f"local-{queue_name}-{ts}-{uuid4().hex[:8]}"

    if not settings.cloud_tasks_project_id:
        raise ValueError("cloud_tasks_project_id 가 설정되지 않았습니다.")

    client = _cloud_tasks_client()
    parent = client.queue_path(
        settings.cloud_tasks_project_id,
        settings.cloud_tasks_location,
        queue_name,
    )

    url = urljoin(settings.queue_target_base_url.rstrip("/") + "/", relative_uri.lstrip("/"))
    body = json.dumps(payload).encode("utf-8")

    task: dict = {
        "http_request": {
            "http_method": "POST",
            "url": url,
            "headers": {"Content-Type": "application/json"},
            "body": body,
        }
    }

    if settings.internal_api_key:
        task["http_request"]["headers"]["X-Internal-Key"] = settings.internal_api_key

    if schedule_at:
        from google.protobuf import timestamp_pb2

        ts = timestamp_pb2.Timestamp()
        ts.FromDatetime(schedule_at.astimezone(timezone.utc))
        task["schedule_time"] = ts

    response = client.create_task(request={"parent": parent, "task": task})
    return response.name
