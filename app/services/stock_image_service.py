from __future__ import annotations

import io
import random

import httpx
from PIL import Image, ImageDraw

from app.core.config import get_settings
from app.services.external_http import request_json
from app.services.hash_utils import sha256_hex


def _deterministic_pick(items: list[str], seed_text: str) -> str | None:
    if not items:
        return None
    seed = int(sha256_hex(seed_text)[:8], 16)
    return items[seed % len(items)]


def _download_image_bytes(url: str) -> bytes | None:
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"Accept": "image/*"})
    except Exception:
        return None

    if not (200 <= resp.status_code < 300):
        return None

    content_type = resp.headers.get("content-type", "").lower()
    if not content_type.startswith("image/"):
        return None

    payload = resp.content
    if not payload or len(payload) > 20 * 1024 * 1024:
        return None
    return payload


def _pexels_candidates(query: str, api_key: str) -> list[str]:
    data = request_json(
        "GET",
        "https://api.pexels.com/v1/search",
        headers={"Authorization": api_key},
        params={
            "query": query,
            "orientation": "portrait",
            "size": "large",
            "per_page": 20,
        },
    )

    urls: list[str] = []
    photos = data.get("photos", [])
    if not isinstance(photos, list):
        return urls

    for photo in photos:
        if not isinstance(photo, dict):
            continue
        src = photo.get("src")
        if not isinstance(src, dict):
            continue
        for key in ("large2x", "large", "original"):
            target = src.get(key)
            if isinstance(target, str) and target.startswith("http"):
                urls.append(target)
                break
    return urls


def _unsplash_candidates(query: str, access_key: str) -> list[str]:
    data = request_json(
        "GET",
        "https://api.unsplash.com/search/photos",
        headers={"Authorization": f"Client-ID {access_key}"},
        params={
            "query": query,
            "orientation": "portrait",
            "content_filter": "high",
            "per_page": 20,
            "lang": "ko",
        },
    )

    urls: list[str] = []
    results = data.get("results", [])
    if not isinstance(results, list):
        return urls

    for row in results:
        if not isinstance(row, dict):
            continue
        src = row.get("urls")
        if not isinstance(src, dict):
            continue
        for key in ("regular", "full", "raw"):
            target = src.get(key)
            if isinstance(target, str) and target.startswith("http"):
                urls.append(target)
                break
    return urls


def _google_candidates(query: str, api_key: str, cx: str) -> list[str]:
    # Google Custom Search API with license filtering.
    data = request_json(
        "GET",
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": api_key,
            "cx": cx,
            "q": query,
            "searchType": "image",
            "rights": "cc_publicdomain,cc_attribute,cc_sharealike,cc_noncommercial,cc_nonderived",
            "safe": "active",
            "imgType": "photo",
            "num": 10,
        },
        timeout=15.0,
    )
    urls: list[str] = []
    items = data.get("items", [])
    if not isinstance(items, list):
        return urls
    for item in items:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        if isinstance(link, str) and link.startswith("http"):
            urls.append(link)
    return urls


def _normalize_query(topic: str) -> str:
    query = " ".join(topic.split()).strip()
    return query[:80]


def _generate_background(topic: str) -> bytes:
    seed = int(sha256_hex(topic)[:8], 16)
    rng = random.Random(seed)

    width, height = 1080, 1350
    base = Image.new("RGB", (width, height), (14, 16, 22))
    draw = ImageDraw.Draw(base, "RGBA")

    palette = [
        (15, 30, 56, 200),
        (40, 35, 72, 180),
        (18, 60, 70, 180),
        (70, 30, 45, 160),
    ]
    for i in range(8):
        color = palette[i % len(palette)]
        x0 = rng.randint(-240, width - 120)
        y0 = rng.randint(-240, height - 120)
        x1 = x0 + rng.randint(260, 760)
        y1 = y0 + rng.randint(260, 760)
        draw.ellipse((x0, y0, x1, y1), fill=color)

    for _ in range(120):
        x = rng.randint(0, width - 1)
        y = rng.randint(0, height - 1)
        a = rng.randint(14, 40)
        draw.point((x, y), fill=(255, 255, 255, a))

    # Bottom readability overlay.
    for i in range(420):
        alpha = int(220 * (i / 420))
        y = height - 420 + i
        draw.rectangle((0, y, width, y + 1), fill=(0, 0, 0, alpha))

    out = io.BytesIO()
    base.save(out, format="JPEG", quality=92)
    return out.getvalue()


def _fetch_from_google(query: str) -> bytes | None:
    settings = get_settings()
    if not settings.google_cse_api_key.strip() or not settings.google_cse_cx.strip():
        return None
    try:
        candidates = _google_candidates(query, settings.google_cse_api_key.strip(), settings.google_cse_cx.strip())
        picked = _deterministic_pick(candidates, f"google|{query}")
        if not picked:
            return None
        return _download_image_bytes(picked)
    except Exception:
        return None


def _fetch_from_stock_api(query: str) -> bytes | None:
    settings = get_settings()
    providers: list[tuple[str, str]] = []
    if settings.pexels_api_key.strip():
        providers.append(("pexels", settings.pexels_api_key.strip()))
    if settings.unsplash_access_key.strip():
        providers.append(("unsplash", settings.unsplash_access_key.strip()))

    for provider_name, key in providers:
        try:
            if provider_name == "pexels":
                candidates = _pexels_candidates(query, key)
            else:
                candidates = _unsplash_candidates(query, key)
            picked = _deterministic_pick(candidates, f"{provider_name}|{query}")
            if not picked:
                continue
            payload = _download_image_bytes(picked)
            if payload:
                return payload
        except Exception:
            continue
    return None


def fetch_background(topic: str, background_mode: str = "google_free") -> bytes | None:
    query = _normalize_query(topic)
    if not query:
        return None

    mode = (background_mode or "").strip().lower()

    if mode in {"generated", "ai_generated"}:
        return _generate_background(query)
    if mode in {"google", "google_free"}:
        return _fetch_from_google(query) or _fetch_from_stock_api(query) or _generate_background(query)
    if mode in {"stock", "api"}:
        return _fetch_from_stock_api(query) or _fetch_from_google(query) or _generate_background(query)

    return _fetch_from_google(query) or _fetch_from_stock_api(query) or _generate_background(query)


def fetch_stock_background(topic: str) -> bytes | None:
    return fetch_background(topic, background_mode="google_free")
