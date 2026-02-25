from __future__ import annotations

from fastapi import Header, HTTPException

from app.core.config import get_settings


def verify_internal_key(x_internal_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected = settings.internal_api_key.strip()
    if not expected:
        return
    if x_internal_key != expected:
        raise HTTPException(status_code=401, detail="invalid internal key")
