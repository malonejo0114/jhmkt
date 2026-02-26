from __future__ import annotations

import datetime as dt
import hashlib
import hmac
from urllib.parse import quote_plus, urlencode

from app.core.config import get_settings
from app.services.exceptions import PermanentPublishError
from app.services.external_http import request_json

DEEPLINK_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"
PRODUCT_SEARCH_PATH = "/v2/providers/affiliate_open_api/apis/openapi/products/search"


def _signed_date() -> str:
    return dt.datetime.utcnow().strftime("%y%m%dT%H%M%SZ")


def _signature(secret_key: str, message: str) -> str:
    return hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def _authorization(access_key: str, secret_key: str, signed_date: str, method: str, path: str, query: str = "") -> str:
    message = f"{signed_date}{method}{path}{query}"
    sign = _signature(secret_key, message)
    return (
        "CEA algorithm=HmacSHA256, "
        f"access-key={access_key}, "
        f"signed-date={signed_date}, "
        f"signature={sign}"
    )


def create_coupang_deeplink(original_url: str) -> str:
    settings = get_settings()
    access_key = settings.coupang_access_key.strip()
    secret_key = settings.coupang_secret_key.strip()
    if not access_key or not secret_key:
        raise PermanentPublishError("Coupang API 키가 설정되지 않았습니다.", code="COUPANG_KEY_MISSING")

    signed_date = _signed_date()
    auth = _authorization(access_key, secret_key, signed_date, "POST", DEEPLINK_PATH)

    data = request_json(
        "POST",
        f"{settings.coupang_base_url.rstrip('/')}{DEEPLINK_PATH}",
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
        },
        json_body={"coupangUrls": [original_url]},
        timeout=15.0,
    )

    # Coupang API often returns HTTP 200 with rCode/rMessage for business-level errors.
    r_code = str(data.get("rCode", "")).strip()
    r_message = str(data.get("rMessage", "")).strip()
    if r_code and r_code != "0":
        raise PermanentPublishError(
            f"Coupang deeplink 실패(rCode={r_code}): {r_message or 'unknown'}",
            code=f"COUPANG_RCODE_{r_code}",
        )

    # Defensive parse for known response variants
    if isinstance(data.get("data"), list) and data["data"]:
        item = data["data"][0]
        for key in ("shortenUrl", "shortUrl", "shorten_url", "landingUrl", "url"):
            val = item.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val

    for key in ("shortenUrl", "shortUrl", "shorten_url", "landingUrl"):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val

    raise PermanentPublishError(
        f"Coupang deeplink 응답 파싱 실패(rCode={r_code or 'N/A'})",
        code="COUPANG_RESPONSE_INVALID",
    )


def _first_http_url(values: list[str | None]) -> str | None:
    for value in values:
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


def find_coupang_best_product_url(keyword: str) -> str | None:
    settings = get_settings()
    if settings.run_mode != "live":
        return None

    access_key = settings.coupang_access_key.strip()
    secret_key = settings.coupang_secret_key.strip()
    if not access_key or not secret_key:
        return None

    query = urlencode({"keyword": keyword, "limit": 1})
    signed_date = _signed_date()
    auth = _authorization(access_key, secret_key, signed_date, "GET", PRODUCT_SEARCH_PATH, query)

    try:
        data = request_json(
            "GET",
            f"{settings.coupang_base_url.rstrip('/')}{PRODUCT_SEARCH_PATH}?{query}",
            headers={
                "Authorization": auth,
                "Content-Type": "application/json",
            },
            timeout=12.0,
        )
    except Exception:  # noqa: BLE001
        return None

    candidates: list[dict] = []
    if isinstance(data.get("data"), dict):
        product_data = data["data"].get("productData")
        if isinstance(product_data, list):
            candidates = [item for item in product_data if isinstance(item, dict)]
    elif isinstance(data.get("data"), list):
        candidates = [item for item in data["data"] if isinstance(item, dict)]
    elif isinstance(data.get("products"), list):
        candidates = [item for item in data["products"] if isinstance(item, dict)]

    if not candidates:
        return None

    first = candidates[0]
    return _first_http_url(
        [
            first.get("productUrl"),
            first.get("productURL"),
            first.get("url"),
            first.get("productLink"),
            first.get("deepLink"),
            first.get("landingUrl"),
        ]
    )


def resolve_coupang_source_url(keyword: str) -> str:
    best = find_coupang_best_product_url(keyword.strip())
    if best:
        return best
    return f"https://www.coupang.com/np/search?q={quote_plus(keyword.strip())}"
