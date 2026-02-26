from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db
from app.services.engagement_service import (
    create_reply_jobs_for_pending_events,
    ingest_instagram_comment_events,
    process_pending_reply_jobs,
    verify_meta_signature,
)

router = APIRouter(tags=["webhooks"])


@router.get("/webhooks/meta")
def verify_meta_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    settings = get_settings()
    expected = settings.meta_webhook_verify_token.strip()

    if hub_mode == "subscribe" and expected and hub_verify_token == expected and hub_challenge:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="webhook verify failed")


@router.post("/webhooks/meta")
async def receive_meta_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_meta_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid json: {str(exc)}") from exc

    ingest_result = ingest_instagram_comment_events(db, payload)
    queue_result = create_reply_jobs_for_pending_events(db, limit=100)
    send_result = process_pending_reply_jobs(db, limit=100)

    return {
        "status": "ok",
        "ingest_result": ingest_result,
        "queue_result": queue_result,
        "send_result": send_result,
    }

