# 자동화 프롬프트 세트 (MVP)

## 1) 콘텐츠 생성 프롬프트

목적:
- Threads 본문/첫 댓글
- Instagram 캡션
- 카드뉴스 5~7장 문구

핵심 제약:
- 본문 첫 줄 고지문 강제
- 본문 500자 이하
- `링크는 첫 댓글` 문구 강제
- 댓글에 고지 + 쿠팡 링크 포함
- 인스타 캡션은 `프로필 링크` 유도
- 금칙어(완치/100%/무조건/절대/기적) 금지

코드 위치:
- `/Users/johanjin/Downloads/마케닥 스튜디오 자료/cpang jehyu/app/services/prompt_templates.py`
- 함수: `build_content_generation_prompt`

## 2) 주간 훅 템플릿 생성 프롬프트

목적:
- 전주 상위 성과 키워드로 훅 템플릿 3개 생성
- 다음 주 콘텐츠 생성 가이드에 주입

핵심 제약:
- JSON만 출력
- 정확히 3개
- 각 문장 14~36자
- 과장/낚시 표현 금지
- 서로 다른 의미

코드 위치:
- `/Users/johanjin/Downloads/마케닥 스튜디오 자료/cpang jehyu/app/services/prompt_templates.py`
- 함수: `build_weekly_hook_prompt`

## 3) 적용 경로

- 콘텐츠 생성:
  - `/Users/johanjin/Downloads/마케닥 스튜디오 자료/cpang jehyu/app/services/content_provider.py`
  - `generate_content_payload` -> Gemini 호출 시 프롬프트 적용
- 주간 개선:
  - `/Users/johanjin/Downloads/마케닥 스튜디오 자료/cpang jehyu/app/services/improvement_service.py`
  - `run_weekly_improvement` -> `weekly_hook_templates` 생성 및 `prompt_profile.style_params` 저장
- 생성기 반영:
  - `/Users/johanjin/Downloads/마케닥 스튜디오 자료/cpang jehyu/app/services/generation_service.py`
  - 활성 `prompt_profile`의 금칙어/훅/목표길이를 읽어 LLM 생성 입력에 반영

