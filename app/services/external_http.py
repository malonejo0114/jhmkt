from __future__ import annotations

from typing import Any

import httpx

from app.services.exceptions import PermanentPublishError, TransientPublishError
from app.services.retry_policy import is_retryable_http_status


DEFAULT_TIMEOUT = 20.0


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.request(method, url, headers=headers, params=params, json=json_body)
    except httpx.TimeoutException as exc:
        raise TransientPublishError(f"timeout: {url}", code="HTTP_TIMEOUT") from exc
    except httpx.TransportError as exc:
        raise TransientPublishError(f"transport_error: {url}", code="HTTP_TRANSPORT") from exc

    if 200 <= resp.status_code < 300:
        if not resp.text:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    detail = resp.text[:500]
    if is_retryable_http_status(resp.status_code):
        raise TransientPublishError(
            f"upstream_status={resp.status_code} body={detail}",
            code=f"HTTP_{resp.status_code}",
        )

    raise PermanentPublishError(
        f"upstream_status={resp.status_code} body={detail}",
        code=f"HTTP_{resp.status_code}",
    )
