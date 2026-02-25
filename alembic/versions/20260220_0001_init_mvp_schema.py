"""init mvp schema

Revision ID: 20260220_0001
Revises:
Create Date: 2026-02-20 02:15:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260220_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


account_status = sa.Enum("ACTIVE", "INACTIVE", name="account_status")
channel_type = sa.Enum("THREADS", "INSTAGRAM", name="channel_type")
job_type = sa.Enum("THREADS_ROOT", "THREADS_REPLY", "INSTAGRAM_CAROUSEL", name="job_type")
job_status = sa.Enum(
    "PENDING",
    "RUNNING",
    "RETRYING",
    "SUCCESS",
    "FAILED",
    "CANCELLED",
    name="job_status",
)
content_status = sa.Enum(
    "DRAFT",
    "READY",
    "FAILED",
    "PUBLISHED_PARTIAL",
    "PUBLISHED_ALL",
    name="content_status",
)
source_type = sa.Enum("PRODUCT_URL", "SEARCH_URL", name="source_type")
improve_run_type = sa.Enum("DAILY", "WEEKLY", name="improve_run_type")


def upgrade() -> None:
    op.create_table(
        "threads_account",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("threads_user_id", sa.String(length=64), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", account_status, nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("threads_user_id"),
    )
    op.create_index("idx_threads_account_status", "threads_account", ["status"])

    op.create_table(
        "instagram_account",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("ig_user_id", sa.String(length=64), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", account_status, nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ig_user_id"),
    )
    op.create_index("idx_instagram_account_status", "instagram_account", ["status"])

    op.create_table(
        "content_source_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("topic", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="50"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("topic", "source_url", name="uq_source_topic_url"),
    )
    op.create_index(
        "idx_source_active_priority", "content_source_item", ["active", "priority"], unique=False
    )

    op.create_table(
        "deeplink_cache",
        sa.Column("original_url_hash", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("short_url", sa.Text(), nullable=False),
        sa.Column("vendor", sa.String(length=20), nullable=False, server_default="COUPANG"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("original_url", name="uq_deeplink_original_url"),
    )
    op.create_index("idx_deeplink_expires_at", "deeplink_cache", ["expires_at"])

    op.create_table(
        "prompt_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("channel", channel_type, nullable=False),
        sa.Column("account_ref", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("disclosure_line", sa.Text(), nullable=False),
        sa.Column("hook_template_weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("style_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("banned_words", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("channel", "account_ref", "version", name="uq_prompt_profile"),
    )

    op.create_table(
        "content_unit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("biz_date", sa.Date(), nullable=False),
        sa.Column("slot_no", sa.SmallInteger(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("original_coupang_url", sa.Text(), nullable=False),
        sa.Column("coupang_short_url", sa.Text(), nullable=False),
        sa.Column("threads_body", sa.Text(), nullable=False),
        sa.Column("threads_first_reply", sa.Text(), nullable=False),
        sa.Column("instagram_caption", sa.Text(), nullable=False),
        sa.Column("slide_script", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("guardrail_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("duplicate_score", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("quality_score", sa.Numeric(6, 3), nullable=False, server_default="0"),
        sa.Column("generation_status", content_status, nullable=False, server_default="DRAFT"),
        sa.Column("failure_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_item_id"], ["content_source_item.id"]),
        sa.UniqueConstraint("biz_date", "slot_no", name="uq_content_unit_date_slot"),
    )
    op.create_index("idx_content_unit_status", "content_unit", ["generation_status"])
    op.create_index("idx_content_unit_schedule", "content_unit", ["scheduled_at"])

    op.create_table(
        "rendered_asset",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("content_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slide_no", sa.SmallInteger(), nullable=False),
        sa.Column("gcs_uri", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["content_unit_id"], ["content_unit.id"]),
        sa.UniqueConstraint("content_unit_id", "slide_no", name="uq_rendered_asset"),
        sa.UniqueConstraint("gcs_uri"),
    )

    op.create_table(
        "post_job",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("content_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", channel_type, nullable=False),
        sa.Column("job_type", job_type, nullable=False),
        sa.Column("account_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("cloud_task_name", sa.String(length=256), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["content_unit_id"], ["content_unit.id"]),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("cloud_task_name"),
    )
    op.create_index("idx_post_job_sched", "post_job", ["status", "scheduled_at"])
    op.create_index("idx_post_job_retry", "post_job", ["status", "next_retry_at"])

    op.create_table(
        "threads_post",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("content_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("threads_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("root_post_id", sa.String(length=64), nullable=True),
        sa.Column("first_reply_id", sa.String(length=64), nullable=True),
        sa.Column("root_text", sa.Text(), nullable=False),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("root_permalink", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reply_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["content_unit_id"], ["content_unit.id"]),
        sa.ForeignKeyConstraint(["threads_account_id"], ["threads_account.id"]),
        sa.UniqueConstraint("content_unit_id"),
        sa.UniqueConstraint("root_post_id"),
        sa.UniqueConstraint("first_reply_id"),
    )

    op.create_table(
        "instagram_post",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("content_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instagram_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_container_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("carousel_creation_id", sa.String(length=64), nullable=True),
        sa.Column("carousel_media_id", sa.String(length=64), nullable=True),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["content_unit_id"], ["content_unit.id"]),
        sa.ForeignKeyConstraint(["instagram_account_id"], ["instagram_account.id"]),
        sa.UniqueConstraint("content_unit_id"),
        sa.UniqueConstraint("carousel_media_id"),
    )

    op.create_table(
        "threads_insight",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("threads_post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_id", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("likes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("replies", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reposts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quotes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shares", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["threads_post_id"], ["threads_post.id"]),
        sa.UniqueConstraint("media_id", "captured_at", name="uq_threads_insight"),
    )
    op.create_index(
        "idx_threads_insight_post_time", "threads_insight", ["threads_post_id", "captured_at"]
    )

    op.create_table(
        "instagram_insight",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("instagram_post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reach", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("likes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("saves", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["instagram_post_id"], ["instagram_post.id"]),
    )

    op.create_table(
        "improvement_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_type", improve_run_type, nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("before_profile_version", sa.Integer(), nullable=False),
        sa.Column("after_profile_version", sa.Integer(), nullable=False),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_type", "run_date", name="uq_improvement_run"),
    )


def downgrade() -> None:
    op.drop_table("improvement_run")
    op.drop_table("instagram_insight")
    op.drop_index("idx_threads_insight_post_time", table_name="threads_insight")
    op.drop_table("threads_insight")
    op.drop_table("instagram_post")
    op.drop_table("threads_post")
    op.drop_index("idx_post_job_retry", table_name="post_job")
    op.drop_index("idx_post_job_sched", table_name="post_job")
    op.drop_table("post_job")
    op.drop_table("rendered_asset")
    op.drop_index("idx_content_unit_schedule", table_name="content_unit")
    op.drop_index("idx_content_unit_status", table_name="content_unit")
    op.drop_table("content_unit")
    op.drop_table("prompt_profile")
    op.drop_index("idx_deeplink_expires_at", table_name="deeplink_cache")
    op.drop_table("deeplink_cache")
    op.drop_index("idx_source_active_priority", table_name="content_source_item")
    op.drop_table("content_source_item")
    op.drop_index("idx_instagram_account_status", table_name="instagram_account")
    op.drop_table("instagram_account")
    op.drop_index("idx_threads_account_status", table_name="threads_account")
    op.drop_table("threads_account")
