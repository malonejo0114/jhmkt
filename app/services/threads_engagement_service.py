from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AccountStatus,
    BrandProfile,
    CommentEventStatus,
    ReplyJobStatus,
    ThreadsAccount,
    ThreadsCommentEvent,
    ThreadsPost,
    ThreadsReplyJob,
)
from app.services.content_provider import generate_comment_reply
from app.services.exceptions import PermanentPublishError, TransientPublishError
from app.services.hash_utils import sha256_hex
from app.services.publisher_service import list_threads_comments, send_threads_comment_reply
from app.services.retry_policy import next_retry_at
from app.services.saju_manseryeok_service import build_saju_reply_context


def ensure_threads_engagement_tables(db: Session) -> None:
    bind = db.get_bind()
    if bind is None:
        return
    with bind.begin() as conn:
        ThreadsCommentEvent.__table__.create(bind=conn, checkfirst=True)
        ThreadsReplyJob.__table__.create(bind=conn, checkfirst=True)


def _threads_event_hash(
    *,
    threads_account_id: UUID,
    root_post_id: str,
    item: dict[str, Any],
) -> str:
    canonical = {
        "threads_account_id": str(threads_account_id),
        "root_post_id": root_post_id,
        "reply_id": item.get("reply_id"),
        "text": item.get("text"),
        "created_at": item.get("created_at"),
        "from_id": item.get("from_id"),
    }
    return sha256_hex(json.dumps(canonical, sort_keys=True, ensure_ascii=False))


def _resolve_threads_style_prompt(db: Session, account: ThreadsAccount) -> str:
    if not account.brand_profile_id:
        return ""
    profile = db.get(BrandProfile, account.brand_profile_id)
    if profile and profile.comment_style_prompt:
        return profile.comment_style_prompt.strip()
    return ""


def _load_related_user_history_texts(
    db: Session,
    event: ThreadsCommentEvent,
    *,
    limit: int = 50,
) -> list[str]:
    user_filters = []
    if event.external_from_id:
        user_filters.append(ThreadsCommentEvent.external_from_id == event.external_from_id)
    if event.external_from_username:
        user_filters.append(ThreadsCommentEvent.external_from_username == event.external_from_username)
    if not user_filters:
        return []

    where_filters = [
        ThreadsCommentEvent.threads_account_id == event.threads_account_id,
        ThreadsCommentEvent.id != event.id,
        or_(*user_filters),
    ]
    if event.external_media_id:
        where_filters.append(ThreadsCommentEvent.external_media_id == event.external_media_id)

    return [
        str(text).strip()
        for text in db.execute(
            select(ThreadsCommentEvent.reply_text)
            .where(and_(*where_filters))
            .order_by(ThreadsCommentEvent.created_at.asc())
            .limit(max(1, min(limit, 200)))
        ).scalars()
        if str(text).strip()
    ]


def _infer_saju_topic(question: str) -> str:
    text = question.replace(" ", "")
    if any(token in text for token in ("연애", "사랑", "결혼", "이별", "재회", "썸")):
        return "연애운"
    if any(token in text for token in ("금전", "재물", "돈", "투자", "수입", "지출")):
        return "금전운"
    if any(token in text for token in ("직장", "취업", "이직", "사업", "승진", "커리어")):
        return "직업운"
    if any(token in text for token in ("건강", "몸", "컨디션", "병원", "질병")):
        return "건강운"
    if any(token in text for token in ("학업", "시험", "공부", "입시")):
        return "학업운"
    return "종합운"


def _build_saju_topic_fallback(topic: str, pillars_kor: str) -> str:
    by_topic = {
        "연애운": f"{pillars_kor} 기준 연애운은 서두르기보다 대화 속도를 맞추는 쪽이 유리합니다.",
        "금전운": f"{pillars_kor} 기준 금전운은 큰 베팅보다 지출 통제와 분산이 더 유리합니다.",
        "직업운": f"{pillars_kor} 기준 직업운은 방향 전환보다 현재 루틴 고도화가 성과에 유리합니다.",
        "건강운": f"{pillars_kor} 기준 건강운은 무리한 강도보다 수면·회복 리듬 관리가 더 중요합니다.",
        "학업운": f"{pillars_kor} 기준 학업운은 과목 확장보다 약점 한 과목 집중 보완이 유리합니다.",
        "종합운": f"{pillars_kor} 기준 종합운은 급한 결정 대신 순서 정리 후 실행하는 흐름이 유리합니다.",
    }
    return by_topic.get(topic, by_topic["종합운"])


