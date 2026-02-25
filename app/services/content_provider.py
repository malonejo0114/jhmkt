from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.prompt_templates import (
    DEFAULT_BANNED_WORDS,
    build_comment_reply_prompt,
    build_content_generation_prompt,
    build_weekly_hook_prompt,
)

EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "]+",
    flags=re.UNICODE,
)


def _strip_emojis_from_text(value: str) -> str:
    return EMOJI_RE.sub("", value)


def _apply_emoji_mode(payload: dict[str, Any], emoji_mode: str) -> dict[str, Any]:
    if emoji_mode != "OFF":
        return payload

    for key in ("threads_body", "threads_first_reply", "instagram_caption"):
        payload[key] = _strip_emojis_from_text(str(payload.get(key, ""))).strip()

    slides = payload.get("slides")
    if isinstance(slides, list):
        normalized: list[dict[str, Any]] = []
        for slide in slides:
            if not isinstance(slide, dict):
                continue
            normalized.append(
                {
                    **slide,
                    "title": _strip_emojis_from_text(str(slide.get("title", ""))).strip(),
                    "body": _strip_emojis_from_text(str(slide.get("body", ""))).strip(),
                }
            )
        payload["slides"] = normalized
    return payload


def _fallback_payload(
    topic: str,
    category: str,
    short_url: str,
    disclosure_line: str,
    variant: int = 0,
    hook_candidates: list[str] | None = None,
    tone_style: str = "CASUAL",
    emoji_mode: str = "ON",
    style_prompt: str = "",
) -> dict[str, Any]:
    hook_pool = [h.strip() for h in (hook_candidates or []) if h and h.strip()]
    hooks = [
        *(hook_pool[:3]),
        f"{topic} 살 때 이 5가지를 비교 안 하면 손해봅니다",
        f"{topic} 구매 전, 대부분 놓치는 핵심 체크포인트",
        f"{topic} 비교할 때 돈 버리는 선택을 막는 기준",
        f"{topic} 고르기 전에 반드시 확인해야 할 순서",
        f"{topic} 가격만 보면 실패하는 이유와 체크리스트",
        f"{topic} 초보자도 바로 쓰는 실전 의사결정 가이드",
    ]
    if tone_style == "FORMAL":
        bodies = [
            f"{category} 관점에서 먼저 봐야 할 비교 순서만 압축했습니다.",
            "리뷰 수보다 먼저 봐야 하는 스펙 우선순위를 정리했습니다.",
            "지금 바로 적용 가능한 1분 체크리스트 형태로 만들었습니다.",
            "실사용 기준으로 헷갈리는 포인트를 먼저 걸러냈습니다.",
            "예산/구성/유지비를 동시에 보는 기준으로 정리했습니다.",
            "처음 사는 분도 따라하기 쉬운 단계별 기준입니다.",
        ]
        cta_line = "링크는 첫 댓글에 남겨둘게요."
    else:
        bodies = [
            f"{category} 기준으로 먼저 봐야 할 순서만 바로 정리했다.",
            "리뷰 수보다 먼저 봐야 하는 핵심 스펙부터 짚어준다.",
            "바로 써먹을 수 있는 체크리스트만 뽑아놨다.",
            "실사용에서 헷갈리는 포인트를 먼저 걸러보자.",
            "예산/구성/유지비를 한 번에 비교해보자.",
            "처음 사도 바로 판단할 수 있게 단계로 정리했다.",
        ]
        cta_line = "링크는 첫 댓글에 남겨둘게."
    hook = hooks[variant % len(hooks)]
    body_line = bodies[variant % len(bodies)]
    if style_prompt.strip():
        body_line = f"{body_line} {style_prompt.strip()[:70]}"

    emoji_suffix = " 🔥" if emoji_mode == "ON" else ""

    threads_body = f"{disclosure_line}\n{hook}{emoji_suffix}\n{body_line}\n{cta_line}"
    threads_first_reply = f"{disclosure_line}\n추천 링크: {short_url}"
    instagram_caption = (
        f"{disclosure_line}\n"
        f"{topic} 핵심을 카드뉴스로 정리했습니다.\n"
        "자세한 링크는 프로필 링크에서 확인하세요."
    )
    slides = [
        {"slide_no": 1, "title": f"{topic} 핵심", "body": hook},
        {"slide_no": 2, "title": "핵심 관점", "body": body_line},
        {"slide_no": 3, "title": "체크 1", "body": f"{category} 기준으로 우선순위를 고정하세요."},
        {"slide_no": 4, "title": "체크 2", "body": "스펙과 구성 차이를 숫자로 비교하세요."},
        {"slide_no": 5, "title": "체크 3", "body": "가격/배송/리뷰를 같은 기준으로 정렬하세요."},
    ]
    payload = {
        "threads_body": threads_body,
        "threads_first_reply": threads_first_reply,
        "instagram_caption": instagram_caption,
        "slides": slides,
        "render_options": {"font_style": "sans", "background_mode": "google_free", "template_style": "campaign"},
    }
    return _apply_emoji_mode(payload, emoji_mode)


