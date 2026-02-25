from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db
from app.schemas.accounts import InstagramAccountCreate, ThreadsAccountCreate
from app.services.accounts_service import upsert_instagram_account, upsert_threads_account
from app.services.auth_service import (
    authenticate_user,
    create_user,
    get_current_user,
    login_user,
    logout_user,
)
from app.services.meta_oauth_service import (
    build_authorize_url,
    build_oauth_state,
    exchange_code_for_token,
    fetch_instagram_identity,
    fetch_threads_identity,
)

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["auth"])


@router.get("/auth/login")
def login_page(request: Request, flash: str | None = None):
    return templates.TemplateResponse(request, "auth_login.html", {"flash": flash})


@router.post("/auth/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, email=email, password=password)
    if not user:
        return RedirectResponse("/auth/login?flash=이메일 또는 비밀번호가 올바르지 않습니다.", status_code=303)

    login_user(request, user)
    return RedirectResponse("/app", status_code=303)


@router.get("/auth/register")
def register_page(request: Request, flash: str | None = None):
    return templates.TemplateResponse(request, "auth_register.html", {"flash": flash})


@router.post("/auth/register")
def register_submit(
    request: Request,
    display_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    if password != password_confirm:
        return RedirectResponse("/auth/register?flash=비밀번호 확인이 일치하지 않습니다.", status_code=303)

    try:
        user = create_user(db, email=email, display_name=display_name, password=password)
    except ValueError as exc:
        return RedirectResponse(f"/auth/register?flash={str(exc)}", status_code=303)

    login_user(request, user)
    return RedirectResponse("/app", status_code=303)


@router.post("/auth/logout")
def logout_submit(request: Request):
    logout_user(request)
    return RedirectResponse("/", status_code=303)


@router.get("/auth/connect/{provider}/start")
def oauth_connect_start(provider: str, request: Request, db: Session = Depends(get_db)):
    if provider not in {"threads", "instagram"}:
        return RedirectResponse("/app?flash=지원하지 않는 연동 타입입니다.", status_code=303)

    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login?flash=로그인이 필요합니다.", status_code=303)

    settings = get_settings()
    if not settings.oauth_enabled:
        return RedirectResponse("/app?flash=OAuth 연동이 비활성화되어 있습니다.", status_code=303)

    try:
        state = build_oauth_state()
        request.session["oauth_state"] = state
        request.session["oauth_provider"] = provider
        url = build_authorize_url(provider, state)
    except ValueError as exc:
        return RedirectResponse(f"/app?flash={str(exc)}", status_code=303)

    return RedirectResponse(url, status_code=302)


@router.get("/auth/connect/{provider}/callback")
def oauth_connect_callback(
    provider: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        return RedirectResponse(f"/app?flash=연동 실패:{error}", status_code=303)

    expected_state = request.session.get("oauth_state")
    expected_provider = request.session.get("oauth_provider")
    if not code or not state or state != expected_state or provider != expected_provider:
        return RedirectResponse("/app?flash=OAuth 상태 검증 실패", status_code=303)

    request.session.pop("oauth_state", None)
    request.session.pop("oauth_provider", None)

    try:
        token = exchange_code_for_token(provider, code)
        if provider == "threads":
            identity = fetch_threads_identity(token)
            payload = ThreadsAccountCreate(
                name=identity["name"],
                threads_user_id=identity["threads_user_id"],
                access_token=token,
            )
            upsert_threads_account(db, payload)
            return RedirectResponse("/app?flash=Threads 계정 연동 완료", status_code=303)

        identity = fetch_instagram_identity(token)
        payload = InstagramAccountCreate(
            name=identity["name"],
            ig_user_id=identity["ig_user_id"],
            access_token=identity["access_token"],
        )
        upsert_instagram_account(db, payload)
        return RedirectResponse("/app?flash=Instagram 계정 연동 완료", status_code=303)

    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/app?flash=연동 실패:{str(exc)}", status_code=303)