def _render_threads_reply_text(db: Session, account: ThreadsAccount, event: ThreadsCommentEvent) -> str:
    settings = get_settings()
    fallback = "댓글 감사합니다. 생년월일(양력)과 태어난 시간을 알려주시면 만세력 기준으로 답변드릴게요."
    style_prompt = _resolve_threads_style_prompt(db, account)

    history_texts = _load_related_user_history_texts(db, event)
    saju_ctx = build_saju_reply_context(event.reply_text or "", history_texts)
    if saju_ctx.error_message:
        return saju_ctx.error_message

    if saju_ctx.has_birth_hint and not saju_ctx.is_complete:
        if saju_ctx.missing_fields:
            missing = ", ".join(saju_ctx.missing_fields)
            return f"좋아요. {missing} 알려주시면 만세력 기준으로 한 줄로 답해드릴게요."
        return fallback

    if saju_ctx.is_complete and saju_ctx.four_pillars:
        question = saju_ctx.question_text or "종합운"
        topic = _infer_saju_topic(question)
        pillars_kor = saju_ctx.four_pillars.korean_string()
        pillars_hanja = saju_ctx.four_pillars.hanja_string()
        saju_style = (
            f"{style_prompt}\n" if style_prompt else ""
        ) + (
            "만세력 기반 한 줄 답변. 단정/공포 조장 금지, 실천 팁 중심.\n"
            f"질문 주제: {topic}\n"
            f"출생정보: {saju_ctx.birth_summary}\n"
            f"사주(한글): {pillars_kor}\n"
            f"사주(한자): {pillars_hanja}\n"
            f"질문: {question}\n"
            "답변 규칙: 질문 주제를 직접 언급하고, 사주(일주/시주) 근거를 짧게 포함하며, 한국어 한 문장으로 작성."
        )
        answer_fallback = _build_saju_topic_fallback(topic, pillars_kor)
        if not settings.engagement_ai_reply_enabled:
            return answer_fallback
        return (
            generate_comment_reply(
                comment_text=question,
                keyword="threads_saju_comment",
                style_prompt=saju_style,
                fallback_reply=answer_fallback,
                max_chars=settings.engagement_ai_reply_max_chars,
            ).strip()
            or answer_fallback
        )

    style_prompt = (
        f"{style_prompt}\n한 줄로 간결하게 답변하고, 사주 질문이면 생년월일(양력)과 생시를 요청하세요."
        if style_prompt
        else "친절하고 간결한 한 줄 답변. 사주 질문이면 생년월일(양력)과 생시를 요청."
    )
    if not settings.engagement_ai_reply_enabled:
        return fallback
    reply = generate_comment_reply(
        comment_text=event.reply_text or "",
        keyword="threads_comment",
        style_prompt=style_prompt,
        fallback_reply=fallback,
        max_chars=settings.engagement_ai_reply_max_chars,
    )
    return reply.strip() or fallback


