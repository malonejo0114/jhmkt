from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import InstagramAccount, RenderedAsset, ThreadsAccount
from app.services.exceptions import PermanentPublishError, TransientPublishError
from app.services.external_http import request_json
from app.services.hash_utils import sha256_hex
from app.services.security import decrypt_token
from app.services.threads_token_service import run_with_threads_token_retry


@dataclass
class ThreadsPublishResult:
    root_post_id: str
    reply_post_id: str | None
    permalink: str


@dataclass
class ThreadsManualPublishResult:
    post_id: str
    permalink: str
    reply_post_id: str | None


@dataclass
class InstagramPublishResult:
    child_container_ids: list[str]
    carousel_creation_id: str
    carousel_media_id: str


@dataclass
class InstagramCommentReplyResult:
    comment_id: str
    reply_id: str
    mode: str


@dataclass
class ThreadsInsightResult:
    media_id: str
    captured_at: datetime
    views: int
    likes: int
    replies: int
    reposts: int
    quotes: int
    shares: int
    raw_payload: dict[str, Any]


@dataclass
class ThreadsCommentResult:
    reply_id: str
    media_id: str
    parent_reply_id: str | None
    text: str
    from_id: str | None
    username: str | None
    created_at: datetime | None
    raw_payload: dict[str, Any]


def _mock_id(prefix: str, seed: str) -> str:
    return f"{prefix}_{sha256_hex(seed)[:14]}"


def _extract_token(account: ThreadsAccount | InstagramAccount) -> str:
    try:
        return decrypt_token(account.access_token_enc)
    except Exception as exc:  # noqa: BLE001
        raise PermanentPublishError("access token decrypt 실패", code="TOKEN_DECRYPT_FAILED") from exc


THREADS_REPLY_RETRY_DELAYS_SECONDS = (0.0, 2.0, 5.0)


def _is_retryable_threads_reply_error(exc: Exception) -> bool:
    if isinstance(exc, TransientPublishError):
        return True
    if not isinstance(exc, PermanentPublishError):
        return False
    if exc.code in {"HTTP_400", "HTTP_408", "HTTP_409", "HTTP_429", "HTTP_500", "HTTP_502", "HTTP_503", "HTTP_504"}:
        return True
    message = str(exc).lower()
    return "reply_to_id" in message or "temporar" in message or "try again" in message


def try_send_threads_comment_reply(
    *,
    db: Session,
    account: ThreadsAccount,
    reply_to_id: str,
    message: str,
) -> str | None:
    clean_message = message.strip()
    if not clean_message:
        return None

    for index, delay_seconds in enumerate(THREADS_REPLY_RETRY_DELAYS_SECONDS):
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            return send_threads_comment_reply(
                db=db,
                account=account,
                reply_to_id=reply_to_id,
                message=clean_message,
            )
        except (TransientPublishError, PermanentPublishError) as exc:
            if not _is_retryable_threads_reply_error(exc):
                raise
            if index == len(THREADS_REPLY_RETRY_DELAYS_SECONDS) - 1:
                return None
    return None


def publish_threads(
    *,
    db: Session,
    account: ThreadsAccount,
    root_text: str,
    reply_text: str,
) -> ThreadsPublishResult:
    settings = get_settings()

    if settings.run_mode == "mock":
        seed = f"{account.id}|{root_text}|{reply_text}|{datetime.now(timezone.utc).isoformat()}"
        root_id = _mock_id("thr_root", seed)
        reply_id = _mock_id("thr_reply", seed)
        return ThreadsPublishResult(
            root_post_id=root_id,
            reply_post_id=reply_id,
            permalink=f"https://www.threads.net/@mock/post/{root_id}",
        )

    base = f"{settings.threads_api_base_url.rstrip('/')}/{settings.threads_api_version}"
    def _publish_with_token(token: str) -> str:
        create_root = request_json(
            "POST",
            f"{base}/{account.threads_user_id}/threads",
            params={
                "text": root_text,
                "media_type": "TEXT",
                "access_token": token,
            },
        )
        creation_id = str(create_root.get("id") or create_root.get("creation_id") or "")
        if not creation_id:
            raise PermanentPublishError("threads root creation_id 누락", code="THREADS_CREATE_INVALID")

        publish_root = request_json(
            "POST",
            f"{base}/{account.threads_user_id}/threads_publish",
            params={
                "creation_id": creation_id,
                "access_token": token,
            },
        )
        root_post_id = str(publish_root.get("id") or "")
        if not root_post_id:
            raise PermanentPublishError("threads root publish id 누락", code="THREADS_PUBLISH_INVALID")
        return root_post_id

    root_post_id = run_with_threads_token_retry(db, account, _publish_with_token)

    reply_post_id = try_send_threads_comment_reply(
        db=db,
        account=account,
        reply_to_id=root_post_id,
        message=reply_text,
    )

    return ThreadsPublishResult(
        root_post_id=root_post_id,
        reply_post_id=reply_post_id,
        permalink=f"https://www.threads.net/t/{root_post_id}",
    )


