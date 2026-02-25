from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.internal import router as internal_router
from app.api.web import router as web_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging()

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="cpang_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=False if settings.app_env == "dev" else True,
)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(internal_router)
app.include_router(web_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