def ingest_threads_comment_events_polling(
    db: Session,
    *,
    limit_posts_per_account: int = 20,
    limit_comments_per_post: int = 50,
    threads_account_id: UUID | None = None,
) -> dict[str, Any]:
    ensure_threads_engagement_tables(db)
    settings = get_settings()
    if not settings.engagement_enabled:
        return {"status": "SKIPPED_DISABLED", "created_events": 0}

    post_limit = max(1, min(limit_posts_per_account, 100))
    comment_limit = max(1, min(limit_comments_per_post, 100))

    accounts = (
        db.execute(
            select(ThreadsAccount)
            .where(
                ThreadsAccount.status == AccountStatus.ACTIVE,
                ThreadsAccount.id == threads_account_id if threads_account_id else True,
            )
            .order_by(ThreadsAccount.created_at.asc())
        )
        .scalars()
        .all()
    )

    created = 0
    poll_errors = 0
    scanned_posts = 0
    scanned_comments = 0
    skipped_duplicate = 0

    for account in accounts:
        posts = (
            db.execute(
                select(ThreadsPost)
                .where(
                    ThreadsPost.threads_account_id == account.id,
                    ThreadsPost.root_post_id.is_not(None),
                )
                .order_by(ThreadsPost.created_at.desc())
                .limit(post_limit)
            )
            .scalars()
            .all()
        )
        for post in posts:
            root_post_id = str(post.root_post_id or "").strip()
            if not root_post_id:
                continue
            try:
                comments = list_threads_comments(
                    account=account,
                    media_id=root_post_id,
                    limit=comment_limit,
                )
            except Exception:  # noqa: BLE001
                poll_errors += 1
                continue

            scanned_posts += 1
            scanned_comments += len(comments)

            for item in comments:
                if not item.reply_id:
                    continue
                if item.parent_reply_id and item.parent_reply_id != root_post_id:
                    continue
                canonical = {
                    "reply_id": item.reply_id,
                    "text": item.text,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "from_id": item.from_id,
                }
                ev_hash = _threads_event_hash(
                    threads_account_id=account.id,
                    root_post_id=root_post_id,
                    item=canonical,
                )
                exists = (
                    db.execute(select(ThreadsCommentEvent).where(ThreadsCommentEvent.event_hash == ev_hash))
                    .scalars()
                    .first()
                )
                if exists:
                    skipped_duplicate += 1
                    continue

                exists_by_reply = (
                    db.execute(
                        select(ThreadsCommentEvent).where(
                            ThreadsCommentEvent.threads_account_id == account.id,
                            ThreadsCommentEvent.external_reply_id == item.reply_id,
                        )
                    )
                    .scalars()
                    .first()
                )
                if exists_by_reply:
                    skipped_duplicate += 1
                    continue

                db.add(
                    ThreadsCommentEvent(
                        threads_account_id=account.id,
                        external_reply_id=item.reply_id,
                        external_media_id=item.media_id or root_post_id,
                        external_parent_reply_id=item.parent_reply_id,
                        external_from_id=item.from_id,
                        external_from_username=item.username,
                        reply_text=item.text or "",
                        reply_created_at=item.created_at,
                        status=CommentEventStatus.PENDING,
                        status_reason=None,
                        event_hash=ev_hash,
                        raw_payload={
                            "root_post_id": root_post_id,
                            "reply": item.raw_payload,
                        },
                    )
                )
                created += 1

    db.commit()
    return {
        "status": "SUCCESS",
        "accounts": len(accounts),
        "scanned_posts": scanned_posts,
        "scanned_comments": scanned_comments,
        "created_events": created,
        "skipped_duplicate": skipped_duplicate,
        "poll_errors": poll_errors,
    }


def create_threads_reply_jobs_for_pending_events(
    db: Session,
    limit: int = 100,
    *,
    threads_account_id: UUID | None = None,
) -> dict[str, Any]:
    ensure_threads_engagement_tables(db)
    settings = get_settings()
    if not settings.engagement_enabled:
        return {"status": "SKIPPED_DISABLED", "created_jobs": 0, "skipped_events": 0}

    events = (
        db.execute(
            select(ThreadsCommentEvent)
            .where(
                ThreadsCommentEvent.status == CommentEventStatus.PENDING,
                ThreadsCommentEvent.threads_account_id == threads_account_id if threads_account_id else True,
            )
            .order_by(ThreadsCommentEvent.created_at.asc())
            .limit(max(1, min(limit, 500)))
        )
        .scalars()
        .all()
    )

    created_jobs = 0
    skipped_events = 0

    for event in events:
        account = db.get(ThreadsAccount, event.threads_account_id)
        if not account:
            event.status = CommentEventStatus.SKIPPED
            event.status_reason = "ACCOUNT_NOT_FOUND"
            skipped_events += 1
            continue

        if event.external_from_id and event.external_from_id == account.threads_user_id:
            event.status = CommentEventStatus.SKIPPED
            event.status_reason = "SELF_REPLY"
            skipped_events += 1
            continue

        idem = sha256_hex(f"{event.threads_account_id}|{event.external_reply_id}|PUBLIC_REPLY")
        exists_job = (
            db.execute(select(ThreadsReplyJob).where(ThreadsReplyJob.idempotency_key == idem))
            .scalars()
            .first()
        )
        if exists_job:
            event.status = CommentEventStatus.PROCESSED
            event.status_reason = "JOB_DUPLICATE"
            continue

        reply_text = _render_threads_reply_text(db, account, event)
        db.add(
            ThreadsReplyJob(
                comment_event_id=event.id,
                threads_account_id=event.threads_account_id,
                reply_text=reply_text,
                status=ReplyJobStatus.PENDING,
                attempts=0,
                max_attempts=3,
                idempotency_key=idem,
                external_reply_id=event.external_reply_id,
            )
        )
        event.status = CommentEventStatus.PROCESSED
        event.status_reason = "JOB_CREATED"
        created_jobs += 1

    db.commit()
    return {
        "status": "SUCCESS",
        "pending_events": len(events),
        "created_jobs": created_jobs,
        "skipped_events": skipped_events,
    }


