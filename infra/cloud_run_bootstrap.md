# Cloud Run + Scheduler + Tasks bootstrap (MVP)

## 1) Cloud Run 배포

```bash
gcloud run deploy cpang-jehyu-api \
  --source . \
  --region asia-northeast3 \
  --no-allow-unauthenticated \
  --set-env-vars "RUN_MODE=live,CLOUD_TASKS_ENABLED=true,CLOUD_TASKS_PROJECT_ID=<PROJECT_ID>,CLOUD_TASKS_LOCATION=asia-northeast3,QUEUE_TARGET_BASE_URL=https://<CLOUD_RUN_URL>,INTERNAL_API_KEY=<INTERNAL_KEY>,OAUTH_ENABLED=true,PUBLIC_BASE_URL=https://<CLOUD_RUN_URL>,NAVER_TREND_ENABLED=true"
```

권장:
- 민감값(`META_APP_SECRET`, `COUPANG_SECRET_KEY`, `NAVER_CLIENT_SECRET`, `TOKEN_ENCRYPTION_KEY`, `SESSION_SECRET`)은 Secret Manager로 주입
- `DATABASE_URL`은 Cloud SQL 연결 문자열 사용

필수 env 항목 예시:
- `DATABASE_URL`
- `TOKEN_ENCRYPTION_KEY`
- `SESSION_SECRET`
- `INTERNAL_API_KEY`
- `COUPANG_ACCESS_KEY`
- `COUPANG_SECRET_KEY`
- `NAVER_CLIENT_ID`
- `NAVER_CLIENT_SECRET`
- `NAVER_TREND_KEYWORDS`
- `META_APP_ID`
- `META_APP_SECRET`
- `OAUTH_ENABLED=true`
- `PUBLIC_BASE_URL=https://<CLOUD_RUN_URL>`
- `CLOUD_TASKS_ENABLED=true`
- `CLOUD_TASKS_PROJECT_ID=<PROJECT_ID>`
- `QUEUE_TARGET_BASE_URL=https://<CLOUD_RUN_URL>`

## 2) Cloud Tasks 큐 생성

```bash
gcloud tasks queues create q-publish-threads --location=asia-northeast3
gcloud tasks queues create q-publish-instagram --location=asia-northeast3
gcloud tasks queues create q-insights --location=asia-northeast3
gcloud tasks queues create q-improve --location=asia-northeast3
```

## 3) Cloud Scheduler 잡 생성

```bash
# 매일 00:05 KST (네이버 트렌드 동기화 + 콘텐츠 생성 + 승인된 건 스케줄/큐)

gcloud scheduler jobs create http daily-bootstrap \
  --location=asia-northeast3 \
  --schedule="5 0 * * *" \
  --time-zone="Asia/Seoul" \
  --uri="https://<CLOUD_RUN_URL>/cron/daily-bootstrap" \
  --http-method=POST \
  --headers="Content-Type=application/json,X-Internal-Key=<INTERNAL_KEY>" \
  --message-body="{}" \
  --oidc-service-account-email="<SCHEDULER_SA>@<PROJECT>.iam.gserviceaccount.com"

# 매일 01:40 KST
gcloud scheduler jobs create http daily-improve \
  --location=asia-northeast3 \
  --schedule="40 1 * * *" \
  --time-zone="Asia/Seoul" \
  --uri="https://<CLOUD_RUN_URL>/cron/improve/daily" \
  --http-method=POST \
  --headers="Content-Type=application/json,X-Internal-Key=<INTERNAL_KEY>" \
  --message-body="{}" \
  --oidc-service-account-email="<SCHEDULER_SA>@<PROJECT>.iam.gserviceaccount.com"

# 매주 월요일 02:00 KST
gcloud scheduler jobs create http weekly-improve \
  --location=asia-northeast3 \
  --schedule="0 2 * * 1" \
  --time-zone="Asia/Seoul" \
  --uri="https://<CLOUD_RUN_URL>/cron/improve/weekly" \
  --http-method=POST \
  --headers="Content-Type=application/json,X-Internal-Key=<INTERNAL_KEY>" \
  --message-body="{}" \
  --oidc-service-account-email="<SCHEDULER_SA>@<PROJECT>.iam.gserviceaccount.com"
```
