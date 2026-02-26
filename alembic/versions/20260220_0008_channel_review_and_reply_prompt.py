"""add channel-level review statuses and comment ai prompt

Revision ID: 20260220_0008
Revises: 20260220_0007
Create Date: 2026-02-26 02:25:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260220_0008"
down_revision = "20260220_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_unit",
        sa.Column(
            "threads_review_status",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.add_column(
        "content_unit",
        sa.Column(
            "instagram_review_status",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.add_column(
        "comment_rule",
        sa.Column(
            "ai_style_prompt",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )

    op.execute(
        """
        UPDATE content_unit
        SET
            threads_review_status = review_status::text,
            instagram_review_status = review_status::text
        """
    )


def downgrade() -> None:
    op.drop_column("comment_rule", "ai_style_prompt")
    op.drop_column("content_unit", "instagram_review_status")
    op.drop_column("content_unit", "threads_review_status")