def _parse_threads_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def list_threads_comments(
    *,
    db: Session,
    account: ThreadsAccount,
    media_id: str,
    limit: int = 50,
) -> list[ThreadsCommentResult]:
    settings = get_settings()
    fetch_limit = max(1, min(limit, 100))

    if settings.run_mode == "mock":
        return []

    base = f"{settings.threads_api_base_url.rstrip('/')}/{settings.threads_api_version}"
    def _list_with_token(token: str) -> dict[str, Any]:
        return request_json(
            "GET",
            f"{base}/{media_id}/replies",
            params={
                "fields": "id,text,username,timestamp,reply_to_id,media,from",
                "limit": fetch_limit,
                "access_token": token,
            },
        )

    data = run_with_threads_token_retry(db, account, _list_with_token)

    items = data.get("data", []) if isinstance(data.get("data"), list) else []
    parsed: list[ThreadsCommentResult] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        reply_id = str(raw.get("id") or "").strip()
        if not reply_id:
            continue
        media_obj = raw.get("media") if isinstance(raw.get("media"), dict) else {}
        from_obj = raw.get("from") if isinstance(raw.get("from"), dict) else {}
        parsed.append(
            ThreadsCommentResult(
                reply_id=reply_id,
                media_id=str(raw.get("media_id") or media_obj.get("id") or media_id).strip(),
                parent_reply_id=str(raw.get("reply_to_id") or "").strip() or None,
                text=str(raw.get("text") or "").strip(),
                from_id=str(raw.get("from_id") or from_obj.get("id") or "").strip() or None,
                username=str(raw.get("username") or from_obj.get("username") or "").strip() or None,
                created_at=_parse_threads_ts(raw.get("timestamp") or raw.get("created_time")),
                raw_payload=raw,
            )
        )
    return parsed


def send_threads_comment_reply(
    *,
    db: Session,
    account: ThreadsAccount,
    reply_to_id: str,
    message: str,
) -> str:
    settings = get_settings()

    if settings.run_mode == "mock":
        seed = f"{account.id}|{reply_to_id}|{message}|{datetime.now(timezone.utc).isoformat()}"
        return _mock_id("thr_comment_reply", seed)

    base = f"{settings.threads_api_base_url.rstrip('/')}/{settings.threads_api_version}"
    def _reply_with_token(token: str) -> str:
        create_reply = request_json(
            "POST",
            f"{base}/{account.threads_user_id}/threads",
            params={
                "text": message,
                "media_type": "TEXT",
                "reply_to_id": reply_to_id,
                "access_token": token,
            },
        )
        creation_id = str(create_reply.get("id") or create_reply.get("creation_id") or "").strip()
        if not creation_id:
            raise PermanentPublishError(
                "threads comment reply creation_id 누락",
                code="THREADS_COMMENT_REPLY_CREATE_INVALID",
            )

        publish_reply = request_json(
            "POST",
            f"{base}/{account.threads_user_id}/threads_publish",
            params={
                "creation_id": creation_id,
                "access_token": token,
            },
        )
        reply_post_id = str(publish_reply.get("id") or "").strip()
        if not reply_post_id:
            raise PermanentPublishError(
                "threads comment reply publish id 누락",
                code="THREADS_COMMENT_REPLY_PUBLISH_INVALID",
            )
        return reply_post_id

    return run_with_threads_token_retry(db, account, _reply_with_token)


