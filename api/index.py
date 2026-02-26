try:
    from app.main import app
except ModuleNotFoundError:  # pragma: no cover - Vercel root directory fallback
    from main import app  # type: ignore
