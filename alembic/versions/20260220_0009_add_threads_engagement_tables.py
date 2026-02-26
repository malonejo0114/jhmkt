"""add threads engagement tables

Revision ID: 20260220_0009
Revises: 20260220_0008
Create Date: 2026-02-26 13:20:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260220_0009"
down_revision: Union[str, None] = "20260220_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


comment_event_status = postgresql.ENUM(
    "PENDING", "PROCESSED", "SKIPPED", "FAILED", name="comment_event_status", create_type=False
)
reply_job_status = postgresql.ENUM(
    "PENDING", "RUNNING", "SENT", "SKIPPED", "FAILED", name="reply_job_status", create_type=False
)


def upgrade() -> None:
    comment_event_status.create(op.get_bind(), checkfirst=True)
    reply_job_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "threads_comment_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("threads_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_reply_id", sa.String(length=64), nullable=False),
        sa.Column("external_media_id", sa.String(length=64), nullable=True),
        sa.Column("external_parent_reply_id", sa.String(length=64), nullable=True),
        sa.Column("external_from_id", sa.String(length=64), nullable=True),
        sa.Column("external_from_username", sa.String(length=120), nullable=True),
        sa.Column("reply_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("reply_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", comment_event_status, nullable=False, server_default="PENDING"),
        sa.Column("status_reason", sa.String(length=80), nullable=True),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["threads_account_id"], ["threads_account.id"]),
        sa.UniqueConstraint("event_hash", name="uq_threads_comment_event_hash"),
        sa.UniqueConstraint("threads_account_id", "external_reply_id", name="uq_threads_comment_event_reply"),
    )
    op.create_index(
        "idx_threads_comment_event_status",
        "threads_comment_event",
        ["status", "created_at"],
    )

    op.create_table(
        "threads_reply_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("comment_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("threads_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reply_text", sa.Text(), nullable=False),
        sa.Column("status", reply_job_status, nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("external_reply_id", sa.String(length=64), nullable=True),
        sa.Column("skip_reason", sa.String(length=80), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["comment_event_id"], ["threads_comment_event.id"]),
        sa.ForeignKeyConstraint(["threads_account_id"], ["threads_account.id"]),
        sa.UniqueConstraint("idempotency_key", name="uq_threads_reply_job_idempotency"),
    )
    op.create_index(
        "idx_threads_reply_job_status",
        "threads_reply_job",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_threads_reply_job_status", table_name="threads_reply_job")
    op.drop_table("threads_reply_job")

    op.drop_index("idx_threads_comment_event_status", table_name="threads_comment_event")
    op.drop_table("threads_comment_event")
