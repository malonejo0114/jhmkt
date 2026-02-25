from __future__ import annotations

from datetime import timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models import ContentUnit, JobStatus, PostJob, ThreadsInsight, ThreadsPost
from app.services.time_utils import kst_today


def get_dashboard_last_7_days(db: Session) -> dict:
    today = kst_today()
    rows = []

    total_units = 0
    total_jobs_success = 0
    total_jobs_failed = 0
    total_jobs_pending = 0
    total_views = 0
    total_likes = 0
    total_replies = 0

    for delta in range(6, -1, -1):
        day = today - timedelta(days=delta)

        unit_count = (
            db.execute(select(func.count(ContentUnit.id)).where(ContentUnit.biz_date == day)).scalar() or 0
        )

        success_count = (
            db.execute(
                select(func.count(PostJob.id))
                .join(ContentUnit, ContentUnit.id == PostJob.content_unit_id)
                .where(and_(ContentUnit.biz_date == day, PostJob.status == JobStatus.SUCCESS))
            ).scalar()
            or 0
        )
        failed_count = (
            db.execute(
                select(func.count(PostJob.id))
                .join(ContentUnit, ContentUnit.id == PostJob.content_unit_id)
                .where(and_(ContentUnit.biz_date == day, PostJob.status == JobStatus.FAILED))
            ).scalar()
            or 0
        )
        pending_count = (
            db.execute(
                select(func.count(PostJob.id))
                .join(ContentUnit, ContentUnit.id == PostJob.content_unit_id)
                .where(
                    and_(
                        ContentUnit.biz_date == day,
                        PostJob.status.in_([JobStatus.PENDING, JobStatus.RETRYING, JobStatus.RUNNING]),
                    )
                )
            ).scalar()
            or 0
        )

        post_ids = (
            db.execute(
                select(ThreadsPost.id)
                .join(ContentUnit, ContentUnit.id == ThreadsPost.content_unit_id)
                .where(ContentUnit.biz_date == day)
            )
            .scalars()
            .all()
        )

        views = likes = replies = 0
        for post_id in post_ids:
            latest = (
                db.execute(
                    select(ThreadsInsight)
                    .where(ThreadsInsight.threads_post_id == post_id)
                    .order_by(ThreadsInsight.captured_at.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if latest:
                views += latest.views
                likes += latest.likes
                replies += latest.replies

        rows.append(
            {
                "biz_date": day,
                "content_units": unit_count,
                "jobs_success": success_count,
                "jobs_failed": failed_count,
                "jobs_pending": pending_count,
                "threads_views": views,
                "threads_likes": likes,
                "threads_replies": replies,
            }
        )

        total_units += unit_count
        total_jobs_success += success_count
        total_jobs_failed += failed_count
        total_jobs_pending += pending_count
        total_views += views
        total_likes += likes
        total_replies += replies

    return {
        "last_7_days": rows,
        "totals": {
            "content_units": total_units,
            "jobs_success": total_jobs_success,
            "jobs_failed": total_jobs_failed,
            "jobs_pending": total_jobs_pending,
            "threads_views": total_views,
            "threads_likes": total_likes,
            "threads_replies": total_replies,
        },
    }
