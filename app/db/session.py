from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()


def _normalize_database_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


database_url = _normalize_database_url(settings.database_url)
engine_kwargs: dict = {"pool_pre_ping": True}
if database_url.startswith("postgresql+psycopg://"):
    # Supabase pooler/pgBouncer(transaction pooling) 환경에서
    # psycopg prepared statement 충돌(DuplicatePreparedStatement)을 피한다.
    engine_kwargs["connect_args"] = {"prepare_threshold": None}

engine = create_engine(database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
