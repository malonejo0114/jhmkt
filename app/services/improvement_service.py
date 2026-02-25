from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    ChannelType,
    ImproveRunType,
    ImprovementRun,
    PromptProfile,
    ThreadsInsight,
    ThreadsPost,
)
from app.services.content_provider import generate_weekly_hook_templates

KST = ZoneInfo("Asia/Seoul")


def _score_row(insight: ThreadsInsight) -> float:
    return (
        insight.views
        + (insight.likes * 3)
        + (insight.replies * 4)
        + (insight.reposts * 5)
        + (insight.quotes * 4)
        + (insight.shares * 4)
    )


def _get_or_create_active_profile(db: Session, channel: ChannelType) -> PromptProfile:
    profile = (
        db.execute(
            select(PromptProfile)
            .where(PromptProfile.channel == channel, PromptProfile.active.is_(True))
            .order_by(PromptProfile.version.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if profile:
        return profile

    settings = get_settings()
    profile = PromptProfile(
        channel=channel,
        account_ref=None,
        version=1,
        disclosure_line=settings.disclosure_line,
        hook_template_weights={"question": 0.34, "checklist": 0.33, "comparison": 0.33},
        style_params={"target_chars": 280, "cta": "first_comment"},
        banned_words={"terms": ["완치", "100%", "무조건", "절대", "기적"]},
        active=True,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def run_daily_improvement(db: Session, target_date: date | None = None) -> dict:
    # target_date defaults to yesterday (KST)
    if target_date is None:
        target_date = (datetime.now(KST) - timedelta(days=1)).date()

    day_start_kst = datetime.combine(target_date, time(0, 0), tzinfo=KST)
    day_end_kst = day_start_kst + timedelta(days=1)
    window_start = day_start_kst.astimezone(timezone.utc)
    window_end = day_end_kst.astimezone(timezone.utc)

    existing = (
        db.execute(
            select(ImprovementRun).where(
                ImprovementRun.run_type == ImproveRunType.DAILY,
                ImprovementRun.run_date == target_date,
            )
        )
        .scalars()
        .first()
    )
    if existing:
        return {
            "run_id": str(existing.id),
            "status": "SKIPPED_ALREADY_RUN",
            "run_date": target_date.isoformat(),
        }

    latest_insights = (
        db.execute(
            select(ThreadsPost, ThreadsInsight)
            .join(ThreadsInsight, ThreadsInsight.threads_post_id == ThreadsPost.id)
            .where(and_(ThreadsInsight.captured_at >= window_start, ThreadsInsight.captured_at < window_end))
            .order_by(ThreadsInsight.captured_at.desc())
        )
        .all()
    )

    best_by_post = {}
    for post, insight in latest_insights:
        current = best_by_post.get(post.id)
        if not current or insight.captured_at > current.captured_at:
            best_by_post[post.id] = insight

    scored = [(post_id, _score_row(ins)) for post_id, ins in best_by_post.items()]
    scored.sort(key=lambda x: x[1], reverse=True)

    top_scores = [s for _, s in scored[:3]]
    bottom_scores = [s for _, s in scored[-3:]] if len(scored) >= 3 else [s for _, s in scored]

    avg_top = (sum(top_scores) / len(top_scores)) if top_scores else 0
    avg_bottom = (sum(bottom_scores) / len(bottom_scores)) if bottom_scores else 0

    profile = _get_or_create_active_profile(db, ChannelType.THREADS)
    before_version = profile.version

    new_weights = dict(profile.hook_template_weights or {})
    uplift = 0.03 if avg_top > avg_bottom else -0.02
    new_weights["question"] = max(0.1, min(0.8, float(new_weights.get("question", 0.33)) + uplift))
    remain = 1.0 - new_weights["question"]
    new_weights["checklist"] = round(remain * 0.55, 4)
    new_weights["comparison"] = round(remain * 0.45, 4)

    # rotate active profile
    profile.active = False
    new_profile = PromptProfile(
        channel=profile.channel,
        account_ref=profile.account_ref,
        version=before_version + 1,
        disclosure_line=profile.disclosure_line,
        hook_template_weights=new_weights,
        style_params=profile.style_params,
        banned_words=profile.banned_words,
        active=True,
    )
    db.add(new_profile)
    db.flush()

    run = ImprovementRun(
        run_type=ImproveRunType.DAILY,
        run_date=target_date,
        window_start=window_start,
        window_end=window_end,
        before_profile_version=before_version,
        after_profile_version=new_profile.version,
        result_json={
            "posts_evaluated": len(scored),
            "avg_top": avg_top,
            "avg_bottom": avg_bottom,
            "weights": new_weights,
        },
        status="SUCCESS",
    )
    db.add(run)
    db.commit()

    return {
        "run_id": str(run.id),
        "status": "SUCCESS",
        "run_date": target_date.isoformat(),
        "posts_evaluated": len(scored),
        "before_profile_version": before_version,
        "after_profile_version": new_profile.version,
    }


def run_weekly_improvement(db: Session, target_date: date | None = None) -> dict:
    # target_date defaults to current week's Monday (KST)
    now_kst = datetime.now(KST)
    if target_date is None:
        target_date = (now_kst - timedelta(days=now_kst.weekday())).date()

    existing = (
        db.execute(
            select(ImprovementRun).where(
                ImprovementRun.run_type == ImproveRunType.WEEKLY,
                ImprovementRun.run_date == target_date,
            )
        )
        .scalars()
        .first()
    )
    if existing:
        return {
            "run_id": str(existing.id),
            "status": "SKIPPED_ALREADY_RUN",
            "run_date": target_date.isoformat(),
        }

    window_start = datetime.combine(target_date, time(0, 0), tzinfo=KST).astimezone(timezone.utc)
    window_end = (window_start + timedelta(days=7))

    # Pull topic frequency of top performing posts
    rows = (
        db.execute(
            select(ThreadsPost.root_text, func.max(ThreadsInsight.views).label("max_views"))
            .join(ThreadsInsight, ThreadsInsight.threads_post_id == ThreadsPost.id)
            .where(and_(ThreadsInsight.captured_at >= window_start, ThreadsInsight.captured_at < window_end))
            .group_by(ThreadsPost.root_text)
            .order_by(func.max(ThreadsInsight.views).desc())
            .limit(20)
        )
        .all()
    )

    tokens = []
    for text, _ in rows:
        parts = [p.strip() for p in str(text).split() if len(p.strip()) >= 2]
        tokens.extend(parts[:6])
    common = Counter(tokens).most_common(3)

    profile = _get_or_create_active_profile(db, ChannelType.THREADS)
    before_version = profile.version
    style_params = dict(profile.style_params or {})
    top_terms = [term for term, _ in common] or ["체크리스트", "비교", "문제해결"]
    style_params["weekly_hook_candidates"] = top_terms
    style_params["weekly_hook_templates"] = generate_weekly_hook_templates(top_terms)

    profile.active = False
    new_profile = PromptProfile(
        channel=profile.channel,
        account_ref=profile.account_ref,
        version=before_version + 1,
        disclosure_line=profile.disclosure_line,
        hook_template_weights=profile.hook_template_weights,
        style_params=style_params,
        banned_words=profile.banned_words,
        active=True,
    )
    db.add(new_profile)
    db.flush()

    run = ImprovementRun(
        run_type=ImproveRunType.WEEKLY,
        run_date=target_date,
        window_start=window_start,
        window_end=window_end,
        before_profile_version=before_version,
        after_profile_version=new_profile.version,
        result_json={
            "top_terms": style_params["weekly_hook_candidates"],
            "hook_templates": style_params["weekly_hook_templates"],
            "rows": len(rows),
        },
        status="SUCCESS",
    )
    db.add(run)
    db.commit()

    return {
        "run_id": str(run.id),
        "status": "SUCCESS",
        "run_date": target_date.isoformat(),
        "before_profile_version": before_version,
        "after_profile_version": new_profile.version,
        "top_terms": style_params["weekly_hook_candidates"],
        "hook_templates": style_params["weekly_hook_templates"],
    }