def _extract_error_code(exc: Exception) -> str:
    if isinstance(exc, (TransientPublishError, PermanentPublishError)):
        return exc.code
    return "SEND_UNKNOWN"


def process_pending_threads_reply_jobs(
    db: Session,
    limit: int = 50,
    *,
    threads_account_id: UUID | None = None,
) -> dict[str, Any]:
    ensure_threads_engagement_tables(db)
    now = datetime.now(timezone.utc)
    jobs = (
        db.execute(
            select(ThreadsReplyJob)
            .where(
                and_(
                    ThreadsReplyJob.status == ReplyJobStatus.PENDING,
                    ThreadsReplyJob.threads_account_id == threads_account_id if threads_account_id else True,
                    or_(ThreadsReplyJob.next_retry_at.is_(None), ThreadsReplyJob.next_retry_at <= now),
                )
            )
            .order_by(ThreadsReplyJob.created_at.asc())
            .limit(max(1, min(limit, 200)))
        )
        .scalars()
        .all()
    )

    sent = 0
    failed = 0
    retrying = 0
    skipped = 0

    for job in jobs:
        event = db.get(ThreadsCommentEvent, job.comment_event_id)
        account = db.get(ThreadsAccount, job.threads_account_id)
        if not event or not account:
            job.status = ReplyJobStatus.SKIPPED
            job.skip_reason = "MISSING_REF"
            job.last_error_code = "MISSING_REF"
            job.last_error_message = "threads_comment_event 또는 threads_account 참조가 없습니다."
            skipped += 1
            continue

        job.status = ReplyJobStatus.RUNNING
        job.attempts += 1
        db.flush()

        try:
            sent_reply_id = send_threads_comment_reply(
                account=account,
                reply_to_id=event.external_reply_id,
                message=job.reply_text,
            )
            job.status = ReplyJobStatus.SENT
            job.sent_at = datetime.now(timezone.utc)
            job.next_retry_at = None
            job.last_error_code = None
            job.last_error_message = None
            job.skip_reason = None
            job.external_reply_id = sent_reply_id
            sent += 1
        except Exception as exc:  # noqa: BLE001
            job.last_error_code = _extract_error_code(exc)
            job.last_error_message = str(exc)[:2000]
            if job.attempts >= job.max_attempts:
                job.status = ReplyJobStatus.FAILED
                job.next_retry_at = None
                job.skip_reason = "MAX_ATTEMPTS"
                failed += 1
            else:
                job.status = ReplyJobStatus.PENDING
                job.next_retry_at = next_retry_at(job.attempts)
                job.skip_reason = "RETRY_SCHEDULED"
                retrying += 1

    db.commit()
    return {
        "status": "SUCCESS",
        "total": len(jobs),
        "sent": sent,
        "failed": failed,
        "retrying": retrying,
        "skipped": skipped,
    }


def retry_threads_reply_job(db: Session, reply_job_id: UUID) -> ThreadsReplyJob:
    ensure_threads_engagement_tables(db)
    job = db.get(ThreadsReplyJob, reply_job_id)
    if not job:
        raise ValueError(f"threads_reply_job_id={reply_job_id} not found")

    if job.status == ReplyJobStatus.RUNNING:
        raise ValueError("RUNNING 상태의 threads reply job은 수동 재처리할 수 없습니다.")
    if job.status == ReplyJobStatus.SENT:
        raise ValueError("SENT 상태의 threads reply job은 수동 재처리할 수 없습니다.")

    job.status = ReplyJobStatus.PENDING
    job.skip_reason = None
    job.next_retry_at = datetime.now(timezone.utc)
    job.last_error_code = None
    job.last_error_message = None
    job.attempts = 0
    db.commit()
    db.refresh(job)
    return job


def list_threads_comment_events(db: Session, limit: int = 100) -> list[ThreadsCommentEvent]:
    ensure_threads_engagement_tables(db)
    return (
        db.execute(
            select(ThreadsCommentEvent)
            .order_by(ThreadsCommentEvent.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
        .scalars()
        .all()
    )


def list_threads_reply_jobs(db: Session, limit: int = 100) -> list[ThreadsReplyJob]:
    ensure_threads_engagement_tables(db)
    return (
        db.execute(
            select(ThreadsReplyJob)
            .order_by(ThreadsReplyJob.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
        .scalars()
        .all()
    )
