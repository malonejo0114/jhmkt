from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

BANNED_TERMS = [
    "완치",
    "100%",
    "무조건",
    "절대",
    "기적",
    "부작용 없음",
    "즉시 효과",
]


@dataclass
class GuardrailResult:
    passed: bool
    reasons: list[str]
    duplicate_score: float


def _contains_banned(text: str) -> list[str]:
    found: list[str] = []
    lowered = text.lower()
    for term in BANNED_TERMS:
        if term.lower() in lowered:
            found.append(term)
    return found


def _normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text


def duplicate_score(text: str, history_texts: list[str]) -> float:
    if not history_texts:
        return 0.0
    candidate = _normalize(text)
    return max(SequenceMatcher(None, candidate, _normalize(item)).ratio() for item in history_texts)


def validate_threads_body(
    body: str,
    disclosure_line: str,
    history_texts: list[str],
    max_chars: int = 500,
    duplicate_threshold: float = 0.72,
) -> GuardrailResult:
    reasons: list[str] = []

    if len(body) > max_chars:
        reasons.append(f"threads_body_too_long:{len(body)}")

    if disclosure_line.strip() and disclosure_line.strip() in body:
        reasons.append("disclosure_line_in_body")

    if "링크는 첫 댓글" not in body:
        reasons.append("missing_first_comment_phrase")

    found_banned = _contains_banned(body)
    if found_banned:
        reasons.append(f"banned_terms:{','.join(found_banned)}")

    score = duplicate_score(body, history_texts)
    if score >= duplicate_threshold:
        reasons.append(f"duplicate_score_too_high:{score:.3f}")

    return GuardrailResult(passed=not reasons, reasons=reasons, duplicate_score=score)
