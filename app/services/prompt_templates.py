from __future__ import annotations

from textwrap import dedent

DEFAULT_BANNED_WORDS = ["완치", "100%", "무조건", "절대", "기적"]


def build_content_generation_prompt(
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
) -> str:
    banned = banned_words or DEFAULT_BANNED_WORDS
    hooks = hook_candidates or ["체크리스트", "문제해결", "비교"]
    tone_label = "존댓말" if tone_style == "FORMAL" else "반말"
    emoji_label = "허용" if emoji_mode == "ON" else "금지"
    clean_disclosure = disclosure_line.strip()
    disclosure_rule = (
        f"1) threads_body에는 아래 고지문을 포함하지 말 것:\n        {clean_disclosure}"
        if clean_disclosure
        else "1) threads_body 고지문 제약 없음"
    )
    first_reply_rule = (
        f"4) threads_first_reply 첫 줄은 아래 고지문과 완전히 동일하고, 다음 줄에 링크 포함:\n        {clean_disclosure}"
        if clean_disclosure
        else "4) threads_first_reply는 링크를 포함"
    )

    return dedent(
        f"""
        너는 한국어 제휴마케팅 콘텐츠 생성기다.
        반드시 JSON object 하나만 출력하고, 설명 문장은 출력하지 마라.

        출력 스키마:
        {{
          "threads_body": "string",
          "threads_first_reply": "string",
          "instagram_caption": "string",
          "render_options": {{
            "font_style": "sans|serif|mono",
            "background_mode": "google_free|generated|stock",
            "template_style": "campaign|classic"
          }},
          "slides": [
            {{"slide_no": 1, "title": "string", "body": "string"}}
          ]
        }}

        하드 제약:
        {disclosure_rule}
        2) threads_body 전체 길이 500자 이하
        3) threads_body 안에 "링크는 첫 댓글" 문구를 반드시 포함
        {first_reply_rule}
        5) instagram_caption은 "프로필 링크" 유도 문구를 포함
        6) slides는 4~7장, slide_no는 1부터 연속 증가
        7) 과장/의학적 단정 금지어 사용 금지: {", ".join(banned)}
        8) 중복 문장 반복 금지

        스타일 가이드:
        - 추천 훅 유형: {", ".join(hooks)}
        - 목표 본문 길이: 약 {target_chars}자
        - 말투: {tone_label}
        - 이모티콘: {emoji_label}
        - 정보형/체크리스트/비교 중심
        - 첫 훅은 손실회피/주의환기 톤으로 직설적으로 작성
          예: "이거 비교 안 하면 손해 봅니다", "모르면 돈만 더 씁니다"
        - 단, 욕설/비하/협박/허위 단정 금지
        - 건강/의학 주제는 생활관리 팁 수준으로만 작성하고,
          치료 단정/절대 표현(예: 완치, 무조건 효과) 금지

        입력:
        - topic: {topic}
        - category: {category}
        - short_url: {short_url}
        - 추가 프롬프트:
        {style_prompt or "없음"}
        """
    ).strip()


def build_weekly_hook_prompt(*, top_terms: list[str], template_count: int = 3) -> str:
    seed_terms = top_terms or ["체크리스트", "비교", "문제해결"]
    return dedent(
        f"""
        너는 한국어 숏카피 라이터다.
        반드시 JSON object 하나만 출력하고, 설명은 출력하지 마라.

        출력 스키마:
        {{
          "hook_templates": ["string", "string", "string"]
        }}

        제약:
        1) hook_templates 길이는 정확히 {template_count}개
        2) 각 훅은 14~36자
        3) 정보형 문장으로 작성 (낚시성 금지)
        4) 과장 표현 금지
        5) 서로 의미가 겹치지 않게 작성

        상위 키워드:
        {", ".join(seed_terms)}
        """
    ).strip()


def build_comment_reply_prompt(
    *,
    comment_text: str,
    keyword: str,
    style_prompt: str,
    max_chars: int = 120,
) -> str:
    return dedent(
        f"""
        너는 인스타 댓글 자동응답 카피라이터다.
        반드시 JSON object 하나만 출력하고, 설명은 출력하지 마라.

        출력 스키마:
        {{
          "reply": "string"
        }}

        제약:
        1) reply 길이 {max_chars}자 이하
        2) 과장/허위/의학적 단정 금지
        3) 욕설/비하/정치/종교 논쟁 유도 금지
        4) 판매 유도 문구는 한 문장 이내
        5) 한국어로 작성

        운영 스타일:
        {style_prompt or "친절하고 간결하게, 행동 유도는 짧게."}

        입력:
        - 댓글 원문: {comment_text}
        - 트리거 키워드: {keyword}
        """
    ).strip()
