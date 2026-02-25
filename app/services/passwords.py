from __future__ import annotations

import base64
import hashlib
import hmac
import os

PBKDF2_ITERATIONS = 240000
ALGORITHM = "pbkdf2_sha256"


def hash_password(raw_password: str) -> str:
    if len(raw_password) < 8:
        raise ValueError("비밀번호는 최소 8자 이상이어야 합니다.")

    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        raw_password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    salt_b64 = base64.urlsafe_b64encode(salt).decode("utf-8")
    digest_b64 = base64.urlsafe_b64encode(digest).decode("utf-8")
    return f"{ALGORITHM}${PBKDF2_ITERATIONS}${salt_b64}${digest_b64}"


def verify_password(raw_password: str, hashed_password: str) -> bool:
    try:
        algorithm, iter_text, salt_b64, digest_b64 = hashed_password.split("$", 3)
        if algorithm != ALGORITHM:
            return False
        iterations = int(iter_text)
        salt = base64.urlsafe_b64decode(salt_b64.encode("utf-8"))
        expected = base64.urlsafe_b64decode(digest_b64.encode("utf-8"))
    except Exception:
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        raw_password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)
