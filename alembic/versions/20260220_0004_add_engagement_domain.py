"""add engagement automation domain tables

Revision ID: 20260220_0004
Revises: 20260220_0003
Create Date: 2026-02-20 16:10:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260220_0004"
down_revision: Union[str, None] = "20260220_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


brand_vertical = postgresql.ENUM("COUPANG", "SAJU", name="brand_vertical", create_type=False)
comment_trigger_type = postgresql.ENUM(
    "KEYWORD", "REGEX", name="comment_trigger_type", create_type=False
)
comment_action_type = postgresql.ENUM(
    "PRIVATE_REPLY", "PUBLIC_REPLY", name="comment_action_type", create_type=False
)
comment_event_status = postgresql.ENUM(
    "PENDING", "PROCESSED", "SKIPPED", "FAILED", name="comment_event_status", create_type=False
)
reply_job_status = postgresql.ENUM(
    "PENDING", "RUNNING", "SENT", "SKIPPED", "FAILED", name="reply_job_status", create_type=False
)
quota_bucket_type = postgresql.ENUM("HOURLY", "DAILY", name="quota_bucket_type", create_type=False)


def upgrade() -> None:
    brand_vertical.create(op.get_bind(), checkfirst=True)
    comment_trigger_type.create(op.get_bind(), checkfirst=True)
    comment_action_type.create(op.get_bind(), checkfirst=True)
    comment_event_status.create(op.get_bind(), checkfirst=True)
    reply_job_status.create(op.get_bind(), checkfirst=True)
    quota_bucket_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "brand_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("vertical_type", brand_vertical, nullable=False),
        sa.Column("comment_style_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_brand_profile_name"),
    )

    op.add_column("instagram_account", sa.Column("brand_profile_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_instagram_account_brand_profile",
        "instagram_account",
        "brand_profile",
        ["brand_profile_id"],
        ["id"],
    )

    op.create_table(
        "comment_rule",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("instagram_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("trigger_type", comment_trigger_type, nullable=False),
        sa.Column("trigger_value", sa.String(length=120), nullable=False),
        sa.Column("action_type", comment_action_type, nullable=False),
        sa.Column("message_template", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["instagram_account_id"], ["instagram_account.id"]),
        sa.ForeignKeyConstraint(["brand_profile_id"], ["brand_profile.id"]),
        sa.UniqueConstraint(
            "instagram_account_id",
            "trigger_type",
            "trigger_value",
            "action_type",
            name="uq_comment_rule_account_trigger_action",
        ),
    )
    op.create_index("idx_comment_rule_account_active", "comment_rule", ["instagram_account_id", "active"])

    op.create_table(
        "comment_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("instagram_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="META"),
        sa.Column("field", sa.String(length=40), nullable=False),
        sa.Column("external_entry_id", sa.String(length=64), nullable=True),
        sa.Column("external_comment_id", sa.String(length=64), nullable=False),
        sa.Column("external_media_id", sa.String(length=64), nullable=True),
        sa.Column("external_from_id", sa.String(length=64), nullable=True),
        sa.Column("external_from_username", sa.String(length=120), nullable=True),
        sa.Column("comment_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("comment_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", comment_event_status, nullable=False, server_default="PENDING"),
        sa.Column("status_reason", sa.String(length=80), nullable=True),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["instagram_account_id"], ["instagram_account.id"]),
        sa.UniqueConstraint("event_hash", name="uq_comment_event_hash"),
        sa.UniqueConstraint("instagram_account_id", "external_comment_id", name="uq_comment_event_comment"),
    )
    op.create_index("idx_comment_event_status", "comment_event", ["status", "created_at"])

    op.create_table(
        "reply_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("comment_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instagram_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", comment_action_type, nullable=False),
        sa.Column("reply_text", sa.Text(), nullable=False),
        sa.Column("status", reply_job_status, nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("skip_reason", sa.String(length=80), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["comment_event_id"], ["comment_event.id"]),
        sa.ForeignKeyConstraint(["instagram_account_id"], ["instagram_account.id"]),
        sa.ForeignKeyConstraint(["rule_id"], ["comment_rule.id"]),
        sa.UniqueConstraint("idempotency_key", name="uq_reply_job_idempotency"),
    )
    op.create_index("idx_reply_job_status", "reply_job", ["status", "created_at"])

    op.create_table(
        "quota_bucket",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("instagram_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", comment_action_type, nullable=False),
        sa.Column("bucket_type", quota_bucket_type, nullable=False),
        sa.Column("bucket_key", sa.String(length=16), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["instagram_account_id"], ["instagram_account.id"]),
        sa.UniqueConstraint(
            "instagram_account_id",
            "action_type",
            "bucket_type",
            "bucket_key",
            name="uq_quota_bucket",
        ),
    )


def downgrade() -> None:
    op.drop_table("quota_bucket")

    op.drop_index("idx_reply_job_status", table_name="reply_job")
    op.drop_table("reply_job")

    op.drop_index("idx_comment_event_status", table_name="comment_event")
    op.drop_table("comment_event")

    op.drop_index("idx_comment_rule_account_active", table_name="comment_rule")
    op.drop_table("comment_rule")

    op.drop_constraint("fk_instagram_account_brand_profile", "instagram_account", type_="foreignkey")
    op.drop_column("instagram_account", "brand_profile_id")

    op.drop_table("brand_profile")

    quota_bucket_type.drop(op.get_bind(), checkfirst=True)
    reply_job_status.drop(op.get_bind(), checkfirst=True)
    comment_event_status.drop(op.get_bind(), checkfirst=True)
    comment_action_type.drop(op.get_bind(), checkfirst=True)
    comment_trigger_type.drop(op.get_bind(), checkfirst=True)
    brand_vertical.drop(op.get_bind(), checkfirst=True)
