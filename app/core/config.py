from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "cpang-jehyu-mvp"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8080

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/cpang_jehyu"
    )
    token_encryption_key: str = Field(default="")
    session_secret: str = Field(default="dev-session-secret-change-this")
    internal_api_key: str = Field(default="")
    cron_secret: str = Field(default="")
    run_mode: str = Field(default="mock")  # mock | live
    daily_unit_count: int = Field(default=3)

    disclosure_line: str = (
        "[광고] 이 포스팅은 쿠팡 파트너스 활동의 일환으로 수수료를 제공받을 수 있습니다."
    )
    saju_disclosure_line: str = Field(default="")

    cloud_tasks_enabled: bool = Field(default=False)
    cloud_tasks_project_id: str = Field(default="")
    cloud_tasks_location: str = Field(default="asia-northeast3")
    queue_publish_threads: str = Field(default="q-publish-threads")
    queue_publish_instagram: str = Field(default="q-publish-instagram")
    queue_insights: str = Field(default="q-insights")
    queue_improve: str = Field(default="q-improve")
    queue_target_base_url: str = Field(default="http://localhost:8080")

    storage_mode: str = Field(default="local")  # local | gcs
    local_asset_dir: str = Field(default="./.local_assets")
    gcs_bucket: str = Field(default="")
    pexels_api_key: str = Field(default="")
    unsplash_access_key: str = Field(default="")
    google_cse_api_key: str = Field(default="")
    google_cse_cx: str = Field(default="")

    threads_api_base_url: str = Field(default="https://graph.threads.net")
    threads_api_version: str = Field(default="v1.0")

    instagram_api_base_url: str = Field(default="https://graph.facebook.com")
    instagram_api_version: str = Field(default="v21.0")

    coupang_base_url: str = Field(default="https://api-gateway.coupang.com")
    coupang_access_key: str = Field(default="")
    coupang_secret_key: str = Field(default="")

    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.0-flash")

    naver_trend_enabled: bool = Field(default=False)
    naver_client_id: str = Field(default="")
    naver_client_secret: str = Field(default="")
    naver_trend_keywords: str = Field(default="")
    naver_trend_top_n: int = Field(default=10)

    oauth_enabled: bool = Field(default=False)
    public_base_url: str = Field(default="http://localhost:8080")
    meta_webhook_verify_token: str = Field(default="")
    engagement_enabled: bool = Field(default=True)
    engagement_ai_reply_enabled: bool = Field(default=False)
    engagement_ai_reply_max_chars: int = Field(default=120)
    private_reply_hourly_limit: int = Field(default=20)
    private_reply_daily_limit: int = Field(default=100)
    public_reply_hourly_limit: int = Field(default=30)
    public_reply_daily_limit: int = Field(default=150)
    threads_app_id: str = Field(default="")
    threads_app_secret: str = Field(default="")
    instagram_app_id: str = Field(default="")
    instagram_app_secret: str = Field(default="")
    meta_app_id: str = Field(default="")
    meta_app_secret: str = Field(default="")
    meta_oauth_version: str = Field(default="v21.0")


@lru_cache
def get_settings() -> Settings:
    return Settings()
