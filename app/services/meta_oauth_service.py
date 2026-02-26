from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from app.core.config import get_settings
from app.services.external_http import request_json


def _provider_scopes(provider: str) -> str:
    if provider == "threads":
        return ",".join(
            [
                "threads_basic",
                "threads_content_publish",
                "threads_manage_replies",
                "threads_manage_insights",
            ]
        )
    if provider == "instagram":
        return ",".join(
            [
                "instagram_basic",
                "instagram_content_publish",
                "instagram_manage_comments",
                "instagram_manage_messages",
                "pages_show_list",
                "pages_read_engagement",
                "business_management",
            ]
        )
    raise ValueError(f"unsupported provider: {provider}")


def build_oauth_state() -> str:
    return secrets.token_urlsafe(24)


def _client_id_for_provider(provider: str) -> str:
    settings = get_settings()
    if provider == "threads":
        return settings.threads_app_id.strip() or settings.meta_app_id.strip()
    if provider == "instagram":
        return settings.instagram_app_id.strip() or settings.meta_app_id.strip()
    raise ValueError(f"unsupported provider: {provider}")


def _client_secret_for_provider(provider: str) -> str:
    settings = get_settings()
    if provider == "threads":
        return settings.threads_app_secret.strip() or settings.meta_app_secret.strip()
    if provider == "instagram":
        return settings.instagram_app_secret.strip() or settings.meta_app_secret.strip()
    raise ValueError(f"unsupported provider: {provider}")


def callback_url(provider: str) -> str:
    settings = get_settings()
    return f"{settings.public_base_url.rstrip('/')}/auth/connect/{provider}/callback"


def build_authorize_url(provider: str, state: str) -> str:
    settings = get_settings()
    client_id = _client_id_for_provider(provider)
    if not client_id:
        if provider == "threads":
            raise ValueError("THREADS_APP_ID(또는 META_APP_ID) 가 설정되지 않았습니다.")
        raise ValueError("INSTAGRAM_APP_ID(또는 META_APP_ID) 가 설정되지 않았습니다.")

    if provider == "threads":
        base = "https://www.threads.net/oauth/authorize"
    else:
        base = f"https://www.facebook.com/{settings.meta_oauth_version}/dialog/oauth"
    query = {
        "client_id": client_id,
        "redirect_uri": callback_url(provider),
        "scope": _provider_scopes(provider),
        "response_type": "code",
        "state": state,
    }
    return f"{base}?{urlencode(query)}"


def exchange_code_for_token(provider: str, code: str) -> str:
    settings = get_settings()
    client_id = _client_id_for_provider(provider)
    client_secret = _client_secret_for_provider(provider)
    if not client_id or not client_secret:
        if provider == "threads":
            raise ValueError("THREADS_APP_ID/THREADS_APP_SECRET(또는 META_APP_ID/META_APP_SECRET) 설정이 필요합니다.")
        raise ValueError("INSTAGRAM_APP_ID/INSTAGRAM_APP_SECRET(또는 META_APP_ID/META_APP_SECRET) 설정이 필요합니다.")

    if provider == "threads":
        token_url = "https://graph.threads.net/oauth/access_token"
    else:
        token_url = f"https://graph.facebook.com/{settings.meta_oauth_version}/oauth/access_token"
    data = request_json(
        "GET",
        token_url,
        params={
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": callback_url(provider),
            "code": code,
            **({"grant_type": "authorization_code"} if provider == "threads" else {}),
        },
    )
    token = str(data.get("access_token") or "")
    if not token:
        raise ValueError("OAuth 토큰 교환 실패")
    return token


def _compute_token_expires_at(expires_in_raw: object) -> datetime | None:
    try:
        expires_in = int(str(expires_in_raw or "").strip())
    except ValueError:
        return None
    if expires_in <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)


def exchange_threads_long_lived_token(short_lived_access_token: str) -> tuple[str, datetime | None]:
    client_secret = _client_secret_for_provider("threads")
    if not client_secret:
        raise ValueError("THREADS_APP_SECRET(또는 META_APP_SECRET) 설정이 필요합니다.")

    data = request_json(
        "GET",
        "https://graph.threads.net/access_token",
        params={
            "grant_type": "th_exchange_token",
            "client_secret": client_secret,
            "access_token": short_lived_access_token,
        },
    )
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise ValueError("Threads long-lived 토큰 교환 실패")
    return token, _compute_token_expires_at(data.get("expires_in"))


def refresh_threads_access_token(long_lived_access_token: str) -> tuple[str, datetime | None]:
    data = request_json(
        "GET",
        "https://graph.threads.net/refresh_access_token",
        params={
            "grant_type": "th_refresh_token",
            "access_token": long_lived_access_token,
        },
    )
    token = str(data.get("access_token") or long_lived_access_token).strip()
    if not token:
        raise ValueError("Threads 토큰 갱신 실패")
    return token, _compute_token_expires_at(data.get("expires_in"))


def fetch_threads_identity(access_token: str) -> dict:
    settings = get_settings()
    base = f"{settings.threads_api_base_url.rstrip('/')}/{settings.threads_api_version}"
    data = request_json(
        "GET",
        f"{base}/me",
        params={
            "fields": "id,username",
            "access_token": access_token,
        },
    )
    user_id = str(data.get("id") or "")
    if not user_id:
        raise ValueError("Threads 사용자 ID 조회 실패")
    username = str(data.get("username") or f"threads-{user_id[-6:]}")
    return {"threads_user_id": user_id, "name": username}


def fetch_instagram_identity(access_token: str) -> dict:
    settings = get_settings()
    base = f"https://graph.facebook.com/{settings.meta_oauth_version}"

    pages = request_json(
        "GET",
        f"{base}/me/accounts",
        params={"access_token": access_token, "limit": 10},
    )
    page_items = pages.get("data", []) if isinstance(pages.get("data"), list) else []
    if not page_items:
        raise ValueError("Instagram 비즈니스 페이지를 찾을 수 없습니다.")

    first_page = page_items[0]
    page_id = str(first_page.get("id") or "")
    page_name = str(first_page.get("name") or "instagram")
    page_access_token = str(first_page.get("access_token") or access_token)

    page_info = request_json(
        "GET",
        f"{base}/{page_id}",
        params={
            "fields": "instagram_business_account",
            "access_token": page_access_token,
        },
    )
    ig_obj = page_info.get("instagram_business_account") or {}
    ig_user_id = str(ig_obj.get("id") or "")
    if not ig_user_id:
        raise ValueError("instagram_business_account ID 조회 실패")

    return {
        "ig_user_id": ig_user_id,
        "name": page_name,
        "access_token": page_access_token,
    }