def publish_threads_manual_post(
    *,
    db: Session,
    account: ThreadsAccount,
    text: str,
    reply_text: str = "",
    image_url: str | None = None,
) -> ThreadsManualPublishResult:
    settings = get_settings()
    clean_text = text.strip()
    clean_reply = reply_text.strip()
    clean_image_url = (image_url or "").strip() or None

    if not clean_text:
        raise ValueError("게시 본문을 입력해주세요.")

    if settings.run_mode == "mock":
        seed = f"{account.id}|{clean_text}|{clean_reply}|{clean_image_url}|{datetime.now(timezone.utc).isoformat()}"
        post_id = _mock_id("thr_manual", seed)
        reply_id = _mock_id("thr_manual_reply", seed) if clean_reply else None
        return ThreadsManualPublishResult(
            post_id=post_id,
            permalink=f"https://www.threads.net/t/{post_id}",
            reply_post_id=reply_id,
        )

    base = f"{settings.threads_api_base_url.rstrip('/')}/{settings.threads_api_version}"

    def _manual_publish_with_token(token: str) -> str:
        create_params: dict[str, str] = {
            "text": clean_text,
            "access_token": token,
        }
        if clean_image_url:
            create_params["media_type"] = "IMAGE"
            create_params["image_url"] = clean_image_url
        else:
            create_params["media_type"] = "TEXT"

        created = request_json(
            "POST",
            f"{base}/{account.threads_user_id}/threads",
            params=create_params,
        )
        creation_id = str(created.get("id") or created.get("creation_id") or "").strip()
        if not creation_id:
            raise PermanentPublishError("threads manual creation_id 누락", code="THREADS_MANUAL_CREATE_INVALID")

        published = request_json(
            "POST",
            f"{base}/{account.threads_user_id}/threads_publish",
            params={
                "creation_id": creation_id,
                "access_token": token,
            },
        )
        post_id = str(published.get("id") or "").strip()
        if not post_id:
            raise PermanentPublishError("threads manual publish id 누락", code="THREADS_MANUAL_PUBLISH_INVALID")
        return post_id

    post_id = run_with_threads_token_retry(db, account, _manual_publish_with_token)

    reply_post_id: str | None = None
    if clean_reply:
        reply_post_id = try_send_threads_comment_reply(
            db=db,
            account=account,
            reply_to_id=post_id,
            message=clean_reply,
        )

    return ThreadsManualPublishResult(
        post_id=post_id,
        permalink=f"https://www.threads.net/t/{post_id}",
        reply_post_id=reply_post_id,
    )


def _to_public_image_url(uri: str) -> str:
    if uri.startswith("http://") or uri.startswith("https://"):
        return uri
    if uri.startswith("gs://"):
        _, rest = uri.split("gs://", 1)
        bucket, object_name = rest.split("/", 1)
        return f"https://storage.googleapis.com/{bucket}/{object_name}"
    raise PermanentPublishError(
        f"Instagram live 모드는 공개 URL 필요: {uri}",
        code="IG_IMAGE_URL_INVALID",
    )


def _poll_ig_container(base: str, container_id: str, token: str) -> None:
    for _ in range(10):
        status = request_json(
            "GET",
            f"{base}/{container_id}",
            params={
                "fields": "status_code,status",
                "access_token": token,
            },
        )
        status_code = str(status.get("status_code") or "").upper()
        if status_code == "FINISHED":
            return
        if status_code in {"ERROR", "EXPIRED"}:
            raise PermanentPublishError(
                f"instagram container status={status_code}",
                code="IG_CONTAINER_ERROR",
            )

    raise TransientPublishError("instagram container polling timeout", code="IG_CONTAINER_TIMEOUT")


def publish_instagram_carousel(
    *,
    account: InstagramAccount,
    caption: str,
    assets: list[RenderedAsset],
) -> InstagramPublishResult:
    settings = get_settings()

    if settings.run_mode == "mock":
        seed = f"{account.id}|{caption}|{len(assets)}|{datetime.now(timezone.utc).isoformat()}"
        children = [_mock_id("ig_child", f"{seed}-{i}") for i in range(len(assets))]
        carousel_creation_id = _mock_id("ig_carousel_creation", seed)
        carousel_media_id = _mock_id("ig_media", seed)
        return InstagramPublishResult(
            child_container_ids=children,
            carousel_creation_id=carousel_creation_id,
            carousel_media_id=carousel_media_id,
        )

    token = _extract_token(account)
    base = f"{settings.instagram_api_base_url.rstrip('/')}/{settings.instagram_api_version}"

    child_ids: list[str] = []
    for asset in assets:
        url = _to_public_image_url(asset.gcs_uri)
        created = request_json(
            "POST",
            f"{base}/{account.ig_user_id}/media",
            params={
                "image_url": url,
                "is_carousel_item": "true",
                "access_token": token,
            },
        )
        child_id = str(created.get("id") or "")
        if not child_id:
            raise PermanentPublishError("instagram child container id 누락", code="IG_CHILD_CREATE_INVALID")
        _poll_ig_container(base, child_id, token)
        child_ids.append(child_id)

    carousel = request_json(
        "POST",
        f"{base}/{account.ig_user_id}/media",
        params={
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "caption": caption,
            "access_token": token,
        },
    )
    carousel_creation_id = str(carousel.get("id") or "")
    if not carousel_creation_id:
        raise PermanentPublishError(
            "instagram carousel creation id 누락",
            code="IG_CAROUSEL_CREATE_INVALID",
        )

    _poll_ig_container(base, carousel_creation_id, token)

    published = request_json(
        "POST",
        f"{base}/{account.ig_user_id}/media_publish",
        params={
            "creation_id": carousel_creation_id,
            "access_token": token,
        },
    )
    media_id = str(published.get("id") or "")
    if not media_id:
        raise PermanentPublishError("instagram publish id 누락", code="IG_PUBLISH_INVALID")

    return InstagramPublishResult(
        child_container_ids=child_ids,
        carousel_creation_id=carousel_creation_id,
        carousel_media_id=media_id,
    )


