from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings

DEFAULT_DEV_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


@lru_cache
def _build_fernet() -> Fernet:
    settings = get_settings()
    key = settings.token_encryption_key.strip() or DEFAULT_DEV_KEY
    return Fernet(key.encode("utf-8"))


def encrypt_token(raw_token: str) -> str:
    return _build_fernet().encrypt(raw_token.encode("utf-8")).decode("utf-8")


def decrypt_token(cipher_text: str) -> str:
    return _build_fernet().decrypt(cipher_text.encode("utf-8")).decode("utf-8")