def _extract_json_block(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    raw = match.group(0)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _validate_payload(data: dict[str, Any]) -> bool:
    required = ["threads_body", "threads_first_reply", "instagram_caption", "slides"]
    if not all(k in data for k in required):
        return False
    if not isinstance(data["slides"], list):
        return False
    if not (4 <= len(data["slides"]) <= 7):
        return False
    render_options = data.get("render_options")
    if render_options is not None and not isinstance(render_options, dict):
        return False
    return True


def _extract_candidate_text(response_json: dict[str, Any]) -> str:
    candidates = response_json.get("candidates", [])
    if not candidates:
        return ""
    text_parts: list[str] = []
    for part in candidates[0].get("content", {}).get("parts", []):
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            text_parts.append(part["text"])
    return "\n".join(text_parts).strip()


def _call_gemini_json(prompt: str) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.gemini_api_key:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
    try:
        with httpx.Client(timeout=25.0) as client:
            resp = client.post(
                url,
                params={"key": settings.gemini_api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.6,
                        "responseMimeType": "application/json",
                    },
                },
            )
    except Exception:
        return None

    if resp.status_code // 100 != 2:
        return None

    try:
        return resp.json()
    except ValueError:
        return None


def _gemini_generate(
    topic: str,
    category: str,
    short_url: str,
    disclosure_line: str,
    banned_words: list[str] | None = None,
    hook_candidates: list[str] | None = None,
    target_chars: int = 280,
    tone_style: str = "CASUAL",
    emoji_mode: str = "ON",
    style_prompt: str = "",
) -> dict[str, Any] | None:
    prompt = build_content_generation_prompt(
        topic=topic,
        category=category,
        short_url=short_url,
        disclosure_line=disclosure_line,
        banned_words=banned_words or DEFAULT_BANNED_WORDS,
        hook_candidates=hook_candidates or [],
        target_chars=target_chars,
        tone_style=tone_style,
        emoji_mode=emoji_mode,
        style_prompt=style_prompt,
    )
    data = _call_gemini_json(prompt)
    if not data:
        return None
    raw_text = _extract_candidate_text(data)
    if not raw_text:
        return None

    parsed = _extract_json_block(raw_text)
    if not parsed or not _validate_payload(parsed):
        return None
    return _apply_emoji_mode(parsed, emoji_mode)


def generate_weekly_hook_templates(top_terms: list[str]) -> list[str]:
    seed_terms = [term.strip() for term in top_terms if term and term.strip()]
    fallback = [
        f"{term} 고를 때 먼저 볼 체크리스트" for term in (seed_terms[:3] or ["상품"])
    ]
    while len(fallback) < 3:
        fallback.append("구매 전 실패 줄이는 비교 기준")

    settings = get_settings()
    if settings.run_mode != "live":
        return fallback[:3]

    prompt = build_weekly_hook_prompt(top_terms=seed_terms, template_count=3)
    data = _call_gemini_json(prompt)
    if not data:
        return fallback[:3]

    raw_text = _extract_candidate_text(data)
    parsed = _extract_json_block(raw_text) if raw_text else None
    if not parsed:
        return fallback[:3]

    hooks_raw = parsed.get("hook_templates", [])
    if not isinstance(hooks_raw, list):
        return fallback[:3]

    hooks: list[str] = []
    for item in hooks_raw:
        text = str(item).strip()
        if 8 <= len(text) <= 60 and text not in hooks:
            hooks.append(text)
    if len(hooks) < 3:
        return fallback[:3]
    return hooks[:3]


def generate_content_payload(
    *,
    topic: str,
    category: str,
    short_url: str,
    disclosure_line: str,
    banned_words: list[str] | None = None,
    hook_candidates: list[str] | None = None,
    target_chars: int = 280,
    tone_style: str = "CASUAL",
    emoji_mode: str = "ON",
    style_prompt: str = "",
    variant: int = 0,
) -> dict[str, Any]:
    settings = get_settings()

    if settings.run_mode == "live":
        generated = _gemini_generate(
            topic,
            category,
            short_url,
            disclosure_line,
            banned_words=banned_words,
            hook_candidates=hook_candidates,
            target_chars=target_chars,
            tone_style=tone_style,
            emoji_mode=emoji_mode,
            style_prompt=style_prompt,
        )
        if generated:
            return generated

    return _fallback_payload(
        topic,
        category,
        short_url,
        disclosure_line,
        variant=variant,
        hook_candidates=hook_candidates,
        tone_style=tone_style,
        emoji_mode=emoji_mode,
        style_prompt=style_prompt,
    )


def generate_comment_reply(
    *,
    comment_text: str,
    keyword: str,
    style_prompt: str = "",
    fallback_reply: str = "",
    max_chars: int = 120,
) -> str:
    safe_fallback = fallback_reply.strip() or "댓글 감사합니다. 안내 메시지 확인 부탁드려요."
    settings = get_settings()
    if settings.run_mode != "live":
        return safe_fallback

    prompt = build_comment_reply_prompt(
        comment_text=comment_text,
        keyword=keyword,
        style_prompt=style_prompt,
        max_chars=max(40, min(max_chars, 300)),
    )
    data = _call_gemini_json(prompt)
    if not data:
        return safe_fallback

    raw_text = _extract_candidate_text(data)
    parsed = _extract_json_block(raw_text) if raw_text else None
    if not parsed:
        return safe_fallback

    reply = str(parsed.get("reply") or "").replace("\n", " ").strip()
    if not reply:
        return safe_fallback

    for banned in DEFAULT_BANNED_WORDS:
        if banned in reply:
            return safe_fallback

    max_len = max(40, min(max_chars, 300))
    if len(reply) > max_len:
        reply = reply[: max_len - 1].rstrip() + "…"
    return reply