def send_instagram_private_reply(
    *,
    account: InstagramAccount,
    comment_id: str,
    message: str,
) -> InstagramCommentReplyResult:
    settings = get_settings()
    if settings.run_mode == "mock":
        seed = f"{account.id}|{comment_id}|{message}|private|{datetime.now(timezone.utc).isoformat()}"
        return InstagramCommentReplyResult(
            comment_id=comment_id,
            reply_id=_mock_id("ig_private_reply", seed),
            mode="PRIVATE_REPLY",
        )

    token = _extract_token(account)
    base = f"{settings.instagram_api_base_url.rstrip('/')}/{settings.instagram_api_version}"
    # NOTE: Endpoint can vary by app type/permissions; this path should be validated in production.
    data = request_json(
        "POST",
        f"{base}/{comment_id}/private_replies",
        params={
            "message": message,
            "access_token": token,
        },
    )
    reply_id = str(data.get("id") or "")
    if not reply_id:
        raise PermanentPublishError("instagram private reply id 누락", code="IG_PRIVATE_REPLY_INVALID")
    return InstagramCommentReplyResult(comment_id=comment_id, reply_id=reply_id, mode="PRIVATE_REPLY")


def send_instagram_public_reply(
    *,
    account: InstagramAccount,
    comment_id: str,
    message: str,
) -> InstagramCommentReplyResult:
    settings = get_settings()
    if settings.run_mode == "mock":
        seed = f"{account.id}|{comment_id}|{message}|public|{datetime.now(timezone.utc).isoformat()}"
        return InstagramCommentReplyResult(
            comment_id=comment_id,
            reply_id=_mock_id("ig_public_reply", seed),
            mode="PUBLIC_REPLY",
        )

    token = _extract_token(account)
    base = f"{settings.instagram_api_base_url.rstrip('/')}/{settings.instagram_api_version}"
    data = request_json(
        "POST",
        f"{base}/{comment_id}/replies",
        params={
            "message": message,
            "access_token": token,
        },
    )
    reply_id = str(data.get("id") or "")
    if not reply_id:
        raise PermanentPublishError("instagram public reply id 누락", code="IG_PUBLIC_REPLY_INVALID")
    return InstagramCommentReplyResult(comment_id=comment_id, reply_id=reply_id, mode="PUBLIC_REPLY")


def collect_threads_insights(
    *,
    db: Session,
    account: ThreadsAccount,
    media_id: str,
) -> ThreadsInsightResult:
    settings = get_settings()
    now = datetime.now(timezone.utc)

    if settings.run_mode == "mock":
        seed = int(sha256_hex(media_id)[:8], 16)
        return ThreadsInsightResult(
            media_id=media_id,
            captured_at=now,
            views=500 + (seed % 1500),
            likes=20 + (seed % 120),
            replies=3 + (seed % 35),
            reposts=1 + (seed % 18),
            quotes=0 + (seed % 10),
            shares=2 + (seed % 40),
            raw_payload={"mock": True, "seed": seed},
        )

    base = f"{settings.threads_api_base_url.rstrip('/')}/{settings.threads_api_version}"
    def _collect_with_token(token: str) -> dict[str, Any]:
        return request_json(
            "GET",
            f"{base}/{media_id}/insights",
            params={
                "metric": "views,likes,replies,reposts,quotes,shares",
                "access_token": token,
            },
        )

    data = run_with_threads_token_retry(db, account, _collect_with_token)

    values: dict[str, int] = {"views": 0, "likes": 0, "replies": 0, "reposts": 0, "quotes": 0, "shares": 0}
    for item in data.get("data", []):
        name = item.get("name")
        value = int(item.get("values", [{}])[0].get("value", 0)) if isinstance(item.get("values"), list) else int(item.get("value", 0))
        if name in values:
            values[name] = value

    return ThreadsInsightResult(
        media_id=media_id,
        captured_at=now,
        views=values["views"],
        likes=values["likes"],
        replies=values["replies"],
        reposts=values["reposts"],
        quotes=values["quotes"],
        shares=values["shares"],
        raw_payload=data,
    )
