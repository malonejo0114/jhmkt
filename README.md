# cpang-jehyu-mvp

Threads + Instagram 제휴마케팅 자동화 MVP.

핵심 흐름:
- 매일 네이버 트렌드 동기화(옵션) -> seed 보강
- 콘텐츠 자동 생성(쿠팡 딥링크 포함)
- 운영자 검수/수정/승인
- 승인된 건만 스케줄/큐 적재 후 발행

## 1) 로컬 실행

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
make db-up
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55432/cpang_jehyu alembic upgrade head
uvicorn app.main:app --reload --port 8080
```

- Swagger: `http://localhost:8080/docs`
- 랜딩: `http://localhost:8080/`
- 로그인: `http://localhost:8080/auth/login`
- 회원가입: `http://localhost:8080/auth/register`
- 운영앱: `http://localhost:8080/app`

## 2) 기능 요약

- 세션 로그인/회원가입
- Threads/Instagram 계정 연동
  - OAuth 연동 버튼(`연동하기`)
  - 실패 시 수동 토큰 입력 fallback
- Seed 등록
  - 수동 입력
  - 네이버 DataLab 트렌드 동기화로 자동 seed upsert
- 콘텐츠 생성(일 2~3개)
  - 고지문 첫 줄 강제
  - Threads 본문 + 첫댓글 + Instagram 캡션 + 5~7 슬라이드 문구
- 검수 큐
  - 문구 수정
  - 승인/반려
  - 승인 시 자동 스케줄 생성 + 큐 적재 시도
- 발행/재시도/성과 수집/개선 루프

## 3) 주요 엔드포인트

### 인증/웹
- `GET /`
- `GET /auth/login`
- `POST /auth/login`
- `GET /auth/register`
- `POST /auth/register`
- `POST /auth/logout`
- `GET /auth/connect/{provider}/start` (`provider=threads|instagram`)
- `GET /auth/connect/{provider}/callback`
- `GET /app`

### Admin API
- `POST /admin/accounts/threads`
- `POST /admin/accounts/instagram`
- `POST /admin/seeds/import`
- `POST /admin/generate/today`
- `POST /admin/schedule/today`
- `POST /admin/enqueue/today`
- `POST /admin/dispatch/due`
- `POST /admin/jobs/{id}/retry`
- `GET /admin/dashboard`
- `POST /admin/trends/naver/sync`
- `GET /admin/review/queue`
- `POST /admin/content-units/{id}/approve`
- `POST /admin/content-units/{id}/reject`
- `PUT /admin/content-units/{id}`

### Internal (Cloud Scheduler/Tasks 호출용)
- `POST /cron/daily-bootstrap`
- `POST /cron/improve/daily`
- `POST /cron/improve/weekly`
- `POST /tasks/publish/threads`
- `POST /tasks/publish/instagram`
- `POST /tasks/insights/threads`
- `POST /tasks/local/dispatch-due`

## 4) 실행 모드

- `RUN_MODE=mock`
  - Threads/Instagram/Coupang/Gemini 실제 호출 없음
  - 로컬 E2E 검증용
- `RUN_MODE=live`
  - 외부 API 실제 호출
  - API 키/토큰 필수

## 5) 필수 환경변수 체크

- 공통
  - `DATABASE_URL`
  - `SESSION_SECRET`
  - `TOKEN_ENCRYPTION_KEY`
  - `INTERNAL_API_KEY`
- 쿠팡 딥링크
  - `COUPANG_ACCESS_KEY`
  - `COUPANG_SECRET_KEY`
- 네이버 트렌드
  - `NAVER_TREND_ENABLED=true`
  - `NAVER_CLIENT_ID`
  - `NAVER_CLIENT_SECRET`
  - `NAVER_TREND_KEYWORDS`
- Meta OAuth 연동
  - `OAUTH_ENABLED=true`
  - `PUBLIC_BASE_URL`
  - `THREADS_APP_ID`
  - `THREADS_APP_SECRET`
  - `INSTAGRAM_APP_ID`
  - `INSTAGRAM_APP_SECRET`
  - (fallback) `META_APP_ID`, `META_APP_SECRET`
- Gemini(옵션)
  - `GEMINI_API_KEY`
  - `GEMINI_MODEL`
- Cloud Tasks
  - `CLOUD_TASKS_ENABLED=true`
  - `CLOUD_TASKS_PROJECT_ID`
  - `CLOUD_TASKS_LOCATION`
  - `QUEUE_TARGET_BASE_URL`

## 6) 로컬 검증 플로우

1. `/auth/register` 가입 -> 로그인
2. `/app`에서 계정 연동(또는 수동 등록)
3. seed 등록 또는 `네이버 트렌드 동기화 실행`
4. `오늘 콘텐츠 생성`
5. 검수 큐에서 수정/승인
6. 승인 시 자동으로 스케줄/큐 적재됨
7. `RUN_MODE=mock` + `CLOUD_TASKS_ENABLED=false` 환경에서는 `디스패치 실행`으로 즉시 발행 테스트

## 7) GCP 배포

- `/infra/cloud_run_bootstrap.md` 참고
- Cloud Run + Cloud Scheduler + Cloud Tasks 구조

## 8) Make 명령

```bash
make install
make db-up
make migrate
make run
make smoke
make db-down
```

## 9) 프롬프트 문서

- 자동화 프롬프트 정의: `/Users/johanjin/Downloads/마케닥 스튜디오 자료/cpang jehyu/docs/automation_prompts_ko.md`
