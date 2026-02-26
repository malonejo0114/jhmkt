from __future__ import annotations

from fastapi import Header, HTTPException

from app.core.config import get_settings


def verify_internal_key(
    x_internal_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    settings = get_settings()
    expected_internal = settings.internal_api_key.strip()
    expected_cron = settings.cron_secret.strip()
    expected_values = {v for v in [expected_internal, expected_cron] if v}
    if not expected_values:
        return

    token_values: set[str] = set()
    if x_internal_key and x_internal_key.strip():
        token_values.add(x_internal_key.strip())
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
        if bearer:
            token_values.add(bearer)

    if token_values & expected_values:
        return

    if not token_values:
        raise HTTPException(status_code=401, detail="missing internal key")
    if x_internal_key is None and authorization is not None:
        # Vercel Cron can use Authorization: Bearer <CRON_SECRET>
        raise HTTPException(status_code=401, detail="invalid cron secret")
    else:
        raise HTTPException(status_code=401, detail="invalid internal key")
